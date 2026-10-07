"""Store-level pins for the LMDB binding.

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
    LmdbCollectionStore,
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
        meta=CollectionMetaModel(units={"length": "angstrom"}),
        records=[RecordModel(meta=MetaModel(), trajectory=trajectory)],
    )


class TestLmdbCollectionCodec:
    def test_an_unchanged_block_is_written_once(self, tmp_path):
        store = LmdbCollectionStore(tmp_path / "c.mrec.lmdb")
        LmdbCollectionCodec().write(_collection(), store)
        env = store.open()
        with env.begin() as txn:
            rows = [decode_frame(txn.get(key(FRAME_PREFIX, j))) for j in range(3)]
        env.close()
        assert set(rows[0].blocks) == {"atoms", "bonds"}
        assert [set(row.blocks) for row in rows[1:]] == [{"atoms"}, {"atoms"}]

    def test_a_store_without_meta_is_refused(self, tmp_path):
        store = LmdbCollectionStore(tmp_path / "c.mrec.lmdb")
        LmdbCollectionCodec().write(_collection(), store)
        env = store.open(write=True)
        with env.begin(write=True) as txn:
            txn.delete(META_KEY)
        env.close()
        with pytest.raises(ValueError, match="not a committed collection"):
            LmdbCollectionCodec().read(store)

    def test_the_collection_document_is_written_as_given(self, tmp_path):
        collection = _collection()
        store = LmdbCollectionStore(tmp_path / "c.mrec.lmdb")
        LmdbCollectionCodec().write(collection, store)
        env = store.open()
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
        meta=CollectionMetaModel(units={}),
        records=[
            RecordModel(meta=MetaModel(), system=empty_atoms),
            _collection().records[0],
        ],
    )
    store = LmdbCollectionStore(tmp_path / "n.mrec.lmdb")
    LmdbCollectionCodec().write(collection, store)
    env = store.open()
    with env.begin() as txn:
        index = decode_frame(txn.get(INDEX_KEY)).blocks[INDEX_BLOCK]
    env.close()
    assert index.columns["n_atoms"].values.tolist() == [0, 2]
    assert index.columns["has_trajectory"].values.tolist() == [False, True]
