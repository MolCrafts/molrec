"""Adapters that put molrs under molrec's conformance suite.

Two methods per module and no assertions. The conversions report what molrs
actually returns -- they never repair it. An adapter that quietly fixed up a
narrowed integer or a widened float would turn a red suite green while the
files on disk stayed wrong, which is the one failure mode this whole harness
exists to prevent. For the same reason nothing here touches the store behind
molrs's back: the store molrs is asked to read is exactly the one the codec
wrote.

The molrs surface used here is molrs 0.15's: the whole-record doors at
``molrs.io`` -- ``write_mrec`` / ``write_mrec_system`` to write a record,
``mrec_sections`` / ``read_mrec`` / ``read_mrec_system`` / ``read_mrec_meta``
to read one back -- and, for a trajectory, ``molrs.io.mrec.SequenceSchema``
(``declare_*``, ``declare_meta_with_fill``) plus
``molrs.io.mrec.TrajectoryWriter(path, schema)`` (``flush_every`` /
``compression`` / ``durable`` left at their defaults: durable,
spec-following) for the streaming writing door and
``molrs.io.read_mrec_trajectory`` for the eager reading door.

molrs refuses malformed input with ``ValueError`` (every ``MolRsError``), and
an array it cannot store as a column with ``molrs.BlockDtypeError``; those are
the adapters' declared refusals. Anything else molrs or the adapter raises is
a defect and the suite reports it as an error.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Any

import molrs
import numpy as np

import molrec
from molrec.core.model import NUMPY_DTYPE

#: ``Block.dtype`` names the domain scalars by role; every other column dtype
#: is already spelled as the contract spells it.
_MOLRS_DTYPE = {"float": "f64", "int": "i32", "uint": "u64"}

#: What molrs refuses malformed input with.
_REFUSALS: tuple[type[Exception], ...] = (ValueError, molrs.BlockDtypeError)


def _dtype_of(native: molrs.Block, column: str) -> str:
    """The contract dtype of a stored column, as molrs reports it -- never guessed."""
    dtype = native.dtype(column)
    return _MOLRS_DTYPE.get(dtype, dtype)


def _to_box(box: molrec.CellModel, cell_defined: bool) -> molrs.Box:
    return molrs.Box(
        box.vectors,
        box.origin,
        None if box.boundary is None else np.array(box.boundary),
        cell_defined=cell_defined,
    )


def _from_box(box: molrs.Box) -> dict[str, Any]:
    return {
        "vectors": np.asarray(box.h),
        "origin": np.asarray(box.origin),
        "boundary": tuple(bool(flag) for flag in np.asarray(box.pbc)),
        "cell_defined": bool(box.cell_defined),
    }


def _to_frame(model: molrec.FrameModel, tags: Mapping[str, str] | None = None) -> molrs.Frame:
    """The model as a molrs frame.

    ``tags`` are declared per-step meta tags. A plain meta write lets molrs
    infer the tag from the Python value (a list of three bools is not
    obviously ``bool3``), so a declared key is written as a ``MetaValue`` of
    its declared tag; anything else is written plain.
    """
    frame = molrs.Frame()
    for name, block in model.blocks.items():
        native = molrs.Block()
        native.resize(block.count)
        for column, payload in block.columns.items():
            native.insert(column, payload.values)
            if payload.validity is not None:
                native.set_validity(column, payload.validity)
        if block.structural_shape is not None:
            native.set_shape(list(block.structural_shape))
        frame[name] = native
    if model.box is not None:
        frame.box = _to_box(model.box, bool(model.box.cell_defined))
    tags = tags or {}
    for key, value in model.meta.items():
        frame.meta[key] = molrs.MetaValue(tags[key], value) if key in tags else value
    return frame


def _from_frame(frame: molrs.Frame | None) -> dict[str, Any] | None:
    if frame is None:
        return None

    blocks: dict[str, Any] = {}
    for name in frame.keys():  # noqa: SIM118 (molrs Frame has no __iter__)
        native = frame[name]
        columns = {}
        for column in native.keys():  # noqa: SIM118
            values = native.copy_column(column)
            validity = native.validity(column)
            columns[column] = {
                "dtype": _dtype_of(native, column),
                "shape": tuple(values.shape),
                "values": values,
                "validity": None if validity is None else np.asarray(validity, dtype=bool),
            }
        structural = native.structural_shape
        blocks[name] = {
            "count": native.nrows,
            "columns": columns,
            "structural_shape": tuple(structural) if structural is not None else None,
        }

    box = None if frame.box is None else _from_box(frame.box)
    return {"blocks": blocks, "box": box, "meta": _meta_values(frame)}


def _meta_values(frame: molrs.Frame) -> dict[str, Any]:
    """The frame's meta as plain values.

    ``frame.meta`` hands back frozen values (tuples, ``MetaDocument``);
    ``typed()`` gives each key's ``MetaValue``, whose ``value`` is the plain
    payload -- a JSON document as a ``dict``, a fixed-width vector as a tuple.
    """
    return {key: value.value for key, value in frame.meta.typed().items()}


def _tag(dtype: Any) -> str:
    """The closed dtype tag as text, whatever enum the model spells it with."""
    return str(getattr(dtype, "value", dtype))


def _nullable_columns(model: molrec.TrajectoryModel) -> dict[str, dict[str, Any]]:
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
                    found.setdefault(name, {})[column] = molrec.SequenceColumnModel(
                        dtype=payload.dtype, trailing=list(payload.shape[1:]), nullable=True
                    )
    return found


def _with_nullable(model: molrec.TrajectoryModel) -> molrs.io.mrec.SequenceSchema:
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
        native = molrs.Block()
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
        frame = molrs.Frame()
        frame[name] = native
        frames.append(frame)
    if not frames:
        return molrs.io.mrec.SequenceSchema()
    return molrs.io.mrec.SequenceSchema.from_frames(frames)


def _declared_schema(model: molrec.TrajectoryModel) -> molrs.io.mrec.SequenceSchema:
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
            if block.structural_shape is not None:
                schema.declare_structural_shape(name, list(block.structural_shape))
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
                if block.structural_shape is not None:
                    schema.declare_structural_shape(name, list(block.structural_shape))
    for key, series in model.meta.items():
        if series.has_fill:
            schema.declare_meta_with_fill(key, series.fill, dtype=_tag(series.dtype))
        else:
            schema.declare_meta(key, _tag(series.dtype))
    return schema


class MolrsRecordAdapter(molrec.RecordAdapter):
    """The whole record -- composed from the primitive doors."""

    backends = ("zarr",)
    refusal_types = _REFUSALS

    def write(self, model: molrec.RecordModel, store) -> None:
        path = Path(store.uri)
        meta = model.meta.model_dump(mode="json", exclude_none=True)
        if model.frame is not None:
            system = None if model.system is None else _to_frame(model.system)
            molrs.io.write_mrec(path, _to_frame(model.frame), system=system, meta=meta)
            return
        if model.system is not None:
            molrs.io.write_mrec_system(path, _to_frame(model.system), meta=meta)
            return
        # molrs has no door for a record of meta (and status / method) alone.
        raise NotImplementedError("molrs writes a record with a frame or a system section")

    def read(self, store) -> Any:
        path = Path(store.uri)
        present = molrs.io.mrec_sections(path)
        frame = _from_frame(molrs.io.read_mrec(path)) if "frame" in present else None
        system = _from_frame(molrs.io.read_mrec_system(path)) if "system" in present else None
        return {
            "meta": molrs.io.read_mrec_meta(path),
            "frame": frame,
            "system": system,
        }


def _resolved_cells(model: molrec.TrajectoryModel) -> list[molrs.Box | None]:
    """The cell each frame resolves to.

    molrec states the cell once per change and indexes it by ordinal; molrs
    carries one on every frame. Resolving one shape into the other is the
    adapter's job -- the impedance is between the two shapes, not a defect in
    either -- and it is pure bookkeeping: no geometry is recomputed.
    """
    updates = {} if model.box is None else {u.step_index: u.box for u in model.box.updates}
    defined = model.box is None or bool(model.box.cell_defined)
    cells: list[molrs.Box | None] = []
    current: molrs.Box | None = None
    for ordinal in range(len(model.frames)):
        if ordinal in updates:
            current = _to_box(updates[ordinal], defined)
        cells.append(current)
    return cells


def _cell_section(frames: list[molrs.Frame]) -> dict[str, Any] | None:
    """The frames' cells folded back into updates at the ordinals they changed.

    The inverse of :func:`_resolved_cells`, and lossy in exactly the way the
    layout is: a run that repeats one cell for every frame is indistinguishable
    from one that stated it once, which is what makes a fixed cell one update.
    """
    updates: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    defined: bool | None = None
    for ordinal, frame in enumerate(frames):
        if frame.box is None:
            continue
        if defined is None:
            defined = bool(frame.box.cell_defined)
        current = {
            "vectors": np.asarray(frame.box.h),
            "origin": np.asarray(frame.box.origin),
            "boundary": tuple(bool(flag) for flag in np.asarray(frame.box.pbc)),
        }
        if previous is not None and _same_cell(previous, current):
            continue
        updates.append({"step_index": ordinal, "box": current})
        previous = current
    if not updates:
        return None
    return {"updates": updates, "cell_defined": defined}


def _same_cell(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Bitwise, like the layout's own rule for what earns a section an update."""
    return (
        np.array_equal(left["vectors"], right["vectors"])
        and np.array_equal(left["origin"], right["origin"])
        and left["boundary"] == right["boundary"]
    )


def _meta_series(frames: list[molrs.Frame]) -> dict[str, dict[str, Any]]:
    """The per-step meta declaration molrs hands back: the tag on each value.

    molrs carries the tag beside the value (``frame.meta.dtype(key)``), so the
    declaration is read off what molrs returns rather than guessed from the
    Python type -- a ``1.0`` that arrived as f32 must not be declared f64. The
    tag vocabulary is the contract's closed set; a tag outside it fails the
    suite. No ``fill`` is reported: molrs's reading door surfaces values, not
    the declaration, and the suite compares a fill only when it is returned.
    """
    declared: dict[str, dict[str, Any]] = {}
    for frame in frames:
        for key in frame.meta:
            declared.setdefault(key, {"dtype": frame.meta.dtype(key)})
    return declared


class MolrsTrajectoryAdapter(molrec.TrajectoryAdapter):
    """A sequence of frames: written through the streaming door, read eagerly.

    Writing goes frame by frame through ``TrajectoryWriter`` so that every
    rule the layout places on the writer -- a reserved name refused at
    declaration, a step that does not increase, a ``time`` that comes and
    goes -- is molrs's to refuse, not the adapter's. Reading goes through
    ``read_mrec_trajectory``, which yields the resolved frames with ``step`` /
    ``time`` beside them.
    """

    backends = ("zarr",)
    refusal_types = _REFUSALS

    def write(self, model: molrec.TrajectoryModel, store: molrec.TrajectoryStore) -> None:
        tags = {key: _tag(series.dtype) for key, series in model.meta.items()}
        frames = []
        for frame, cell in zip(model.frames, _resolved_cells(model), strict=True):
            native = _to_frame(frame, tags)
            if cell is not None:
                native.box = cell
            frames.append(native)

        schema = _declared_schema(model)

        times = model.time if model.time is not None else [None] * len(frames)
        with molrs.io.mrec.TrajectoryWriter(Path(store.uri), schema) as writer:
            for native, step, time in zip(frames, model.step, times, strict=True):
                writer.append(native, step=int(step), time=None if time is None else float(time))

    def read(self, store: molrec.TrajectoryStore) -> Any:
        trajectory = molrs.io.read_mrec_trajectory(Path(store.uri))
        frames = list(trajectory.frames)
        described = []
        for frame in frames:
            # The cell is the sequence's section, never the frame's: molrec
            # refuses a trajectory whose frames carry one of their own.
            described.append({**_from_frame(frame), "box": None})

        # A store with no committed frame reads back with no step series at
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


def _installed_version() -> str:
    version = getattr(molrs, "__version__", None)
    if version:
        return str(version)
    try:
        return metadata.version("molcrafts-molrs")
    except metadata.PackageNotFoundError:
        return "unknown"


class Molrs(molrec.Implementation):
    name = "molrs"
    version = _installed_version()
    # Frame cases run inside records: molrs.io.write_mrec writes a Structure
    # (meta + frame/), not a bare frame at the store root.
    record = MolrsRecordAdapter()
    trajectory = MolrsTrajectoryAdapter()
