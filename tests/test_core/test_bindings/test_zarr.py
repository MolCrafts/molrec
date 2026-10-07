"""Storage-level pins for the core Zarr binding.

Mirrors ``src/molrec/core/bindings/zarr.py``.

The conformance suite judges the *logical* round trip; these tests look at
the bytes the reference codec lays down, where the spec names them: the
pinned ``sequence_schema`` attribute, ``meta_dtype`` on per-step arrays,
``boundary`` as an array, sharded arrays with the index at the start, the
always-present ``meta/`` group, and the reader's refusal of a non-monotonic ``offset``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import zarr

from molrec.core.bindings.zarr import (
    ZarrFrameCodec,
    ZarrFrameStorage,
    ZarrRecordCodec,
    ZarrRecordStorage,
    ZarrTrajectoryCodec,
    ZarrTrajectoryStorage,
)
from molrec.core.model import (
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    ColumnModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    MethodModel,
    RecordModel,
    StatusModel,
    TrajectoryBoxModel,
    TrajectoryModel,
)


def _atoms(*xs: float) -> BlockModel:
    array = np.array(xs, dtype="float64")
    return BlockModel(
        count=len(xs), columns={"x": ColumnModel(dtype="f64", shape=array.shape, values=array)}
    )


def _trajectory() -> TrajectoryModel:
    bonds = BlockModel(
        count=1,
        columns={
            "atomi": ColumnModel(dtype="u64", shape=(1,), values=np.array([0], dtype="uint64")),
        },
    )
    return (
        TrajectoryModel(
            frames=[
                FrameModel(blocks={"atoms": _atoms(0.0, 1.0), "bonds": bonds}, meta={"pe": -1.0}),
                FrameModel(blocks={"atoms": _atoms(0.5, 1.5, 2.5)}, meta={"pe": -1.5}),
            ],
            step=[0, 10],
            meta={
                "pe": MetaSeriesModel(dtype="f64"),
                "note": MetaSeriesModel(dtype="json", fill=None),
            },
        )
        if False
        else TrajectoryModel(
            frames=[
                FrameModel(blocks={"atoms": _atoms(0.0, 1.0), "bonds": bonds}, meta={"pe": -1.0}),
                FrameModel(blocks={"atoms": _atoms(0.5, 1.5, 2.5)}, meta={}),
            ],
            step=[0, 10],
            meta={"pe": MetaSeriesModel(dtype="f64", fill=0.0)},
        )
    )


def _box_group_without_boundary(path: Path) -> ZarrFrameStorage:
    """A frame whose box declares vectors and origin and nothing else."""
    root = zarr.open_group(store=path, mode="w")
    box = root.create_group("box")
    box.create_array("vectors", shape=(3, 3), dtype="float64")[...] = np.eye(3)
    box.create_array("origin", shape=(3,), dtype="float64")[...] = np.zeros(3)
    return ZarrFrameStorage(path)


def test_a_box_group_without_boundary_reads_all_periodic(tmp_path: Path) -> None:
    storage = _box_group_without_boundary(tmp_path / "absent-boundary.mrec")
    assert "boundary" not in storage.root(mode="r")["box"], (
        "the storage under test must not carry the array"
    )

    box = ZarrFrameCodec().read(storage).box

    assert box is not None
    assert box.boundary == (True, True, True)
    assert box.cell_defined is True


def test_boundary_is_an_array_on_the_frame_path(tmp_path: Path) -> None:
    storage = ZarrFrameStorage(tmp_path / "boundary.mrec")
    ZarrFrameCodec().write(
        FrameModel(box=BoxModel(vectors=np.eye(3), boundary=(True, True, False))),
        storage,
    )
    box = storage.root(mode="r")["box"]
    assert isinstance(box["boundary"], zarr.Array)
    assert box["boundary"][...].tolist() == [True, True, False]
    assert "boundary" not in box.attrs
    assert "cell_defined" not in box.attrs
    assert (
        ZarrFrameCodec().read(storage).box
        == FrameModel(box=BoxModel(vectors=np.eye(3), boundary=(True, True, False))).box
    )


def test_the_trajectory_group_pins_sequence_schema(tmp_path: Path) -> None:
    storage = ZarrTrajectoryStorage(tmp_path / "pinned.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), storage)
    root = storage.root(mode="r")

    pinned = root["trajectory"].attrs["sequence_schema"]
    assert pinned == {
        "blocks": {
            "atoms": {"columns": {"x": {"dtype": "f64", "trailing": []}}},
            "bonds": {"columns": {"atomi": {"dtype": "u64", "trailing": []}}},
        },
        "meta": {"pe": {"dtype": "f64", "fill": 0.0}},
    }
    assert root["trajectory/meta/pe"].attrs["meta_dtype"] == "f64"


def test_the_elision_markers_never_ride_beside_an_index(tmp_path: Path) -> None:
    storage = ZarrTrajectoryStorage(tmp_path / "hints.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), storage)
    root = storage.root(mode="r")

    # atoms: 2 rows then 3 -- ragged, so it carries its index and no markers.
    atoms = root["trajectory/atoms"]
    assert "uniform_rows" not in atoms.attrs and "dense_updates" not in atoms.attrs
    assert {"step_index", "offset"} <= {name for name, _ in atoms.arrays()}
    # bonds: one update of one row at ordinal 0 -- regular, so no index at all.
    bonds = root["trajectory/bonds"]
    assert bonds.attrs["uniform_rows"] == 1 and bonds.attrs["dense_updates"] is True
    assert {name for name, _ in bonds.arrays()} == {"atomi"}


def test_the_common_run_costs_one_array_per_column(tmp_path: Path) -> None:
    """Fixed atom count, every frame, fixed cell, regular step and time."""
    model = TrajectoryModel(
        frames=[FrameModel(blocks={"atoms": _atoms(x, x + 1.0)}) for x in (0.0, 0.5, 1.0)],
        step=[0, 10, 20],
        time=[0.0, 0.25, 0.5],
        box=TrajectoryBoxModel(
            updates=[BoxUpdateModel(step_index=0, box=CellModel(vectors=np.eye(3) * 4.0))]
        ),
    )
    storage = ZarrTrajectoryStorage(tmp_path / "common.mrec")
    ZarrTrajectoryCodec().write(model, storage)
    root = storage.root(mode="r")
    trajectory = root["trajectory"]

    arrays = sorted(
        str(path.parent.relative_to(storage.path))
        for path in (storage.path / "trajectory").rglob("zarr.json")
        if json.loads(path.read_text())["node_type"] == "array"
    )
    assert arrays == ["trajectory/atoms/x"]
    assert trajectory.attrs["step_progression"] == {"start": 0, "stride": 10}
    assert trajectory.attrs["time_progression"] == {"start": 0.0, "stride": 0.25}
    assert trajectory.attrs["nstep"] == 3
    assert trajectory["box"].attrs["vectors"] == (np.eye(3) * 4.0).tolist()
    assert ZarrTrajectoryCodec().read(storage) == model


def test_an_irregular_step_series_is_an_array(tmp_path: Path) -> None:
    model = TrajectoryModel(
        frames=[FrameModel(blocks={"atoms": _atoms(x)}) for x in (0.0, 0.5, 1.0)],
        step=[0, 1, 5],
        time=[0.0, 0.1, 0.30000000000000004 + 1e-9],
    )
    storage = ZarrTrajectoryStorage(tmp_path / "irregular.mrec")
    ZarrTrajectoryCodec().write(model, storage)
    trajectory = storage.root(mode="r")["trajectory"]
    assert "step_progression" not in trajectory.attrs
    assert trajectory["step"][...].tolist() == [0, 1, 5]
    assert "time_progression" not in trajectory.attrs
    assert ZarrTrajectoryCodec().read(storage) == model


def test_a_progression_without_its_marker_is_refused(tmp_path: Path) -> None:
    storage = ZarrTrajectoryStorage(tmp_path / "unmarked.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), storage)
    trajectory = zarr.open_group(store=storage.path, mode="r+")["trajectory"]
    attrs = dict(trajectory.attrs)
    del attrs["nstep"]
    trajectory.attrs.clear()
    trajectory.attrs.update(attrs)
    with pytest.raises(ValueError, match="nstep"):
        ZarrTrajectoryCodec().read(storage)


@pytest.mark.parametrize(
    "markers",
    [{"uniform_rows": 1}, {"dense_updates": True}, {"uniform_rows": 0, "dense_updates": True}],
)
def test_half_an_elision_is_refused(tmp_path: Path, markers: dict) -> None:
    storage = ZarrTrajectoryStorage(tmp_path / "half.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), storage)
    bonds = zarr.open_group(store=storage.path, mode="r+")["trajectory/bonds"]
    bonds.attrs.clear()
    bonds.attrs.update(markers)
    with pytest.raises(ValueError, match="elide"):
        ZarrTrajectoryCodec().read(storage)


def test_a_declared_block_never_updated_is_absent(tmp_path: Path) -> None:
    from molrec.core.model import SequenceBlockModel, SequenceColumnModel

    model = TrajectoryModel(
        frames=[FrameModel(blocks={"atoms": _atoms(0.0)})],
        step=[0],
        blocks={
            "atoms": SequenceBlockModel(columns={"x": SequenceColumnModel(dtype="f64")}),
            "bonds": SequenceBlockModel(columns={"atomi": SequenceColumnModel(dtype="u64")}),
        },
    )
    storage = ZarrTrajectoryStorage(tmp_path / "declared.mrec")
    ZarrTrajectoryCodec().write(model, storage)
    bonds = storage.root(mode="r")["trajectory/bonds"]
    assert dict(bonds.attrs) == {} and bonds["atomi"].shape == (0,)
    back = ZarrTrajectoryCodec().read(storage)
    assert back == model and "bonds" not in back.frames[0].blocks


def test_every_trajectory_array_is_sharded_with_the_index_at_the_start(tmp_path: Path) -> None:
    storage = ZarrTrajectoryStorage(tmp_path / "sharded.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), storage)

    arrays = [
        p
        for p in (storage.path / "trajectory").rglob("zarr.json")
        if p.parent != storage.path / "trajectory"
    ]
    assert arrays
    for path in arrays:
        document = json.loads(path.read_text())
        if document["node_type"] != "array":
            continue
        sharding = document["codecs"][0]
        assert sharding["name"] == "sharding_indexed", path
        assert sharding["configuration"]["index_location"] == "start", path
        inner = [codec["name"] for codec in sharding["configuration"]["codecs"]]
        assert inner[-1] == "crc32c", path
        assert set(inner) <= {"bytes", "vlen-utf8", "gzip", "crc32c"}, path

    # Float columns are uncompressed; dense arrays and non-float columns take gzip.
    x = json.loads((storage.path / "trajectory/atoms/x/zarr.json").read_text())
    assert [c["name"] for c in x["codecs"][0]["configuration"]["codecs"]] == ["bytes", "crc32c"]
    dense = json.loads((storage.path / "trajectory/meta/pe/zarr.json").read_text())
    assert [c["name"] for c in dense["codecs"][0]["configuration"]["codecs"]] == [
        "bytes",
        "gzip",
        "crc32c",
    ]
    assert dense["codecs"][0]["configuration"]["chunk_shape"] == [1024]
    assert dense["chunk_grid"]["configuration"]["chunk_shape"] == [1024 * 256]


def test_a_bare_trajectory_storage_has_a_root_and_an_empty_meta_document(tmp_path: Path) -> None:
    storage = ZarrTrajectoryStorage(tmp_path / "bare.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), storage)
    root = storage.root(mode="r")
    assert (storage.path / "zarr.json").exists()
    assert "meta" in root
    assert dict(root["meta"].attrs) == {}


def test_a_non_monotonic_offset_is_refused(tmp_path: Path) -> None:
    storage = ZarrTrajectoryStorage(tmp_path / "broken.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), storage)
    offset = zarr.open_group(store=storage.path, mode="r+")["trajectory/atoms/offset"]
    offset[...] = np.array([0, 5, 2], dtype="uint64")

    with pytest.raises(ValueError, match="not monotonic"):
        ZarrTrajectoryCodec().read(storage)


def test_a_longer_array_is_tolerated_a_shorter_one_refused(tmp_path: Path) -> None:
    """L8: a reader is bound by ``len(step)``."""
    storage = ZarrTrajectoryStorage(tmp_path / "reopen.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), storage)
    root = zarr.open_group(store=storage.path, mode="r+")

    root["trajectory/meta/pe"].resize((5,))
    assert len(ZarrTrajectoryCodec().read(storage).frames) == 2

    root["trajectory/meta/pe"].resize((1,))
    with pytest.raises(ValueError, match="committed"):
        ZarrTrajectoryCodec().read(storage)


def test_the_record_codec_writes_meta_as_given_and_reads_a_missing_meta_as_empty(
    tmp_path: Path,
) -> None:
    storage = ZarrRecordStorage(tmp_path / "record.mrec")
    codec = ZarrRecordCodec()
    codec.write(
        RecordModel(
            meta=MetaModel(),
            status=StatusModel(state="running", stage="train"),
            method=MethodModel(type="classical", description="NVT", engine={"name": "molrs"}),
        ),
        storage,
    )
    root = storage.root(mode="r")
    assert dict(root["meta"].attrs) == {}
    assert root["status"].attrs["stage"] == "train"
    back = codec.read(storage)
    assert back.status is not None and back.status.state == "running"
    assert back.method is not None and back.method.engine.name == "molrs"

    del root
    import shutil

    shutil.rmtree(storage.path / "meta")
    assert codec.read(storage).meta == MetaModel()


def test_a_mask_lands_in_the_block_validity_subgroup(tmp_path: Path) -> None:
    storage = ZarrFrameStorage(tmp_path / "masked.mrec")
    charge = ColumnModel(
        dtype="f64",
        shape=(3,),
        values=np.array([0.5, 0.0, -0.5]),
        validity=np.array([True, False, True]),
    )
    frame = FrameModel(blocks={"atoms": BlockModel(count=3, columns={"charge": charge})})
    ZarrFrameCodec().write(frame, storage)
    root = storage.root(mode="r")
    mask = root["atoms/_validity/charge"]
    assert isinstance(mask, zarr.Array) and mask.dtype == np.bool_
    assert mask[...].tolist() == [True, False, True]
    assert ZarrFrameCodec().read(storage) == frame


def test_an_unmasked_block_writes_no_validity_subgroup(tmp_path: Path) -> None:
    storage = ZarrFrameStorage(tmp_path / "plain.mrec")
    ZarrFrameCodec().write(FrameModel(blocks={"atoms": _atoms(0.0, 1.0)}), storage)
    assert "_validity" not in storage.root(mode="r")["atoms"]


def test_a_trajectory_mask_is_dense_over_the_rows(tmp_path: Path) -> None:
    def frame(validity: list[bool] | None) -> FrameModel:
        q = ColumnModel(
            dtype="f64",
            shape=(2,),
            values=np.zeros(2),
            validity=None if validity is None else np.array(validity),
        )
        return FrameModel(blocks={"atoms": BlockModel(count=2, columns={"q": q})})

    storage = ZarrTrajectoryStorage(tmp_path / "masked.mrec")
    model = TrajectoryModel(frames=[frame([False, True]), frame(None)], step=[0, 1])
    ZarrTrajectoryCodec().write(model, storage)
    root = storage.root(mode="r")
    assert root["trajectory"].attrs["sequence_schema"]["blocks"]["atoms"]["columns"]["q"] == {
        "dtype": "f64",
        "trailing": [],
        "nullable": True,
    }
    assert root["trajectory/atoms/_validity/q"][...].tolist() == [False, True, True, True]
    assert ZarrTrajectoryCodec().read(storage) == model


def test_the_record_codec_carries_unknown_content_through(tmp_path: Path) -> None:
    from molrec.core.model import ArrayNodeModel, NodeModel

    vendor = NodeModel(
        attributes={"tool": "x", "maybe": None},
        arrays={
            "grid": ArrayNodeModel(
                dtype="i32", shape=(2,), values=np.array([1, 2], dtype="int32"), attributes={"u": 1}
            )
        },
        groups={"inner": NodeModel(attributes={"depth": 2})},
    )
    block = BlockModel.model_validate(
        {"count": 1, "columns": {"x": ColumnModel(dtype="f64", shape=(1,), values=np.zeros(1))}}
        | {"x_vendor_flag": True}
    )
    record = RecordModel.model_validate(
        {
            "meta": {"x_vendor_version": 7, "x_reviewed": None},
            "status": {"state": "running", "x_note": None},
            "frame": FrameModel(blocks={"atoms": block}),
            "x_vendor": vendor,
        }
    )
    storage = ZarrRecordStorage(tmp_path / "unknown.mrec")
    ZarrRecordCodec().write(record, storage)
    root = storage.root(mode="r")
    assert dict(root["frame/atoms"].attrs) == {"count": 1, "x_vendor_flag": True}
    assert dict(root["meta"].attrs) == {"x_vendor_version": 7, "x_reviewed": None}
    back = ZarrRecordCodec().read(storage)
    assert back == record
    assert back.model_extra == {"x_vendor": vendor}
