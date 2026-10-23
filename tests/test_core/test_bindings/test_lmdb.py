"""Storage-level pins for the LMDB binding.

Mirrors ``src/molrec/core/bindings/lmdb.py``.

The conformance suites judge the logical round trip; these look at what the
spec names on disk (``docs/spec/lmdb.md``): a frame row holds only the blocks
that changed there, every column buffer is 8-byte aligned, ``meta`` is the
commit marker, and a value with a foreign magic is refused.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from molrec.core.bindings.lmdb import (
    FRAME_PREFIX,
    META_KEY,
    LmdbCollectionCodec,
    LmdbCollectionStorage,
    LmdbTrajectoryCodec,
    LmdbTrajectoryStorage,
    decode_frame,
    encode_frame,
    key,
)
from molrec.core.model import (
    BlockModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    RecordModel,
    TrajectoryModel,
    document,
)


def _column(dtype: str, values: list) -> ColumnModel:
    numpy = {"f64": "float64", "u64": "uint64", "i8": "int8", "string": str}[dtype]
    array = np.asarray(values, dtype=numpy)
    return ColumnModel(dtype=dtype, shape=array.shape, values=array)


def _collection() -> CollectionModel:
    bonds = BlockModel(
        count=1, columns={"atomi": _column("u64", [0]), "atomj": _column("u64", [1])}
    )
    frames = [
        FrameModel(
            blocks={
                "atoms": BlockModel(count=2, columns={"x": _column("f64", [x, x + 1])}),
                "bonds": bonds,
            },
            meta={"pe": -x},
        )
        for x in (0.0, 0.5, 1.0)
    ]
    trajectory = TrajectoryModel(
        frames=frames, step=[0, 1, 2], meta={"pe": MetaSeriesModel(dtype="f64")}
    )
    return CollectionModel(
        meta=CollectionMetaModel(units={"length": "angstrom", "energy": "kcal/mol"}),
        records=[RecordModel(meta=MetaModel(), trajectory=trajectory)],
    )


class TestLmdbCollectionCodec:
    def test_an_unchanged_block_is_written_once(self, tmp_path):
        storage = LmdbCollectionStorage(tmp_path / "c.mrec.lmdb")
        LmdbCollectionCodec().write(_collection(), storage)
        env = storage.open()
        with env.begin() as txn:
            rows = [decode_frame(txn.get(key(FRAME_PREFIX, j))) for j in range(3)]
        env.close()
        assert set(rows[0].blocks) == {"atoms", "bonds"}
        assert [set(row.blocks) for row in rows[1:]] == [{"atoms"}, {"atoms"}]

    def test_a_storage_without_meta_is_refused(self, tmp_path):
        storage = LmdbCollectionStorage(tmp_path / "c.mrec.lmdb")
        LmdbCollectionCodec().write(_collection(), storage)
        env = storage.open(write=True)
        with env.begin(write=True) as txn:
            txn.delete(META_KEY)
        env.close()
        with pytest.raises(ValueError, match="not a committed collection"):
            LmdbCollectionCodec().read(storage)

    def test_the_collection_document_is_written_as_given(self, tmp_path):
        collection = _collection()
        storage = LmdbCollectionStorage(tmp_path / "c.mrec.lmdb")
        LmdbCollectionCodec().write(collection, storage)
        env = storage.open()
        with env.begin() as txn:
            meta = json.loads(bytes(txn.get(META_KEY)))
        env.close()
        assert meta["layout"] == "mrec-lmdb"
        assert meta["collection"] == document(collection.meta)


class TestFrameBytes:
    def test_every_buffer_is_eight_byte_aligned(self):
        # An odd-length int8 column first puts the next buffer off 8 unless padded.
        block = BlockModel(
            count=3,
            columns={"flag": _column("i8", [1, 2, 3]), "x": _column("f64", [0.0, 1.0, 2.0])},
        )
        value = encode_frame({"atoms": block}, {})
        decoded = decode_frame(value)
        x = decoded.blocks["atoms"].columns["x"].values
        np.testing.assert_array_equal(x, [0.0, 1.0, 2.0])
        assert (
            x.__array_interface__["data"][0]
            - np.frombuffer(value, dtype="u1").__array_interface__["data"][0]
        ) % 8 == 0

    def test_a_foreign_magic_is_refused(self):
        value = bytearray(encode_frame({}, {}))
        value[:4] = b"XXXX"
        with pytest.raises(ValueError, match="magic"):
            decode_frame(bytes(value))


def test_n_atoms_is_the_system_count_even_when_zero(tmp_path):
    from molrec.core.bindings.lmdb import INDEX_BLOCK, INDEX_KEY

    empty_atoms = FrameModel(blocks={"atoms": BlockModel(count=0)})
    collection = CollectionModel(
        meta=CollectionMetaModel(units={"length": "angstrom", "energy": "kcal/mol"}),
        records=[
            RecordModel(meta=MetaModel(), system=empty_atoms),
            _collection().records[0],
        ],
    )
    storage = LmdbCollectionStorage(tmp_path / "n.mrec.lmdb")
    LmdbCollectionCodec().write(collection, storage)
    env = storage.open()
    with env.begin() as txn:
        index = decode_frame(txn.get(INDEX_KEY)).blocks[INDEX_BLOCK]
    env.close()
    assert index.columns["n_atoms"].values.tolist() == [0, 2]
    assert index.columns["has_trajectory"].values.tolist() == [False, True]


class TestColumnUnit:
    def test_header_stores_unit_beside_precision(self) -> None:
        values = np.array([1.0])
        stated = ColumnModel(dtype="f64", shape=values.shape, values=values, unit="nm")
        bare = ColumnModel(dtype="f64", shape=values.shape, values=values)
        stated_frame = decode_frame(
            encode_frame({"atoms": BlockModel(count=1, columns={"x": stated})}, {})
        )
        bare_frame = decode_frame(
            encode_frame({"atoms": BlockModel(count=1, columns={"x": bare})}, {})
        )
        assert stated_frame.blocks["atoms"].columns["x"].unit == "nm"
        assert bare_frame.blocks["atoms"].columns["x"].unit is None

    def test_bare_trajectory_round_trips_without_units(self, tmp_path) -> None:
        values = np.array([1.0])
        model = TrajectoryModel(
            frames=[
                FrameModel(
                    blocks={
                        "atoms": BlockModel(
                            count=1,
                            columns={
                                "x": ColumnModel(dtype="f64", shape=values.shape, values=values)
                            },
                        )
                    }
                )
            ],
            step=[0],
        )
        storage = LmdbTrajectoryStorage(tmp_path / "bare.mrec.lmdb")
        LmdbTrajectoryCodec().write(model, storage)
        back = LmdbTrajectoryCodec().read(storage)
        assert back.frames[0].blocks["atoms"].columns["x"].values.tolist() == [1.0]
