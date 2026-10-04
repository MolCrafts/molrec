"""Adapters that put molrs under molrec's conformance suite.

Two methods per module and no assertions. The conversions report what molrs
actually returns -- they never repair it. An adapter that quietly fixed up a
narrowed integer or a widened float would turn a red suite green while the
files on disk stayed wrong, which is the one failure mode this whole harness
exists to prevent. For the same reason nothing here touches the store behind
molrs's back: the store molrs is asked to read is exactly the one the codec
wrote.

The molrs surface used here is the one the maintainer rulings name:
``molrs.io.mrec.write_frame`` / ``write_system`` / ``read_*`` for records,
``SequenceSchema.from_frames`` + ``declare_meta_with_fill`` and
``TrajectoryWriter(path, schema)`` (``flush_every`` / ``compression`` /
``durable`` left at their defaults: durable, spec-following) for the streaming
trajectory door, ``read_trajectory`` for the eager reading door.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Any

import molrs
import numpy as np

import molrec

_NUMPY_TO_MOLREC = {
    "float16": "f16",
    "float32": "f32",
    "float64": "f64",
    "int8": "i8",
    "int16": "i16",
    "int32": "i32",
    "int64": "i64",
    "uint8": "u8",
    "uint16": "u16",
    "uint32": "u32",
    "uint64": "u64",
    "bool": "bool",
    "complex64": "c64",
    "complex128": "c128",
}


def _dtype_of(values: np.ndarray) -> str:
    if values.dtype.kind in ("U", "T", "O", "S"):
        return "string"
    return _NUMPY_TO_MOLREC[values.dtype.name]


def _to_box(box: molrec.BoxModel) -> molrs.Box:
    return molrs.Box(
        box.vectors,
        box.origin,
        None if box.boundary is None else np.array(box.boundary),
    )


def _to_frame(model: molrec.FrameModel) -> molrs.Frame:
    frame = molrs.Frame()
    for name, block in model.blocks.items():
        native = molrs.Block()
        native.resize(block.count)
        for column, payload in block.columns.items():
            native.insert(column, payload.values)
        if block.structural_shape is not None:
            native.set_shape(list(block.structural_shape))
        frame[name] = native
    if model.box is not None:
        frame.box = _to_box(model.box)
    if model.meta:
        frame.meta = model.meta
    return frame


def _from_frame(frame: molrs.Frame | None) -> dict[str, Any] | None:
    if frame is None:
        return None

    blocks: dict[str, Any] = {}
    for name in frame.keys():  # noqa: SIM118 (molrs Frame has no __iter__)
        native = frame[name]
        columns = {}
        for column in native.keys():  # noqa: SIM118
            values = np.asarray(native.view(column))
            columns[column] = {
                "dtype": _dtype_of(values),
                "shape": tuple(values.shape),
                "values": values,
            }
        structural = native.structural_shape
        blocks[name] = {
            "count": native.nrows if native.nrows is not None else 0,
            "columns": columns,
            "structural_shape": tuple(structural) if structural is not None else None,
        }

    box = None
    if frame.box is not None:
        box = {
            "vectors": np.asarray(frame.box.h),
            "origin": np.asarray(frame.box.origin),
            "boundary": tuple(bool(flag) for flag in np.asarray(frame.box.pbc)),
            "cell_defined": bool(frame.box.cell_defined),
        }

    raw_meta = dict(frame.meta) if frame.meta else {}
    meta = {
        key: (value.value if hasattr(value, "value") else value) for key, value in raw_meta.items()
    }
    return {"blocks": blocks, "box": box, "meta": meta}


def _tag(dtype: Any) -> str:
    """The closed dtype tag as text, whatever enum the model spells it with."""
    return str(getattr(dtype, "value", dtype))


def _declared_schema(model: molrec.TrajectoryModel) -> molrs.io.mrec.SequenceSchema:
    """The pinned declaration molrs is asked to hold the frames to.

    ``blocks`` stated on the model is the declaration; left unstated, the
    first presentation of each block fixes its columns (the model's own rule),
    so a later frame that widens a block is refused rather than absorbed. Meta
    keys are only ever what ``model.meta`` declares -- a key a frame carries
    without a declaration is the ``undeclared_meta_key`` violation, not a
    derivation.
    """
    schema = molrs.io.mrec.SequenceSchema()
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
        if series.fill is not None:
            schema.declare_meta_with_fill(key, series.fill, dtype=_tag(series.dtype))
        else:
            schema.declare_meta(key, _tag(series.dtype))
    return schema


class MolrsRecordAdapter(molrec.RecordAdapter):
    """The whole record -- composed from the primitive doors."""

    backends = ("zarr",)

    def write(self, model: molrec.RecordModel, store) -> None:
        path = Path(store.uri)
        meta = model.meta.model_dump(mode="json", exclude_none=True)
        if model.frame is not None:
            system = None if model.system is None else _to_frame(model.system)
            molrs.io.mrec.write_frame(path, _to_frame(model.frame), system=system, meta=meta)
            return
        if model.system is not None:
            molrs.io.mrec.write_system(path, _to_frame(model.system), meta=meta)
            return
        raise ValueError("record model has neither frame nor system")

    def read(self, store) -> Any:
        path = Path(store.uri)
        present = molrs.io.mrec.sections(path)
        frame = _from_frame(molrs.io.mrec.read_frame(path)) if "frame" in present else None
        system = _from_frame(molrs.io.mrec.read_system(path)) if "system" in present else None
        if frame is None and system is None:
            raise ValueError(f"{path} has neither frame nor system")
        return {
            "meta": molrs.io.mrec.read_meta(path),
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
    cells: list[molrs.Box | None] = []
    current: molrs.Box | None = None
    for ordinal in range(len(model.frames)):
        if ordinal in updates:
            current = _to_box(updates[ordinal])
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

    molrs carries the tag on the value itself, so the declaration is read off
    what molrs returns rather than guessed from the Python type -- a ``1.0``
    that arrived as f32 must not be declared f64. The tag vocabulary is the
    contract's closed set; a tag outside it fails validation in the suite.
    No ``fill`` is reported: molrs's reading door surfaces values, not the
    declaration, and the suite compares a fill only when it is returned.
    """
    declared: dict[str, dict[str, Any]] = {}
    for frame in frames:
        for key, value in dict(frame.meta).items():
            declared.setdefault(key, {"dtype": str(value.dtype)})
    return declared


class MolrsTrajectoryAdapter(molrec.TrajectoryAdapter):
    """A sequence of frames: written through the streaming door, read eagerly.

    Writing goes frame by frame through ``TrajectoryWriter`` so that every
    rule the layout places on the writer -- a reserved name refused at
    declaration, a step that does not increase, a ``time`` that comes and
    goes -- is molrs's to refuse, not the adapter's. Reading goes through
    ``read_trajectory``, which yields the resolved frames with ``step`` /
    ``time`` beside them.
    """

    backends = ("zarr",)

    def write(self, model: molrec.TrajectoryModel, store: molrec.TrajectoryStore) -> None:
        frames = []
        for frame, cell in zip(model.frames, _resolved_cells(model), strict=True):
            native = _to_frame(frame)
            if cell is not None:
                native.box = cell
            frames.append(native)

        schema = _declared_schema(model)

        times = model.time if model.time is not None else [None] * len(frames)
        with molrs.io.mrec.TrajectoryWriter(Path(store.uri), schema) as writer:
            for native, step, time in zip(frames, model.step, times, strict=True):
                writer.append(native, step=int(step), time=None if time is None else float(time))

    def read(self, store: molrec.TrajectoryStore) -> Any:
        trajectory = molrs.io.mrec.read_trajectory(Path(store.uri))
        frames = list(trajectory.frames)
        described = []
        for frame in frames:
            # The cell is the sequence's section, never the frame's: molrec
            # refuses a trajectory whose frames carry one of their own.
            described.append({**_from_frame(frame), "box": None})

        time = trajectory.time
        return {
            "frames": described,
            "step": [int(value) for value in trajectory.step],
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
    # Frame cases run inside records: molrs.write_frame writes Structure
    # (meta + frame/), not a bare frame at the store root.
    record = MolrsRecordAdapter()
    trajectory = MolrsTrajectoryAdapter()
