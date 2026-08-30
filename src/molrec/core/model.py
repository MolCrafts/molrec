"""L0-L2 models: Column, Block, Box, Frame, Trajectory, Meta, Record.

These models *are* the specification. The JSON Schema published for other
languages is generated from them, and the conformance suite compares against
them -- so a change here is a change to the contract.

Nothing in this module reads or writes anything. There is no container
library: no ``Frame`` you build a molecule with, no block algebra, no
compute. Storage lives in ``bindings/``.

The structural invariants are enforced as validators, which means a
deliberately malformed negative case has to be built with
``model_construct()`` to bypass them.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from molrec.arrays import NDArray, arrays_equal

DType = Literal[
    "f16",
    "f32",
    "f64",
    "i8",
    "i16",
    "i32",
    "i64",
    "u8",
    "u16",
    "u32",
    "u64",
    "bool",
    "string",
    "c64",
    "c128",
]

#: The dtype set is closed and every numeric width is explicit. A tool that
#: cannot represent one natively must preserve it rather than silently narrow
#: it -- reading f32 back as f64 doubles the file and reading f64 back as f32
#: destroys data, and both are conformance failures.
#:
#: ``bytes`` is deliberately absent: it has no Zarr V3 specification, so a
#: contract that included it would not be portable.
DTYPES: tuple[DType, ...] = (
    "f16",
    "f32",
    "f64",
    "i8",
    "i16",
    "i32",
    "i64",
    "u8",
    "u16",
    "u32",
    "u64",
    "bool",
    "string",
    "c64",
    "c128",
)

#: The in-memory equivalent of each spec dtype.
NUMPY_DTYPE: dict[DType, str] = {
    "f16": "float16",
    "f32": "float32",
    "f64": "float64",
    "i8": "int8",
    "i16": "int16",
    "i32": "int32",
    "i64": "int64",
    "u8": "uint8",
    "u16": "uint16",
    "u32": "uint32",
    "u64": "uint64",
    "bool": "bool",
    "string": "str",
    "c64": "complex64",
    "c128": "complex128",
}

_FROM_NUMPY: dict[str, DType] = {
    numpy_name: spec_name for spec_name, numpy_name in NUMPY_DTYPE.items() if spec_name != "string"
}


def dtype_of(dtype: np.dtype) -> DType:
    """The spec dtype an in-memory array carries.

    UTF-8 strings reach us in more than one numpy spelling (``StringDType``,
    fixed-width ``<U``, object arrays), and all of them are one spec dtype.
    """
    if dtype.kind in ("U", "T", "O", "S"):
        return "string"
    if dtype.name not in _FROM_NUMPY:
        raise ValueError(
            f"dtype {dtype.name!r} is outside the closed molrec set {DTYPES}; "
            "preserve it rather than narrowing it, or declare a module for it"
        )
    return _FROM_NUMPY[dtype.name]


class ColumnModel(BaseModel):
    """A typed N-dimensional array.

    The leading axis length is the owning block's count; trailing axes are
    per-entity structure, so ``Float[count][3]`` is one column, not three.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    dtype: DType
    shape: tuple[int, ...] = Field(min_length=1)
    values: NDArray | None = None

    @model_validator(mode="after")
    def _values_match_declaration(self) -> ColumnModel:
        if self.values is None:
            return self
        if tuple(self.values.shape) != self.shape:
            raise ValueError(f"values have shape {self.values.shape}, declared {self.shape}")
        carried = dtype_of(self.values.dtype)
        if carried != self.dtype:
            raise ValueError(f"values carry dtype {carried!r}, declared {self.dtype!r}")
        return self

    @property
    def count(self) -> int:
        return self.shape[0]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ColumnModel):
            return NotImplemented
        if self.dtype != other.dtype or self.shape != other.shape:
            return False
        return arrays_equal(self.values, other.values)

    __hash__ = None  # type: ignore[assignment]


class BlockModel(BaseModel):
    """Named columns sharing one count, plus an optional structural shape.

    A plain table has implicit shape ``[count]``. A volumetric block declares
    ``structural_shape = (nx, ny, nz)`` with ``nx * ny * nz == count`` -- the
    only thing that makes a flat column reshapable after a roundtrip.

    A block imposes no meaning on its column names.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    count: int = Field(ge=0)
    columns: dict[str, ColumnModel] = Field(default_factory=dict)
    structural_shape: tuple[int, ...] | None = None

    @model_validator(mode="after")
    def _columns_share_the_count(self) -> BlockModel:
        for name, column in self.columns.items():
            if column.count != self.count:
                raise ValueError(
                    f"column {name!r} has {column.count} rows, block count is {self.count}"
                )
        if self.structural_shape is not None:
            product = math.prod(self.structural_shape)
            if product != self.count:
                raise ValueError(
                    f"structural shape {self.structural_shape} has product {product}, "
                    f"block count is {self.count}"
                )
        return self


class BoxModel(BaseModel):
    """The triclinic cell. Columns of ``vectors`` are the lattice vectors.

    A box belongs to a frame, so fixed-cell and variable-cell runs are both
    natural -- each frame in a trajectory carries its own.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    vectors: NDArray
    origin: NDArray | None = None
    boundary: tuple[bool, ...] | None = None

    @model_validator(mode="after")
    def _square_and_filled_in(self) -> BoxModel:
        """Shape check, then materialize the defaults.

        Leaving ``origin`` and ``boundary`` absent looks harmless until two
        implementations disagree about what absent means -- one writes zeros
        and all-periodic, the other writes nothing, and a round trip that
        should be lossless reports a difference. So absence is resolved here,
        once: an unstated origin is the coordinate origin, and an unstated
        boundary is periodic on every axis.
        """
        shape = tuple(self.vectors.shape)
        if len(shape) != 2 or shape[0] != shape[1]:
            raise ValueError(f"vectors must be [ndim][ndim], found {shape}")
        ndim = shape[0]

        if self.origin is None:
            object.__setattr__(self, "origin", np.zeros(ndim, dtype="float64"))
        elif tuple(self.origin.shape) != (ndim,):
            raise ValueError(f"origin must be [{ndim}], found {tuple(self.origin.shape)}")

        if self.boundary is None:
            object.__setattr__(self, "boundary", (True,) * ndim)
        elif len(self.boundary) != ndim:
            raise ValueError(f"boundary must have {ndim} flags, found {len(self.boundary)}")
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BoxModel):
            return NotImplemented
        return (
            arrays_equal(self.vectors, other.vectors)
            and arrays_equal(self.origin, other.origin)
            and self.boundary == other.boundary
        )

    __hash__ = None  # type: ignore[assignment]


class FrameModel(BaseModel):
    """A map of names to blocks, plus free-form meta and an optional box.

    A frame enforces no relationship between blocks: block counts are
    independent and any block name is legal.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    blocks: dict[str, BlockModel] = Field(default_factory=dict)
    box: BoxModel | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


#: Children of ``trajectory`` the layout owns. A block cannot take one of
#: these names -- and it is refused when the sequence is declared, not at the
#: first write, because by then the block would already have overwritten a
#: section of the index.
RESERVED_TRAJECTORY_NAMES = frozenset({"step", "time", "meta", "box"})

#: Children of a block's own group. A column cannot take one of these names.
RESERVED_BLOCK_NAMES = frozenset({"offset", "step_index"})

#: What a per-step meta value may be shaped like: a scalar, or a vector of
#: fixed width. Anything ragged belongs in a block, which is what blocks are.
META_SHAPES: tuple[tuple[int, ...], ...] = ((), (3,), (6,), (9,))


class MetaSeriesModel(BaseModel):
    """One per-step meta key, declared once for the whole sequence.

    The declaration is what makes the value exact: two runs both handing back
    ``1.0`` are not the same run if one wrote f32 and the other f64, and
    nothing in the value itself says which.

    ``fill`` is the only thing that lets a frame omit the key. A key declared
    without one must be supplied by every frame -- there is **no implicit
    NaN**, so a gap a producer did not declare is refused rather than
    invented.

    ``fill`` is **write-side only**. The value is materialized into the array
    at the omitting step and no attribute records that it was a fill, so a
    reader cannot distinguish a filled value from a written one -- both are
    simply the value at that step -- and hands back no fill at all. The
    declaration does not survive the round trip, and is therefore not compared
    on read-back.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    dtype: DType
    shape: tuple[int, ...] = ()
    fill: Any | None = None

    @model_validator(mode="after")
    def _shape_is_scalar_or_a_fixed_vector(self) -> MetaSeriesModel:
        if self.shape not in META_SHAPES:
            raise ValueError(f"per-step meta shape {self.shape} is not one of {META_SHAPES}")
        return self


class BoxUpdateModel(BaseModel):
    """The cell as of one frame ordinal.

    ``step_index`` is a frame **ordinal** -- a position in the sequence -- and
    never a step number.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    step_index: int = Field(ge=0)
    box: BoxModel


class TrajectoryBoxModel(BaseModel):
    """The cell section: one box, indexed by the ordinals it changed at.

    A fixed-cell run holds exactly one update. There is no absence marker
    here: once a run states a cell every later frame resolves to the most
    recent one, so a frame that drops its cell mid-run reads back carrying the
    previous cell.

    ``cell_defined`` is not periodicity -- ``boundary`` says which axes wrap,
    ``cell_defined`` says whether there is a cell at all -- and absence means
    ``True``, resolved here for the same reason ``BoxModel`` resolves its own.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    updates: list[BoxUpdateModel] = Field(min_length=1)
    cell_defined: bool | None = None

    @model_validator(mode="after")
    def _one_update_per_ordinal_in_order(self) -> TrajectoryBoxModel:
        ordinals = [update.step_index for update in self.updates]
        if ordinals != sorted(set(ordinals)):
            raise ValueError(
                f"cell updates must be at strictly increasing ordinals, got {ordinals}"
            )
        if self.cell_defined is None:
            object.__setattr__(self, "cell_defined", True)
        return self


class TrajectoryModel(BaseModel):
    """An ordered sequence of frames -- the time evolution of the system.

    This is the *logical* content, the thing a reader hands back. The physical
    form is the binding's: one CSR row range per section update, a sparse
    index of the ordinals a section changed at, and each section written again
    only when it changed. Two conforming stores of one trajectory are expected
    to differ byte for byte, so none of that appears here.

    Two integers index a trajectory and they are not the same one. A frame's
    **ordinal** is its position in ``frames``; its **step number** is the
    producer's own iteration counter at ``step[ordinal]``, which may start
    anywhere and may skip values.

    Sparsity is block-level: a frame may omit a whole block, which is how a
    heterogeneous run is expressed. It may not omit one column of a block it
    presents -- all columns of a block share one row range, so a missing
    column has no representation at all.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    frames: list[FrameModel] = Field(default_factory=list)
    step: list[int]
    time: list[float] | None = None
    meta: dict[str, MetaSeriesModel] = Field(default_factory=dict)
    box: TrajectoryBoxModel | None = None

    @model_validator(mode="after")
    def _indices_align_with_the_frames(self) -> TrajectoryModel:
        if len(self.step) != len(self.frames):
            raise ValueError(
                f"step has {len(self.step)} entries, frames {len(self.frames)} -- every "
                "conforming writer states a step number for every frame"
            )
        if any(later <= earlier for earlier, later in zip(self.step, self.step[1:], strict=False)):
            raise ValueError(f"step numbers increase strictly along the sequence, got {self.step}")
        if self.time is not None and len(self.time) != len(self.frames):
            raise ValueError(
                f"time has {len(self.time)} entries, frames {len(self.frames)} -- time is "
                "all-or-nothing, a run supplies one for every frame or for none"
            )
        return self

    @model_validator(mode="after")
    def _the_cell_is_a_section(self) -> TrajectoryModel:
        for ordinal, frame in enumerate(self.frames):
            if frame.box is not None:
                raise ValueError(
                    f"frame {ordinal} carries a box of its own; a trajectory's cell is the box "
                    "section, resolved by ordinal, so a fixed cell is stated once and not nstep "
                    "times"
                )
        if self.box is not None:
            for update in self.box.updates:
                if update.step_index >= len(self.frames):
                    raise ValueError(
                        f"cell update at ordinal {update.step_index} indexes no frame; the "
                        f"sequence has {len(self.frames)}"
                    )
        return self

    @model_validator(mode="after")
    def _blocks_keep_one_declaration(self) -> TrajectoryModel:
        """Blocks, columns, dtypes and trailing shapes are fixed for the run.

        A later frame may present a **subset** of the declaration, never
        anything outside it. A run that decides halfway through to record a
        new column needs a new store, so a frame that invents one is refused
        here rather than half-written there.
        """
        declared: dict[str, dict[str, tuple[DType, tuple[int, ...]]]] = {}
        grids: dict[str, tuple[int, ...] | None] = {}
        for ordinal, frame in enumerate(self.frames):
            for name, block in frame.blocks.items():
                if name in RESERVED_TRAJECTORY_NAMES:
                    raise ValueError(
                        f"{name!r} is reserved by the trajectory layout; a block cannot take it"
                    )
                taken = sorted(set(block.columns) & RESERVED_BLOCK_NAMES)
                if taken:
                    raise ValueError(
                        f"{taken} is reserved by a block's own index; block {name!r} cannot "
                        "take it for a column"
                    )
                shape = {
                    key: (column.dtype, column.shape[1:]) for key, column in block.columns.items()
                }
                if name not in declared:
                    declared[name] = shape
                    grids[name] = block.structural_shape
                    continue
                if shape != declared[name]:
                    raise ValueError(
                        f"block {name!r} presents {shape} at ordinal {ordinal}, declared "
                        f"{declared[name]} -- a block presents all of its columns or none of them"
                    )
                if block.structural_shape != grids[name]:
                    raise ValueError(
                        f"block {name!r} has structural shape {block.structural_shape} at ordinal "
                        f"{ordinal}, declared {grids[name]}"
                    )
        return self

    @model_validator(mode="after")
    def _every_declared_meta_key_reaches_every_frame(self) -> TrajectoryModel:
        """Resolve the declared fills, once, the way ``BoxModel`` resolves its defaults.

        A frame that omits a declared key is an error unless that key was
        declared with a fill, which stands in for the omitted value. So after
        validation every frame carries every declared key, which is also what
        a reader hands back: the arrays hold ``nstep`` values either way and
        nothing on disk records that a value was ever omitted.
        """
        resolved: list[FrameModel] = []
        for ordinal, frame in enumerate(self.frames):
            undeclared = sorted(set(frame.meta) - set(self.meta))
            if undeclared:
                raise ValueError(
                    f"frame {ordinal} carries per-step meta {undeclared} that the sequence never "
                    "declared; a meta key is declared once, when the sequence is created"
                )
            fills = {}
            for key, series in self.meta.items():
                if key in frame.meta:
                    continue
                if series.fill is None:
                    raise ValueError(
                        f"frame {ordinal} omits declared meta key {key!r}, which was declared "
                        "without a fill value -- there is no implicit NaN"
                    )
                fills[key] = series.fill
            resolved.append(
                frame.model_copy(update={"meta": {**frame.meta, **fills}}) if fills else frame
            )
        object.__setattr__(self, "frames", resolved)
        return self


class MetaModel(BaseModel):
    """The record's identity document.

    ``extra="allow"`` is not convenience -- it is the preserve-the-unknown
    invariant: a reader must keep keys it does not recognize.

    ``format_name`` is the record format brand, not a binding id. It may be
    omitted at L2; when present it is ``"mrec"``. The retired string
    ``"molrec"`` is refused.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    record_schema_version: int = Field(ge=1)
    format_name: Literal["mrec"] | None = None
    record_id: str | None = None
    content_hash: str | None = None


class RecordModel(BaseModel):
    """The record root.

    ``meta`` is always required, plus at least one substantive section. The
    other sections arrive with their own modules; this module owns ``frame``,
    ``system`` and ``trajectory``.

    Each section is a valid **sole** section beside ``meta``: a trajectory-only
    record is conforming and a reader must not require a frame beside it,
    because frames may embed full blocks including topology.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    meta: MetaModel
    frame: FrameModel | None = None
    system: FrameModel | None = None
    trajectory: TrajectoryModel | None = None

    @model_validator(mode="after")
    def _has_a_section(self) -> RecordModel:
        if self.frame is None and self.system is None and self.trajectory is None:
            raise ValueError("a record needs at least one of frame, system, trajectory")
        return self
