"""Store-level pins for the core Zarr binding.

Mirrors ``src/molrec/core/bindings/zarr.py``.

The conformance suite judges the *logical* round trip; these tests look at
the bytes the reference codec lays down, where the spec names them: the
pinned ``sequence_schema`` attribute, ``meta_dtype`` on per-step arrays,
``boundary`` as an array, sharded arrays with the index at the start, the
always-present ``meta/`` group without a version key, and the reader's
refusal of a non-monotonic ``offset``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import zarr

from molrec.core.bindings.zarr import (
    ZarrFrameCodec,
    ZarrFrameStore,
    ZarrRecordCodec,
    ZarrRecordStore,
    ZarrTrajectoryCodec,
    ZarrTrajectoryStore,
)
from molrec.core.model import (
    BlockModel,
    BoxModel,
    ColumnModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    MethodModel,
    RecordModel,
    StatusModel,
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


def _box_group_without_boundary(path: Path) -> ZarrFrameStore:
    """A frame whose box declares vectors and origin and nothing else."""
    root = zarr.open_group(store=path, mode="w")
    box = root.create_group("box")
    box.create_array("vectors", shape=(3, 3), dtype="float64")[...] = np.eye(3)
    box.create_array("origin", shape=(3,), dtype="float64")[...] = np.zeros(3)
    return ZarrFrameStore(path)


def test_a_box_group_without_boundary_reads_all_periodic(tmp_path: Path) -> None:
    store = _box_group_without_boundary(tmp_path / "absent-boundary.mrec")
    assert "boundary" not in store.root(mode="r")["box"], (
        "the store under test must not carry the array"
    )

    box = ZarrFrameCodec().read(store).box

    assert box is not None
    assert box.boundary == (True, True, True)
    assert box.cell_defined is True


def test_boundary_is_an_array_on_the_frame_path(tmp_path: Path) -> None:
    store = ZarrFrameStore(tmp_path / "boundary.mrec")
    ZarrFrameCodec().write(
        FrameModel(
            box=BoxModel(vectors=np.eye(3), boundary=(True, True, False), cell_defined=False)
        ),
        store,
    )
    box = store.root(mode="r")["box"]
    assert isinstance(box["boundary"], zarr.Array)
    assert box["boundary"][...].tolist() == [True, True, False]
    assert "boundary" not in box.attrs
    assert box.attrs["cell_defined"] is False
    assert (
        ZarrFrameCodec().read(store).box
        == FrameModel(
            box=BoxModel(vectors=np.eye(3), boundary=(True, True, False), cell_defined=False)
        ).box
    )


def test_the_trajectory_group_pins_sequence_schema(tmp_path: Path) -> None:
    store = ZarrTrajectoryStore(tmp_path / "pinned.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), store)
    root = store.root(mode="r")

    pinned = root["trajectory"].attrs["sequence_schema"]
    assert pinned == {
        "blocks": {
            "atoms": {"columns": {"x": {"dtype": "f64", "trailing": []}}},
            "bonds": {"columns": {"atomi": {"dtype": "u64", "trailing": []}}},
        },
        "meta": {"pe": {"dtype": "f64", "fill": 0.0}},
    }
    assert "molrs_sequence_schema" not in root["trajectory"].attrs
    assert root["trajectory/meta/pe"].attrs["meta_dtype"] == "f64"
    assert "molrs_meta_dtype" not in root["trajectory/meta/pe"].attrs


def test_block_groups_carry_the_writer_hints(tmp_path: Path) -> None:
    store = ZarrTrajectoryStore(tmp_path / "hints.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), store)
    root = store.root(mode="r")

    atoms = root["trajectory/atoms"].attrs
    assert atoms["dense_updates"] is True
    assert "uniform_rows" not in atoms  # 2 rows then 3
    bonds = root["trajectory/bonds"].attrs
    assert bonds["uniform_rows"] == 1 and bonds["dense_updates"] is True


def test_every_trajectory_array_is_sharded_with_the_index_at_the_start(tmp_path: Path) -> None:
    store = ZarrTrajectoryStore(tmp_path / "sharded.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), store)

    arrays = [
        p
        for p in (store.path / "trajectory").rglob("zarr.json")
        if p.parent != store.path / "trajectory"
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
    x = json.loads((store.path / "trajectory/atoms/x/zarr.json").read_text())
    assert [c["name"] for c in x["codecs"][0]["configuration"]["codecs"]] == ["bytes", "crc32c"]
    step = json.loads((store.path / "trajectory/step/zarr.json").read_text())
    assert [c["name"] for c in step["codecs"][0]["configuration"]["codecs"]] == [
        "bytes",
        "gzip",
        "crc32c",
    ]
    assert step["codecs"][0]["configuration"]["chunk_shape"] == [1024]


def test_a_bare_trajectory_store_has_a_root_and_an_empty_meta_document(tmp_path: Path) -> None:
    store = ZarrTrajectoryStore(tmp_path / "bare.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), store)
    root = store.root(mode="r")
    assert (store.path / "zarr.json").exists()
    assert "meta" in root
    assert dict(root["meta"].attrs) == {}


def test_a_non_monotonic_offset_is_refused(tmp_path: Path) -> None:
    store = ZarrTrajectoryStore(tmp_path / "broken.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), store)
    offset = zarr.open_group(store=store.path, mode="r+")["trajectory/atoms/offset"]
    offset[...] = np.array([0, 5, 2], dtype="uint64")

    with pytest.raises(ValueError, match="not monotonic"):
        ZarrTrajectoryCodec().read(store)


def test_a_longer_array_is_tolerated_a_shorter_one_refused(tmp_path: Path) -> None:
    """L8: a reader is bound by ``len(step)``."""
    store = ZarrTrajectoryStore(tmp_path / "reopen.mrec")
    ZarrTrajectoryCodec().write(_trajectory(), store)
    root = zarr.open_group(store=store.path, mode="r+")

    root["trajectory/meta/pe"].resize((5,))
    assert len(ZarrTrajectoryCodec().read(store).frames) == 2

    root["trajectory/meta/pe"].resize((1,))
    with pytest.raises(ValueError, match="committed"):
        ZarrTrajectoryCodec().read(store)


def test_the_record_codec_writes_no_version_and_reads_a_missing_meta_as_empty(
    tmp_path: Path,
) -> None:
    store = ZarrRecordStore(tmp_path / "record.mrec")
    codec = ZarrRecordCodec()
    codec.write(
        RecordModel(
            meta=MetaModel(),
            status=StatusModel(state="running", stage="train"),
            method=MethodModel(type="classical", description="NVT", engine={"name": "molrs"}),
        ),
        store,
    )
    root = store.root(mode="r")
    assert dict(root["meta"].attrs) == {}
    assert root["status"].attrs["stage"] == "train"
    back = codec.read(store)
    assert back.status is not None and back.status.state == "running"
    assert back.method is not None and back.method.engine.name == "molrs"

    del root
    import shutil

    shutil.rmtree(store.path / "meta")
    assert codec.read(store).meta == MetaModel()
