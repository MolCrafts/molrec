"""Record models: Column, Block, Box, Frame, Trajectory, Meta, Record.

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
from enum import StrEnum
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    WithJsonSchema,
    model_serializer,
    model_validator,
)

from molrec import jsonvalue
from molrec.arrays import NDArray, arrays_equal

DType = Literal[
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

#: The dtype set is closed and every integer width is explicit. A tool that
#: cannot represent one natively must preserve it rather than silently change
#: it -- reading a u64 identifier back as i64, or an i32 as i64, is a
#: conformance failure.
#:
#: There is **one float**, ``f64``: a narrow real (``f16`` / ``f32``) is not a
#: column dtype, and a reader refuses an array stored as one rather than
#: widening it. ``c64`` / ``c128`` are the complex pairs the reference
#: implementation stores. ``bytes`` is deliberately absent: it has no Zarr V3
#: specification, so a contract that included it would not be portable.
DTYPES: tuple[DType, ...] = (
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


# ---------------------------------------------------------------------------
# Per-step meta tags
# ---------------------------------------------------------------------------

#: The closed tag set a per-step ``meta`` key is declared with
#: (``docs/spec/ragged.md``, per-step metadata) -- exactly the reference
#: implementation's sixteen, each the element dtype and trailing shape one
#: step's value is stored as. ``json`` is one UTF-8 JSON document per step,
#: physically a ``string`` array, and a **meta** tag only: a column never
#: carries it.
META_LAYOUT: dict[str, tuple[DType, tuple[int, ...]]] = {
    "bool": ("bool", ()),
    "i32": ("i32", ()),
    "i64": ("i64", ()),
    "u32": ("u32", ()),
    "u64": ("u64", ()),
    "f64": ("f64", ()),
    "string": ("string", ()),
    "json": ("string", ()),
    "bool3": ("bool", (3,)),
    "i32x3": ("i32", (3,)),
    "i64x3": ("i64", (3,)),
    "u32x3": ("u32", (3,)),
    "u64x3": ("u64", (3,)),
    "f64x3": ("f64", (3,)),
    "f64x6": ("f64", (6,)),
    "f64x9": ("f64", (9,)),
}

META_TAGS: tuple[str, ...] = tuple(META_LAYOUT)

MetaTag = Literal[*META_TAGS]


def meta_tag_parts(tag: str) -> tuple[DType, tuple[int, ...]]:
    """The element dtype and trailing shape a per-step tag stands for."""
    if tag not in META_LAYOUT:
        raise ValueError(f"per-step meta tag {tag!r} is not one of the closed set {META_TAGS}")
    return META_LAYOUT[tag]


def coerce_meta_value(tag: str, value: Any) -> Any:
    """One step's value exactly as ``tag`` declares it, or a ``ValueError``.

    A scalar becomes the Python value of its element dtype (an ``f64`` given
    as ``1`` is ``1.0``; an integer given as ``1.0`` is refused, not
    rounded), a vector a list of exactly its width, a ``json`` value a plain
    finite JSON document. What a writer stores is what this returns, so two
    implementations that were handed the same Python value store the same
    thing.
    """
    if tag == "json":
        return jsonvalue.check_document(value)
    element, shape = meta_tag_parts(tag)
    if not shape:
        return jsonvalue.coerce(element, value)
    items = jsonvalue.plain(value)
    if not isinstance(items, list) or len(items) != shape[0]:
        raise ValueError(f"a {tag} value is {shape[0]} elements, found {value!r}")
    return [jsonvalue.coerce(element, item) for item in items]


def encode_meta_value(tag: str, value: Any) -> Any:
    """One step's value in its typed JSON form (:mod:`molrec.jsonvalue`)."""
    if tag == "json":
        return jsonvalue.check_document(value)
    element, shape = meta_tag_parts(tag)
    value = coerce_meta_value(tag, value)
    if not shape:
        return jsonvalue.encode(element, value)
    return [jsonvalue.encode(element, item) for item in value]


def decode_meta_value(tag: str, raw: Any) -> Any:
    """The inverse of :func:`encode_meta_value`; refuses any other form."""
    if tag == "json":
        return jsonvalue.check_document(raw)
    element, shape = meta_tag_parts(tag)
    if not shape:
        return jsonvalue.decode(element, raw)
    if not isinstance(raw, list) or len(raw) != shape[0]:
        raise ValueError(f"a {tag} value is {shape[0]} elements, found {raw!r}")
    return [jsonvalue.decode(element, item) for item in raw]


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


#: The published shapes of the cell's parts. The contract is three-dimensional:
#: ``vectors`` is ``f64[3][3]``, ``origin`` ``f64[3]``, ``boundary`` ``bool[3]``.
_VECTOR3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_MATRIX3 = {"type": "array", "items": _VECTOR3, "minItems": 3, "maxItems": 3}
_FLAGS3 = {"type": "array", "items": {"type": "boolean"}, "minItems": 3, "maxItems": 3}

BOX_NDIM = 3


class BoxModel(BaseModel):
    """The triclinic cell. Columns of ``vectors`` are the lattice vectors.

    A box belongs to a frame, so fixed-cell and variable-cell runs are both
    natural -- each frame in a trajectory carries its own.

    ``cell_defined`` is not periodicity -- ``boundary`` says which axes wrap,
    ``cell_defined`` says whether there is a cell at all. Absent means
    ``True``; a writer records it only to say ``False``.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    vectors: Annotated[NDArray, WithJsonSchema(_MATRIX3)]
    origin: Annotated[NDArray, WithJsonSchema(_VECTOR3)] | None = None
    boundary: Annotated[tuple[bool, ...], WithJsonSchema(_FLAGS3)] | None = None
    cell_defined: bool | None = None

    @model_validator(mode="after")
    def _square_and_filled_in(self) -> BoxModel:
        """Shape check, then materialize the defaults.

        Leaving ``origin`` and ``boundary`` absent looks harmless until two
        implementations disagree about what absent means -- one writes zeros
        and all-periodic, the other writes nothing, and a round trip that
        should be lossless reports a difference. So absence is resolved here,
        once: an unstated origin is the coordinate origin, an unstated
        boundary is periodic on every axis, and an unstated ``cell_defined``
        is a defined cell.
        """
        shape = tuple(self.vectors.shape)
        if shape != (BOX_NDIM, BOX_NDIM):
            raise ValueError(f"vectors must be [{BOX_NDIM}][{BOX_NDIM}], found {shape}")

        if self.origin is None:
            object.__setattr__(self, "origin", np.zeros(BOX_NDIM, dtype="float64"))
        elif tuple(self.origin.shape) != (BOX_NDIM,):
            raise ValueError(f"origin must be [{BOX_NDIM}], found {tuple(self.origin.shape)}")

        if self.boundary is None:
            object.__setattr__(self, "boundary", (True,) * BOX_NDIM)
        elif len(self.boundary) != BOX_NDIM:
            raise ValueError(f"boundary must have {BOX_NDIM} flags, found {len(self.boundary)}")

        if self.cell_defined is None:
            object.__setattr__(self, "cell_defined", True)
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BoxModel):
            return NotImplemented
        return (
            arrays_equal(self.vectors, other.vectors)
            and arrays_equal(self.origin, other.origin)
            and self.boundary == other.boundary
            and self.cell_defined == other.cell_defined
        )

    __hash__ = None  # type: ignore[assignment]


class FrameModel(BaseModel):
    """A map of names to blocks, plus free-form meta and an optional box.

    A frame enforces no relationship between its blocks: block counts are
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


class MetaSeriesModel(BaseModel):
    """One per-step meta key, declared once for the whole sequence.

    ``dtype`` is a tag from the closed per-step set (:data:`META_TAGS`): a
    scalar dtype, ``f64x3`` / ``bool3`` / ... for a fixed-width vector,
    ``json`` for one JSON document per step. The tag is what makes the value
    exact: two runs both handing back ``1`` are not the same run if one wrote
    i32 and the other u64, and nothing in the value says which.

    ``fill`` is the only thing that lets a frame omit the key. A key declared
    without one must be supplied by every frame -- there is **no implicit
    NaN**, so a gap a producer did not declare is refused rather than
    invented. The fill is coerced to the tag (:func:`coerce_meta_value`),
    materialized into the array at the omitting step *and* recorded in the
    pinned sequence declaration (``trajectory`` attribute
    ``sequence_schema``), so a reader that opens the declaration can hand it
    back.

    A fill is declared by **stating** it: ``fill=None`` on a ``json`` key
    declares the JSON document ``null``, while leaving ``fill`` out declares
    no fill (:attr:`has_fill`). ``null`` is a fill for ``json`` only.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    dtype: MetaTag
    fill: Any = Field(
        default=None,
        description="The value an omitting frame is completed with, in the typed JSON form "
        "of its tag. Absent means no fill; null is a fill only for json.",
        json_schema_extra=lambda schema: schema.pop("default", None),
    )

    @property
    def has_fill(self) -> bool:
        """Whether a fill was declared -- ``fill is None`` alone cannot say."""
        return "fill" in self.model_fields_set

    @property
    def element_dtype(self) -> DType:
        """The column dtype the values are stored as (``json`` -> ``string``)."""
        return meta_tag_parts(self.dtype)[0]

    @property
    def shape(self) -> tuple[int, ...]:
        """The trailing shape of one step's value: ``()`` or ``(3|6|9,)``."""
        return meta_tag_parts(self.dtype)[1]

    @model_validator(mode="before")
    @classmethod
    def _fill_arrives_in_its_json_form(cls, data: Any) -> Any:
        """A fill read from a store is in the typed JSON form; one built in
        Python is already a value. Both reach the same coerced value."""
        if isinstance(data, dict) and "fill" in data and isinstance(data.get("dtype"), str):
            tag, fill = data["dtype"], data["fill"]
            typed = tag in META_LAYOUT and tag not in ("json", "string")
            if typed and isinstance(fill, (str, list)):
                return {**data, "fill": decode_meta_value(tag, fill)}
        return data

    @model_validator(mode="after")
    def _fill_is_a_value_of_the_tag(self) -> MetaSeriesModel:
        if self.has_fill:
            object.__setattr__(self, "fill", coerce_meta_value(self.dtype, self.fill))
        return self

    @model_serializer(mode="wrap")
    def _fill_only_when_declared(self, handler: Any, info: Any) -> dict[str, Any]:
        data = handler(self)
        data.pop("fill", None)
        if self.has_fill:
            data["fill"] = (
                encode_meta_value(self.dtype, self.fill) if info.mode == "json" else self.fill
            )
        return data

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MetaSeriesModel):
            return NotImplemented
        return (
            self.dtype == other.dtype
            and self.has_fill == other.has_fill
            and (not self.has_fill or jsonvalue.same(self.fill, other.fill))
        )

    __hash__ = None  # type: ignore[assignment]


class SequenceColumnModel(BaseModel):
    """One column's type in a sequence declaration.

    A column is fixed for the run by its ``dtype`` -- the same closed
    vocabulary as :class:`ColumnModel` -- and its ``trailing`` axes, the
    per-entity structure after the leading count axis. A ``Float[count][3]``
    column declares ``trailing = [3]``; a scalar column declares
    ``trailing = []``.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    dtype: DType
    trailing: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)


class SequenceBlockModel(BaseModel):
    """One block's declaration: its columns and, when it is a grid, its shape.

    A block that declares ``structural_shape`` is a fixed-size object: every
    update of it holds exactly ``prod(structural_shape)`` rows, and a writer
    refuses one that does not.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    columns: dict[str, SequenceColumnModel] = Field(default_factory=dict)
    structural_shape: tuple[int, ...] | None = None


class SequenceSchemaModel(BaseModel):
    """The ``trajectory/`` group attribute ``sequence_schema``.

    The set of blocks, columns, dtypes, trailing shapes and per-step meta keys
    a trajectory may carry, declared when it is created and fixed for its
    lifetime. ``blocks`` mirrors the frame blocks; ``meta`` declares each
    per-step key as ``{dtype, fill?}`` -- the tag the array's ``meta_dtype``
    attribute repeats, and the fill an omitting frame is completed with.

    The attribute carries no version of its own; the record's
    ``meta["molrec_version"]`` covers it.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    blocks: dict[str, SequenceBlockModel] = Field(default_factory=dict)
    meta: dict[str, MetaSeriesModel] = Field(default_factory=dict)


def declare_block(block: BlockModel) -> SequenceBlockModel:
    """The declaration a presented block implies."""
    return SequenceBlockModel(
        columns={
            name: SequenceColumnModel(dtype=column.dtype, trailing=list(column.shape[1:]))
            for name, column in block.columns.items()
        },
        structural_shape=block.structural_shape,
    )


class BlockState(StrEnum):
    """What a block *is* at one frame ordinal -- the three states of S1.

    * ``PRESENT``: the most recent update at or before this ordinal has rows.
    * ``EMPTY``: the most recent update is a zero-row update -- the block is
      there, with its declared columns and no rows.
    * ``ABSENT``: no update at or before this ordinal. A block is absent only
      before its first update; once present it never becomes absent again
      (there are no tombstones -- to clear a block, write a zero-row update).

    A frame that **omits** a declared block carries no update: the block is
    whatever it was at the previous ordinal (carry forward).
    """

    PRESENT = "present"
    EMPTY = "empty"
    ABSENT = "absent"


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

    ``cell_defined`` is the section's flag; every update's box carries the
    same value, resolved here so the two cannot disagree.
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
        aligned = [
            update
            if update.box.cell_defined == self.cell_defined
            else update.model_copy(
                update={"box": update.box.model_copy(update={"cell_defined": self.cell_defined})}
            )
            for update in self.updates
        ]
        object.__setattr__(self, "updates", aligned)
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

    ``blocks`` and ``meta`` are the pinned declaration. ``blocks`` may be left
    unstated, in which case it is derived from the frames (first presentation
    wins); stated, every frame is held to it. After validation every frame
    carries every block's carried-forward state (see :class:`BlockState`) and
    every declared meta key, which is also what a reader hands back.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    frames: list[FrameModel] = Field(default_factory=list)
    step: list[int]
    time: list[float] | None = None
    blocks: dict[str, SequenceBlockModel] | None = None
    meta: dict[str, MetaSeriesModel] = Field(default_factory=dict)
    box: TrajectoryBoxModel | None = None

    def state_of(self, name: str, ordinal: int) -> BlockState:
        """The three-state answer for block ``name`` at frame ``ordinal``."""
        block = self.frames[ordinal].blocks.get(name)
        if block is None:
            return BlockState.ABSENT
        return BlockState.EMPTY if block.count == 0 else BlockState.PRESENT

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

        A frame may present a **subset** of the declaration, never anything
        outside it. A run that decides halfway through to record a new block
        or column needs a new store, so a frame that invents one is refused
        here rather than half-written there. Reserved names are refused at
        declaration for the same reason.
        """
        stated = self.blocks is not None
        declared: dict[str, SequenceBlockModel] = dict(self.blocks or {})
        for name, block in declared.items():
            _refuse_reserved(name, block.columns)

        for ordinal, frame in enumerate(self.frames):
            for name, block in frame.blocks.items():
                _refuse_reserved(name, block.columns)
                presented = declare_block(block)
                if name not in declared:
                    if stated:
                        raise ValueError(
                            f"frame {ordinal} presents block {name!r}, which the sequence never "
                            "declared; the declaration is fixed when the sequence is created"
                        )
                    declared[name] = presented
                    continue
                pinned = declared[name]
                if presented.columns != pinned.columns:
                    raise ValueError(
                        f"block {name!r} presents {presented.columns} at ordinal {ordinal}, "
                        f"declared {pinned.columns} -- a block presents all of its declared "
                        "columns or none of them, at the declared dtype and trailing shape"
                    )
                # S4: a grid block's row count is fixed. ``BlockModel`` already
                # holds each presentation to ``count == prod(structural_shape)``,
                # so pinning the shape pins the count.
                if presented.structural_shape != pinned.structural_shape:
                    raise ValueError(
                        f"block {name!r} has structural shape {presented.structural_shape} at "
                        f"ordinal {ordinal}, declared {pinned.structural_shape} -- a grid's row "
                        "count is fixed for the run"
                    )
        object.__setattr__(self, "blocks", declared)
        return self

    @model_validator(mode="after")
    def _omission_carries_forward(self) -> TrajectoryModel:
        """Resolve S1 once, so the frames are what a reader hands back.

        A frame that omits a declared block carries no update for it: the
        block at that ordinal is its most recent update, rows included (or
        none, after a zero-row update). Before the first update the block is
        absent -- the frame has no such key -- and once present it is never
        absent again.
        """
        resolved: list[FrameModel] = []
        current: dict[str, BlockModel] = {}
        for frame in self.frames:
            current = {**current, **frame.blocks}
            resolved.append(
                frame
                if len(frame.blocks) == len(current)
                else frame.model_copy(update={"blocks": dict(current)})
            )
        object.__setattr__(self, "frames", resolved)
        return self

    @model_validator(mode="after")
    def _every_declared_meta_key_reaches_every_frame(self) -> TrajectoryModel:
        """Resolve the declared fills, once, the way ``BoxModel`` resolves its defaults.

        A frame that omits a declared key is an error unless that key was
        declared with a fill, which stands in for the omitted value. So after
        validation every frame carries every declared key, which is also what
        a reader hands back: the arrays hold ``nstep`` values either way.
        """
        resolved: list[FrameModel] = []
        for ordinal, frame in enumerate(self.frames):
            undeclared = sorted(set(frame.meta) - set(self.meta))
            if undeclared:
                raise ValueError(
                    f"frame {ordinal} carries per-step meta {undeclared} that the sequence never "
                    "declared; a meta key is declared once, when the sequence is created"
                )
            completed: dict[str, Any] = {}
            for key, series in self.meta.items():
                if key in frame.meta:
                    try:
                        completed[key] = coerce_meta_value(series.dtype, frame.meta[key])
                    except ValueError as exc:
                        raise ValueError(
                            f"frame {ordinal}: meta key {key!r} is declared {series.dtype!r}, "
                            f"and its value is not one: {exc}"
                        ) from None
                    continue
                if not series.has_fill:
                    raise ValueError(
                        f"frame {ordinal} omits declared meta key {key!r}, which was declared "
                        "without a fill value -- there is no implicit NaN"
                    )
                completed[key] = series.fill
            resolved.append(frame.model_copy(update={"meta": completed}))
        object.__setattr__(self, "frames", resolved)
        return self


def _refuse_reserved(name: str, columns: dict[str, Any]) -> None:
    if name in RESERVED_TRAJECTORY_NAMES:
        raise ValueError(f"{name!r} is reserved by the trajectory layout; a block cannot take it")
    taken = sorted(set(columns) & RESERVED_BLOCK_NAMES)
    if taken:
        raise ValueError(
            f"{taken} is reserved by a block's own index; "
            f"block {name!r} cannot take it for a column"
        )


class CreatorModel(BaseModel):
    """The tool that wrote the record."""

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    name: str
    version: str | None = None


class AuthorModel(BaseModel):
    """The person or group responsible for the record."""

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    name: str
    email: str | None = None


class ModuleModel(BaseModel):
    """A shared interpretation beyond this specification, keyed by name under
    ``meta/modules``: a major/minor ``version`` plus module-specific keys."""

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    version: tuple[int, int]


#: The contract version this package speaks. Every writer stamps it on
#: ``meta``; a reader validates a present key and refuses a newer one.
MOLREC_VERSION = 1

#: ``meta["molrec_version"]``: absent, or an integer in ``1..=MOLREC_VERSION``.
#: Strict -- ``"1"``, ``1.0`` and ``true`` are not versions -- and never
#: ``null``: present means validated.
MolrecVersion = Annotated[StrictInt, Field(ge=1, le=MOLREC_VERSION)]

_VERSION_SCHEMA = {
    "type": "integer",
    "minimum": 1,
    "maximum": MOLREC_VERSION,
    "description": "Absent on a store written before version 1; never null.",
}


def revalidated[M: BaseModel](model: M) -> M:
    """``model`` run through its validators again.

    A model built around them (``model_construct``) is how a negative case
    reaches a writer; a codec that refuses what the contract refuses calls
    this first, so the one statement of the rules -- the model's -- is also
    the writer's. Only the fields that were set are handed back in, so an
    absent optional key stays absent rather than becoming an explicit null.
    """
    return type(model).model_validate(model.model_dump(exclude_unset=True))


def stamp_version(document: dict[str, Any]) -> dict[str, Any]:
    """``document`` with ``molrec_version`` stamped in when the producer gave none.

    Every writer -- molrec's own codecs included -- emits the version it
    writes; a producer that set the key keeps its value.
    """
    return {"molrec_version": MOLREC_VERSION, **document}


class MetaModel(BaseModel):
    """The record's identity document.

    ``extra="allow"`` is not convenience -- it is the preserve-the-unknown
    invariant: a reader must keep keys it does not recognize.

    ``molrec_version`` is stamped by every writer (:func:`stamp_version`). A
    reader validates it only when present: absent is a store written before
    version 1, read best-effort; present must be an integer in
    ``1..=MOLREC_VERSION`` -- ``null``, ``0``, a string, a float or a newer
    version is refused. Identity of a record is the ``*.mrec`` path suffix
    plus a Zarr root, not this key.

    ``record_id`` and ``content_hash`` are optional provenance, like
    ``creator``, ``author``, ``created_at`` and ``source``.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    molrec_version: Annotated[MolrecVersion, WithJsonSchema(_VERSION_SCHEMA)] = Field(
        default=None, json_schema_extra=lambda schema: schema.pop("default", None)
    )
    creator: CreatorModel | None = None
    author: AuthorModel | None = None
    created_at: str | None = None
    source: str | None = None
    modules: dict[str, ModuleModel] | None = None
    record_id: str | None = None
    content_hash: str | None = None


class StatusModel(BaseModel):
    """The lifecycle document (``docs/spec/status.md``). ``state`` is required
    whenever the section exists; every other key is preserved as given."""

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    state: str


class EngineModel(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    name: str
    version: str | None = None


class MethodModel(BaseModel):
    """The scientific / training context document (``docs/spec/method.md``).
    ``type``, ``description`` and ``engine.name`` are required whenever the
    section exists."""

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    type: str
    description: str
    engine: EngineModel


#: The root sections of which a record must carry at least one beside ``meta``.
SUBSTANTIVE_SECTIONS: tuple[str, ...] = ("frame", "system", "trajectory", "status")


class RecordModel(BaseModel):
    """The record root.

    ``meta`` is always present (an empty document is a valid one), plus at
    least one of ``frame``, ``system``, ``trajectory`` or ``status``. Each of
    those is a valid **sole** section beside ``meta``: a trajectory-only
    record is conforming and a reader must not require a frame beside it,
    because frames may embed full blocks including topology.

    ``metrics`` and ``observables`` are carried as documents here; their
    array layouts are specified in their own chapters and judged by their own
    suites.
    """

    model_config = ConfigDict(
        frozen=True,
        from_attributes=True,
        extra="allow",
        json_schema_extra={
            "anyOf": [
                {"required": [section], "properties": {section: {"type": "object"}}}
                for section in SUBSTANTIVE_SECTIONS
            ]
        },
    )

    meta: MetaModel
    frame: FrameModel | None = None
    system: FrameModel | None = None
    trajectory: TrajectoryModel | None = None
    status: StatusModel | None = None
    method: MethodModel | None = None
    metrics: dict[str, Any] | None = None
    observables: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _has_a_section(self) -> RecordModel:
        if all(getattr(self, section) is None for section in SUBSTANTIVE_SECTIONS):
            raise ValueError(f"a record needs at least one of {', '.join(SUBSTANTIVE_SECTIONS)}")
        return self


#: The collection index columns a binding owns; a collection's own index
#: columns may not take these names (``docs/spec/lmdb.md``).
RESERVED_INDEX_COLUMNS = frozenset({"first_frame", "n_frames", "n_atoms"})

#: The record sections a collection carries (``docs/spec/collection.md``).
COLLECTION_SECTIONS: tuple[str, ...] = ("system", "trajectory")


class CollectionMetaModel(BaseModel):
    """The collection's document. ``units`` is required; other keys are kept.

    ``units`` maps a quantity (``length``, ``energy``, ``force``, ``charge``,
    ``mass``, ``time``) to a unit string. It is the only place a collection's
    numbers get a unit: columns and per-step tags carry none.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    units: dict[str, str]
    molrec_version: Annotated[MolrecVersion, WithJsonSchema(_VERSION_SCHEMA)] = Field(
        default=None, json_schema_extra=lambda schema: schema.pop("default", None)
    )


class CollectionModel(BaseModel):
    """Many records under one declaration (``docs/spec/collection.md``).

    Each record is an ordinary :class:`RecordModel` restricted to ``meta``,
    ``system`` and ``trajectory``. Every record's trajectory uses
    ``sequence_schema`` -- stated, or derived from the first record that has a
    trajectory. ``index`` is a block of one row per record whose columns the
    writer derived from the records; it is handed back, never recomputed.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    meta: CollectionMetaModel
    sequence_schema: SequenceSchemaModel | None = None
    index: BlockModel | None = None
    records: list[RecordModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _records_are_collection_records(self) -> CollectionModel:
        for r, record in enumerate(self.records):
            extra = [
                section
                for section in ("frame", "status", "method", "metrics", "observables")
                if getattr(record, section) is not None
            ]
            if extra:
                raise ValueError(
                    f"record {r} carries {extra}; a collection record holds meta, system and "
                    "trajectory only"
                )
            if record.system is None and record.trajectory is None:
                raise ValueError(f"record {r} has neither system nor trajectory")
        return self

    @model_validator(mode="after")
    def _one_declaration(self) -> CollectionModel:
        schema = self.sequence_schema
        for r, record in enumerate(self.records):
            trajectory = record.trajectory
            if trajectory is None:
                continue
            declared = SequenceSchemaModel(blocks=trajectory.blocks or {}, meta=trajectory.meta)
            if schema is None:
                schema = declared
                continue
            if declared != schema:
                raise ValueError(
                    f"record {r} declares its trajectory as {declared}, the collection as "
                    f"{schema}; every record in a collection uses one declaration"
                )
        object.__setattr__(self, "sequence_schema", schema)
        return self

    @model_validator(mode="after")
    def _system_and_trajectory_align(self) -> CollectionModel:
        for r, record in enumerate(self.records):
            if record.system is None or record.trajectory is None:
                continue
            for name, fixed in record.system.blocks.items():
                for ordinal, frame in enumerate(record.trajectory.frames):
                    update = frame.blocks.get(name)
                    if update is None:
                        continue
                    if update.count != fixed.count:
                        raise ValueError(
                            f"record {r}: trajectory block {name!r} has {update.count} rows at "
                            f"ordinal {ordinal}, system block {fixed.count}; blocks sharing a "
                            "name align 1:1 by row"
                        )
                    shared = set(update.columns) & set(fixed.columns)
                    if shared:
                        raise ValueError(
                            f"record {r}: columns {sorted(shared)} of block {name!r} are in both "
                            "system and trajectory; a column is time-independent or not"
                        )
        return self

    @model_validator(mode="after")
    def _index_has_a_row_per_record(self) -> CollectionModel:
        if self.index is None:
            object.__setattr__(self, "index", BlockModel(count=len(self.records)))
        if self.index.count != len(self.records):
            raise ValueError(f"index has {self.index.count} rows for {len(self.records)} records")
        reserved = sorted(RESERVED_INDEX_COLUMNS & set(self.index.columns))
        if reserved:
            raise ValueError(f"index columns {reserved} are reserved for the binding")
        return self
