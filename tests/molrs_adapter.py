"""Adapters that put molrs under molrec's conformance suite.

Two methods per module and no assertions. The conversions report what molrs
actually returns -- they never repair it. An adapter that quietly fixed up a
narrowed integer or a widened float would turn a red suite green while the
files on disk stayed wrong, which is the one failure mode this whole harness
exists to prevent. For the same reason nothing here touches the store behind
molrs's back: the store molrs is asked to read is exactly the one the codec
wrote.

The molrs surface used here is molrs 0.16's: the whole-record doors are
functions at the top of ``molrs.io`` -- ``write_mrec`` / ``write_mrec_system``
(both taking ``forcefield=``) and ``write_mrec_forcefield`` to write a record,
``read_mrec`` / ``read_mrec_system`` / ``read_mrec_meta`` /
``read_mrec_forcefield`` to read one back, and ``read_mrec_trajectory`` for
the eager trajectory read -- and the store's own classes are
``molrs.io.mrec``'s: ``section_names`` lists a record's sections, a force
field travels as a ``ForceFieldSection`` (the document plus one ``Block`` per
style table, kept whole), and a trajectory is declared by a
``SequenceSchema`` (``declare_*``, ``declare_meta_with_fill``) and streamed
through ``MrecWriter(path, schema)`` (``flush_every`` / ``compression`` /
``durable`` left at their defaults: durable, spec-following).

molrs refuses malformed input with ``ValueError`` (every ``MolRsError``), and
an array it cannot store as a column with ``molrs.store.BlockDtypeError``; those are
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
from molrec.core.model import MOLREC_VERSION, NUMPY_DTYPE, CellModel, document, same_cell

#: ``Block.dtype`` names the domain scalars by role; every other column dtype
#: is already spelled as the contract spells it.
_MOLRS_DTYPE = {"float": "f64", "int": "i32", "uint": "u64"}

#: What molrs refuses malformed input with.
_REFUSALS: tuple[type[Exception], ...] = (ValueError, molrs.store.BlockDtypeError)

# ---------------------------------------------------------------------------
# What molrs cannot run yet -- the one place it is declared.
#
# Each entry names the molrs API a group of cases needs, whether this molrs
# build has it, and the cases, per conformance module. A case whose API is
# present is judged like any other (so it goes red, not skipped, the moment
# molrs lands the API with a defect); one whose API is absent is reported as
# a skip carrying the missing API's name. Nothing here is an xfail.
# ---------------------------------------------------------------------------

_MREC = molrs.io.mrec

#: Whether this molrs build carries a block's row references (molrec F4).
_HAS_TARGETS = hasattr(molrs.store.Block, "set_target") and hasattr(molrs.store.Block, "targets")


def _refuses_pair_conflicts() -> bool:
    """Whether this molrs build refuses, on reading a section, a pair table that
    restates ``{A, B}`` as ``B``-``A`` with another epsilon (molrec forcefield
    rule 3). molrs 0.15.1 refuses it only when it compiles the kernel."""
    if not hasattr(_MREC, "ForceFieldSection"):
        return False
    rows = molrs.store.Block()
    rows.resize(2)
    for column, values in {
        "name": ["A-B", "B-A"],
        "itom": ["A", "B"],
        "jtom": ["B", "A"],
        "epsilon": [0.9, 0.8],
        "sigma": [2.0, 2.0],
    }.items():
        rows.insert(column, np.array(values))
    document = {
        "name": "probe",
        "units": {"preset": "real"},
        "styles": [{"category": "pair", "style": "lj/cut"}],
    }
    try:
        _MREC.ForceFieldSection(document, {"pair.lj%2Fcut": rows}).validate()
    except _REFUSALS:
        return True
    return False


#: Whether this molrs build writes and reads molrec_version 2 (molrs 0.16).
#: Until it does it refuses every store the suite's codec stamps 2 and stamps
#: 1 on every record it writes, so no positive record, trajectory or
#: force-field case -- and no version-1 refusal -- can be judged on it.
_SPEAKS_VERSION_2 = getattr(_MREC.schema, "MOLREC_VERSION", 1) >= MOLREC_VERSION


def _version_2_cases(*modules: str) -> dict[str, tuple[str, ...]]:
    return {
        module: tuple(
            case.id
            for case in molrec.registry.REGISTRY.suite_for(module)().cases()
            if not case.expect_violation or case.id.startswith("reject-v1-")
        )
        for module in modules
    }


_PENDING: tuple[tuple[str, bool, dict[str, tuple[str, ...]]], ...] = (
    (
        "molrec_version 2 (molrs.io.mrec.schema.MOLREC_VERSION 2: the stamp, and version-1 "
        "records converted on read)",
        _SPEAKS_VERSION_2,
        _version_2_cases("record", "trajectory", "forcefield"),
    ),
    (
        "molrs.store.Block.set_target / Block.targets (row references, molrec F4)",
        _HAS_TARGETS,
        {
            "record": (
                "frame/targets-declared",
                "frame/reject-target-out-of-range",
                "frame/reject-target-missing-block",
                "frame/reject-target-not-u64",
                "targets-absolute",
                "reject-target-absolute-out-of-range",
                "reject-target-into-trajectory",
            ),
        },
    ),
    (
        "molrs.io.mrec.SequenceSchema.declare_target (row references, molrec F4)",
        hasattr(_MREC.SequenceSchema, "declare_target"),
        {"trajectory": ("targets-pinned", "reject-target-out-of-range-resolved")},
    ),
    (
        "molrs.io.mrec.ForceFieldSection.validate refusing conflicting pair rows "
        "(molrec forcefield rule 3)",
        _refuses_pair_conflicts(),
        {"forcefield": ("reject-ff-pair-conflict",)},
    ),
    (
        "molrs.ff.forcefield.CmapStyle (the cmap category and its f64[T, N, N] grid)",
        hasattr(molrs.ff.forcefield, "CmapStyle"),
        {"forcefield": ("ff-cmap-grid",)},
    ),
    (
        "molrs.io.mrec.SequenceSchema.declare_aligned (aligned blocks, molrec F5)",
        hasattr(_MREC.SequenceSchema, "declare_aligned"),
        {
            "trajectory": (
                "aligned-carries-forward",
                "aligned-restated-on-growth",
                "aligned-absent-then-present",
                "aligned-empty-target",
                "reject-aligned-not-restated",
                "reject-aligned-count-mismatch",
                "reject-aligned-target-undeclared",
                "reject-aligned-chain",
                "reject-aligned-shared-column",
                "reject-aligned-target-absent",
            ),
        },
    ),
)


def _unsupported(module: str) -> dict[str, str]:
    """``module``'s cases whose molrs API this build lacks, each with the API."""
    return {
        case: f"molrs lacks {api}"
        for api, available, cases in _PENDING
        if not available
        for case in cases.get(module, ())
    }


def _dtype_of(native: molrs.store.Block, column: str) -> str:
    """The contract dtype of a stored column, as molrs reports it -- never guessed."""
    dtype = native.dtype(column)
    return _MOLRS_DTYPE.get(dtype, dtype)


def _to_box(box: CellModel, cell_defined: bool) -> molrs.spatial.Box:
    return molrs.spatial.Box(
        box.vectors,
        box.origin,
        None if box.boundary is None else np.array(box.boundary),
        cell_defined=cell_defined,
    )


def _from_box(box: molrs.spatial.Box) -> dict[str, Any]:
    return {
        "vectors": np.asarray(box.h),
        "origin": np.asarray(box.origin),
        "boundary": tuple(bool(flag) for flag in np.asarray(box.pbc)),
        "cell_defined": bool(box.cell_defined),
    }


def _to_block(block: molrec.core.model.BlockModel) -> molrs.store.Block:
    """One block as a molrs block: columns, masks, precision, shape, targets."""
    native = molrs.store.Block()
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
) -> molrs.store.Frame:
    """The model as a molrs frame.

    Every meta key is written as a ``MetaValue`` of its tag -- the frame's
    ``meta_types``, or the trajectory's declared ``tags`` -- because a plain
    write lets molrs infer the tag from the Python value (a list of three
    bools is not obviously ``bool3``, a ``1`` not obviously ``i32``). A key
    with no tag at all (a model built around the validators) is written plain.
    """
    frame = molrs.store.Frame()
    for name, block in model.blocks.items():
        frame[name] = _to_block(block)
    if model.box is not None:
        frame.box = _to_box(model.box, bool(model.box.cell_defined))
    tags = {**(getattr(model, "meta_types", None) or {}), **(tags or {})}
    for key, value in model.meta.items():
        frame.meta[key] = molrs.store.MetaValue(tags[key], value) if key in tags else value
    return frame


def _from_frame(
    frame: molrs.store.Frame | None, *, in_trajectory: bool = False
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


def _from_block(native: molrs.store.Block, *, in_trajectory: bool = False) -> dict[str, Any]:
    """One molrs block as molrec's duck: what molrs returned, column by column."""
    columns = {}
    for column in native.keys():  # noqa: SIM118 (molrs Block has no __iter__)
        values = native.copy_column(column)
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
        "count": native.nrows,
        "columns": columns,
        "structural_shape": tuple(structural) if structural is not None else None,
    }
    if _HAS_TARGETS and not in_trajectory:
        # On a trajectory the declaration states a block's targets.
        targets = native.targets
        targets = dict(targets() if callable(targets) else targets)
        block["targets"] = targets or None
    return block


def _to_section(model: molrec.core.model.ForceFieldModel) -> molrs.io.mrec.ForceFieldSection:
    """The force field as molrs's section: the document and every table, whole."""
    tables = {name: _to_block(table) for name, table in model.tables.items()}
    return molrs.io.mrec.ForceFieldSection(model.document(), tables)


def _from_section(section: molrs.io.mrec.ForceFieldSection | None) -> dict[str, Any] | None:
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


def _with_nullable(model: molrec.core.model.TrajectoryModel) -> molrs.io.mrec.SequenceSchema:
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
        native = molrs.store.Block()
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
        frame = molrs.store.Frame()
        frame[name] = native
        frames.append(frame)
    if not frames:
        return molrs.io.mrec.SequenceSchema()
    return molrs.io.mrec.SequenceSchema.from_frames(frames)


def _declared_schema(model: molrec.core.model.TrajectoryModel) -> molrs.io.mrec.SequenceSchema:
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
            schema.declare_meta_with_fill(key, series.fill, dtype=_tag(series.dtype))
        else:
            schema.declare_meta(key, _tag(series.dtype))
    return schema


class MolrsRecordAdapter(molrec.core.adapter.RecordAdapter):
    """The whole record -- composed from the primitive doors."""

    backends = ("zarr",)
    refusal_types = _REFUSALS
    unsupported = _unsupported("record")

    def write(self, model: molrec.core.model.RecordModel, store) -> None:
        path = Path(store.uri)
        meta = document(model.meta)
        forcefield = None if model.forcefield is None else _to_section(model.forcefield)
        if model.frame is not None:
            system = None if model.system is None else _to_frame(model.system)
            molrs.io.write_mrec(
                path, _to_frame(model.frame), system=system, meta=meta, forcefield=forcefield
            )
            return
        if model.system is not None:
            molrs.io.write_mrec_system(
                path, _to_frame(model.system), meta=meta, forcefield=forcefield
            )
            return
        if forcefield is not None:
            molrs.io.write_mrec_forcefield(path, forcefield, meta=meta)
            return
        # molrs has no door for a record of meta (and status / method) alone.
        raise NotImplementedError(
            "molrs writes a record with a frame, a system or a forcefield section"
        )

    def read(self, store) -> Any:
        path = Path(store.uri)
        present = molrs.io.mrec.section_names(path)
        frame = _from_frame(molrs.io.read_mrec(path)) if "frame" in present else None
        system = _from_frame(molrs.io.read_mrec_system(path)) if "system" in present else None
        return {
            "meta": molrs.io.read_mrec_meta(path),
            "frame": frame,
            "system": system,
            "forcefield": _from_section(molrs.io.read_mrec_forcefield(path)),
        }


def _resolved_cells(model: molrec.core.model.TrajectoryModel) -> list[molrs.spatial.Box | None]:
    """The cell each frame resolves to.

    molrec states the cell once per change and indexes it by ordinal; molrs
    carries one on every frame. Resolving one shape into the other is the
    adapter's job -- the impedance is between the two shapes, not a defect in
    either -- and it is pure bookkeeping: no geometry is recomputed.
    """
    updates = {} if model.box is None else {u.step_index: u.box for u in model.box.updates}
    defined = model.box is None or bool(model.box.cell_defined)
    cells: list[molrs.spatial.Box | None] = []
    current: molrs.spatial.Box | None = None
    for ordinal in range(len(model.frames)):
        if ordinal in updates:
            current = _to_box(updates[ordinal], defined)
        cells.append(current)
    return cells


def _cell_section(frames: list[molrs.store.Frame]) -> dict[str, Any] | None:
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
            defined = bool(frame.box.cell_defined)
        current = CellModel(
            vectors=np.asarray(frame.box.h),
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


def _meta_series(frames: list[molrs.store.Frame]) -> dict[str, dict[str, Any]]:
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

    Written through ``molrs.io.write_mrec_forcefield`` and read through
    ``molrs.io.read_mrec_forcefield``, which carry the section whole -- every document
    key, every table, units as stated -- so a section molrs could not compile
    (``nm`` units, smirks keys, an unknown category) is still judged on what
    molrs stores. Turning it into a ``molrs.ff.forcefield.ForceField`` is
    ``ForceField.from_section``, which this format-level suite does not ask
    for.
    """

    backends = ("zarr",)
    refusal_types = _REFUSALS
    unsupported = _unsupported("forcefield")

    def write(
        self, model: molrec.core.model.ForceFieldModel, store: molrec.core.store.ForceFieldStore
    ) -> None:
        molrs.io.write_mrec_forcefield(Path(store.uri), _to_section(model))

    def read(self, store: molrec.core.store.ForceFieldStore) -> Any:
        return _from_section(molrs.io.read_mrec_forcefield(Path(store.uri)))


class MolrsTrajectoryAdapter(molrec.core.adapter.TrajectoryAdapter):
    """A sequence of frames: written through the streaming door, read eagerly.

    Writing goes frame by frame through ``MrecWriter`` so that every
    rule the layout places on the writer -- a reserved name refused at
    declaration, a step that does not increase, a ``time`` that comes and
    goes -- is molrs's to refuse, not the adapter's. Reading goes through
    ``molrs.io.read_mrec_trajectory``, which yields the resolved frames with ``step`` /
    ``time`` beside them.
    """

    backends = ("zarr",)
    refusal_types = _REFUSALS
    unsupported = _unsupported("trajectory")

    def write(
        self, model: molrec.core.model.TrajectoryModel, store: molrec.core.store.TrajectoryStore
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
        with molrs.io.mrec.MrecWriter(Path(store.uri), schema) as writer:
            for native, step, time in zip(frames, model.step, times, strict=True):
                writer.append(native, step=int(step), time=None if time is None else float(time))

    def read(self, store: molrec.core.store.TrajectoryStore) -> Any:
        trajectory = molrs.io.read_mrec_trajectory(Path(store.uri))
        frames = list(trajectory.frames)
        described = []
        for frame in frames:
            # The cell is the sequence's section, never the frame's: molrec
            # refuses a trajectory whose frames carry one of their own.
            described.append({**_from_frame(frame, in_trajectory=True), "box": None})

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
    try:
        return metadata.version("molcrafts-molrs")
    except metadata.PackageNotFoundError:
        return "unknown"


class Molrs(molrec.adapter.Implementation):
    name = "molrs"
    version = _installed_version()
    # Frame cases run inside records: molrs.io.write_mrec writes a Structure
    # (meta + frame/), not a bare frame at the store root.
    record = MolrsRecordAdapter()
    trajectory = MolrsTrajectoryAdapter()
    forcefield = MolrsForceFieldAdapter()
    # No `collection` adapter: molrs has no collection door.
