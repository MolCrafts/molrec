"""Adapters that put molrs under molrec's conformance suite.

Two methods per module and no assertions. The conversions report what molrs
actually returns -- they never repair it. An adapter that quietly fixed up a
narrowed integer or a widened float would turn a red suite green while the
files on disk stayed wrong, which is the one failure mode this whole harness
exists to prevent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import molrs
import numpy as np
import zarr

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


def _to_frame(model: molrec.FrameModel) -> molrs.Frame:
    frame = molrs.Frame()
    for name, block in model.blocks.items():
        native = molrs.Block()
        if not block.columns:
            native.resize(block.count)
        for column, payload in block.columns.items():
            native.insert(column, payload.values)
        if block.structural_shape is not None:
            native.set_shape(list(block.structural_shape))
        frame[name] = native
    if model.box is not None:
        frame.box = molrs.Box(
            model.box.vectors,
            model.box.origin,
            None if model.box.boundary is None else np.array(model.box.boundary),
        )
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
        }

    raw_meta = dict(frame.meta) if frame.meta else {}
    meta = {
        key: (value.value if hasattr(value, "value") else value) for key, value in raw_meta.items()
    }
    return {"blocks": blocks, "box": box, "meta": meta}


class MolrsRecordAdapter(molrec.RecordAdapter):
    """The whole record -- the shape molrs actually emits."""

    backends = ("zarr",)

    def write(self, model: molrec.RecordModel, store) -> None:
        record = molrs.Record()
        record.meta = model.meta.model_dump(mode="json", exclude_none=True)
        if model.frame is not None:
            record.set_frame(_to_frame(model.frame))
        if model.system is not None:
            record.set_system(_to_frame(model.system))
        record.write(store.uri)

    def read(self, store) -> Any:
        record = molrs.Record.read(store.uri)
        return {
            "meta": dict(record.meta),
            "frame": _from_frame(record.frame),
            "system": _from_frame(record.system),
        }


#: molrs's per-step meta dtype tag -> the molrec dtype and trailing shape it
#: declares. molrs carries the tag on the value itself, so the declaration is
#: read off what molrs returns rather than guessed from the Python type -- a
#: `1.0` that arrived as f32 must not be declared f64.
_META_DTYPE: dict[str, tuple[str, tuple[int, ...]]] = {
    "f32": ("f32", ()),
    "f64": ("f64", ()),
    "i32": ("i32", ()),
    "i64": ("i64", ()),
    "u32": ("u32", ()),
    "u64": ("u64", ()),
    "bool": ("bool", ()),
    "string": ("string", ()),
    "f64x3": ("f64", (3,)),
    "f64x6": ("f64", (6,)),
    "f64x9": ("f64", (9,)),
    "i64x3": ("i64", (3,)),
    "u64x3": ("u64", (3,)),
    "bool3": ("bool", (3,)),
}


def _to_box(box: molrec.BoxModel) -> molrs.Box:
    return molrs.Box(
        box.vectors,
        box.origin,
        None if box.boundary is None else np.array(box.boundary),
    )


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
    """The per-step meta declaration molrs hands back.

    ``fill`` is absent on purpose: it is not something molrs returns. See the
    note on :class:`MolrsTrajectoryAdapter`.
    """
    declared: dict[str, dict[str, Any]] = {}
    for frame in frames:
        for key, value in dict(frame.meta).items():
            tag = str(value.dtype)
            if tag not in _META_DTYPE:
                raise ValueError(f"per-step meta key {key!r} came back as molrs dtype {tag!r}")
            dtype, shape = _META_DTYPE[tag]
            declared.setdefault(key, {"dtype": dtype, "shape": shape})
    return declared


def _record_shaped(store: molrec.TrajectoryStore) -> str:
    """The store path, with the identity document molrs's doors require.

    molrs has no bare-trajectory door: ``Trajectory.read`` goes through the
    record reader and refuses a root without ``meta/`` -- "not a MolRec
    record: missing required 'meta' section" -- while the suite mints a store
    holding ``trajectory/`` alone. Adding the minimal meta group is a
    store-shape graft, hand-built the same way the absent-boundary fixture is;
    it touches nothing in the sequence and repairs nothing molrs returns.
    """
    root = zarr.open_group(store=Path(store.uri), mode="a")
    if "meta" not in root:
        root.create_group("meta").attrs.update({"record_schema_version": 1, "format_name": "mrec"})
    return store.uri


class MolrsTrajectoryAdapter(molrec.TrajectoryAdapter):
    """A sequence of frames, through molrs's eager trajectory door.

    ``Trajectory.write`` / ``Trajectory.read`` are the only public doors:
    ``FrameSequence`` is not bound to Python this release, so the streaming
    surface -- and with it ``declare_meta``, the only place a per-step meta
    **fill** can be stated -- is unreachable from here. A declared fill
    therefore does not survive either direction, and this adapter reports that
    rather than filling it in from the store behind molrs's back.
    """

    backends = ("zarr",)

    def write(self, model: molrec.TrajectoryModel, store: molrec.TrajectoryStore) -> None:
        frames = []
        for frame, cell in zip(model.frames, _resolved_cells(model), strict=True):
            native = _to_frame(frame)
            if cell is not None:
                native.box = cell
            frames.append(native)

        molrs.Trajectory.from_frames(
            frames,
            step=np.asarray(model.step, dtype="int64"),
            time=None if model.time is None else np.asarray(model.time, dtype="float64"),
        ).write(store.uri)

    def read(self, store: molrec.TrajectoryStore) -> Any:
        trajectory = molrs.Trajectory.read(_record_shaped(store))
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


class Molrs(molrec.Implementation):
    name = "molrs"
    version = "0.14.0"
    # No frame adapter: molrs has no public door for a bare frame at a store
    # root, and inventing one to satisfy a suite would test something nobody
    # ships. The frame cases run inside records instead.
    record = MolrsRecordAdapter()
    trajectory = MolrsTrajectoryAdapter()
