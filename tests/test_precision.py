"""Declared precision: the rounding rule, its bounds, the models that apply it,
and what it buys on disk (``docs/spec/frame.md``, ``docs/spec/chunking.md``)."""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pytest
import zarr

from molrec.core.bindings.zarr import (
    PRECISION_ATTR,
    ZarrFrameCodec,
    ZarrFrameStore,
    ZarrRecordCodec,
    ZarrRecordStore,
    ZarrTrajectoryCodec,
    ZarrTrajectoryStore,
)
from molrec.core.model import (
    MOLREC_VERSION,
    STORED,
    BlockModel,
    ColumnModel,
    FrameModel,
    MetaModel,
    RecordModel,
    SequenceBlockModel,
    SequenceColumnModel,
    TrajectoryModel,
)
from molrec.precision import PRECISION_MAX, PRECISION_MIN, on_grid, quantize, quantum


class TestQuantum:
    def test_the_largest_power_of_two_not_above_p(self) -> None:
        assert quantum(1e-3) == 2.0**-10
        assert quantum(1e-2) == 2.0**-7
        assert quantum(0.5) == 0.5
        assert quantum(0.75) == 0.5
        assert quantum(1.0) == 1.0

    @pytest.mark.parametrize("bad", [0.0, -1.0, math.inf, math.nan, PRECISION_MIN / 2])
    def test_out_of_bounds_is_refused(self, bad: float) -> None:
        with pytest.raises(ValueError, match="precision"):
            quantum(bad)

    def test_the_bounds_themselves_are_admitted(self) -> None:
        assert quantum(PRECISION_MIN) == PRECISION_MIN
        assert quantum(PRECISION_MAX) == PRECISION_MAX


class TestQuantize:
    def test_ties_go_to_even(self) -> None:
        q = quantum(1e-3)
        assert quantize(np.array([2.5 * q, 3.5 * q, -2.5 * q]), 1e-3).tolist() == [
            2 * q,
            4 * q,
            -2 * q,
        ]

    def test_non_finite_and_huge_values_are_kept(self) -> None:
        values = np.array([math.nan, math.inf, -math.inf, 2.0**60 + 1024.0])
        np.testing.assert_array_equal(quantize(values, 1e-3), values)

    def test_a_small_negative_rounds_to_negative_zero(self) -> None:
        stored = quantize(np.array([-1e-5]), 1e-3)
        assert stored[0] == 0.0 and math.copysign(1.0, stored[0]) == -1.0

    def test_the_writer_bound_and_grid_membership_on_a_sweep(self) -> None:
        rng = np.random.default_rng(7)
        for precision in (1e-3, 1e-2, 0.37, 5.0):
            values = rng.uniform(-1e4, 1e4, 4096)
            stored = quantize(values, precision)
            assert np.all(np.abs(values - stored) <= precision / 2)
            assert np.all(np.abs(values - stored) <= quantum(precision) / 2)
            assert on_grid(stored, precision)
            assert not on_grid(values, precision)
            np.testing.assert_array_equal(quantize(stored, precision), stored)


class TestModels:
    def test_a_column_holds_its_stored_values(self) -> None:
        column = ColumnModel(dtype="f64", shape=(1,), values=np.array([0.1234]), precision=1e-3)
        assert column.values.tolist() == quantize(np.array([0.1234]), 1e-3).tolist()

    def test_a_reader_keeps_what_it_read(self) -> None:
        column = ColumnModel.model_validate(
            {"dtype": "f64", "shape": (1,), "values": np.array([0.1234]), "precision": 1e-3},
            context=STORED,
        )
        assert column.values.tolist() == [0.1234]
        # pydantic runs a model's after-validators again when the instance is
        # handed to another model; the stored values must survive that.
        frame = FrameModel(blocks={"atoms": BlockModel(count=1, columns={"x": column})})
        assert frame.blocks["atoms"].columns["x"].values.tolist() == [0.1234]

    def test_a_trajectory_reader_keeps_what_it_read(self, tmp_path) -> None:
        declared = {
            "atoms": SequenceBlockModel(
                columns={"x": SequenceColumnModel(dtype="f64", precision=1e-3)}
            )
        }
        frame = FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=1,
                    columns={"x": ColumnModel(dtype="f64", shape=(1,), values=np.array([0.5]))},
                )
            }
        )
        store = ZarrTrajectoryStore(tmp_path / "t.mrec")
        ZarrTrajectoryCodec().write(
            TrajectoryModel(frames=[frame], step=[0], blocks=declared), store
        )
        zarr.open_group(store=store.path, mode="r+")["trajectory/atoms/x"][...] = [0.1234]
        read = ZarrTrajectoryCodec().read(store)
        assert read.frames[0].blocks["atoms"].columns["x"].values.tolist() == [0.1234]
        record = RecordModel(meta=MetaModel(), trajectory=read)
        assert record.trajectory.frames[0].blocks["atoms"].columns["x"].values.tolist() == [0.1234]

    def test_only_f64_declares_one(self) -> None:
        with pytest.raises(ValueError, match="only an f64"):
            ColumnModel(dtype="i64", shape=(1,), values=np.array([1]), precision=1e-3)
        with pytest.raises(ValueError, match="only an f64"):
            SequenceColumnModel(dtype="u64", precision=1e-3)

    def test_precision_is_part_of_equality(self) -> None:
        values = np.array([0.5])
        assert ColumnModel(dtype="f64", shape=(1,), values=values, precision=1e-3) != (
            ColumnModel(dtype="f64", shape=(1,), values=values)
        )

    def test_the_declaration_writes_precision_only_when_declared(self) -> None:
        assert "precision" not in SequenceColumnModel(dtype="f64").model_dump()
        assert SequenceColumnModel(dtype="f64", precision=0.01).model_dump()["precision"] == 0.01

    def test_a_trajectory_derives_the_first_stated_precision(self) -> None:
        frame = FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=1,
                    columns={
                        "x": ColumnModel(
                            dtype="f64", shape=(1,), values=np.array([0.1234]), precision=1e-3
                        )
                    },
                )
            }
        )
        model = TrajectoryModel(frames=[frame, frame], step=[0, 1])
        assert model.blocks["atoms"].columns["x"].precision == 1e-3
        for resolved in model.frames:
            assert resolved.blocks["atoms"].columns["x"].precision is None
        again = TrajectoryModel.model_validate(model.model_dump(exclude_unset=True))
        assert again.blocks == model.blocks

    def test_a_frame_cannot_restate_another_precision(self) -> None:
        def presented(precision: float) -> FrameModel:
            column = ColumnModel(
                dtype="f64", shape=(1,), values=np.array([0.5]), precision=precision
            )
            return FrameModel(blocks={"atoms": BlockModel(count=1, columns={"x": column})})

        with pytest.raises(ValueError, match="declares a column's precision once"):
            TrajectoryModel(frames=[presented(1e-3), presented(1e-2)], step=[0, 1])


def test_the_frame_path_stores_the_attribute_and_the_pipeline(tmp_path) -> None:
    store = ZarrFrameStore(tmp_path / "f.mrec")
    column = ColumnModel(dtype="f64", shape=(4,), values=np.linspace(0, 1, 4), precision=1e-3)
    ZarrFrameCodec().write(
        FrameModel(blocks={"atoms": BlockModel(count=4, columns={"x": column})}), store
    )
    array = zarr.open_group(store=store.path, mode="r")["atoms/x"]
    assert array.attrs[PRECISION_ATTR] == 1e-3
    names = [codec["name"] for codec in array.metadata.to_dict()["codecs"]]
    assert names == ["bytes", "numcodecs.shuffle", "zstd", "crc32c"]


def test_a_sub_quantum_change_writes_one_update(tmp_path) -> None:
    def frame(x: float) -> FrameModel:
        column = ColumnModel(dtype="f64", shape=(1,), values=np.array([x]))
        return FrameModel(blocks={"atoms": BlockModel(count=1, columns={"x": column})})

    declared = {
        "atoms": SequenceBlockModel(columns={"x": SequenceColumnModel(dtype="f64", precision=1e-3)})
    }
    q = quantum(1e-3)
    model = TrajectoryModel(frames=[frame(0.5), frame(0.5 + 0.4 * q)], step=[0, 1], blocks=declared)
    store = ZarrTrajectoryStore(tmp_path / "t.mrec")
    ZarrTrajectoryCodec().write(model, store)
    assert zarr.open_group(store=store.path, mode="r")["trajectory/atoms/x"].shape == (1,)
    assert ZarrTrajectoryCodec().read(store) == model


def _bytes_per_atom_frame(tmp_path, precision: float | None) -> float:
    """3000 atoms uniform in a 40 A box, 40 frames of a 0.05 A random walk
    (the design's worst case: no molecular order), through the reference
    trajectory writer; the stored bytes of the three coordinate columns."""
    rng = np.random.default_rng(2026)
    natoms, nframes = 3000, 40
    positions = rng.uniform(0.0, 40.0, (natoms, 3))
    frames = []
    for _ in range(nframes):
        positions = positions + rng.normal(0.0, 0.05, positions.shape)
        columns = {
            axis: ColumnModel(dtype="f64", shape=(natoms,), values=positions[:, i].copy())
            for i, axis in enumerate("xyz")
        }
        frames.append(FrameModel(blocks={"atoms": BlockModel(count=natoms, columns=columns)}))
    declared = {
        "atoms": SequenceBlockModel(
            columns={axis: SequenceColumnModel(dtype="f64", precision=precision) for axis in "xyz"}
        )
    }
    store = ZarrTrajectoryStore(tmp_path / f"density-{precision}.mrec")
    ZarrTrajectoryCodec().write(
        TrajectoryModel(frames=frames, step=list(range(nframes)), blocks=declared), store
    )
    root = zarr.open_group(store=store.path, mode="r")
    stored = 0
    for axis in "xyz":
        array = root[f"trajectory/atoms/{axis}"]
        # Each shard file opens with its index (16 B per inner chunk + a
        # crc32c), a fixed cost a 40-frame run cannot amortize; the density
        # is that of the chunk payloads.
        index = 16 * (array.shards[0] // array.chunks[0]) + 4
        shards = [
            path
            for path in (store.path / "trajectory" / "atoms" / axis).rglob("*")
            if path.is_file() and path.name != "zarr.json"
        ]
        stored += sum(path.stat().st_size - index for path in shards)
    return stored / (natoms * nframes)


def test_density_bytes_per_atom_per_frame(tmp_path) -> None:
    """What declared precision buys: ~24 B/atom/frame raw, ~7.6 at 1e-3 A and
    ~5.8 at 1e-2 A with the reference shuffle + zstd-3 pipeline."""
    raw = _bytes_per_atom_frame(tmp_path, None)
    milli = _bytes_per_atom_frame(tmp_path, 1e-3)
    centi = _bytes_per_atom_frame(tmp_path, 1e-2)
    print(f"B/atom/frame: raw {raw:.2f}, p=1e-3 {milli:.2f}, p=1e-2 {centi:.2f}")
    assert raw > 23.5
    assert milli < 8.0
    assert centi < 6.2


# ---------------------------------------------------------------------------
# fixtures/precision.mrec.zip -- a store another implementation wrote, for
# molrs's readers (the wasm32 build included) to decode: numcodecs.shuffle +
# zstd on the frame path and the trajectory path. Regenerate with
# ``python tests/test_precision.py``.
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "precision.mrec.zip"


def precision_fixture_model() -> RecordModel:
    """A frame and a trajectory whose coordinates declare a precision of 1e-3."""
    rng = np.random.default_rng(1)
    positions = rng.uniform(0.0, 10.0, (8, 3))

    def coordinates(values: np.ndarray, precision: float | None) -> BlockModel:
        return BlockModel(
            count=len(values),
            columns={
                axis: ColumnModel(
                    dtype="f64", shape=(len(values),), values=values[:, i], precision=precision
                )
                for i, axis in enumerate("xyz")
            },
        )

    frames = []
    for _ in range(4):
        positions = positions + rng.normal(0.0, 0.05, positions.shape)
        frames.append(FrameModel(blocks={"atoms": coordinates(positions.copy(), None)}))
    declared = {
        "atoms": SequenceBlockModel(
            columns={axis: SequenceColumnModel(dtype="f64", precision=1e-3) for axis in "xyz"}
        )
    }
    return RecordModel(
        meta=MetaModel(molrec_version=MOLREC_VERSION),
        frame=FrameModel(blocks={"atoms": coordinates(positions, 1e-3)}),
        trajectory=TrajectoryModel(frames=frames, step=[0, 10, 20, 30], blocks=declared),
    )


def pack(directory: Path, archive: Path) -> None:
    """``*.mrec/`` -> ``*.mrec.zip`` by the at-rest rules of ``docs/spec/chunking.md``:
    one stored entry per file, paths relative to the root, no directory entries."""
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(directory).as_posix())


class _ZipRecordStore(ZarrRecordStore):
    def root(self, mode: str = "r") -> zarr.Group:
        return zarr.open_group(store=zarr.storage.ZipStore(self.path, mode="r"), mode="r")


def test_the_precision_fixture_is_what_the_reference_writer_emits() -> None:
    model = precision_fixture_model()
    assert ZarrRecordCodec().read(_ZipRecordStore(FIXTURE)) == model
    with zipfile.ZipFile(FIXTURE) as zf:
        names = zf.namelist()
        assert all(info.compress_type == zipfile.ZIP_STORED for info in zf.infolist())
        codecs = json.loads(zf.read("trajectory/atoms/x/zarr.json"))["codecs"]
    assert not any(name.endswith("/") for name in names)
    inner = codecs[0]["configuration"]["codecs"]
    assert [codec["name"] for codec in inner] == ["bytes", "numcodecs.shuffle", "zstd", "crc32c"]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        live = ZarrRecordStore(Path(tmp) / "precision.mrec")
        ZarrRecordCodec().write(precision_fixture_model(), live)
        FIXTURE.unlink(missing_ok=True)
        pack(live.path, FIXTURE)
    print(FIXTURE)
