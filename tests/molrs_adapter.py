"""Adapters that put molrs under molrec's conformance suite.

Two methods per module and no assertions. The conversions report what molrs
actually returns -- they never repair it. An adapter that quietly fixed up a
narrowed integer or a widened float would turn a red suite green while the
files on disk stayed wrong, which is the one failure mode this whole harness
exists to prevent. For the same reason nothing here touches the storage behind
molrs's back: the storage molrs is asked to read is exactly the one the codec
wrote.

The molrs surface used here is the current ``molpy`` package (no second
name for the same door). A record is written by ``molpy.io.write_mrec`` and
read back through ``molpy.io.mrec.MrecFile`` (``sections``, ``meta``,
``frame``, ``system``, ``forcefield``). A force field travels as a
``ForceFieldSection``. A trajectory is declared by a ``SequenceSchema``
(``declare_*``; a fill is ``declare_meta(..., fill=)``) and streamed through
``MrecWriter(path, schema)``, then read with ``MrecReader``.

molrs refuses malformed input with ``ValueError`` (every ``MolRsError``), and
an array it cannot storage as a column with ``mp.core.BlockDtypeError``; those are
the adapters' declared refusals. Anything else molrs or the adapter raises is
a defect and the suite reports it as an error.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import molpy as mp
import numpy as np

import molrec
from molrec.core.model import NUMPY_DTYPE, CellModel, document, same_cell, values_dtype
from molrec.safe_name import original_name, safe_name

#: ``Block.dtype`` names the domain scalars by role; every other column dtype
#: is already spelled as the contract spells it.
_MOLRS_DTYPE = {"float": "f64", "int": "i32", "uint": "u64"}

#: What molrs refuses malformed input with.
_REFUSALS: tuple[type[Exception], ...] = (ValueError, mp.core.BlockDtypeError)


def _dtype_of(native: mp.core.Block, column: str) -> str:
    """The contract dtype of a stored column, as molrs reports it -- never guessed."""
    dtype = native.dtype(column)
    return _MOLRS_DTYPE.get(dtype, dtype)


def _to_box(box: CellModel, cell_defined: bool) -> mp.core.Box:
    boundary = None if box.boundary is None else np.array(box.boundary)
    cell = box.vectors if cell_defined else mp.core.Cell.undefined()
    return mp.core.Box(cell, box.origin, boundary)


def _from_box(box: mp.core.Box) -> dict[str, Any]:
    """The box as molrec's cell parts.

    ``Box.matrix`` is the cell matrix (lattice vectors as columns). An
    undefined cell still carries the identity there; ``is_cell_defined`` is
    the flag the record stores only when it is false.
    """
    return {
        "vectors": np.asarray(box.matrix),
        "origin": np.asarray(box.origin),
        "boundary": tuple(bool(flag) for flag in np.asarray(box.pbc)),
        "cell_defined": bool(box.is_cell_defined),
    }


def _to_block(block: molrec.core.model.BlockModel) -> mp.core.Block:
    """One block as a molrs block: columns, masks, precision, shape, targets."""
    native = mp.core.Block()
    native.resize(block.count)
    for column, payload in block.columns.items():
        # The values as the producer handed them: rounding to a declared
        # precision is the writer's job, not the adapter's.
        native.insert(column, payload.values)
        if payload.validity is not None:
            native.set_validity(column, payload.validity)
        if getattr(payload, "precision", None) is not None:
            native.set_precision(column, payload.precision)
    if block.structural_shape is not None:
        native.set_shape(list(block.structural_shape))
    for column, target in (getattr(block, "targets", None) or {}).items():
        native.set_target(column, target)
    return native


def _to_frame(
    model: molrec.core.model.FrameModel, tags: Mapping[str, str] | None = None
) -> mp.core.Frame:
    """The model as a molrs frame.

    Every meta key is written as a ``MetaValue`` of its tag -- the frame's
    ``meta_types``, or the trajectory's declared ``tags`` -- because a plain
    write lets molrs infer the tag from the Python value (a list of three
    bools is not obviously ``bool3``, a ``1`` not obviously ``i32``). A key
    with no tag at all (a model built around the validators) is written plain.
    """
    frame = mp.core.Frame()
    for name, block in model.blocks.items():
        frame[name] = _to_block(block)
    if model.box is not None:
        frame.box = _to_box(model.box, bool(model.box.cell_defined))
    tags = {**(getattr(model, "meta_types", None) or {}), **(tags or {})}
    for key, value in model.meta.items():
        frame.meta[key] = mp.core.MetaValue(tags[key], value) if key in tags else value
    return frame


def _from_frame(
    frame: mp.core.Frame | None, *, in_trajectory: bool = False
) -> dict[str, Any] | None:
    """The frame as molrec's duck.

    A column's declared precision is reported for a frame-shaped section; a
    trajectory states it in its declaration only, never per frame, so a
    trajectory frame's columns report none.
    """
    if frame is None:
        return None

    blocks = {
        name: _from_block(frame[name], in_trajectory=in_trajectory)
        for name in frame.keys()  # noqa: SIM118 (molrs Frame has no __iter__)
    }

    box = None if frame.box is None else _from_box(frame.box)
    typed = frame.meta.typed()
    return {
        "blocks": blocks,
        "box": box,
        "meta": {key: value.value for key, value in typed.items()},
        "meta_types": {key: value.dtype for key, value in typed.items()},
    }


def _from_block(native: mp.core.Block, *, in_trajectory: bool = False) -> dict[str, Any]:
    """One molrs block as molrec's duck: what molrs returned, column by column."""
    columns = {}
    for column in native.keys():  # noqa: SIM118 (molrs Block has no __iter__)
        values = native[column]
        validity = native.validity(column)
        columns[column] = {
            "dtype": _dtype_of(native, column),
            "shape": tuple(values.shape),
            "values": values,
            "validity": None if validity is None else np.asarray(validity, dtype=bool),
            "precision": None if in_trajectory else native.precision(column),
        }
    structural = native.structural_shape
    block: dict[str, Any] = {
        "count": native.n_rows,
        "columns": columns,
        "structural_shape": tuple(structural) if structural is not None else None,
    }
    if not in_trajectory:
        # On a trajectory the declaration states a block's targets.
        block["targets"] = dict(native.targets()) or None
    return block


def _to_section(model: molrec.core.model.ForceFieldModel) -> mp.io.mrec.ForceFieldSection:
    """The force field as molrs's section: the document and every table, whole."""
    tables = {name: _to_block(table) for name, table in model.tables.items()}
    return mp.io.mrec.ForceFieldSection(model.document(), tables)


def _from_section(section: mp.io.mrec.ForceFieldSection | None) -> dict[str, Any] | None:
    """molrs's section as molrec's duck: the document's keys plus its tables."""
    if section is None:
        return None
    document = section.document
    # A style entry states `params` and `endpoint_key` only when they say
    # something; read, absent means none and "type" (forcefield.md, styles).
    styles = [{"params": {}, "endpoint_key": "type", **entry} for entry in document["styles"]]
    tables = {name: _from_block(table) for name, table in section.tables.items()}
    return {**document, "styles": styles, "tables": tables}


def _tag(dtype: Any) -> str:
    """The closed dtype tag as text, whatever enum the model spells it with."""
    return str(getattr(dtype, "value", dtype))


def _nullable_columns(model: molrec.core.model.TrajectoryModel) -> dict[str, dict[str, Any]]:
    """Block -> nullable column -> its declaration, as the model pins it.

    Stated, the declaration's ``nullable`` flags; unstated, the union over the
    frames of every column presented with a mask (the model's own rule).
    """
    found: dict[str, dict[str, Any]] = {}
    if model.blocks:
        for name, block in model.blocks.items():
            for column, declared in block.columns.items():
                if declared.nullable:
                    found.setdefault(name, {})[column] = declared
        return found
    for frame in model.frames:
        for name, block in frame.blocks.items():
            for column, payload in block.columns.items():
                if payload.validity is not None:
                    found.setdefault(name, {})[column] = molrec.core.model.SequenceColumnModel(
                        dtype=payload.dtype, trailing=list(payload.shape[1:]), nullable=True
                    )
    return found


def _with_nullable(model: molrec.core.model.TrajectoryModel) -> mp.io.mrec.SequenceSchema:
    """An empty declaration that already pins the model's nullable columns.

    molrs's Python ``SequenceSchema`` has no door that declares a column
    nullable by hand; it unions nullability from masked frames in
    ``from_frames``. So each nullable column is shown to it once, in a
    one-row frame (``prod(structural_shape)`` rows for a grid) that masks the
    row -- no geometry, no values that are kept -- and every other column and
    key is then declared on top as usual.
    """
    frames = []
    shapes = {name: block.structural_shape for name, block in (model.blocks or {}).items()}
    for name, columns in _nullable_columns(model).items():
        rows = int(np.prod(shapes.get(name) or (1,)))
        native = mp.core.Block()
        native.resize(rows)
        for column, declared in columns.items():
            dtype = _tag(declared.dtype)
            shape = (rows, *declared.trailing)
            values = (
                np.full(shape, "", dtype=str)
                if dtype == "string"
                else np.zeros(shape, dtype=NUMPY_DTYPE[dtype])
            )
            native.insert(column, values)
            native.set_validity(column, np.zeros(rows, dtype=bool))
        frame = mp.core.Frame()
        frame[name] = native
        frames.append(frame)
    if not frames:
        return mp.io.mrec.SequenceSchema.from_frames([])
    return mp.io.mrec.SequenceSchema.from_frames(frames)


def _declared_schema(model: molrec.core.model.TrajectoryModel) -> mp.io.mrec.SequenceSchema:
    """The pinned declaration molrs is asked to hold the frames to.

    ``blocks`` stated on the model is the declaration; left unstated, the
    first presentation of each block fixes its columns (the model's own rule),
    so a later frame that widens a block is refused rather than absorbed. Meta
    keys are only ever what ``model.meta`` declares -- a key a frame carries
    without a declaration is the ``undeclared_meta_key`` violation, not a
    derivation.
    """
    schema = _with_nullable(model)
    if model.blocks:
        for name, block in model.blocks.items():
            schema.declare_block(name)
            for column, declared in block.columns.items():
                schema.declare_column(name, column, _tag(declared.dtype), list(declared.trailing))
                if declared.precision is not None:
                    schema.declare_precision(name, column, declared.precision)
            if block.structural_shape is not None:
                schema.declare_structural_shape(name, list(block.structural_shape))
            for column, target in (getattr(block, "targets", None) or {}).items():
                schema.declare_target(name, column, target)
        # Alignment last: a target must be declared before a block aligns with it.
        for name, block in model.blocks.items():
            if getattr(block, "aligned_with", None) is not None:
                schema.declare_aligned(name, block.aligned_with)
    else:
        seen: set[str] = set()
        for frame in model.frames:
            for name, block in frame.blocks.items():
                if name in seen:
                    continue
                seen.add(name)
                schema.declare_block(name, rows=block.count)
                for column, declared in block.columns.items():
                    trailing = list(getattr(declared, "shape", ()) or ())[1:]
                    schema.declare_column(name, column, _tag(declared.dtype), trailing)
                    if getattr(declared, "precision", None) is not None:
                        schema.declare_precision(name, column, declared.precision)
                if block.structural_shape is not None:
                    schema.declare_structural_shape(name, list(block.structural_shape))
                for column, target in (getattr(block, "targets", None) or {}).items():
                    schema.declare_target(name, column, target)
    for key, series in model.meta.items():
        if series.has_fill:
            schema.declare_meta(key, _tag(series.dtype), fill=series.fill)
        else:
            schema.declare_meta(key, _tag(series.dtype))
    return schema


class MolrsRecordAdapter(molrec.core.adapter.RecordAdapter):
    """The whole record -- composed from the primitive doors."""

    backends = ("zarr",)
    refusal_types = _REFUSALS

    def write(self, model: molrec.core.model.RecordModel, storage) -> None:
        path = Path(storage.uri)
        meta = document(model.meta)
        forcefield = None if model.forcefield is None else _to_section(model.forcefield)
        frame = None if model.frame is None else _to_frame(model.frame)
        system = None if model.system is None else _to_frame(model.system)
        status = None if model.status is None else document(model.status)
        method = None if model.method is None else document(model.method)
        metrics = None if model.metrics is None else _to_metrics(model.metrics)
        observables = None if model.observables is None else _to_observables(model.observables)
        if frame is None and system is None and forcefield is None and status is None:
            raise NotImplementedError(
                "molrs writes a record with a frame, a system, a forcefield or a status section"
            )
        mp.io.write_mrec(
            path,
            meta=meta,
            frame=frame,
            system=system,
            forcefield=forcefield,
            status=status,
            method=method,
            metrics=metrics,
            observables=observables,
        )

    def read(self, storage) -> Any:
        path = Path(storage.uri)
        opened = mp.io.mrec.MrecFile(path)
        present = set(opened.sections())
        frame = _from_frame(opened.frame()) if "frame" in present else None
        system = _from_frame(opened.system()) if "system" in present else None
        return {
            "meta": opened.meta(),
            "frame": frame,
            "system": system,
            "forcefield": _from_section(opened.forcefield()) if "forcefield" in present else None,
            "status": opened.status(),
            "method": opened.method(),
            "metrics": _from_metrics(opened.metrics()),
            "observables": _from_observables(opened.observables()),
        }


def _resolved_cells(model: molrec.core.model.TrajectoryModel) -> list[mp.core.Box | None]:
    """The cell each frame resolves to.

    molrec states the cell once per change and indexes it by ordinal; molrs
    carries one on every frame. Resolving one shape into the other is the
    adapter's job -- the impedance is between the two shapes, not a defect in
    either -- and it is pure bookkeeping: no geometry is recomputed.
    """
    updates = {} if model.box is None else {u.step_index: u.box for u in model.box.updates}
    defined = model.box is None or bool(model.box.cell_defined)
    cells: list[mp.core.Box | None] = []
    current: mp.core.Box | None = None
    for ordinal in range(len(model.frames)):
        if ordinal in updates:
            current = _to_box(updates[ordinal], defined)
        cells.append(current)
    return cells


def _cell_section(frames: list[mp.core.Frame]) -> dict[str, Any] | None:
    """The frames' cells folded back into updates at the ordinals they changed.

    The inverse of :func:`_resolved_cells`, and lossy in exactly the way the
    layout is: a run that repeats one cell for every frame is indistinguishable
    from one that stated it once, which is what makes a fixed cell one update.
    """
    updates: list[dict[str, Any]] = []
    previous: CellModel | None = None
    defined: bool | None = None
    for ordinal, frame in enumerate(frames):
        if frame.box is None:
            continue
        if defined is None:
            defined = bool(frame.box.is_cell_defined)
        current = CellModel(
            vectors=np.asarray(frame.box.matrix),
            origin=np.asarray(frame.box.origin),
            boundary=tuple(bool(flag) for flag in np.asarray(frame.box.pbc)),
        )
        # Bit for bit: the layout's own rule for what earns the section an update.
        if previous is not None and same_cell(previous, current):
            continue
        updates.append({"step_index": ordinal, "box": current})
        previous = current
    if not updates:
        return None
    return {"updates": updates, "cell_defined": defined}


def _meta_series(frames: list[mp.core.Frame]) -> dict[str, dict[str, Any]]:
    """The per-step meta declaration molrs hands back: the tag on each value.

    molrs carries the tag beside the value (``frame.meta.dtype(key)``), so the
    declaration is read off what molrs returns rather than guessed from the
    Python type -- a ``1`` that arrived as u64 must not be declared i64. The
    tag vocabulary is the contract's closed set; a tag outside it fails the
    suite. No ``fill`` is reported: molrs's reading door surfaces values, not
    the declaration, and the suite compares a fill only when it is returned.
    """
    declared: dict[str, dict[str, Any]] = {}
    for frame in frames:
        for key in frame.meta:
            declared.setdefault(key, {"dtype": frame.meta.dtype(key)})
    return declared


class MolrsForceFieldAdapter(molrec.core.adapter.ForceFieldAdapter):
    """A force-field package: ``meta`` and the ``forcefield`` section alone.

    Written by ``molpy.io.write_mrec(..., forcefield=)`` and read through
    ``MrecFile.forcefield``, which carry the section whole -- every document
    key, every table, units as stated -- so a section molrs could not compile
    (``nm`` units, smirks keys, an unknown category) is still judged on what
    molrs stores. Turning it into a force field is
    ``ForceFieldSection.to_forcefield``, which this format-level suite does not
    ask for.
    """

    backends = ("zarr",)
    refusal_types = _REFUSALS

    def write(
        self,
        model: molrec.core.model.ForceFieldModel,
        storage: molrec.core.storage.ForceFieldStorage,
    ) -> None:
        mp.io.write_mrec(Path(storage.uri), forcefield=_to_section(model))

    def read(self, storage: molrec.core.storage.ForceFieldStorage) -> Any:
        return _from_section(mp.io.mrec.MrecFile(Path(storage.uri)).forcefield())


class MolrsTrajectoryAdapter(molrec.core.adapter.TrajectoryAdapter):
    """A sequence of frames: written through the streaming door, read eagerly.

    Writing goes frame by frame through ``MrecWriter`` so that every
    rule the layout places on the writer -- a reserved name refused at
    declaration, a step that does not increase, a ``time`` that comes and
    goes -- is molrs's to refuse, not the adapter's. Reading goes through
    ``MrecReader``, which yields the resolved frames with ``step`` and
    ``time`` beside them.
    """

    backends = ("zarr",)
    refusal_types = _REFUSALS

    def write(
        self,
        model: molrec.core.model.TrajectoryModel,
        storage: molrec.core.storage.TrajectoryStorage,
    ) -> None:
        tags = {key: _tag(series.dtype) for key, series in model.meta.items()}
        frames = []
        for frame, cell in zip(model.frames, _resolved_cells(model), strict=True):
            native = _to_frame(frame, tags)
            if cell is not None:
                native.box = cell
            frames.append(native)

        schema = _declared_schema(model)

        times = model.time if model.time is not None else [None] * len(frames)
        with mp.io.mrec.MrecWriter(Path(storage.uri), schema) as writer:
            for native, step, time in zip(frames, model.step, times, strict=True):
                writer.append(native, step=int(step), time=None if time is None else float(time))

    def read(self, storage: molrec.core.storage.TrajectoryStorage) -> Any:
        trajectory = mp.io.mrec.MrecReader(Path(storage.uri))
        frames = list(trajectory)
        described = []
        for frame in frames:
            # The cell is the sequence's section, never the frame's: molrec
            # refuses a trajectory whose frames carry one of their own.
            described.append({**_from_frame(frame, in_trajectory=True), "box": None})

        # A storage with no committed frame reads back with no step series at
        # all; that is the empty sequence. Step numbers missing beside frames
        # are reported as they are, for the suite to judge.
        step = trajectory.step
        if step is not None:
            step = [int(value) for value in step]
        elif not frames:
            step = []
        time = trajectory.time
        return {
            "frames": described,
            "step": step,
            "time": None if time is None else [float(value) for value in time],
            "meta": _meta_series(frames),
            "box": _cell_section(frames),
        }


def _to_metrics(node: molrec.core.model.NodeModel) -> dict[str, Any]:
    """A metrics node as molrs's section: logical series names, dense arrays."""

    def columns(child: str) -> dict[str, Any]:
        group = node.groups.get(child)
        if group is None:
            return {}
        return {original_name(name): array.values for name, array in group.arrays.items()}

    section: dict[str, Any] = {
        "catalog": dict(node.attributes),
        "series": columns("series"),
        "steps": columns("steps"),
        "wall_time": columns("wall_time"),
    }
    return section


def _array_node(values: np.ndarray) -> dict[str, Any]:
    return {
        "dtype": values_dtype(np.asarray(values)),
        "shape": tuple(int(n) for n in np.asarray(values).shape),
        "values": np.asarray(values),
        "attributes": {},
    }


def _from_metrics(section: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """molrs's metrics section as the node the record stores."""
    if section is None:
        return None

    def group(child: str) -> dict[str, Any]:
        arrays = {safe_name(name): _array_node(values) for name, values in section[child].items()}
        return {"attributes": {}, "arrays": arrays, "groups": {}}

    groups = {child: group(child) for child in ("series", "steps", "wall_time") if section[child]}
    return {"attributes": dict(section["catalog"]), "arrays": {}, "groups": groups}


def _to_observables(model: molrec.observables.model.ObservablesModel) -> dict[str, Any]:
    return {
        name: {"meta": document(item.meta), "data": item.data.values}
        for name, item in model.observables.items()
    }


def _observable_items(section: Mapping[str, Any]) -> dict[str, Any]:
    """An observable's array is an ``ArrayModel``: dtype, shape and values."""
    return {
        name: {
            "meta": dict(item["meta"]),
            "data": {
                "dtype": values_dtype(np.asarray(item["data"])),
                "shape": tuple(int(n) for n in np.asarray(item["data"]).shape),
                "values": np.asarray(item["data"]),
            },
        }
        for name, item in section.items()
    }


def _from_observables(section: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if section is None:
        return None
    return {"observables": _observable_items(section)}


def _installed_version() -> str:
    return mp.__version__


class MolrsObservablesAdapter(molrec.observables.adapter.ObservableAdapter):
    """The observables section inside a record.

    A record needs a substantive section, so the written store also carries a
    status document. The suite compares only the observables section.
    """

    backends = ("zarr",)
    refusal_types = _REFUSALS

    def write(self, model: molrec.observables.model.ObservablesModel, storage) -> None:
        mp.io.write_mrec(
            Path(storage.uri),
            status={"state": "succeeded"},
            observables=_to_observables(model),
        )

    def read(self, storage) -> Any:
        section = mp.io.mrec.MrecFile(Path(storage.uri)).observables()
        return {"observables": {} if section is None else _observable_items(section)}


class Molrs(molrec.adapter.Implementation):
    name = "molrs"
    version = _installed_version()
    # Frame cases run inside records: write_mrec writes meta plus a frame
    # section, not a bare frame at the storage root.
    record = MolrsRecordAdapter()
    trajectory = MolrsTrajectoryAdapter()
    forcefield = MolrsForceFieldAdapter()
    observables = MolrsObservablesAdapter()
    # No `collection` adapter. molrec's LMDB codec is the plain reference the
    # suite already judges; the collection store is molhub's.
