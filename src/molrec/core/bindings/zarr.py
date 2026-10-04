"""The Zarr V3 binding for the core module.

Three codecs: a frame, a sequence of frames, and the record root that carries
both. Each documents its own layout; the one below is the frame's, which the
other two build on.

Layout::

    <frame root>/               group attributes = the frame's meta document
    ├── <block>/                group attributes: count, structural_shape
    │   └── <column>            array
    └── box/                    group attribute cell_defined, only when false
        ├── vectors             f64[3][3]
        ├── origin              f64[3]   (optional; absent = zeros)
        └── boundary            bool[3]  (optional; absent = all periodic)

Blocks are flat children of the frame group. The frame's meta document is the
group's attribute map rather than a child, so ``box`` is the only reserved
name in that namespace -- a block may be called ``meta``, ``atoms``,
``values`` or anything else. A block named ``box`` is refused at write time
rather than silently overwriting the cell.

Two things are stored that a naive writer would think are derivable, and are
not:

* ``count`` -- a block with no columns still has one.
* ``structural_shape`` -- without it a volumetric column reads back flat and
  can never be reshaped. That is data loss, not an inconvenience.

The dtype mapping is exact and total in both directions, with every numeric
width explicit. Chunk extents, shards and codecs follow
``docs/spec/chunking.md``; none of them is contractual beyond the must-decode
codec set, and a conforming reader opens any chunking.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import zarr
from zarr.codecs import Crc32cCodec, GzipCodec

from molrec import jsonvalue
from molrec.binding import Binding, Codec
from molrec.chunking import (
    DENSE_CHUNKS_PER_SHARD,
    DENSE_ROWS_PER_CHUNK,
    chunks_per_shard,
    plan,
    row_bytes,
    rows_per_chunk,
)
from molrec.core.model import (
    NUMPY_DTYPE,
    RESERVED_BLOCK_NAMES,
    RESERVED_TRAJECTORY_NAMES,
    VALIDITY_GROUP,
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    ColumnModel,
    DType,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    MethodModel,
    RecordModel,
    SequenceBlockModel,
    SequenceSchemaModel,
    StatusModel,
    TrajectoryBoxModel,
    TrajectoryModel,
    coerce_meta_value,
    dtype_of,
    revalidated,
    same_bits,
    stamp_version,
)
from molrec.core.store import FrameStore, RecordStore, TrajectoryStore
from molrec.registry import REGISTRY
from molrec.store import Store

BOX_GROUP = "box"

#: molrec dtype -> the Zarr V3 dtype a conforming writer emits.
TO_ZARR: dict[DType, str] = {**NUMPY_DTYPE, "string": "string"}

#: Float columns are left uncompressed by default (``docs/spec/chunking.md``,
#: codec policy); every other array takes gzip level 1. crc32c closes every
#: inner pipeline.
FLOAT_DTYPES: frozenset[str] = frozenset({"f64", "c64", "c128"})

STRUCTURAL_SHAPE_ATTR = "structural_shape"
CELL_DEFINED_ATTR = "cell_defined"


def _itemsize(dtype: DType) -> int | None:
    """Bytes per element, or ``None`` for a variable-width dtype."""
    if dtype == "string":
        return None
    return np.dtype(NUMPY_DTYPE[dtype]).itemsize


def _compressors(dtype: DType, dense: bool) -> tuple[Any, ...]:
    """The bytes->bytes tail of an inner pipeline: (gzip-1)? then crc32c."""
    pipeline: list[Any] = [] if (dtype in FLOAT_DTYPES and not dense) else [GzipCodec(level=1)]
    pipeline.append(Crc32cCodec())
    return tuple(pipeline)


def create_fixed(group: zarr.Group, name: str, shape: tuple[int, ...], dtype: DType) -> zarr.Array:
    """A fixed-size (frame / system / observables) array, chunked per
    :func:`molrec.chunking.plan`: 512 KiB leading-axis chunks, one shard over
    the whole array above four of them, one chunk for a string, an empty or a
    0-d array."""
    chunks, shards = plan(shape, _itemsize(dtype))
    options: dict[str, Any] = {
        "chunks": chunks if chunks is not None else tuple(max(1, n) for n in shape)
    }
    if shards is not None:
        options["shards"] = shards
    return group.create_array(
        name,
        shape=shape,
        dtype=TO_ZARR[dtype],
        compressors=_compressors(dtype, dense=False),
        **options,
    )


def _create_sharded(
    group: zarr.Group,
    name: str,
    shape: tuple[int, ...],
    dtype: DType,
    rows: int,
    per_shard: int,
    dense: bool,
) -> zarr.Array:
    """A trajectory array: ``sharding_indexed`` with the index at the start."""
    return group.create_array(
        name,
        shape=shape,
        dtype=TO_ZARR[dtype],
        chunks=(rows, *shape[1:]),
        shards={"shape": (rows * per_shard, *shape[1:]), "index_location": "start"},
        compressors=_compressors(dtype, dense),
    )


def _create_dense(group: zarr.Group, name: str, shape: tuple[int, ...], dtype: DType) -> zarr.Array:
    """``step``, ``time``, ``meta/*``, ``offset``, ``step_index``, ``box/*``."""
    return _create_sharded(
        group, name, shape, dtype, DENSE_ROWS_PER_CHUNK, DENSE_CHUNKS_PER_SHARD, dense=True
    )


def _create_column(
    group: zarr.Group, name: str, shape: tuple[int, ...], dtype: DType, frame_rows: int
) -> zarr.Array:
    """A block column: frame-aligned inner chunks, 256 MiB shards."""
    per_row = row_bytes(shape[1:], _itemsize(dtype))
    rows = rows_per_chunk(frame_rows, per_row)
    return _create_sharded(
        group, name, shape, dtype, rows, chunks_per_shard(rows * per_row), dense=False
    )


class ZarrStore(Store):
    """A Zarr V3 root on the filesystem -- a ``*.mrec/`` directory.

    The one store every Zarr binding hands an adapter: ``uri`` / ``path`` for
    an implementation that takes a path (PyO3, the C ABI, a CLI), ``root``
    for one already speaking zarr-python.
    """

    backend: ClassVar[str] = "zarr"

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def uri(self) -> str:
        return str(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def root(self, mode: str = "a") -> zarr.Group:
        return zarr.open_group(store=self._path, mode=mode)

    def clear(self) -> None:
        if self._path.exists():
            shutil.rmtree(self._path)


class ZarrFrameStore(ZarrStore, FrameStore):
    """A Zarr V3 root holding one bare frame (its attributes are the frame's meta)."""


class ZarrFrameCodec(Codec):
    """The official translation. Kept thin -- it is the arbiter."""

    def write(self, model: FrameModel, store: ZarrFrameStore) -> None:
        store.clear()
        self.write_into(store.root(mode="w"), model)

    def read(self, store: ZarrFrameStore) -> FrameModel:
        return self.read_from(store.root(mode="r"))

    def write_into(self, root: zarr.Group, model: FrameModel) -> None:
        """Lay a frame out under an already-opened group.

        Split out so the record codec reuses it: a frame section inside a
        record and a bare frame at a store root are the same bytes, and one
        description of that is better than two that can drift.
        """
        root.attrs.update(model.meta)

        for name, block in model.blocks.items():
            if name == BOX_GROUP:
                raise ValueError(
                    f"{BOX_GROUP!r} names the cell in a frame group; a block cannot take it"
                )
            self._write_block(root, name, block)

        if model.box is not None:
            self._write_box(root, model.box)

    def read_from(self, root: zarr.Group) -> FrameModel:
        blocks = {
            name: self._read_block(member)
            for name, member in root.members()
            if isinstance(member, zarr.Group) and name != BOX_GROUP
        }

        box = self._read_box(root[BOX_GROUP]) if BOX_GROUP in root else None
        return FrameModel(blocks=blocks, box=box, meta=dict(root.attrs))

    def _write_block(self, parent: zarr.Group, name: str, block: BlockModel) -> None:
        if VALIDITY_GROUP in block.columns:
            raise ValueError(
                f"{VALIDITY_GROUP!r} names the validity masks of block {name!r}; a column "
                "cannot take it"
            )
        group = parent.create_group(name)
        group.attrs["count"] = block.count
        if block.structural_shape is not None:
            group.attrs[STRUCTURAL_SHAPE_ATTR] = list(block.structural_shape)

        for column_name, column in block.columns.items():
            array = create_fixed(group, column_name, column.shape, column.dtype)
            if column.values is not None:
                array[...] = column.values

        # Only a masked column writes a mask, and a block with none writes no
        # subgroup: its bytes are what a writer that predates masks wrote.
        masked = {
            column_name: column.validity
            for column_name, column in block.columns.items()
            if column.validity is not None
        }
        if masked:
            masks = group.create_group(VALIDITY_GROUP)
            for column_name, mask in masked.items():
                create_fixed(masks, column_name, mask.shape, "bool")[...] = mask

    def _read_block(self, group: zarr.Group) -> BlockModel:
        attrs = dict(group.attrs)
        if "count" not in attrs:
            raise ValueError(f"block {group.name!r} has no count attribute")

        count = int(attrs["count"])
        masks = _read_masks(group, count)
        columns = {
            name: self._read_column(member, masks.pop(name, None))
            for name, member in group.members()
            if isinstance(member, zarr.Array)
        }
        if masks:
            raise ValueError(
                f"{group.name}/{VALIDITY_GROUP} masks {sorted(masks)}, which are no columns of "
                "the block"
            )
        structural = attrs.get(STRUCTURAL_SHAPE_ATTR)
        return BlockModel(
            count=count,
            columns=columns,
            structural_shape=tuple(structural) if structural is not None else None,
        )

    def _read_column(self, array: zarr.Array, validity: np.ndarray | None) -> ColumnModel:
        return ColumnModel(
            dtype=dtype_of(np.dtype(array.dtype)),
            shape=tuple(int(n) for n in array.shape),
            values=array[...],
            validity=validity,
        )

    def _write_box(self, root: zarr.Group, box: BoxModel) -> None:
        """``vectors`` always; ``origin`` / ``boundary`` as arrays, omitted at their
        normative defaults; ``cell_defined`` as an attribute, only when false."""
        group = root.create_group(BOX_GROUP)
        create_fixed(group, "vectors", tuple(box.vectors.shape), "f64")[...] = box.vectors
        origin = np.asarray(box.origin, dtype="float64")
        if origin.any():
            create_fixed(group, "origin", tuple(origin.shape), "f64")[...] = origin
        boundary = np.asarray(box.boundary, dtype="bool")
        if not boundary.all():
            create_fixed(group, "boundary", tuple(boundary.shape), "bool")[...] = boundary
        if box.cell_defined is False:
            group.attrs[CELL_DEFINED_ATTR] = False

    def _read_box(self, group: zarr.Group) -> BoxModel:
        origin = group["origin"][...] if "origin" in group else None
        boundary = group["boundary"][...] if "boundary" in group else None
        defined = _cell_defined(group)
        return BoxModel(
            # An undefined cell's vectors mean nothing and are not read.
            vectors=group["vectors"][...] if defined else np.eye(3),
            origin=origin,
            boundary=tuple(bool(flag) for flag in boundary) if boundary is not None else None,
            cell_defined=defined,
        )


def _cell_defined(group: zarr.Group) -> bool:
    """The ``box`` group's ``cell_defined`` attribute: absent is a defined cell."""
    defined = group.attrs.get(CELL_DEFINED_ATTR, True)
    if not isinstance(defined, bool):
        raise ValueError(f"{group.name}: cell_defined is a boolean, found {defined!r}")
    return defined


def _read_masks(block: zarr.Group, rows: int | None) -> dict[str, np.ndarray]:
    """The arrays of ``<block>/_validity``: absent means every row is valid.

    A mask that is not ``bool``, or does not carry exactly ``rows`` flags, is a
    corrupt store and is refused -- padding or truncating it would invent the
    very answer a mask exists to give. ``rows`` of ``None`` skips the length
    check (a trajectory section's masks are cut per update by the caller).
    """
    if VALIDITY_GROUP not in block:
        return {}
    group = block[VALIDITY_GROUP]
    if not isinstance(group, zarr.Group):
        raise ValueError(f"{block.name}/{VALIDITY_GROUP} must be a group of masks")
    masks: dict[str, np.ndarray] = {}
    for name, member in group.members():
        if not isinstance(member, zarr.Array):
            continue
        if np.dtype(member.dtype) != np.bool_ or member.ndim != 1:
            raise ValueError(
                f"{member.name} is stored as {member.dtype}{list(member.shape)}; a validity "
                "mask is one bool per row"
            )
        if rows is not None and member.shape[0] != rows:
            raise ValueError(f"{member.name} carries {member.shape[0]} flags for {rows} rows")
        masks[name] = member if rows is None else member[...]
    return masks


@REGISTRY.binding
class ZarrFrameBinding(Binding):
    module: ClassVar[str] = "core"
    backend: ClassVar[str] = "zarr"

    def new_store(self, workdir: Path) -> ZarrFrameStore:
        store = ZarrFrameStore(workdir.with_suffix(".mrec"))
        store.clear()
        return store

    def codec(self) -> ZarrFrameCodec:
        return ZarrFrameCodec()


TRAJECTORY_GROUP = "trajectory"

#: The members of the two reserved namespaces the codec addresses by name.
#: The sets themselves are the model's (``RESERVED_TRAJECTORY_NAMES`` and
#: ``RESERVED_BLOCK_NAMES``), which is where a block or column taking one of
#: them is refused.
STEP_ARRAY = "step"
TIME_ARRAY = "time"
META_GROUP = "meta"
STEP_INDEX_ARRAY = "step_index"
OFFSET_ARRAY = "offset"

#: The attributes the layout names (``docs/spec/ragged.md``): the pinned
#: declaration on the trajectory group, the exact tag on each per-step meta
#: array, the cell's one meaningful-when-absent flag, and two writer-maintained
#: hints on a block group that let a reader resolve a frame in O(1).
SEQUENCE_SCHEMA_ATTR = "sequence_schema"
META_DTYPE_ATTR = "meta_dtype"
UNIFORM_ROWS_ATTR = "uniform_rows"
DENSE_UPDATES_ATTR = "dense_updates"
#: Trajectory-group attribute: the commit marker (frames fully on disk).
NSTEP_ATTR = "nstep"
#: Trajectory-group attributes: ``step`` / ``time`` as ``{start, stride}``
#: while they are arithmetic progressions (no array is written then).
STEP_PROGRESSION_ATTR = "step_progression"
TIME_PROGRESSION_ATTR = "time_progression"


class ZarrTrajectoryStore(ZarrStore, TrajectoryStore):
    """A Zarr V3 root holding one trajectory, under ``trajectory/``.

    The sequence sits under its section name rather than at the root, so the
    tree a bare trajectory store holds and the tree a record's ``trajectory/``
    section holds are the same bytes. An implementation needs one door for
    both, not two that can drift.
    """


class ZarrTrajectoryCodec(Codec):
    """The official translation for a sequence of frames (``docs/spec/ragged.md``).

    Layout::

        trajectory/        attrs sequence_schema (the pin), nstep (the commit
        │                  marker, written last), step_progression /
        │                  time_progression ({start, stride} while regular)
        ├── step           i64[nstep]      only once the numbering is not a progression
        ├── time           f64[nstep]      only when supplied, and not a progression
        ├── meta/<key>     <tag>[nstep][...]     attr meta_dtype
        ├── box/           attr cell_defined (only when false); a fixed cell from
        │   │              ordinal 0 as attributes vectors / origin / boundary
        │   ├── step_index u64[n_updates]         the arrays, once the cell changes
        │   ├── vectors    f64[n_updates][3][3]
        │   ├── origin     f64[n_updates][3]     omitted when every update is zero
        │   └── boundary   bool[n_updates][3]    omitted when every update is periodic
        └── <block>/       attrs structural_shape?; uniform_rows + dense_updates
            │              while the block is regular (elision markers)
            ├── step_index u64[n_updates]         absent while the block is regular
            ├── offset     u64[n_updates+1]       absent while the block is regular
            ├── <column>   <dtype>[total_rows][...]
            └── _validity/<column>  bool[total_rows]   nullable columns only

    The common run -- a fixed number of atoms moving every frame, a topology
    written once, a fixed cell, frames dumped every ``k`` steps -- costs one
    array per column and nothing else: no index arrays, no ``step`` array, no
    ``box/`` arrays.

    Three states per block and frame (S1). A frame that omits a block writes
    no update, so the block carries forward; a zero-row update means present
    and empty from that ordinal on; no update at or before an ordinal means
    absent. Row counts are never stored: they are ``diff(offset)``, computed
    with checked subtraction, and a non-monotonic ``offset`` is refused.
    """

    def write(self, model: TrajectoryModel, store: ZarrTrajectoryStore) -> None:
        store.clear()
        root = store.root(mode="w")
        # Root, then ``meta/`` (stamped with the contract version), then the
        # sequence -- the creation order every writer follows.
        root.create_group(RECORD_META).attrs.update(stamp_version({}))
        self.write_into(root.create_group(TRAJECTORY_GROUP), model)

    def read(self, store: ZarrTrajectoryStore) -> TrajectoryModel:
        return self.read_from(store.root(mode="r")[TRAJECTORY_GROUP])

    # -- write -------------------------------------------------------------

    def write_into(self, group: zarr.Group, model: TrajectoryModel) -> None:
        """Lay a trajectory out under an already-opened group.

        Split out so the record codec reuses it: a trajectory section inside a
        record and a bare trajectory store are the same bytes.

        The codec refuses what the contract refuses. A model built around the
        validators (``model_construct``) is validated again here, so the one
        statement of the rules -- the model's -- is also the writer's: a
        reserved name, an undeclared block or column or key, an omitted key
        without a fill, a non-increasing step, a partial ``time``, a grid
        whose row count moved, none of them reaches the disk.

        Order is the commit protocol's: the pin when the sequence is created,
        every array next, and the trajectory group's ``nstep`` (with the
        progression attributes) last.
        """
        model = revalidated(model)
        nstep = len(model.frames)

        declaration = SequenceSchemaModel(blocks=model.blocks or {}, meta=model.meta)
        group.attrs[SEQUENCE_SCHEMA_ATTR] = declaration.model_dump(mode="json", exclude_none=True)

        for name, pinned in declaration.blocks.items():
            frame_rows = max(
                (frame.blocks[name].count for frame in model.frames if name in frame.blocks),
                default=0,
            )
            self._write_block(group, name, pinned, _updates(model, name), frame_rows)

        if model.box is not None:
            self._write_box(group, model.box)

        self._write_meta(group, model)

        marker: dict[str, Any] = {}
        step = _progression(model.step, exact_int=True)
        if step is not None:
            marker[STEP_PROGRESSION_ATTR] = step
        elif nstep:
            _create_dense(group, STEP_ARRAY, (nstep,), "i64")[...] = np.asarray(
                model.step, dtype="int64"
            )
        if model.time is not None and nstep:
            time = _progression(model.time, exact_int=False)
            if time is not None:
                marker[TIME_PROGRESSION_ATTR] = time
            else:
                _create_dense(group, TIME_ARRAY, (nstep,), "f64")[...] = np.asarray(
                    model.time, dtype="float64"
                )
        # The commit marker lands last, in one metadata update with the
        # progressions: a crash before it costs the uncommitted frames only.
        group.attrs.update({**marker, NSTEP_ATTR: nstep})

    def _write_block(
        self,
        parent: zarr.Group,
        name: str,
        pinned: SequenceBlockModel,
        entries: list[tuple[int, BlockModel]],
        frame_rows: int,
    ) -> None:
        group = parent.create_group(name)
        attrs: dict[str, Any] = {}
        if pinned.structural_shape is not None:
            attrs[STRUCTURAL_SHAPE_ATTR] = list(pinned.structural_shape)

        ordinals = [ordinal for ordinal, _ in entries]
        counts = [block.count for _, block in entries]
        # Regular: a fixed, non-zero row count at ordinals 0, 1, 2, ... -- the
        # block's index is then implied, and the two markers say so. A block
        # with no columns has no length to imply it from, so it keeps one.
        regular = (
            bool(entries)
            and bool(pinned.columns)
            and counts[0] > 0
            and len(set(counts)) == 1
            and ordinals == list(range(len(entries)))
        )
        if regular:
            attrs[UNIFORM_ROWS_ATTR] = counts[0]
            attrs[DENSE_UPDATES_ATTR] = True
        group.attrs.update(attrs)

        offset = np.zeros(len(entries) + 1, dtype="uint64")
        offset[1:] = np.cumsum(counts, dtype="uint64")
        if entries and not regular:
            _create_dense(group, STEP_INDEX_ARRAY, (len(entries),), "u64")[...] = np.asarray(
                ordinals, dtype="uint64"
            )
            _create_dense(group, OFFSET_ARRAY, (len(entries) + 1,), "u64")[...] = offset

        # One rows-per-chunk for the whole block, sized by its narrowest
        # column, so a frame's rows stay chunk-aligned across columns.
        narrowest = min(
            (
                row_bytes(tuple(spec.trailing), _itemsize(spec.dtype))
                for spec in pinned.columns.values()
            ),
            default=8,
        )
        rows = rows_per_chunk(frame_rows, narrowest)
        total = int(offset[-1])
        for column_name, spec in pinned.columns.items():
            array = _create_sharded(
                group,
                column_name,
                (total, *spec.trailing),
                spec.dtype,
                rows,
                chunks_per_shard(rows * row_bytes(tuple(spec.trailing), _itemsize(spec.dtype))),
                dense=False,
            )
            for index, (_, block) in enumerate(entries):
                values = block.columns[column_name].values
                if values is not None and block.count:
                    array[int(offset[index]) : int(offset[index + 1])] = values

        # A nullable column's mask is dense over the section's rows, grown in
        # lockstep with the values: an update that carries no mask lands
        # all-true, so a frame's flags sit at exactly its values' row range.
        nullable = [column for column, spec in pinned.columns.items() if spec.nullable]
        if nullable:
            masks = group.create_group(VALIDITY_GROUP)
            for column_name in nullable:
                mask = np.ones(total, dtype="bool")
                for index, (_, block) in enumerate(entries):
                    validity = block.columns[column_name].validity
                    if validity is not None:
                        mask[int(offset[index]) : int(offset[index + 1])] = validity
                _create_sharded(
                    masks,
                    column_name,
                    mask.shape,
                    "bool",
                    rows,
                    chunks_per_shard(rows),
                    dense=False,
                )[...] = mask

    def _write_box(self, parent: zarr.Group, section: TrajectoryBoxModel) -> None:
        """A fixed cell from ordinal 0 as the group's attributes; arrays otherwise."""
        group = parent.create_group(BOX_GROUP)
        updates = section.updates
        attrs: dict[str, Any] = {}
        # Absent means true, so the flag is emitted only to record false.
        if section.cell_defined is False:
            attrs[CELL_DEFINED_ATTR] = False

        origins = np.stack([update.box.origin for update in updates])
        boundaries = np.asarray([update.box.boundary for update in updates], dtype="bool")
        if len(updates) == 1 and updates[0].step_index == 0:
            cell = updates[0].box
            attrs["vectors"] = cell.vectors.tolist()
            if origins.any():
                attrs["origin"] = cell.origin.tolist()
            if not boundaries.all():
                attrs["boundary"] = list(cell.boundary)
            group.attrs.update(attrs)
            return

        group.attrs.update(attrs)
        count = len(updates)
        _create_dense(group, STEP_INDEX_ARRAY, (count,), "u64")[...] = np.asarray(
            [update.step_index for update in updates], dtype="uint64"
        )
        _create_dense(group, "vectors", (count, 3, 3), "f64")[...] = np.stack(
            [update.box.vectors for update in updates]
        )
        # ``origin`` and ``boundary`` are optional with normative defaults;
        # each is written only when some update departs from its default.
        if origins.any():
            _create_dense(group, "origin", (count, 3), "f64")[...] = origins
        if not boundaries.all():
            _create_dense(group, "boundary", (count, 3), "bool")[...] = boundaries

    def _write_meta(self, group: zarr.Group, model: TrajectoryModel) -> None:
        if not model.meta:
            return
        meta = group.create_group(META_GROUP)
        for key, series in model.meta.items():
            array = _create_dense(
                meta, key, (len(model.frames), *series.shape), series.element_dtype
            )
            array.attrs[META_DTYPE_ATTR] = series.dtype
            # Validation has already resolved every declared fill, so every
            # frame carries every declared key by the time we get here. The
            # fill lands as an ordinary value; the declaration that it *was*
            # a fill is the ``sequence_schema`` attribute's.
            values = [frame.meta[key] for frame in model.frames]
            if not values:
                continue
            if series.dtype == "json":
                array[...] = np.asarray([jsonvalue.dumps(value) for value in values], dtype="str")
            else:
                array[...] = np.asarray(values, dtype=NUMPY_DTYPE[series.element_dtype]).reshape(
                    (len(values), *series.shape)
                )

    # -- read --------------------------------------------------------------

    def read_from(self, group: zarr.Group) -> TrajectoryModel:
        nstep = self._nstep(group)
        step = self._series(group, STEP_PROGRESSION_ATTR, STEP_ARRAY, nstep, int)
        if step is None:
            if nstep:
                raise ValueError(f"{group.name}: no step series (attribute or array)")
            step = []
        declaration = self._declaration(group)
        declared_meta, meta = self._read_meta(group, nstep, declaration)

        blocks: list[dict[str, BlockModel]] = [{} for _ in range(nstep)]
        for name, member in self._block_groups(group, declaration):
            for ordinal, block in enumerate(self._resolve(member, nstep)):
                if block is not None:
                    blocks[ordinal][name] = block

        time = self._series(group, TIME_PROGRESSION_ATTR, TIME_ARRAY, nstep, float)

        return TrajectoryModel(
            frames=[
                FrameModel(blocks=blocks[ordinal], meta=meta[ordinal]) for ordinal in range(nstep)
            ],
            step=step,
            time=time,
            blocks=None if declaration is None else declaration.blocks,
            meta=declared_meta,
            box=self._read_box(group[BOX_GROUP], nstep) if BOX_GROUP in group else None,
        )

    def _block_groups(
        self, group: zarr.Group, declaration: SequenceSchemaModel | None
    ) -> list[tuple[str, zarr.Group]]:
        """The block sections to resolve.

        With a pin, exactly the declared blocks -- ``sequence_schema.blocks``
        is the authoritative list, a declared block whose group is missing is
        absent at every ordinal, and a child group the pin does not name is
        not a block of this sequence. Without one (a foreign store), every
        child group outside the reserved names.
        """
        if declaration is None:
            return [
                (name, member)
                for name, member in group.members()
                if isinstance(member, zarr.Group) and name not in RESERVED_TRAJECTORY_NAMES
            ]
        found = []
        for name in declaration.blocks:
            if name in group:
                member = group[name]
                if not isinstance(member, zarr.Group):
                    raise ValueError(f"{group.name}/{name} is declared a block but is no group")
                found.append((name, member))
        return found

    def _nstep(self, group: zarr.Group) -> int:
        """The commit marker: the ``nstep`` attribute, else ``len(step)`` for
        a store from a writer that kept no marker attribute.

        A progression attribute is only ever written together with the
        marker, so one without it is a malformed store, not an old one.
        """
        marker = group.attrs.get(NSTEP_ATTR)
        if marker is not None:
            if type(marker) is not int or marker < 0:
                raise ValueError(f"{group.name}: nstep must be a non-negative integer")
            return marker
        for attribute in (STEP_PROGRESSION_ATTR, TIME_PROGRESSION_ATTR):
            if attribute in group.attrs:
                raise ValueError(
                    f"{group.name}: {attribute} without the nstep marker it is committed with"
                )
        if STEP_ARRAY in group:
            return int(group[STEP_ARRAY].shape[0])
        return 0

    def _series(
        self,
        group: zarr.Group,
        attribute: str,
        array: str,
        nstep: int,
        cast: Any,
    ) -> list[Any] | None:
        """A dense per-frame series: the progression attribute when present,
        else the array cut to ``nstep``, else ``None``.

        A value of a progression is ``start + f64(i) * stride`` in IEEE
        binary64 (no fused multiply-add) for ``time``, exact integer
        arithmetic for ``step``.
        """
        progression = group.attrs.get(attribute)
        if progression is not None:
            if not isinstance(progression, dict) or "start" not in progression:
                raise ValueError(f"{group.name}: {attribute} is not a progression")
            start = cast(progression["start"])
            if nstep <= 1:
                return [start] * nstep
            if "stride" not in progression:
                raise ValueError(f"{group.name}: {attribute} has no stride for {nstep} frames")
            stride = cast(progression["stride"])
            return [cast(start + cast(i) * stride) for i in range(nstep)]
        if array in group:
            return [cast(value) for value in _logical(group[array], nstep, array)]
        return None

    def _declaration(self, group: zarr.Group) -> SequenceSchemaModel | None:
        """The pinned declaration, when the writer left one.

        The reference writer always does. A store without it is still read --
        the declaration is then derived from the groups -- but anything the
        attribute names is held to.
        """
        pinned = group.attrs.get(SEQUENCE_SCHEMA_ATTR)
        return None if pinned is None else SequenceSchemaModel.model_validate(pinned)

    def _index(self, group: zarr.Group, nstep: int) -> tuple[list[int], list[int]]:
        """A section's logical ``step_index`` and ``offset`` (L8, checked).

        The logical update count is the prefix of ``step_index`` below
        ``nstep``: a longer array is a partially committed tail and is read
        past, never into. ``step_index`` is held to strictly ascending and
        ``offset`` to ``offset[0] == 0`` and non-decreasing -- the row count of
        update ``j`` is ``offset[j+1] - offset[j]`` with checked subtraction,
        so a store where that would go negative is refused rather than
        wrapped.
        """
        if OFFSET_ARRAY not in group:
            raise ValueError(f"{group.name}: step_index without the offset it indexes")
        ordinals = [int(value) for value in group[STEP_INDEX_ARRAY][...]]
        n_updates = 0
        while n_updates < len(ordinals) and ordinals[n_updates] < nstep:
            n_updates += 1
        ordinals = ordinals[:n_updates]
        if any(later <= earlier for earlier, later in zip(ordinals, ordinals[1:], strict=False)):
            raise ValueError(f"{group.name}: step_index must be strictly ascending, got {ordinals}")

        raw = group[OFFSET_ARRAY][...]
        if len(raw) < n_updates + 1:
            raise ValueError(
                f"{group.name}: offset has {len(raw)} entries for {n_updates} updates; "
                f"needs {n_updates + 1}"
            )
        offset = [int(value) for value in raw[: n_updates + 1]]
        if offset[0] != 0:
            raise ValueError(f"{group.name}: offset[0] must be 0, got {offset[0]}")
        for j in range(n_updates):
            if offset[j + 1] < offset[j]:
                raise ValueError(
                    f"{group.name}: offset is not monotonic at update {j} "
                    f"({offset[j]} -> {offset[j + 1]}); row counts are diff(offset) and a "
                    "negative one is refused, not wrapped"
                )
        return ordinals, offset

    def _resolve(self, group: zarr.Group, nstep: int) -> list[BlockModel | None]:
        """One block, at every ordinal.

        Binary-search the block's ``step_index`` for the largest entry ``<= i``:
        that is the update whose rows the frame owns. No entry ``<= i`` means
        the block does not exist at that frame -- absent. A zero-row update
        means present and empty: a block with its declared columns and no
        rows, which does appear in the frame.
        """
        grid = group.attrs.get(STRUCTURAL_SHAPE_ATTR)
        columns = {
            name: member
            for name, member in group.members()
            if isinstance(member, zarr.Array) and name not in RESERVED_BLOCK_NAMES
        }
        masks = _read_masks(group, None)
        unknown = sorted(set(masks) - set(columns))
        if unknown:
            raise ValueError(
                f"{group.name}/{VALIDITY_GROUP} masks {unknown}, which are no columns of the block"
            )
        rows = group.attrs.get(UNIFORM_ROWS_ATTR)
        dense = group.attrs.get(DENSE_UPDATES_ATTR)
        if STEP_INDEX_ARRAY in group:
            # The arrays are authoritative. A crash between materializing
            # them and withdrawing the markers can leave both; the arrays win.
            ordinals, offset = self._index(group, nstep)
        elif rows is None and dense is None:
            # Declared and never updated within the committed frames: absent
            # at every ordinal. Rows a column holds are an uncommitted tail.
            ordinals, offset = [], [0]
        else:
            if type(rows) is not int or rows <= 0 or dense is not True or not columns:
                raise ValueError(
                    f"{group.name}: uniform_rows {rows!r} / dense_updates {dense!r} do not elide "
                    "an index (both, a positive row count, and a column to measure are needed)"
                )
            landed = min(int(array.shape[0]) for array in columns.values())
            n_updates = min(landed // rows, nstep)
            ordinals = list(range(n_updates))
            offset = [j * rows for j in range(n_updates + 1)]
        total = offset[-1]
        for name, array in {**columns, **masks}.items():
            if array.shape[0] < total:
                raise ValueError(
                    f"{group.name}/{name} holds {array.shape[0]} rows, offset claims {total}"
                )

        updates: list[BlockModel] = []
        for j in range(len(ordinals)):
            start, stop = offset[j], offset[j + 1]
            updates.append(
                BlockModel(
                    count=stop - start,
                    columns={
                        name: ColumnModel(
                            dtype=dtype_of(np.dtype(array.dtype)),
                            shape=(stop - start, *(int(n) for n in array.shape[1:])),
                            values=array[start:stop],
                            validity=masks[name][start:stop] if name in masks else None,
                        )
                        for name, array in columns.items()
                    },
                    structural_shape=tuple(grid) if grid is not None else None,
                )
            )

        resolved: list[BlockModel | None] = []
        for ordinal in range(nstep):
            update = int(np.searchsorted(ordinals, ordinal, side="right")) - 1
            resolved.append(None if update < 0 else updates[update])
        return resolved

    def _read_box(self, group: zarr.Group, nstep: int) -> TrajectoryBoxModel | None:
        defined = _cell_defined(group)
        if "vectors" not in group:
            # A fixed cell from ordinal 0 lives in the group attributes: no
            # arrays at all until it changes.
            vectors = group.attrs.get("vectors")
            if vectors is None or nstep == 0:
                # No cell committed yet: the section holds no update, and a
                # section of no updates is no section.
                return None
            origin = group.attrs.get("origin")
            boundary = group.attrs.get("boundary")
            return TrajectoryBoxModel(
                updates=[
                    BoxUpdateModel(
                        step_index=0,
                        box=CellModel(
                            vectors=np.asarray(vectors, dtype="float64") if defined else np.eye(3),
                            origin=None if origin is None else np.asarray(origin, dtype="float64"),
                            boundary=None if boundary is None else tuple(bool(f) for f in boundary),
                        ),
                    )
                ],
                cell_defined=defined,
            )
        # A trivial ``step_index`` (exactly one update at ordinal 0) may be
        # omitted; absence reads back as ``[0]``. The logical update count is
        # the prefix below ``nstep``, as for a block.
        if STEP_INDEX_ARRAY in group:
            ordinals = [int(ordinal) for ordinal in group[STEP_INDEX_ARRAY][...]]
            ordinals = [ordinal for ordinal in ordinals if ordinal < nstep]
            if any(b <= a for a, b in zip(ordinals, ordinals[1:], strict=False)):
                raise ValueError(f"{group.name}: step_index must be strictly ascending")
        else:
            ordinals = [0] if nstep else []
        if not ordinals:
            return None
        count = len(ordinals)
        vectors = _logical(group["vectors"], count, f"{BOX_GROUP}/vectors")
        origin = (
            _logical(group["origin"], count, f"{BOX_GROUP}/origin") if "origin" in group else None
        )
        boundary = (
            _logical(group["boundary"], count, f"{BOX_GROUP}/boundary")
            if "boundary" in group
            else None
        )
        return TrajectoryBoxModel(
            updates=[
                BoxUpdateModel(
                    step_index=ordinal,
                    box=CellModel(
                        vectors=vectors[index] if defined else np.eye(3),
                        origin=None if origin is None else origin[index],
                        boundary=None
                        if boundary is None
                        else tuple(bool(flag) for flag in boundary[index]),
                    ),
                )
                for index, ordinal in enumerate(ordinals)
            ],
            cell_defined=defined,
        )

    def _read_meta(
        self, group: zarr.Group, nstep: int, declaration: SequenceSchemaModel | None
    ) -> tuple[dict[str, MetaSeriesModel], list[dict[str, Any]]]:
        declared: dict[str, MetaSeriesModel] = {}
        values: list[dict[str, Any]] = [{} for _ in range(nstep)]
        if META_GROUP not in group:
            return declared, values

        pinned = {} if declaration is None else declaration.meta
        for name, array in group[META_GROUP].members():
            if not isinstance(array, zarr.Array):
                continue
            tag = array.attrs.get(META_DTYPE_ATTR)
            if tag is None:
                raise ValueError(
                    f"meta/{name} carries no {META_DTYPE_ATTR} attribute; its per-step values "
                    "cannot be read back exactly"
                )
            series = pinned.get(name, MetaSeriesModel(dtype=tag))
            if series.dtype != tag:
                raise ValueError(
                    f"meta/{name}: {META_DTYPE_ATTR} is {tag!r} but the pinned declaration says "
                    f"{series.dtype!r}"
                )
            element, shape = series.element_dtype, series.shape
            if dtype_of(np.dtype(array.dtype)) != element or tuple(array.shape[1:]) != shape:
                raise ValueError(
                    f"meta/{name} is stored as {array.dtype}{list(array.shape[1:])}, but its tag "
                    f"{tag!r} is {element}{list(shape)}"
                )
            declared[name] = series
            rows = _logical(array, nstep, f"{META_GROUP}/{name}")
            for ordinal in range(nstep):
                value = rows[ordinal]
                values[ordinal][name] = coerce_meta_value(
                    tag, json.loads(str(value)) if tag == "json" else value
                )
        return declared, values


def _updates(model: TrajectoryModel, name: str) -> list[tuple[int, BlockModel]]:
    """One block's changes, in ordinal order.

    A block earns an update when it is presented and differs **bit for bit**
    (masks included) from its previous update -- which is what makes a
    constant topology one entry instead of ``nstep``, a repeated NaN unchanged
    and a ``-0.0`` after a ``0.0`` a change. Before its first presentation it
    earns nothing: no entry ``<= i`` already means absent. A zero-row block is
    an update like any other, and it is the *only* way a zero-row update is
    written: an omission never becomes one.
    """
    entries: list[tuple[int, BlockModel]] = []
    previous: BlockModel | None = None
    for ordinal, frame in enumerate(model.frames):
        current = frame.blocks.get(name)
        if current is None:
            continue
        if previous is not None and same_bits(current, previous):
            continue
        entries.append((ordinal, current))
        previous = current
    return entries


def _progression(values: list[Any], *, exact_int: bool) -> dict[str, Any] | None:
    """``{start, stride}`` when ``values`` is an arithmetic progression, else ``None``.

    ``stride`` is ``values[1] - values[0]``; value ``i`` must equal
    ``start + i * stride`` exactly -- integer arithmetic for ``step``, IEEE
    binary64 ``start + f64(i) * stride`` (no fused multiply-add) for ``time``.
    A non-finite time is never a progression (JSON cannot spell it), and
    neither is an empty series.
    """
    if not values:
        return None
    if not exact_int and not all(math.isfinite(value) for value in values):
        return None
    start = values[0]
    if len(values) == 1:
        return {"start": start}
    stride = values[1] - values[0]
    for i, value in enumerate(values):
        expected = start + i * stride if exact_int else start + float(i) * stride
        if expected != value:
            return None
    return {"start": start, "stride": stride}


def _logical(array: zarr.Array, length: int, what: str) -> np.ndarray:
    """The first ``length`` rows of a per-step array (L8).

    A reader is bound by ``nstep``: a longer array is a tail the writer had
    not yet committed, and is tolerated; a shorter one cannot supply every
    committed frame, and is refused.
    """
    if array.shape[0] < length:
        raise ValueError(f"{what} holds {array.shape[0]} rows, {length} are committed")
    return array[:length]


@REGISTRY.binding
class ZarrTrajectoryBinding(Binding):
    module: ClassVar[str] = "trajectory"
    backend: ClassVar[str] = "zarr"

    def new_store(self, workdir: Path) -> ZarrTrajectoryStore:
        store = ZarrTrajectoryStore(workdir.with_suffix(".mrec"))
        store.clear()
        return store

    def codec(self) -> ZarrTrajectoryCodec:
        return ZarrTrajectoryCodec()


RECORD_META = "meta"
RECORD_FRAME = "frame"
RECORD_SYSTEM = "system"
RECORD_STATUS = "status"
RECORD_METHOD = "method"
RECORD_OBSERVABLES = "observables"


class ZarrRecordStore(ZarrStore, RecordStore):
    """A Zarr V3 root holding a whole record.

    This is the shape a real producer writes. A bare frame at a store root is
    a useful unit to pin down on its own, but nothing ships one -- an
    implementation writes a record, and the frame is a section inside it.
    """


class ZarrRecordCodec(Codec):
    """The official record translation.

    Document sections are group attribute maps, not child arrays -- ``meta``,
    ``status`` and ``method`` are JSON documents and Zarr already has a place
    for those. Frame-shaped sections delegate to the frame codec, so there is
    exactly one description of how blocks are laid out.

    ``meta/`` is always written, first, and carries ``molrec_version``: a
    writer stamps the version it writes when the producer's document has
    none. A root without ``meta/`` reads as an empty document.
    """

    def __init__(self) -> None:
        self._frames = ZarrFrameCodec()
        self._trajectories = ZarrTrajectoryCodec()

    def write(self, model: RecordModel, store: ZarrRecordStore) -> None:
        store.clear()
        root = store.root(mode="w")
        root.create_group(RECORD_META).attrs.update(
            stamp_version(model.meta.model_dump(mode="json", exclude_none=True))
        )
        for name, document in ((RECORD_STATUS, model.status), (RECORD_METHOD, model.method)):
            if document is not None:
                root.create_group(name).attrs.update(
                    document.model_dump(mode="json", exclude_none=True)
                )
        if model.metrics is not None:
            raise NotImplementedError(
                "the reference record codec lays out meta, status, method, frame, system, "
                "trajectory and observables; metrics have their own chapter"
            )
        if model.observables is not None:
            self._observables().write_into(root.create_group(RECORD_OBSERVABLES), model.observables)
        for name, frame in (
            (RECORD_FRAME, model.frame),
            (RECORD_SYSTEM, model.system),
        ):
            if frame is not None:
                self._frames.write_into(root.create_group(name), frame)

        # The section's name is the trajectory group's own name -- one
        # constant, so a record's `trajectory/` and a bare trajectory store
        # cannot drift apart.
        if model.trajectory is not None:
            self._trajectories.write_into(root.create_group(TRAJECTORY_GROUP), model.trajectory)

    def read(self, store: ZarrRecordStore) -> RecordModel:
        root = store.root(mode="r")
        meta = dict(root[RECORD_META].attrs) if RECORD_META in root else {}
        return RecordModel(
            meta=MetaModel.model_validate(meta),
            frame=self._section(root, RECORD_FRAME),
            system=self._section(root, RECORD_SYSTEM),
            trajectory=self._trajectories.read_from(root[TRAJECTORY_GROUP])
            if TRAJECTORY_GROUP in root
            else None,
            status=StatusModel.model_validate(dict(root[RECORD_STATUS].attrs))
            if RECORD_STATUS in root
            else None,
            method=MethodModel.model_validate(dict(root[RECORD_METHOD].attrs))
            if RECORD_METHOD in root
            else None,
            observables=self._observables().read_from(root[RECORD_OBSERVABLES])
            if RECORD_OBSERVABLES in root
            else None,
        )

    @staticmethod
    def _observables() -> Codec:
        """The v1 observables codec, which builds on this module's helpers."""
        from molrec.observables.bindings.zarr import ZarrObservablesCodec

        return ZarrObservablesCodec()

    def _section(self, root: zarr.Group, name: str) -> FrameModel | None:
        if name not in root:
            return None
        return self._frames.read_from(root[name])


@REGISTRY.binding
class ZarrRecordBinding(Binding):
    module: ClassVar[str] = "record"
    backend: ClassVar[str] = "zarr"

    def new_store(self, workdir: Path) -> ZarrRecordStore:
        store = ZarrRecordStore(workdir.with_suffix(".mrec"))
        store.clear()
        return store

    def codec(self) -> ZarrRecordCodec:
        return ZarrRecordCodec()
