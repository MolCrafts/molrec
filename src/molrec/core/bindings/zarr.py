"""The Zarr V3 binding for the core module.

Three codecs: a frame, a sequence of frames, and the record root that carries
both. Each documents its own layout; the one below is the frame's, which the
other two build on.

Layout::

    <frame root>/               group attributes = the frame's meta document
    ├── <block>/                group attributes: count, structural_shape
    │   └── <column>            array
    └── box/
        ├── vectors             array
        ├── origin              array (optional)
        └──                     group attributes: boundary

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
width explicit. Nothing molrec-specific is stashed in attributes to recover
it: an implementation that writes the mapped Zarr dtype is readable by anyone
who has read the spec, which is the entire point of a binding.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import zarr

from molrec.binding import Binding, Codec
from molrec.chunking import plan
from molrec.core.model import (
    NUMPY_DTYPE,
    RESERVED_BLOCK_NAMES,
    RESERVED_TRAJECTORY_NAMES,
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    ColumnModel,
    DType,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    RecordModel,
    TrajectoryBoxModel,
    TrajectoryModel,
    dtype_of,
)
from molrec.core.store import FrameStore, RecordStore, TrajectoryStore
from molrec.registry import REGISTRY

BOX_GROUP = "box"

#: molrec dtype -> the Zarr V3 dtype a conforming writer emits.
TO_ZARR: dict[DType, str] = {**NUMPY_DTYPE, "string": "string"}


def _itemsize(dtype: DType) -> int | None:
    """Bytes per element, or ``None`` for a variable-width dtype."""
    if dtype == "string":
        return None
    return np.dtype(NUMPY_DTYPE[dtype]).itemsize


def _create(group: zarr.Group, name: str, shape: tuple[int, ...], dtype: DType) -> zarr.Array:
    """One array, chunked and sharded by molrec's plan.

    None of that is contractual -- a conforming reader opens any chunking --
    but every array molrec writes should be laid out by one decision rather
    than by whichever call site got there first.
    """
    chunks, shards = plan(shape, _itemsize(dtype))
    options: dict[str, tuple[int, ...]] = {}
    if chunks is not None:
        options["chunks"] = chunks
    if shards is not None:
        options["shards"] = shards
    return group.create_array(name, shape=shape, dtype=TO_ZARR[dtype], **options)


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
        group = parent.create_group(name)
        group.attrs["count"] = block.count
        if block.structural_shape is not None:
            group.attrs["structural_shape"] = list(block.structural_shape)

        for column_name, column in block.columns.items():
            self._write_column(group, column_name, column)

    def _write_column(self, group: zarr.Group, name: str, column: ColumnModel) -> None:
        array = _create(group, name, column.shape, column.dtype)
        if column.values is not None:
            array[...] = column.values

    def _read_block(self, group: zarr.Group) -> BlockModel:
        attrs = dict(group.attrs)
        if "count" not in attrs:
            raise ValueError(f"block {group.name!r} has no count attribute")

        columns = {
            name: self._read_column(member)
            for name, member in group.members()
            if isinstance(member, zarr.Array)
        }
        structural = attrs.get("structural_shape")
        return BlockModel(
            count=int(attrs["count"]),
            columns=columns,
            structural_shape=tuple(structural) if structural is not None else None,
        )

    def _read_column(self, array: zarr.Array) -> ColumnModel:
        return ColumnModel(
            dtype=dtype_of(np.dtype(array.dtype)),
            shape=tuple(int(n) for n in array.shape),
            values=array[...],
        )

    def _write_box(self, root: zarr.Group, box: BoxModel) -> None:
        group = root.create_group(BOX_GROUP)
        vectors = group.create_array("vectors", shape=box.vectors.shape, dtype="float64")
        vectors[...] = box.vectors
        if box.origin is not None:
            origin = group.create_array("origin", shape=box.origin.shape, dtype="float64")
            origin[...] = box.origin
        if box.boundary is not None:
            group.attrs["boundary"] = list(box.boundary)

    def _read_box(self, group: zarr.Group) -> BoxModel:
        boundary = group.attrs.get("boundary")
        origin = group["origin"][...] if "origin" in group else None
        return BoxModel(
            vectors=group["vectors"][...],
            origin=origin,
            boundary=tuple(bool(flag) for flag in boundary) if boundary is not None else None,
        )


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

#: The only two attributes the layout names: a per-step meta array carries its
#: exact dtype tag, and the cell carries the one flag whose absence is
#: meaningful. A declared fill is deliberately *not* among them -- it is a
#: writer-side declaration, materialized into the array, and the reference
#: codec does not emit attributes the contract does not name.
META_DTYPE_ATTR = "molrs_meta_dtype"
CELL_DEFINED_ATTR = "cell_defined"


def _meta_dtype_tag(series: MetaSeriesModel) -> str:
    """The value of ``molrs_meta_dtype``: the exact tag of what the array holds.

    molrec reads the dtype off the array itself -- there is no string round
    trip -- so this exists for a reader that has only the tag. The vocabulary
    is the reference implementation's, spelling included: a vector of bools is
    ``bool3`` where a vector of doubles is ``f64x3``.
    """
    if not series.shape:
        return series.dtype
    width = series.shape[0]
    return f"{series.dtype}{width}" if series.dtype == "bool" else f"{series.dtype}x{width}"


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

        trajectory/
        ├── step           Int[nstep]      always written, and written last
        ├── time           Float[nstep]    only when the run supplied times
        ├── meta/<key>     <typed>[nstep][...]    attr molrs_meta_dtype
        ├── box/           attr cell_defined, written only when false
        │   ├── step_index UInt[n_updates]        frame ordinals
        │   ├── vectors    Float[n_updates][3][3]
        │   ├── origin     Float[n_updates][3]
        │   └── boundary   Bool[n_updates][3]
        └── <block>/       attr structural_shape when declared
            ├── step_index UInt[n_updates]        frame ordinals
            ├── offset     UInt[n_updates+1]      CSR row pointer
            └── <column>   <dtype>[total_rows][...]

    Dense per-step arrays carry one row per frame. Everything else -- the cell
    and each block -- carries its own sparse index of the ordinals at which it
    changed, so a section costs what it *changes*, not what the run *lasts*: a
    constant topology is one entry and a fixed cell is one entry, however long
    the run.

    Row counts are never stored. They are ``diff(offset)``, so the two cannot
    disagree. Absence is a zero-row update, with the consequence worth stating
    rather than discovering: a block genuinely present with zero rows is
    indistinguishable from an absent one.
    """

    def write(self, model: TrajectoryModel, store: ZarrTrajectoryStore) -> None:
        store.clear()
        self.write_into(store.root(mode="w").create_group(TRAJECTORY_GROUP), model)

    def read(self, store: ZarrTrajectoryStore) -> TrajectoryModel:
        return self.read_from(store.root(mode="r")[TRAJECTORY_GROUP])

    def write_into(self, group: zarr.Group, model: TrajectoryModel) -> None:
        """Lay a trajectory out under an already-opened group.

        Split out so the record codec reuses it: a trajectory section inside a
        record and a bare trajectory store are the same bytes.
        """
        for name, updates in self._updates(model).items():
            self._write_block(group, name, updates)

        if model.box is not None:
            self._write_box(group, model.box)

        self._write_meta(group, model)

        if model.time is not None:
            _create(group, TIME_ARRAY, (len(model.time),), "f64")[...] = np.asarray(
                model.time, dtype="float64"
            )

        # `step` lands last, after every other array of the commit. It is the
        # commit marker: a reader takes nstep from it, so a crash between two
        # writes costs the uncommitted frames and nothing else.
        _create(group, STEP_ARRAY, (len(model.step),), "i64")[...] = np.asarray(
            model.step, dtype="int64"
        )

    def read_from(self, group: zarr.Group) -> TrajectoryModel:
        step = [int(value) for value in group[STEP_ARRAY][...]]
        nstep = len(step)
        declared, meta = self._read_meta(group, nstep)

        blocks: list[dict[str, BlockModel]] = [{} for _ in range(nstep)]
        for name, member in group.members():
            if not isinstance(member, zarr.Group) or name in RESERVED_TRAJECTORY_NAMES:
                continue
            for ordinal, block in enumerate(self._resolve(member, nstep)):
                if block is not None:
                    blocks[ordinal][name] = block

        return TrajectoryModel(
            frames=[
                FrameModel(blocks=blocks[ordinal], meta=meta[ordinal]) for ordinal in range(nstep)
            ],
            step=step,
            time=[float(value) for value in group[TIME_ARRAY][...]]
            if TIME_ARRAY in group
            else None,
            meta=declared,
            box=self._read_box(group[BOX_GROUP]) if BOX_GROUP in group else None,
        )

    def _updates(self, model: TrajectoryModel) -> dict[str, list[tuple[int, BlockModel | None]]]:
        """Each block's changes, in ordinal order.

        A section earns an entry only when its content differs from its
        previous one -- which is what makes a constant topology one entry
        instead of ``nstep``. A block that goes away earns a zero-row entry,
        the absence marker; a block not yet seen earns nothing at all, because
        no entry ``<= i`` already means absent.
        """
        names = {name for frame in model.frames for name in frame.blocks}
        changes: dict[str, list[tuple[int, BlockModel | None]]] = {}
        for name in sorted(names):
            entries: list[tuple[int, BlockModel | None]] = []
            previous: BlockModel | None = None
            for ordinal, frame in enumerate(model.frames):
                current = frame.blocks.get(name)
                if entries and current == previous:
                    continue
                if not entries and current is None:
                    continue
                entries.append((ordinal, current))
                previous = current
            changes[name] = entries
        return changes

    def _write_block(
        self, parent: zarr.Group, name: str, entries: list[tuple[int, BlockModel | None]]
    ) -> None:
        group = parent.create_group(name)

        offset = np.zeros(len(entries) + 1, dtype="uint64")
        offset[1:] = np.cumsum([0 if block is None else block.count for _, block in entries])
        _create(group, STEP_INDEX_ARRAY, (len(entries),), "u64")[...] = np.asarray(
            [ordinal for ordinal, _ in entries], dtype="uint64"
        )
        _create(group, OFFSET_ARRAY, (len(entries) + 1,), "u64")[...] = offset

        # Every update of a block presents the same columns at the same dtype
        # and trailing shape -- the model refuses anything else -- so the first
        # one that is present is the declaration.
        declared = next(block for _, block in entries if block is not None)
        if declared.structural_shape is not None:
            group.attrs["structural_shape"] = list(declared.structural_shape)

        for column_name, column in declared.columns.items():
            array = _create(
                group,
                column_name,
                (int(offset[-1]), *column.shape[1:]),
                column.dtype,
            )
            for index, (_, block) in enumerate(entries):
                if block is None:
                    continue
                values = block.columns[column_name].values
                if values is not None:
                    array[int(offset[index]) : int(offset[index + 1])] = values

    def _resolve(self, group: zarr.Group, nstep: int) -> list[BlockModel | None]:
        """One block, at every ordinal.

        Binary-search the block's ``step_index`` for the largest entry ``<= i``:
        that is the update whose rows the frame owns. No entry ``<= i`` means
        the block does not exist at that frame -- absence, not an empty block
        -- and neither does a zero-row update.
        """
        ordinals = np.asarray(group[STEP_INDEX_ARRAY][...])
        offset = np.asarray(group[OFFSET_ARRAY][...])
        grid = group.attrs.get("structural_shape")
        columns = {
            name: member
            for name, member in group.members()
            if isinstance(member, zarr.Array) and name not in RESERVED_BLOCK_NAMES
        }

        resolved: list[BlockModel | None] = []
        for ordinal in range(nstep):
            update = int(np.searchsorted(ordinals, ordinal, side="right")) - 1
            if update < 0:
                resolved.append(None)
                continue
            start, stop = int(offset[update]), int(offset[update + 1])
            if start == stop:
                resolved.append(None)
                continue
            resolved.append(
                BlockModel(
                    count=stop - start,
                    columns={
                        name: ColumnModel(
                            dtype=dtype_of(np.dtype(array.dtype)),
                            shape=(stop - start, *(int(n) for n in array.shape[1:])),
                            values=array[start:stop],
                        )
                        for name, array in columns.items()
                    },
                    structural_shape=tuple(grid) if grid is not None else None,
                )
            )
        return resolved

    def _write_box(self, parent: zarr.Group, section: TrajectoryBoxModel) -> None:
        group = parent.create_group(BOX_GROUP)
        updates = section.updates
        count = len(updates)
        ndim = int(updates[0].box.vectors.shape[0])

        _create(group, STEP_INDEX_ARRAY, (count,), "u64")[...] = np.asarray(
            [update.step_index for update in updates], dtype="uint64"
        )
        _create(group, "vectors", (count, ndim, ndim), "f64")[...] = np.stack(
            [update.box.vectors for update in updates]
        )
        _create(group, "origin", (count, ndim), "f64")[...] = np.stack(
            [np.asarray(update.box.origin) for update in updates]
        )
        _create(group, "boundary", (count, ndim), "bool")[...] = np.asarray(
            [update.box.boundary for update in updates], dtype="bool"
        )

        # Absent means true -- every store predating the flag holds a defined
        # cell -- so it is emitted only to record false.
        if section.cell_defined is False:
            group.attrs[CELL_DEFINED_ATTR] = False

    def _read_box(self, group: zarr.Group) -> TrajectoryBoxModel:
        vectors = group["vectors"][...]
        origin = group["origin"][...]
        boundary = group["boundary"][...]
        defined = group.attrs.get(CELL_DEFINED_ATTR)
        return TrajectoryBoxModel(
            updates=[
                BoxUpdateModel(
                    step_index=int(ordinal),
                    box=BoxModel(
                        vectors=vectors[index],
                        origin=origin[index],
                        boundary=tuple(bool(flag) for flag in boundary[index]),
                    ),
                )
                for index, ordinal in enumerate(group[STEP_INDEX_ARRAY][...])
            ],
            cell_defined=None if defined is None else bool(defined),
        )

    def _write_meta(self, group: zarr.Group, model: TrajectoryModel) -> None:
        if not model.meta:
            return
        meta = group.create_group(META_GROUP)
        for key, series in model.meta.items():
            array = _create(meta, key, (len(model.frames), *series.shape), series.dtype)
            array.attrs[META_DTYPE_ATTR] = _meta_dtype_tag(series)
            # Validation has already resolved every declared fill, so every
            # frame carries every declared key by the time we get here -- and
            # the fill lands as an ordinary value, indistinguishable from one
            # the producer supplied. Nothing records that it was a fill.
            array[...] = np.asarray(
                [frame.meta[key] for frame in model.frames], dtype=NUMPY_DTYPE[series.dtype]
            )

    def _read_meta(
        self, group: zarr.Group, nstep: int
    ) -> tuple[dict[str, MetaSeriesModel], list[dict[str, Any]]]:
        declared: dict[str, MetaSeriesModel] = {}
        values: list[dict[str, Any]] = [{} for _ in range(nstep)]
        if META_GROUP not in group:
            return declared, values

        for name, array in group[META_GROUP].members():
            if not isinstance(array, zarr.Array):
                continue
            # No `fill`: it was a writer-side declaration and the store keeps
            # no record of it. A reader cannot distinguish a filled value from
            # a written one, and does not need to -- both are the value there.
            declared[name] = MetaSeriesModel(
                dtype=dtype_of(np.dtype(array.dtype)),
                shape=tuple(int(n) for n in array.shape[1:]),
            )
            rows = array[...]
            for ordinal in range(nstep):
                values[ordinal][name] = np.asarray(rows[ordinal]).tolist()
        return declared, values


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

    Document sections are group attribute maps, not child arrays -- ``meta``
    is a JSON document and Zarr already has a place for those. Frame-shaped
    sections delegate to the frame codec, so there is exactly one description
    of how blocks are laid out.
    """

    def __init__(self) -> None:
        self._frames = ZarrFrameCodec()
        self._trajectories = ZarrTrajectoryCodec()

    def write(self, model: RecordModel, store: ZarrRecordStore) -> None:
        store.clear()
        root = store.root(mode="w")
        root.create_group(RECORD_META).attrs.update(
            model.meta.model_dump(mode="json", exclude_none=True)
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
        return RecordModel(
            meta=MetaModel.model_validate(dict(root[RECORD_META].attrs)),
            frame=self._section(root, RECORD_FRAME),
            system=self._section(root, RECORD_SYSTEM),
            trajectory=self._trajectories.read_from(root[TRAJECTORY_GROUP])
            if TRAJECTORY_GROUP in root
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
