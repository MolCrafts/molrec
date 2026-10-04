"""The LMDB binding: a collection in one file (``docs/spec/lmdb.md``).

Two codecs: a :class:`~molrec.core.model.CollectionModel` (module
``collection``), and a bare trajectory (module ``trajectory``), which is a
collection of one record with no system -- the same bytes, one door.

Layout::

    meta                      JSON: layout tag, collection meta, sequence_schema, counts
    index                     frame bytes: block ``records`` (first_frame, n_frames, n_atoms, ...)
    r <u64be>                 JSON: record r's meta document
    s <u64be>                 frame bytes: record r's system (absent = no system)
    f <u64be>                 frame bytes: the trajectory update at global ordinal j

A trajectory update holds only the blocks that changed at its ordinal, so a
section costs what it changes -- the sparse semantics of the ragged layout,
one row per frame. ``meta`` is written last and is the commit marker.

``lmdb`` is imported where a store is opened, not here, so importing molrec
registers the binding without requiring the backend (``pip install
molrec[lmdb]``).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from molrec.binding import Binding, Codec
from molrec.core.model import (
    DTYPES,
    NUMPY_DTYPE,
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    RecordModel,
    SequenceSchemaModel,
    TrajectoryBoxModel,
    TrajectoryModel,
)
from molrec.core.store import CollectionStore, TrajectoryStore
from molrec.registry import REGISTRY

MAGIC = b"MRF1"
LAYOUT = "mrec-lmdb"
LAYOUT_VERSION = 1
META_KEY = b"meta"
INDEX_KEY = b"index"
INDEX_BLOCK = "records"
RECORD_META_PREFIX = b"r"
SYSTEM_PREFIX = b"s"
FRAME_PREFIX = b"f"
ALIGN = 8
#: The map size the writer reserves. LMDB grows the file only as data lands;
#: this is an address-space bound, not an allocation.
MAP_SIZE = 1 << 40

_HEADER = struct.Struct("<4sI")


def key(prefix: bytes, n: int) -> bytes:
    """``prefix`` then ``n`` as a big-endian u64: byte order is numeric order."""
    return prefix + int(n).to_bytes(8, "big")


# ---------------------------------------------------------------------------
# Frame bytes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameBytes:
    """What one frame-bytes value holds."""

    blocks: dict[str, BlockModel]
    meta: dict[str, Any]
    step: int | None = None
    time: float | None = None
    box: BoxModel | None = None


def encode_frame(
    blocks: dict[str, BlockModel],
    meta: dict[str, Any],
    *,
    step: int | None = None,
    time: float | None = None,
    box: BoxModel | None = None,
) -> bytes:
    """One frame as ``magic | u32 header length | JSON header | pad | buffers``.

    Args:
        blocks: The blocks this value carries.
        meta: A JSON-serialisable meta document.
        step: A trajectory update's step number.
        time: A trajectory update's time.
        box: The cell, when this value states it.

    Returns:
        The encoded value.
    """
    header_blocks: dict[str, Any] = {}
    buffers: list[bytes] = []
    offset = 0
    for name, block in blocks.items():
        columns: dict[str, Any] = {}
        for column_name, column in block.columns.items():
            entry: dict[str, Any] = {"dtype": column.dtype, "shape": list(column.shape)}
            values = column.values
            if column.dtype == "string":
                entry["values"] = (
                    [] if values is None else np.asarray(values).astype(str).ravel().tolist()
                )
            else:
                array = np.ascontiguousarray(
                    np.zeros(column.shape, dtype=NUMPY_DTYPE[column.dtype])
                    if values is None
                    else values,
                    dtype=np.dtype(NUMPY_DTYPE[column.dtype]).newbyteorder("<"),
                )
                raw = array.tobytes()
                entry["offset"] = offset
                buffers.append(raw)
                pad = (-len(raw)) % ALIGN
                if pad:
                    buffers.append(b"\0" * pad)
                offset += len(raw) + pad
            columns[column_name] = entry
        header_blocks[name] = {
            "count": block.count,
            "structural_shape": None
            if block.structural_shape is None
            else list(block.structural_shape),
            "columns": columns,
        }
    header: dict[str, Any] = {"blocks": header_blocks, "meta": meta}
    if step is not None:
        header["step"] = int(step)
    if time is not None:
        header["time"] = float(time)
    if box is not None:
        header["box"] = {
            "vectors": np.asarray(box.vectors, dtype="float64").tolist(),
            "origin": np.asarray(box.origin, dtype="float64").tolist(),
            "boundary": [bool(flag) for flag in box.boundary],
            "cell_defined": bool(box.cell_defined),
        }
    text = json.dumps(header, separators=(",", ":")).encode()
    head = _HEADER.pack(MAGIC, len(text)) + text
    head += b"\0" * ((-len(head)) % ALIGN)
    return head + b"".join(buffers)


def decode_frame(value: bytes | memoryview) -> FrameBytes:
    """Decode one frame-bytes value; numeric columns are views where aligned.

    Raises:
        ValueError: unknown magic, a dtype outside the closed set, a misaligned
            offset, or a buffer that runs past the value.
    """
    view = memoryview(value)
    if len(view) < _HEADER.size:
        raise ValueError("frame bytes shorter than their fixed header")
    magic, length = _HEADER.unpack_from(view, 0)
    if magic != MAGIC:
        raise ValueError(f"frame bytes carry magic {bytes(magic)!r}, expected {MAGIC!r}")
    start = _HEADER.size
    header = json.loads(bytes(view[start : start + length]))
    payload = start + length
    payload += (-payload) % ALIGN
    blocks: dict[str, BlockModel] = {}
    for name, entry in header["blocks"].items():
        columns: dict[str, ColumnModel] = {}
        for column_name, spec in entry["columns"].items():
            dtype = spec["dtype"]
            if dtype not in DTYPES:
                raise ValueError(f"{name}/{column_name}: dtype {dtype!r} is outside the closed set")
            shape = tuple(int(n) for n in spec["shape"])
            if dtype == "string":
                values = np.asarray(spec["values"], dtype=str).reshape(shape)
            else:
                at = int(spec["offset"])
                if at % ALIGN:
                    raise ValueError(f"{name}/{column_name}: offset {at} is not a multiple of 8")
                numpy_dtype = np.dtype(NUMPY_DTYPE[dtype]).newbyteorder("<")
                size = int(np.prod(shape)) * numpy_dtype.itemsize
                begin = payload + at
                if begin + size > len(view):
                    raise ValueError(f"{name}/{column_name}: buffer runs past the value")
                values = (
                    np.frombuffer(view, dtype=numpy_dtype, count=int(np.prod(shape)), offset=begin)
                    .reshape(shape)
                    .astype(NUMPY_DTYPE[dtype], copy=False)
                )
            columns[column_name] = ColumnModel(dtype=dtype, shape=shape, values=values)
        grid = entry.get("structural_shape")
        blocks[name] = BlockModel(
            count=int(entry["count"]),
            columns=columns,
            structural_shape=None if grid is None else tuple(grid),
        )
    box = header.get("box")
    return FrameBytes(
        blocks=blocks,
        meta=header.get("meta", {}),
        step=header.get("step"),
        time=header.get("time"),
        box=None
        if box is None
        else BoxModel(
            vectors=np.asarray(box["vectors"], dtype="float64"),
            origin=np.asarray(box["origin"], dtype="float64"),
            boundary=tuple(bool(flag) for flag in box["boundary"]),
            cell_defined=bool(box["cell_defined"]),
        ),
    )


def _step_meta_out(value: Any, series: MetaSeriesModel) -> Any:
    """A per-step value as JSON, at its declared exact type."""
    if series.dtype == "json":
        return value
    array = np.asarray(value, dtype=NUMPY_DTYPE[series.element_dtype])
    if np.iscomplexobj(array):
        return np.stack([array.real, array.imag], axis=-1).tolist()
    return array.tolist()


def _step_meta_in(value: Any, series: MetaSeriesModel) -> Any:
    if series.dtype == "json":
        return value
    if series.element_dtype in ("c64", "c128"):
        pairs = np.asarray(value, dtype="float64")
        return (
            (pairs[..., 0] + 1j * pairs[..., 1]).astype(NUMPY_DTYPE[series.element_dtype]).tolist()
        )
    return np.asarray(value, dtype=NUMPY_DTYPE[series.element_dtype]).tolist()


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


class LmdbCollectionStore(CollectionStore):
    """One ``*.mrec.lmdb`` file holding a collection."""

    backend: ClassVar[str] = "lmdb"

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def uri(self) -> str:
        return str(self._path)

    def open(self, *, write: bool = False) -> Any:
        """The LMDB environment, single file, one unnamed database."""
        import lmdb

        if write:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        return lmdb.open(
            str(self._path),
            subdir=False,
            readonly=not write,
            lock=write,
            map_size=MAP_SIZE,
            max_dbs=0,
        )

    def clear(self) -> None:
        for suffix in ("", "-lock"):
            target = Path(str(self._path) + suffix)
            if target.exists():
                target.unlink()


class LmdbTrajectoryStore(LmdbCollectionStore, TrajectoryStore):
    """A collection of one record holding one bare trajectory."""


# ---------------------------------------------------------------------------
# Codecs
# ---------------------------------------------------------------------------


class LmdbCollectionCodec(Codec):
    """The official translation of a collection. Thin: it is the arbiter."""

    def write(self, model: CollectionModel, store: LmdbCollectionStore) -> None:
        model = CollectionModel.model_validate(model.model_dump())
        schema = model.sequence_schema or SequenceSchemaModel()
        store.clear()
        env = store.open(write=True)
        first_frame: list[int] = []
        n_frames: list[int] = []
        n_atoms: list[int] = []
        ordinal = 0
        try:
            with env.begin(write=True) as txn:
                for r, record in enumerate(model.records):
                    txn.put(
                        key(RECORD_META_PREFIX, r),
                        json.dumps(record.meta.model_dump(mode="json", exclude_none=True)).encode(),
                    )
                    atoms = 0
                    if record.system is not None:
                        system = record.system
                        txn.put(
                            key(SYSTEM_PREFIX, r),
                            encode_frame(system.blocks, system.meta, box=system.box),
                        )
                        if "atoms" in system.blocks:
                            atoms = system.blocks["atoms"].count
                    first_frame.append(ordinal)
                    frames = 0
                    if record.trajectory is not None:
                        opening = (
                            record.trajectory.frames[0].blocks if record.trajectory.frames else {}
                        )
                        if not atoms and "atoms" in opening:
                            atoms = opening["atoms"].count
                        for value in self._updates(record.trajectory, schema):
                            txn.put(key(FRAME_PREFIX, ordinal), value)
                            ordinal += 1
                            frames += 1
                    n_frames.append(frames)
                    n_atoms.append(atoms)
                index = model.index
                columns = dict(index.columns)
                for name, values in (
                    ("first_frame", first_frame),
                    ("n_frames", n_frames),
                    ("n_atoms", n_atoms),
                ):
                    array = np.asarray(values, dtype="uint64").reshape(len(model.records))
                    columns[name] = ColumnModel(dtype="u64", shape=array.shape, values=array)
                txn.put(
                    INDEX_KEY,
                    encode_frame(
                        {INDEX_BLOCK: BlockModel(count=len(model.records), columns=columns)}, {}
                    ),
                )
                txn.put(
                    META_KEY,
                    json.dumps(
                        {
                            "layout": LAYOUT,
                            "layout_version": LAYOUT_VERSION,
                            "collection": model.meta.model_dump(mode="json", exclude_none=True),
                            "sequence_schema": schema.model_dump(mode="json", exclude_none=True),
                            "n_records": len(model.records),
                            "n_frames": ordinal,
                        }
                    ).encode(),
                )
        finally:
            env.close()

    @staticmethod
    def _updates(trajectory: TrajectoryModel, schema: SequenceSchemaModel) -> list[bytes]:
        """One value per frame: the blocks that changed there, plus step, meta, box."""
        cells = {
            update.step_index: update.box
            for update in (trajectory.box.updates if trajectory.box else [])
        }
        values: list[bytes] = []
        carried: dict[str, BlockModel] = {}
        for ordinal, frame in enumerate(trajectory.frames):
            changed = {
                name: block for name, block in frame.blocks.items() if carried.get(name) != block
            }
            carried.update(frame.blocks)
            meta = {k: _step_meta_out(v, schema.meta[k]) for k, v in frame.meta.items()}
            values.append(
                encode_frame(
                    changed,
                    meta,
                    step=trajectory.step[ordinal],
                    time=None if trajectory.time is None else trajectory.time[ordinal],
                    box=cells.get(ordinal),
                )
            )
        return values

    def read(self, store: LmdbCollectionStore) -> CollectionModel:
        env = store.open()
        try:
            with env.begin() as txn:
                raw = txn.get(META_KEY)
                if raw is None:
                    raise ValueError(f"{store.path}: no 'meta' key -- not a committed collection")
                meta = json.loads(bytes(raw))
                if meta.get("layout") != LAYOUT:
                    raise ValueError(
                        f"{store.path}: layout {meta.get('layout')!r}, expected {LAYOUT!r}"
                    )
                schema = SequenceSchemaModel.model_validate(meta["sequence_schema"])
                index = decode_frame(txn.get(INDEX_KEY)).blocks[INDEX_BLOCK]
                n_records, total = int(meta["n_records"]), int(meta["n_frames"])
                first = index.columns["first_frame"].values.astype(int)
                counts = index.columns["n_frames"].values.astype(int)
                if index.count != n_records:
                    raise ValueError(f"index has {index.count} rows, meta says {n_records} records")
                expected = np.concatenate([[0], np.cumsum(counts)[:-1]]) if n_records else first
                if not np.array_equal(first, expected) or int(counts.sum()) != total:
                    raise ValueError("index first_frame is not the prefix sum of n_frames")
                records = [
                    self._record(txn, r, int(first[r]), int(counts[r]), schema)
                    for r in range(n_records)
                ]
        finally:
            env.close()
        own = {
            name: column
            for name, column in index.columns.items()
            if name not in ("first_frame", "n_frames", "n_atoms")
        }
        return CollectionModel(
            meta=CollectionMetaModel.model_validate(meta["collection"]),
            sequence_schema=schema if (schema.blocks or schema.meta) else None,
            index=BlockModel(count=n_records, columns=own),
            records=records,
        )

    def _record(
        self, txn: Any, r: int, first: int, count: int, schema: SequenceSchemaModel
    ) -> RecordModel:
        system = None
        raw = txn.get(key(SYSTEM_PREFIX, r))
        if raw is not None:
            decoded = decode_frame(raw)
            system = FrameModel(blocks=decoded.blocks, meta=decoded.meta, box=decoded.box)
        trajectory = None
        if count:
            frames, steps, times, cells = [], [], [], []
            for j in range(count):
                raw = txn.get(key(FRAME_PREFIX, first + j))
                if raw is None:
                    raise ValueError(f"record {r}: frame {first + j} is missing")
                decoded = decode_frame(raw)
                for name in decoded.blocks:
                    if name not in schema.blocks:
                        raise ValueError(f"frame {first + j} carries undeclared block {name!r}")
                frames.append(
                    FrameModel(
                        blocks=decoded.blocks,
                        meta={k: _step_meta_in(v, schema.meta[k]) for k, v in decoded.meta.items()},
                    )
                )
                steps.append(int(decoded.step))
                times.append(decoded.time)
                if decoded.box is not None:
                    cells.append(BoxUpdateModel(step_index=j, box=decoded.box))
            trajectory = TrajectoryModel(
                frames=frames,
                step=steps,
                time=None if all(t is None for t in times) else times,
                blocks=schema.blocks,
                meta=schema.meta,
                box=TrajectoryBoxModel(updates=cells, cell_defined=cells[0].box.cell_defined)
                if cells
                else None,
            )
        raw = txn.get(key(RECORD_META_PREFIX, r))
        meta = MetaModel.model_validate(json.loads(bytes(raw)) if raw is not None else {})
        return RecordModel(meta=meta, system=system, trajectory=trajectory)


class LmdbTrajectoryCodec(Codec):
    """A bare trajectory: a collection of one record with no system."""

    #: The units a bare trajectory's collection states. A trajectory carries
    #: no unit declaration of its own (``docs/spec/trajectory.md``), so the
    #: one-record collection wrapping it states none it could be wrong about.
    UNITS: ClassVar[dict[str, str]] = {}

    def write(self, model: TrajectoryModel, store: LmdbTrajectoryStore) -> None:
        model = TrajectoryModel.model_validate(model.model_dump())
        LmdbCollectionCodec().write(
            CollectionModel(
                meta=CollectionMetaModel(units=dict(self.UNITS)),
                records=[RecordModel(meta=MetaModel(), trajectory=model)],
            ),
            store,
        )

    def read(self, store: LmdbTrajectoryStore) -> TrajectoryModel:
        collection = LmdbCollectionCodec().read(store)
        if len(collection.records) != 1 or collection.records[0].trajectory is None:
            raise ValueError(f"{store.path}: not a one-trajectory collection")
        return collection.records[0].trajectory


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


@REGISTRY.binding
class LmdbCollectionBinding(Binding):
    module: ClassVar[str] = "collection"
    backend: ClassVar[str] = "lmdb"

    def new_store(self, workdir: Path) -> LmdbCollectionStore:
        store = LmdbCollectionStore(workdir.with_suffix(".mrec.lmdb"))
        store.clear()
        return store

    def codec(self) -> LmdbCollectionCodec:
        return LmdbCollectionCodec()


@REGISTRY.binding
class LmdbTrajectoryBinding(Binding):
    module: ClassVar[str] = "trajectory"
    backend: ClassVar[str] = "lmdb"

    def new_store(self, workdir: Path) -> LmdbTrajectoryStore:
        store = LmdbTrajectoryStore(workdir.with_suffix(".mrec.lmdb"))
        store.clear()
        return store

    def codec(self) -> LmdbTrajectoryCodec:
        return LmdbTrajectoryCodec()


__all__ = [
    "FrameBytes",
    "LmdbCollectionBinding",
    "LmdbCollectionCodec",
    "LmdbCollectionStore",
    "LmdbTrajectoryBinding",
    "LmdbTrajectoryCodec",
    "LmdbTrajectoryStore",
    "decode_frame",
    "encode_frame",
    "key",
]
