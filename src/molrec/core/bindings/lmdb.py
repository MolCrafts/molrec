"""The LMDB binding: a collection in one file (``docs/spec/lmdb.md``).

Two codecs: a :class:`~molrec.core.model.CollectionModel` (module
``collection``), and a bare trajectory (module ``trajectory``), which is a
collection of one record with no system -- the same bytes, one door.

Layout::

    meta                      JSON: layout tag, collection meta, sequence_schema, counts
    index                     frame bytes: block ``records`` (first_frame, n_frames, n_atoms, ...)
    ff                        frame bytes: the collection's force field (absent = none)
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

from molrec import jsonvalue
from molrec.binding import Binding, Codec
from molrec.core.model import (
    DTYPES,
    META_TYPES_ATTR,
    MOLREC_VERSION,
    NUMPY_DTYPE,
    RESERVED_INDEX_COLUMNS,
    STORED,
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    ForceFieldModel,
    FrameModel,
    MetaModel,
    RecordModel,
    SequenceSchemaModel,
    TrajectoryBoxModel,
    TrajectoryModel,
    check_target,
    decode_meta_value,
    decode_typed_meta,
    document,
    encode_meta_value,
    encode_typed_meta,
    revalidated,
    same_bits,
    stamp_version,
)
from molrec.core.store import CollectionStore, TrajectoryStore
from molrec.core.v1 import V1Upgrade, read_version
from molrec.registry import REGISTRY

MAGIC = b"MRF1"
LAYOUT = "mrec-lmdb"
LAYOUT_VERSION = 1
META_KEY = b"meta"
INDEX_KEY = b"index"
#: The collection's one force field: frame bytes whose ``meta`` is the
#: force-field document and whose blocks are its style tables.
FF_KEY = b"ff"
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
    #: The tag of every ``meta`` key, on a value that types its meta document
    #: itself (a system frame); ``None`` where a declaration types it.
    meta_types: dict[str, str] | None = None
    step: int | None = None
    time: float | None = None
    box: BoxModel | None = None


def encode_frame(
    blocks: dict[str, BlockModel],
    meta: dict[str, Any],
    *,
    meta_types: dict[str, str] | None = None,
    step: int | None = None,
    time: float | None = None,
    box: BoxModel | None = None,
) -> bytes:
    """One frame as ``magic | u32 header length | JSON header | pad | buffers``.

    Args:
        blocks: The blocks this value carries.
        meta: The meta document: already in its typed JSON forms (a
            trajectory update, typed by the declaration), or -- with
            ``meta_types`` -- plain values typed by those tags.
        meta_types: Types ``meta`` itself (a system frame): every value is
            written in its tag's typed JSON form and the header carries
            ``meta_types``.
        step: A trajectory update's step number.
        time: A trajectory update's time.
        box: The cell, when this value states it.

    Returns:
        The encoded value.
    """
    header_blocks: dict[str, Any] = {}
    buffers: list[bytes] = []
    offset = 0

    def land(raw: bytes) -> int:
        """Append one buffer, padded to the next multiple of 8; its offset."""
        nonlocal offset
        at = offset
        buffers.append(raw)
        pad = (-len(raw)) % ALIGN
        if pad:
            buffers.append(b"\0" * pad)
        offset += len(raw) + pad
        return at

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
                entry["offset"] = land(array.tobytes())
            if column.validity is not None:
                entry["validity"] = land(np.ascontiguousarray(column.validity, "bool").tobytes())
            if column.precision is not None:
                entry["precision"] = column.precision
            columns[column_name] = entry
        header_blocks[name] = {
            "count": block.count,
            "structural_shape": None
            if block.structural_shape is None
            else list(block.structural_shape),
            "columns": columns,
        }
        if block.targets is not None:
            for column_name, target in block.targets.items():
                check_target(column_name, target)
            header_blocks[name]["targets"] = dict(block.targets)
        if block.model_extra:
            header_blocks[name]["attributes"] = jsonvalue.check_document(block.model_extra)
    if meta_types is None:
        header: dict[str, Any] = {"blocks": header_blocks, "meta": jsonvalue.check_document(meta)}
    else:
        typed = encode_typed_meta(meta, meta_types)
        tags = typed.pop(META_TYPES_ATTR, {})
        header = {"blocks": header_blocks, "meta": typed, "meta_types": tags}
    if step is not None:
        header["step"] = jsonvalue.encode("i64", step)
    if time is not None:
        header["time"] = jsonvalue.encode("f64", time)
    if box is not None:
        header["box"] = {
            "vectors": np.asarray(box.vectors, dtype="float64").tolist(),
            "origin": np.asarray(box.origin, dtype="float64").tolist(),
            "boundary": [bool(flag) for flag in box.boundary],
            "cell_defined": bool(box.cell_defined),
        }
    text = jsonvalue.dumps(header).encode()
    head = _HEADER.pack(MAGIC, len(text)) + text
    head += b"\0" * ((-len(head)) % ALIGN)
    return head + b"".join(buffers)


def _buffer(
    view: memoryview, payload: int, at: int, dtype: str, shape: tuple[int, ...]
) -> np.ndarray:
    """One column buffer at ``at`` bytes into the payload, viewed in place."""
    if at % ALIGN:
        raise ValueError(f"offset {at} is not a multiple of 8")
    numpy_dtype = np.dtype(NUMPY_DTYPE[dtype]).newbyteorder("<")
    count = int(np.prod(shape))
    begin = payload + at
    if begin + count * numpy_dtype.itemsize > len(view):
        raise ValueError("buffer runs past the value")
    return (
        np.frombuffer(view, dtype=numpy_dtype, count=count, offset=begin)
        .reshape(shape)
        .astype(NUMPY_DTYPE[dtype], copy=False)
    )


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
                try:
                    values = _buffer(view, payload, int(spec["offset"]), dtype, shape)
                except ValueError as exc:
                    raise ValueError(f"{name}/{column_name}: {exc}") from None
            validity = None
            if "validity" in spec:
                validity = _buffer(view, payload, int(spec["validity"]), "bool", (shape[0],))
            # Stored values come back exactly: a reader never re-rounds.
            columns[column_name] = ColumnModel.model_validate(
                {
                    "dtype": dtype,
                    "shape": shape,
                    "values": values,
                    "validity": validity,
                    "precision": spec.get("precision"),
                },
                context=STORED,
            )
        grid = entry.get("structural_shape")
        blocks[name] = BlockModel(
            count=int(entry["count"]),
            columns=columns,
            structural_shape=None if grid is None else tuple(grid),
            targets=entry.get("targets"),
            **entry.get("attributes", {}),
        )
    box = header.get("box")
    return FrameBytes(
        blocks=blocks,
        meta=header.get("meta", {}),
        meta_types=header.get("meta_types"),
        step=None if header.get("step") is None else jsonvalue.decode("i64", header["step"]),
        time=None if header.get("time") is None else jsonvalue.decode("f64", header["time"]),
        box=None
        if box is None
        else BoxModel(
            vectors=np.asarray(box["vectors"], dtype="float64"),
            origin=np.asarray(box["origin"], dtype="float64"),
            boundary=tuple(bool(flag) for flag in box["boundary"]),
            cell_defined=bool(box["cell_defined"]),
        ),
    )


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
        # Readers take LMDB's reader lock too: without it a reader cannot
        # be told apart from a writer's free pages.
        return lmdb.open(
            str(self._path),
            subdir=False,
            readonly=not write,
            lock=True,
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
        model = revalidated(model)
        schema = model.sequence_schema or SequenceSchemaModel()
        store.clear()
        env = store.open(write=True)
        derived: dict[str, list[int]] = {name: [] for name in RESERVED_INDEX_COLUMNS}
        ordinal = 0
        try:
            with env.begin(write=True) as txn:
                for r, record in enumerate(model.records):
                    txn.put(
                        key(RECORD_META_PREFIX, r), jsonvalue.dumps(document(record.meta)).encode()
                    )
                    if record.system is not None:
                        system = record.system
                        txn.put(
                            key(SYSTEM_PREFIX, r),
                            encode_frame(
                                system.blocks,
                                system.meta,
                                meta_types=system.meta_types,
                                box=system.box,
                            ),
                        )
                    derived["first_frame"].append(ordinal)
                    frames = 0
                    if record.trajectory is not None:
                        for value in self._updates(record.trajectory, schema):
                            txn.put(key(FRAME_PREFIX, ordinal), value)
                            ordinal += 1
                            frames += 1
                    derived["n_frames"].append(frames)
                    derived["n_atoms"].append(_atom_count(record))
                    derived["has_trajectory"].append(int(record.trajectory is not None))
                columns = dict(model.index.columns)
                for name, values in derived.items():
                    array = np.asarray(values, dtype="uint64").reshape(len(model.records))
                    if name == "has_trajectory":
                        array = array.astype("bool")
                        columns[name] = ColumnModel(dtype="bool", shape=array.shape, values=array)
                    else:
                        columns[name] = ColumnModel(dtype="u64", shape=array.shape, values=array)
                txn.put(
                    INDEX_KEY,
                    encode_frame(
                        {INDEX_BLOCK: BlockModel(count=len(model.records), columns=columns)}, {}
                    ),
                )
                if model.forcefield is not None:
                    ff = model.forcefield
                    txn.put(FF_KEY, encode_frame(ff.tables, ff.document()))
                txn.put(
                    META_KEY,
                    jsonvalue.dumps(
                        {
                            "layout": LAYOUT,
                            "layout_version": LAYOUT_VERSION,
                            "collection": stamp_version(document(model.meta)),
                            "sequence_schema": schema.model_dump(mode="json"),
                            "n_records": len(model.records),
                            "n_frames": ordinal,
                        }
                    ).encode(),
                )
        finally:
            env.close()

    @staticmethod
    def _updates(trajectory: TrajectoryModel, schema: SequenceSchemaModel) -> list[bytes]:
        """One value per frame: the blocks that changed there (bit for bit,
        masks included), plus step, meta, and the cell where it changed."""
        cells = {
            update.step_index: BoxModel(
                vectors=update.box.vectors,
                origin=update.box.origin,
                boundary=update.box.boundary,
                cell_defined=trajectory.box.cell_defined,
            )
            for update in (trajectory.box.updates if trajectory.box else [])
        }
        values: list[bytes] = []
        carried: dict[str, BlockModel] = {}
        for ordinal, frame in enumerate(trajectory.frames):
            changed = {
                name: block
                for name, block in frame.blocks.items()
                if name not in carried or not same_bits(carried[name], block)
            }
            carried.update(frame.blocks)
            meta = {k: encode_meta_value(schema.meta[k].dtype, v) for k, v in frame.meta.items()}
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
                _check_layout_version(meta.get("layout_version"), store.path)
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
                # A record's trajectory may hold zero frames; only the flag says
                # it has one at all.
                flags = index.columns.get("has_trajectory")
                carries = [False] * n_records if flags is None else flags.values.tolist()
                raw = txn.get(FF_KEY)
                stored = None if raw is None else decode_frame(raw)
                # The collection's version covers every record: a version-1
                # collection's force field and frames are converted.
                CollectionMetaModel.model_validate(meta["collection"])
                upgrade = None
                if read_version(meta["collection"]) != MOLREC_VERSION:
                    upgrade = (
                        V1Upgrade() if stored is None else V1Upgrade(stored.meta, stored.blocks)
                    )
                records = [
                    self._record(
                        txn, r, int(first[r]), int(counts[r]), bool(carries[r]), schema, upgrade
                    )
                    for r in range(n_records)
                ]
                forcefield = None
                if stored is not None:
                    document, tables = stored.meta, stored.blocks
                    if upgrade is not None:
                        document, tables = upgrade.forcefield(document, tables)
                    forcefield = ForceFieldModel.model_validate({**document, "tables": tables})
        finally:
            env.close()
        own = {
            name: column
            for name, column in index.columns.items()
            if name not in RESERVED_INDEX_COLUMNS
        }
        return CollectionModel.model_validate(
            {
                "meta": CollectionMetaModel.model_validate(meta["collection"]),
                "sequence_schema": schema if (schema.blocks or schema.meta) else None,
                "index": BlockModel(count=n_records, columns=own),
                "forcefield": forcefield,
                "records": records,
            },
            context=STORED,
        )

    def _record(
        self,
        txn: Any,
        r: int,
        first: int,
        count: int,
        carries_trajectory: bool,
        schema: SequenceSchemaModel,
        upgrade: V1Upgrade | None = None,
    ) -> RecordModel:
        system = None
        raw = txn.get(key(SYSTEM_PREFIX, r))
        if raw is not None:
            decoded = decode_frame(raw)
            meta, meta_types = decode_typed_meta(
                {**decoded.meta, META_TYPES_ATTR: decoded.meta_types or {}}, f"record {r} system"
            )
            system = FrameModel(
                blocks=decoded.blocks, meta=meta, meta_types=meta_types, box=decoded.box
            )
        trajectory = None
        if count or carries_trajectory:
            frames, steps, times, cells, ordinals = [], [], [], [], []
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
                        meta={
                            k: decode_meta_value(schema.meta[k].dtype, v)
                            for k, v in decoded.meta.items()
                        },
                    )
                )
                steps.append(decoded.step)
                times.append(decoded.time)
                if decoded.box is not None:
                    cells.append(decoded.box)
                    ordinals.append(j)
            trajectory = TrajectoryModel.model_validate(
                {
                    "frames": frames,
                    "step": steps,
                    "time": None if all(t is None for t in times) else times,
                    "blocks": schema.blocks,
                    "meta": schema.meta,
                    "box": _cell_section(r, ordinals, cells),
                },
                context=STORED,
            )
        raw = txn.get(key(RECORD_META_PREFIX, r))
        meta = MetaModel.model_validate(json.loads(bytes(raw)) if raw is not None else {})
        if upgrade is not None:
            system = None if system is None else upgrade.frame(system)
            trajectory = None if trajectory is None else upgrade.trajectory(trajectory)
        return RecordModel(meta=meta, system=system, trajectory=trajectory)


def _check_layout_version(version: Any, path: Path) -> None:
    """``layout_version`` is the binding's own layout version: required, an
    integer in ``1..=LAYOUT_VERSION``. It is not ``molrec_version``, which the
    collection document carries under the record rule."""
    if type(version) is not int or not 1 <= version <= LAYOUT_VERSION:
        raise ValueError(
            f"{path}: layout_version {version!r} is not one this reader supports "
            f"(1..={LAYOUT_VERSION})"
        )


def _cell_section(r: int, ordinals: list[int], cells: list[BoxModel]) -> TrajectoryBoxModel | None:
    """A record's cell updates as one section: one ``cell_defined`` for all."""
    if not cells:
        return None
    defined = {cell.cell_defined for cell in cells}
    if len(defined) != 1:
        raise ValueError(f"record {r}: cell updates disagree on cell_defined")
    return TrajectoryBoxModel(
        updates=[
            BoxUpdateModel(
                step_index=j,
                box=CellModel(vectors=cell.vectors, origin=cell.origin, boundary=cell.boundary),
            )
            for j, cell in zip(ordinals, cells, strict=True)
        ],
        cell_defined=defined.pop(),
    )


def _atom_count(record: RecordModel) -> int:
    """``n_atoms``: the rows of the system's ``atoms`` block, else of the
    trajectory's first update of ``atoms``, else ``0`` -- a system block of
    zero rows is an answer, not a reason to look further."""
    if record.system is not None and "atoms" in record.system.blocks:
        return record.system.blocks["atoms"].count
    if record.trajectory is not None:
        for frame in record.trajectory.frames:
            if "atoms" in frame.blocks:
                return frame.blocks["atoms"].count
    return 0


class LmdbTrajectoryCodec(Codec):
    """A bare trajectory: a collection of one record with no system."""

    #: The units a bare trajectory's collection states. A trajectory carries
    #: no unit declaration of its own (``docs/spec/trajectory.md``), so the
    #: one-record collection wrapping it states none it could be wrong about.
    UNITS: ClassVar[dict[str, str]] = {}

    def write(self, model: TrajectoryModel, store: LmdbTrajectoryStore) -> None:
        model = revalidated(model)
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
