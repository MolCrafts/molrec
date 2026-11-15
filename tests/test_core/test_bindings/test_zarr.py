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
    read_block,
    write_block,
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
        path.parent.relative_to(storage.path).as_posix()
        for path in (storage.path / "trajectory").rglob("zarr.json")
        if json.loads(path.read_text(encoding="utf-8"))["node_type"] == "array"
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
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["node_type"] != "array":
            continue
        sharding = document["codecs"][0]
        assert sharding["name"] == "sharding_indexed", path
        assert sharding["configuration"]["index_location"] == "start", path
        inner = [codec["name"] for codec in sharding["configuration"]["codecs"]]
        assert inner[-1] == "crc32c", path
        assert set(inner) <= {"bytes", "vlen-utf8", "gzip", "crc32c"}, path

    # Float columns are uncompressed; dense arrays and non-float columns take gzip.
    x = json.loads((storage.path / "trajectory/atoms/x/zarr.json").read_text(encoding="utf-8"))
    assert [c["name"] for c in x["codecs"][0]["configuration"]["codecs"]] == ["bytes", "crc32c"]
    dense = json.loads((storage.path / "trajectory/meta/pe/zarr.json").read_text(encoding="utf-8"))
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


def _weights(*values: float) -> BlockModel:
    array = np.array(values, dtype="float64")
    return BlockModel(
        count=len(values),
        columns={"weight": ColumnModel(dtype="f64", shape=array.shape, values=array)},
    )


def _stated_once(box: TrajectoryBoxModel | None = None) -> TrajectoryModel:
    """Three frames whose ``labels`` block is stated at ordinal 0 and carried
    forward: a regular block with fewer updates than the run has frames."""
    return TrajectoryModel(
        frames=[
            FrameModel(blocks={"atoms": _atoms(0.0, 1.0), "labels": _weights(1.0, 2.0)}),
            FrameModel(blocks={"atoms": _atoms(0.5, 1.5)}),
            FrameModel(blocks={"atoms": _atoms(1.0, 2.0)}),
        ],
        step=[0, 10, 20],
        box=box,
    )


def test_an_interrupted_index_materialization_reads_as_the_last_commit(tmp_path: Path) -> None:
    """The materialization order of ``docs/spec/chunking.md``: a flush that
    gives a regular block its index lands ``offset``, then ``step_index``,
    then the rows, then withdraws the markers. Stopped after any of them, the
    record still reads as the three frames it committed."""
    model = _stated_once()
    storage = ZarrTrajectoryStorage(tmp_path / "materializing.mrec")
    codec = ZarrTrajectoryCodec()
    codec.write(model, storage)
    labels = zarr.open_group(store=storage.path, mode="r+")["trajectory/labels"]
    assert labels.attrs["uniform_rows"] == 2 and labels.attrs["dense_updates"] is True

    # The flush of frame 3 restates `labels`: update 1 at ordinal 3 is not at
    # its own ordinal, so the block stops being regular.
    labels.create_array("offset", shape=(3,), dtype="uint64")[...] = [0, 2, 4]
    assert codec.read(storage) == model

    labels.create_array("step_index", shape=(2,), dtype="uint64")[...] = [0, 3]
    assert codec.read(storage) == model

    labels["weight"].resize((4,))
    labels["weight"][2:] = [9.0, 9.0]
    assert codec.read(storage) == model

    labels.attrs.clear()
    assert codec.read(storage) == model


def test_an_interrupted_cell_materialization_reads_as_the_last_commit(tmp_path: Path) -> None:
    """A fixed cell leaves the ``box/`` attributes for arrays with ``vectors``
    last: until it exists a reader is still on the attributes, and once it
    does the other arrays already hold the attribute cell as update 0."""
    cell = CellModel(
        vectors=np.eye(3) * 4.0, origin=np.array([1.0, 2.0, 3.0]), boundary=(True, True, False)
    )
    model = _stated_once(TrajectoryBoxModel(updates=[BoxUpdateModel(step_index=0, box=cell)]))
    storage = ZarrTrajectoryStorage(tmp_path / "cell.mrec")
    codec = ZarrTrajectoryCodec()
    codec.write(model, storage)
    box = zarr.open_group(store=storage.path, mode="r+")["trajectory/box"]
    assert {name for name, _ in box.arrays()} == set()

    # The flush of frame 3 changes the cell: update 0 is the attribute cell,
    # backfilled, and update 1 sits at ordinal 3.
    box.create_array("step_index", shape=(2,), dtype="uint64")[...] = [0, 3]
    box.create_array("origin", shape=(2, 3), dtype="float64")[...] = [[1.0, 2.0, 3.0]] * 2
    box.create_array("boundary", shape=(2, 3), dtype="bool")[...] = [[True, True, False]] * 2
    assert codec.read(storage) == model

    box.create_array("vectors", shape=(2, 3, 3), dtype="float64")[...] = np.stack(
        [np.eye(3) * 4.0, np.eye(3) * 5.0]
    )
    assert codec.read(storage) == model

    box.attrs.clear()
    assert codec.read(storage) == model


def test_an_interrupted_first_cell_reads_as_no_cell(tmp_path: Path) -> None:
    """A cell that first appears after ordinal 0 lands its ``step_index``
    before its ``vectors``: ``vectors`` alone would read as one update at
    ordinal 0, a cell the committed frames never had."""
    model = _stated_once()
    storage = ZarrTrajectoryStorage(tmp_path / "first-cell.mrec")
    codec = ZarrTrajectoryCodec()
    codec.write(model, storage)
    box = zarr.open_group(store=storage.path, mode="r+")["trajectory"].create_group("box")

    box.create_array("step_index", shape=(1,), dtype="uint64")[...] = [3]
    assert codec.read(storage) == model

    box.create_array("vectors", shape=(1, 3, 3), dtype="float64")[...] = np.eye(3)[None] * 4.0
    assert codec.read(storage) == model


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
            "meta": {
                "x_vendor_version": 7,
                "x_reviewed": None,
                "units": {"length": "angstrom"},
            },
            "status": {"state": "running", "x_note": None},
            "frame": FrameModel(blocks={"atoms": block}),
            "x_vendor": vendor,
        }
    )
    storage = ZarrRecordStorage(tmp_path / "unknown.mrec")
    ZarrRecordCodec().write(record, storage)
    root = storage.root(mode="r")
    assert dict(root["frame/atoms"].attrs) == {"count": 1, "x_vendor_flag": True}
    assert dict(root["meta"].attrs) == {
        "x_vendor_version": 7,
        "x_reviewed": None,
        "units": {"length": "angstrom"},
    }
    back = ZarrRecordCodec().read(storage)
    assert back == record
    assert back.model_extra == {"x_vendor": vendor}


class TestPublishing:
    """A one-shot write builds beside the record and renames it into place
    (``docs/spec/chunking.md``, publishing): the ``*.mrec`` name never holds a
    half-written record."""

    @staticmethod
    def _record(x: float) -> RecordModel:
        return RecordModel(
            meta=MetaModel(units={"length": "angstrom", "energy": "kcal/mol"}),
            frame=FrameModel(blocks={"atoms": _atoms(x)}),
            trajectory=_trajectory(),
        )

    @staticmethod
    def _break_the_trajectory(monkeypatch: pytest.MonkeyPatch) -> None:
        def torn(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(ZarrTrajectoryCodec, "write_into", torn)

    def test_a_failed_write_leaves_the_previous_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        storage = ZarrRecordStorage(tmp_path / "run.mrec")
        ZarrRecordCodec().write(self._record(1.0), storage)
        self._break_the_trajectory(monkeypatch)
        with pytest.raises(OSError, match="disk full"):
            ZarrRecordCodec().write(self._record(2.0), storage)
        monkeypatch.undo()
        back = ZarrRecordCodec().read(storage)
        assert back.frame.blocks["atoms"].columns["x"].values.tolist() == [1.0]
        assert back.trajectory is not None
        assert [entry.name for entry in tmp_path.iterdir()] == ["run.mrec"]

    def test_a_failed_first_write_publishes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._break_the_trajectory(monkeypatch)
        with pytest.raises(OSError, match="disk full"):
            ZarrRecordCodec().write(self._record(1.0), ZarrRecordStorage(tmp_path / "run.mrec"))
        assert list(tmp_path.iterdir()) == []

    def test_a_record_under_construction_is_not_named_like_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[list[str]] = []
        write_into = ZarrTrajectoryCodec.write_into

        def watching(self: ZarrTrajectoryCodec, *args: object, **kwargs: object) -> None:
            seen.append(sorted(entry.name for entry in tmp_path.iterdir()))
            write_into(self, *args, **kwargs)

        monkeypatch.setattr(ZarrTrajectoryCodec, "write_into", watching)
        ZarrRecordCodec().write(self._record(1.0), ZarrRecordStorage(tmp_path / "run.mrec"))
        (during,) = seen
        assert len(during) == 1
        assert not during[0].endswith((".mrec", ".mrec.zip"))
        assert [entry.name for entry in tmp_path.iterdir()] == ["run.mrec"]


class TestColumnUnit:
    def test_frame_array_stores_unit(self, tmp_path: Path) -> None:
        values = np.array([1.0])
        stated = ColumnModel(dtype="f64", shape=values.shape, values=values, unit="nm")
        bare = ColumnModel(dtype="f64", shape=values.shape, values=values)
        group = zarr.open_group(tmp_path / "frame.zarr", mode="w")
        write_block(group, "atoms", BlockModel(count=1, columns={"x": stated}))
        write_block(group, "bare", BlockModel(count=1, columns={"x": bare}))
        assert group["atoms"]["x"].attrs["unit"] == "nm"
        assert "unit" not in group["bare"]["x"].attrs
        assert read_block(group["atoms"]).columns["x"].unit == "nm"

    def test_trajectory_array_stores_unit(self, tmp_path: Path) -> None:
        values = np.array([1.0])
        column = ColumnModel(dtype="f64", shape=values.shape, values=values, unit="nm")
        model = TrajectoryModel(
            frames=[FrameModel(blocks={"atoms": BlockModel(count=1, columns={"x": column})})],
            step=[0],
        )
        storage = ZarrTrajectoryStorage(tmp_path / "unit.mrec")
        ZarrTrajectoryCodec().write(model, storage)
        array = storage.root(mode="r")["trajectory"]["atoms"]["x"]
        assert array.attrs["unit"] == "nm"
        back = ZarrTrajectoryCodec().read(storage)
        assert back.frames[0].blocks["atoms"].columns["x"].unit == "nm"

    def test_record_write_refuses_coordinates_without_length(self, tmp_path: Path) -> None:
        record = RecordModel(meta=MetaModel(), frame=FrameModel(blocks={"atoms": _atoms(0.0)}))
        with pytest.raises(ValueError, match="length"):
            ZarrRecordCodec().write(record, ZarrRecordStorage(tmp_path / "bare.mrec"))
