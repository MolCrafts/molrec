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
    fixed_chunk_rows,
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
    stamp_version,
)
from molrec.core.store import FrameStore, RecordStore, TrajectoryStore
from molrec.registry import REGISTRY

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


def _create_fixed(group: zarr.Group, name: str, shape: tuple[int, ...], dtype: DType) -> zarr.Array:
    """A fixed-size (frame / system) array: one chunk up to 4 MiB, no shard."""
    rows = fixed_chunk_rows(shape[0], row_bytes(shape[1:], _itemsize(dtype)))
    return group.create_array(
        name,
        shape=shape,
        dtype=TO_ZARR[dtype],
        chunks=(rows, *shape[1:]),
        compressors=_compressors(dtype, dense=False),
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


class ZarrFrameStore(FrameStore):
    """A Zarr V3 root holding one frame."""

    backend: ClassVar[str] = "zarr"

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def uri(self) -> str:
        """For bindings that take a path -- PyO3, the C ABI, a CLI."""
        return str(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def root(self, mode: str = "a") -> zarr.Group:
        """For consumers already speaking zarr-python."""
        return zarr.open_group(store=self._path, mode=mode)

    def clear(self) -> None:
        if self._path.exists():
            shutil.rmtree(self._path)


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
            array = _create_fixed(group, column_name, column.shape, column.dtype)
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
                _create_fixed(masks, column_name, mask.shape, "bool")[...] = mask

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
        _create_fixed(group, "vectors", tuple(box.vectors.shape), "f64")[...] = box.vectors
        origin = np.asarray(box.origin, dtype="float64")
        if origin.any():
            _create_fixed(group, "origin", tuple(origin.shape), "f64")[...] = origin
        boundary = np.asarray(box.boundary, dtype="bool")
        if not boundary.all():
            _create_fixed(group, "boundary", tuple(boundary.shape), "bool")[...] = boundary
        if box.cell_defined is False:
            group.attrs[CELL_DEFINED_ATTR] = False

    def _read_box(self, group: zarr.Group) -> BoxModel:
        origin = group["origin"][...] if "origin" in group else None
        boundary = group["boundary"][...] if "boundary" in group else None
        defined = group.attrs.get(CELL_DEFINED_ATTR)
        return BoxModel(
            vectors=group["vectors"][...],
            origin=origin,
            boundary=tuple(bool(flag) for flag in boundary) if boundary is not None else None,
            cell_defined=None if defined is None else bool(defined),
        )


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


class ZarrTrajectoryStore(TrajectoryStore):
    """A Zarr V3 root holding one trajectory, under ``trajectory/``.

    The sequence sits under its section name rather than at the root, so the
    tree a bare trajectory store holds and the tree a record's ``trajectory/``
    section holds are the same bytes. An implementation needs one door for
    both, not two that can drift.
    """

    backend: ClassVar[str] = "zarr"

    def __init__(self, path: Path) -> None:
        self._path = path

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


class ZarrTrajectoryCodec(Codec):
    """The official translation for a sequence of frames.

    Layout::

        trajectory/                attr sequence_schema (the pinned declaration)
        +-- nstep                          the commit marker, written last
        +-- step_progression / time_progression   {start, stride} while regular
        ├── step           i64[nstep]      only once the numbering is not a progression
        ├── time           f64[nstep]      only when supplied, and not a progression
        ├── meta/<key>     <tag>[nstep][...]     attr meta_dtype
        ├── box/           attr cell_defined, written only when false
        │   +-- vectors / origin / boundary       a fixed cell from ordinal 0, as attributes
        │   ├── step_index u64[n_updates]         frame ordinals (arrays once the cell changes)
        │   ├── vectors    f64[n_updates][3][3]
        │   ├── origin     f64[n_updates][3]     omitted when every update is zero
        │   └── boundary   bool[n_updates][3]    omitted when every update is periodic
        └── <block>/       attrs structural_shape?, uniform_rows?, dense_updates?
            ├── step_index u64[n_updates]         frame ordinals (absent while the block is regular)
            ├── offset     u64[n_updates+1]       CSR row pointer
            └── <column>   <dtype>[total_rows][...]

    Dense per-step arrays carry one row per frame. Everything else -- the cell
    and each block -- carries its own sparse index of the ordinals at which it
    changed, so a section costs what it *changes*, not what the run *lasts*.

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
            self._write_block(group, name, pinned, self._updates(model, name), frame_rows)

        if model.box is not None:
            self._write_box(group, model.box)

        self._write_meta(group, model)

        if model.time is not None:
            _create_dense(group, TIME_ARRAY, (nstep,), "f64")[...] = np.asarray(
                model.time, dtype="float64"
            )

        _create_dense(group, STEP_ARRAY, (nstep,), "i64")[...] = np.asarray(
            model.step, dtype="int64"
        )
        # The commit marker lands last, after every array of the commit: the
        # trajectory group's ``nstep`` attribute. A reader takes ``nstep``
        # from it, so a crash between two writes costs the uncommitted frames
        # and nothing else. (This codec keeps ``step`` / ``time`` as arrays;
        # the reference writer records a regular series as a progression
        # attribute instead and writes the array only once it stops being
        # regular -- a reader accepts either.)
        group.attrs[NSTEP_ATTR] = nstep

    def read_from(self, group: zarr.Group) -> TrajectoryModel:
        nstep = self._nstep(group)
        step = self._series(group, STEP_PROGRESSION_ATTR, STEP_ARRAY, nstep, int)
        if step is None:
            raise ValueError(f"{group.name}: no step series (attribute or array)")
        if len(step) != nstep:
            raise ValueError(f"{group.name}: nstep={nstep} but {len(step)} step numbers")
        declaration = self._declaration(group)
        declared_meta, meta = self._read_meta(group, nstep, declaration)

        blocks: list[dict[str, BlockModel]] = [{} for _ in range(nstep)]
        for name, member in group.members():
            if not isinstance(member, zarr.Group) or name in RESERVED_TRAJECTORY_NAMES:
                continue
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

    def _nstep(self, group: zarr.Group) -> int:
        """The commit marker: the ``nstep`` attribute, else ``len(step)`` for
        a store from a writer that kept no marker attribute."""
        marker = group.attrs.get(NSTEP_ATTR)
        if marker is not None:
            return int(marker)
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
        else the array cut to ``nstep``, else ``None``."""
        progression = group.attrs.get(attribute)
        if progression is not None:
            start = cast(progression["start"])
            if nstep <= 1:
                return [start] * nstep
            if "stride" not in progression:
                raise ValueError(f"{group.name}: {attribute} has no stride for {nstep} frames")
            stride = cast(progression["stride"])
            return [cast(start + i * stride) for i in range(nstep)]
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

    def _updates(self, model: TrajectoryModel, name: str) -> list[tuple[int, BlockModel]]:
        """One block's changes, in ordinal order.

        A block earns an update when it is presented and differs from its
        previous update -- which is what makes a constant topology one entry
        instead of ``nstep``. Before its first presentation it earns nothing:
        no entry ``<= i`` already means absent. A zero-row block is an
        update like any other, and it is the *only* way a zero-row update is
        written: an omission never becomes one.
        """
        entries: list[tuple[int, BlockModel]] = []
        previous: BlockModel | None = None
        for ordinal, frame in enumerate(model.frames):
            current = frame.blocks.get(name)
            if current is None:
                continue
            if entries and current == previous:
                continue
            entries.append((ordinal, current))
            previous = current
        return entries

    def _write_block(
        self,
        parent: zarr.Group,
        name: str,
        pinned: SequenceBlockModel,
        entries: list[tuple[int, BlockModel]],
        frame_rows: int,
    ) -> None:
        group = parent.create_group(name)
        if pinned.structural_shape is not None:
            group.attrs[STRUCTURAL_SHAPE_ATTR] = list(pinned.structural_shape)

        ordinals = [ordinal for ordinal, _ in entries]
        counts = [block.count for _, block in entries]
        if entries:
            # Writer-maintained hints: a reader may resolve a frame in O(1)
            # when every update has the same row count and updates are dense.
            if len(set(counts)) == 1:
                group.attrs[UNIFORM_ROWS_ATTR] = counts[0]
            if ordinals == list(range(len(entries))):
                group.attrs[DENSE_UPDATES_ATTR] = True

        offset = np.zeros(len(entries) + 1, dtype="uint64")
        offset[1:] = np.cumsum(counts, dtype="uint64")
        _create_dense(group, STEP_INDEX_ARRAY, (len(entries),), "u64")[...] = np.asarray(
            ordinals, dtype="uint64"
        )
        _create_dense(group, OFFSET_ARRAY, (len(entries) + 1,), "u64")[...] = offset

        for column_name, spec in pinned.columns.items():
            array = _create_column(
                group,
                column_name,
                (int(offset[-1]), *spec.trailing),
                spec.dtype,
                frame_rows,
            )
            for index, (_, block) in enumerate(entries):
                values = block.columns[column_name].values
                if values is not None and block.count:
                    array[int(offset[index]) : int(offset[index + 1])] = values

        # A nullable column's mask is dense over the section's rows, grown in
        # lockstep with the values: an update that carries no mask lands
        # all-true, so a frame's flags sit at exactly its values' row range.
        nullable = [name for name, spec in pinned.columns.items() if spec.nullable]
        if nullable:
            masks = group.create_group(VALIDITY_GROUP)
            for column_name in nullable:
                mask = np.ones(int(offset[-1]), dtype="bool")
                for index, (_, block) in enumerate(entries):
                    validity = block.columns[column_name].validity
                    if validity is not None:
                        mask[int(offset[index]) : int(offset[index + 1])] = validity
                _create_column(masks, column_name, mask.shape, "bool", frame_rows)[...] = mask

    def _index(self, group: zarr.Group, nstep: int) -> tuple[list[int], list[int]]:
        """A section's logical ``step_index`` and ``offset`` (L8, checked).

        The logical update count is the prefix of ``step_index`` below
        ``nstep``: a longer array is a partially committed tail and is read
        past, never into. ``offset`` is held to ``offset[0] == 0`` and
        monotonic non-decreasing -- the row count of update ``j`` is
        ``offset[j+1] - offset[j]`` with checked subtraction, so a store where
        that would go negative is refused rather than wrapped.
        """
        ordinals = [int(value) for value in group[STEP_INDEX_ARRAY][...]]
        n_updates = 0
        while n_updates < len(ordinals) and ordinals[n_updates] < nstep:
            n_updates += 1
        ordinals = ordinals[:n_updates]
        if ordinals != sorted(set(ordinals)):
            raise ValueError(
                f"{group.name}: step_index must be strictly increasing, got {ordinals}"
            )

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
        if STEP_INDEX_ARRAY in group:
            ordinals, offset = self._index(group, nstep)
        else:
            # A regular block writes no index: ``uniform_rows`` /
            # ``dense_updates`` plus the columns' own length say everything.
            rows = group.attrs.get(UNIFORM_ROWS_ATTR)
            if not (rows and group.attrs.get(DENSE_UPDATES_ATTR) and columns):
                return [None] * nstep
            landed = min(int(array.shape[0]) for array in columns.values())
            n_updates = min(landed // int(rows), nstep)
            ordinals = list(range(n_updates))
            offset = [j * int(rows) for j in range(n_updates + 1)]
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

    def _write_box(self, parent: zarr.Group, section: TrajectoryBoxModel) -> None:
        group = parent.create_group(BOX_GROUP)
        updates = section.updates
        count = len(updates)
        ndim = int(updates[0].box.vectors.shape[0])

        _create_dense(group, STEP_INDEX_ARRAY, (count,), "u64")[...] = np.asarray(
            [update.step_index for update in updates], dtype="uint64"
        )
        _create_dense(group, "vectors", (count, ndim, ndim), "f64")[...] = np.stack(
            [update.box.vectors for update in updates]
        )
        # ``origin`` and ``boundary`` are optional with normative defaults
        # (zero origin, all-periodic); each is written only when some update
        # departs from its default.
        origin = np.stack([np.asarray(update.box.origin, dtype="float64") for update in updates])
        if origin.any():
            _create_dense(group, "origin", (count, ndim), "f64")[...] = origin
        boundary = np.asarray([update.box.boundary for update in updates], dtype="bool")
        if not boundary.all():
            _create_dense(group, "boundary", (count, ndim), "bool")[...] = boundary

        # Absent means true -- every store predating the flag holds a defined
        # cell -- so it is emitted only to record false.
        if section.cell_defined is False:
            group.attrs[CELL_DEFINED_ATTR] = False

    def _read_box(self, group: zarr.Group, nstep: int) -> TrajectoryBoxModel | None:
        defined = group.attrs.get(CELL_DEFINED_ATTR)
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
                        box=BoxModel(
                            vectors=np.asarray(vectors, dtype="float64"),
                            origin=None if origin is None else np.asarray(origin, dtype="float64"),
                            boundary=None if boundary is None else tuple(bool(f) for f in boundary),
                        ),
                    )
                ],
                cell_defined=None if defined is None else bool(defined),
            )
        # A trivial ``step_index`` (exactly one update at ordinal 0 -- the
        # fixed-cell case) may be omitted; absence reads back as ``[0]``. The
        # logical update count is the prefix below ``nstep``, as for a block.
        if STEP_INDEX_ARRAY in group:
            ordinals = [int(ordinal) for ordinal in group[STEP_INDEX_ARRAY][...]]
            ordinals = [ordinal for ordinal in ordinals if ordinal < nstep]
        else:
            ordinals = [0]
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
                    box=BoxModel(
                        vectors=vectors[index],
                        origin=None if origin is None else origin[index],
                        boundary=None
                        if boundary is None
                        else tuple(bool(flag) for flag in boundary[index]),
                    ),
                )
                for index, ordinal in enumerate(ordinals)
            ],
            cell_defined=None if defined is None else bool(defined),
        )

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
            if series.dtype == "json":
                array[...] = np.asarray([jsonvalue.dumps(value) for value in values], dtype="str")
            else:
                array[...] = np.asarray(values, dtype=NUMPY_DTYPE[series.element_dtype]).reshape(
                    (len(values), *series.shape)
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
            element, shape = series.element_dtype, series.shape
            if dtype_of(np.dtype(array.dtype)) != element or tuple(array.shape[1:]) != shape:
                raise ValueError(
                    f"meta/{name} is stored as {array.dtype}{list(array.shape[1:])}, but its tag "
                    f"{tag!r} is {element}{list(shape)}"
                )
            if series.dtype != tag:
                raise ValueError(
                    f"meta/{name}: {META_DTYPE_ATTR} is {tag!r} but the pinned declaration says "
                    f"{series.dtype!r}"
                )
            declared[name] = series
            rows = _logical(array, nstep, f"{META_GROUP}/{name}")
            for ordinal in range(nstep):
                value = rows[ordinal]
                values[ordinal][name] = coerce_meta_value(
                    tag, json.loads(str(value)) if tag == "json" else value
                )
        return declared, values


def _logical(array: zarr.Array, length: int, what: str) -> np.ndarray:
    """The first ``length`` rows of a per-step array (L8).

    A reader is bound by ``len(step)``: a longer array is a tail the writer
    had not yet committed, and is tolerated; a shorter one cannot supply every
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


class ZarrRecordStore(RecordStore):
    """A Zarr V3 root holding a whole record.

    This is the shape a real producer writes. A bare frame at a store root is
    a useful unit to pin down on its own, but nothing ships one -- an
    implementation writes a record, and the frame is a section inside it.
    """

    backend: ClassVar[str] = "zarr"

    def __init__(self, path: Path) -> None:
        self._path = path

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
        if model.metrics is not None or model.observables is not None:
            raise NotImplementedError(
                "the reference record codec lays out meta, status, method, frame, system and "
                "trajectory; metrics and observables have their own chapters and suites"
            )
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
        )

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
