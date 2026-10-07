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
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PrivateAttr,
    StrictInt,
    ValidationInfo,
    WithJsonSchema,
    model_serializer,
    model_validator,
)

from molrec import jsonvalue
from molrec.arrays import NDArray, arrays_equal, arrays_identical
from molrec.precision import PRECISION_MAX, PRECISION_MIN, quantize
from molrec.safe_name import percent_decode, percent_encode


class DocumentModel(BaseModel):
    """A JSON document the contract names some keys of and preserves the rest of.

    ``extra="allow"`` is the preserve-the-unknown invariant: a key a reader
    does not recognise is kept, verbatim. Serialized, a document holds the
    keys that were stated -- a named key left at ``None`` is absent, never
    written as ``null`` -- and every unknown key as it was, a ``null``-valued
    one included. That is what lets a reader hand back exactly the document
    it read.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    @model_serializer(mode="wrap")
    def _named_nulls_are_absent(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for name in type(self).model_fields:
            if getattr(self, name) is None:
                data.pop(name, None)
        return data


def document(model: BaseModel) -> dict[str, Any]:
    """A document model as the JSON object a binding stores: plain, finite."""
    return jsonvalue.check_document(model.model_dump())


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

    Unicode strings reach us in two numpy spellings (``StringDType``,
    fixed-width ``<U``), and both are the one ``string`` dtype. Raw bytes
    (``S``) are not text and are refused; an object array is judged by its
    elements (:func:`values_dtype`).
    """
    if dtype.kind in ("U", "T"):
        return "string"
    if dtype.kind in ("S", "O"):
        raise ValueError(
            f"a {dtype} array is not a column dtype: bytes are not text, and an object "
            "array is a string column only when every element is a str"
        )
    if dtype.name not in _FROM_NUMPY:
        raise ValueError(
            f"dtype {dtype.name!r} is outside the closed molrec set {DTYPES}; "
            "preserve it rather than narrowing it, or declare a module for it"
        )
    return _FROM_NUMPY[dtype.name]


def values_dtype(values: np.ndarray) -> DType:
    """The spec dtype of an in-memory array, looking inside an object array:
    one of Python ``str`` objects is a ``string`` column, anything else in one
    is refused."""
    if values.dtype.kind == "O":
        if all(isinstance(value, str) for value in values.flat):
            return "string"
        raise ValueError("an object array is a string column only when every element is a str")
    return dtype_of(values.dtype)


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


#: The attribute of a frame-shaped group that maps every key of its meta
#: document to its tag (``docs/spec/storage.md``, array groups). One leading
#: underscore, like ``_validity``: binding-owned, and never a meta key.
META_TYPES_ATTR = "_meta_types"


def infer_meta_tag(value: Any) -> str:
    """The tag an untagged meta value reads back as.

    JSON ``true`` / ``false`` is ``bool``; an integer in ``[-2**63, 2**63)``
    is ``i64`` and one in ``[2**63, 2**64)`` is ``u64``; any other number is
    ``f64``; a string is ``string``; an array, an object or ``null`` is
    ``json``. A string ``"NaN"`` is a ``string`` -- only a tag says otherwise.
    """
    value = jsonvalue.plain(value)
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        if -(2**63) <= value < 2**63:
            return "i64"
        if 2**63 <= value < 2**64:
            return "u64"
        return "f64"
    if isinstance(value, float):
        return "f64"
    if isinstance(value, str):
        return "string"
    return "json"


def encode_typed_meta(meta: dict[str, Any], tags: dict[str, str]) -> dict[str, Any]:
    """A frame's meta document as a binding stores it (a frame-shaped group's
    attributes; a system frame's frame-bytes header).

    Every value in the typed JSON form of its tag, and ``_meta_types`` naming
    the tag of every key (omitted for an empty document). A key the producer
    left untagged takes the tag it would read back as; a tag for a key the
    document lacks is not written. A meta key named ``_meta_types`` is
    refused: the name is the binding's.
    """
    if META_TYPES_ATTR in meta:
        raise ValueError(
            f"{META_TYPES_ATTR!r} is reserved beside a frame's meta document; a meta key cannot "
            "take it"
        )
    written: dict[str, str] = {}
    attrs: dict[str, Any] = {}
    for key, value in meta.items():
        tag = tags.get(key) or infer_meta_tag(value)
        attrs[key] = encode_meta_value(tag, value)
        written[key] = tag
    if written:
        attrs[META_TYPES_ATTR] = written
    return attrs


def decode_typed_meta(attrs: dict[str, Any], where: str) -> tuple[dict[str, Any], dict[str, str]]:
    """A stored meta document (with its ``_meta_types``) as values and tags.

    A tagged key is decoded under its tag and any other form is refused; an
    untagged key gets the tag it is inferred as (a store written before
    ``_meta_types``); a tag whose key is absent is ignored.
    """
    tags = attrs.pop(META_TYPES_ATTR, {})
    if not isinstance(tags, dict) or any(
        not isinstance(tag, str) or tag not in META_LAYOUT for tag in tags.values()
    ):
        raise ValueError(f"{where}: {META_TYPES_ATTR} is a map of key to meta tag, found {tags!r}")
    meta: dict[str, Any] = {}
    types: dict[str, str] = {}
    for key, raw in attrs.items():
        tag = tags.get(key)
        if tag is None:
            tag = infer_meta_tag(raw)
            value = coerce_meta_value(tag, raw)
        else:
            try:
                value = decode_meta_value(tag, raw)
            except ValueError as exc:
                raise ValueError(f"{where}: meta key {key!r} is tagged {tag!r}: {exc}") from None
        meta[key] = value
        types[key] = tag
    return meta, types


#: The subgroup of a block group holding its columns' validity masks
#: (``<block>/_validity/<column>``) -- reserved in every block, on the frame
#: path and the trajectory path alike. One underscore: Zarr V3 reserves the
#: ``__`` prefix for node names.
VALIDITY_GROUP = "_validity"

#: A column's validity mask in the published schema: one flag per row.
_MASK = {"type": "array", "items": {"type": "boolean"}}

#: A declared precision (``docs/spec/frame.md``, declared precision): an
#: absolute tolerance, finite, in ``[2**-1000, 2**1000]``.
Precision = Annotated[float, Field(ge=PRECISION_MIN, le=PRECISION_MAX, allow_inf_nan=False)]

#: The validation context a reader builds its models under: the values are
#: the **stored** ones, handed back exactly -- a reader never re-rounds a
#: declared precision (an off-grid value is the writer's defect, for a
#: validator to report).
STORED: dict[str, bool] = {"stored": True}


def _stored(info: ValidationInfo | None) -> bool:
    """Whether a model is being built from a store (:data:`STORED`)."""
    return bool(info is not None and info.context and info.context.get("stored"))


def _as_stored(model: BaseModel, info: ValidationInfo | None) -> bool:
    """Whether ``model`` holds stored values that must not be rounded again.

    Built from a store (:data:`STORED`), or already rounded once: pydantic
    runs a model's after-validators again whenever the instance is handed to
    another model, so the first verdict is remembered on the instance.
    """
    settled = model._as_stored or _stored(info)
    model._as_stored = True
    return settled


#: The published form of "only an f64 column declares a precision".
_PRECISION_ON_F64 = {
    "if": {"required": ["precision"], "properties": {"precision": {"type": "number"}}},
    "then": {"properties": {"dtype": {"const": "f64"}}},
}


def _precision_on_f64(precision: float | None, dtype: str, what: str) -> None:
    if precision is not None and dtype != "f64":
        raise ValueError(f"{what} declares a precision; only an f64 column can, found {dtype}")


class ColumnModel(BaseModel):
    """A typed N-dimensional array, optionally nullable.

    The leading axis length is the owning block's count; trailing axes are
    per-entity structure, so ``Float[count][3]`` is one column, not three.

    ``validity`` is the column's mask: one flag per row, ``True`` where the
    row holds a value and ``False`` where it holds none (the value stored
    under a null row is carried as written and means nothing). ``None`` --
    no mask -- means every row is valid, and an all-``True`` mask *is* no
    mask: it is normalized to ``None``, so the two spellings of "nothing is
    null" are one model.

    ``precision`` is the column's declared precision (``f64`` only). Like
    ``BoxModel`` materializing its defaults, a validated model holds the
    **stored** values -- rounded to the precision's binary grid
    (:func:`molrec.precision.quantize`) -- which is what a writer stores and
    a reader hands back. A model built from a store (:data:`STORED`) keeps
    the values exactly as stored.
    """

    model_config = ConfigDict(
        frozen=True, from_attributes=True, json_schema_extra=_PRECISION_ON_F64
    )

    dtype: DType
    shape: tuple[int, ...] = Field(min_length=1)
    values: NDArray | None = None
    validity: Annotated[NDArray, WithJsonSchema(_MASK)] | None = None
    precision: Precision | None = None
    _as_stored: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def _values_match_declaration(self, info: ValidationInfo) -> ColumnModel:
        _precision_on_f64(self.precision, self.dtype, "a column")
        if self.values is not None:
            if tuple(self.values.shape) != self.shape:
                raise ValueError(f"values have shape {self.values.shape}, declared {self.shape}")
            carried = values_dtype(self.values)
            if carried != self.dtype:
                raise ValueError(f"values carry dtype {carried!r}, declared {self.dtype!r}")
            if not _as_stored(self, info) and self.precision is not None:
                object.__setattr__(self, "values", quantize(self.values, self.precision))
        if self.validity is not None:
            mask = np.asarray(self.validity)
            if mask.dtype != np.bool_:
                raise ValueError(f"a validity mask is bool, found {mask.dtype}")
            if mask.shape != (self.count,):
                raise ValueError(
                    f"a validity mask carries one flag per row: shape {mask.shape} for "
                    f"{self.count} rows"
                )
            object.__setattr__(self, "validity", None if mask.all() else mask)
        return self

    @property
    def count(self) -> int:
        return self.shape[0]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ColumnModel):
            return NotImplemented
        if (
            self.dtype != other.dtype
            or self.shape != other.shape
            or self.precision != other.precision
        ):
            return False
        return arrays_equal(self.values, other.values) and arrays_equal(
            self.validity, other.validity
        )

    __hash__ = None  # type: ignore[assignment]


#: The unsigned identifiers and relation endpoints: exactly ``u64`` wherever
#: they appear. This is the set the reference implementation refuses at any
#: other width on read (``docs/spec/conventions.md``, canonical dtypes).
CANONICAL_U64: frozenset[str] = frozenset(
    {
        "id",
        "atomic_number",
        "type_id",
        "mol_id",
        "res_id",
        "atomi",
        "atomj",
        "atomk",
        "atoml",
        "atomm",
        "ibead",
        "bond_type",
        "bond_number",
    }
)

#: Every canonical column key and the one dtype it has wherever it appears,
#: in any block of any section, always one value per row (no trailing axes).
#: Published as ``schema/core/vocabulary.json``, the table another
#: implementation's vocabulary is gated against.
CANONICAL_COLUMNS: dict[str, DType] = {
    **dict.fromkeys(("x", "y", "z", "vx", "vy", "vz", "fx", "fy", "fz"), "f64"),
    **dict.fromkeys(("charge", "mass"), "f64"),
    **dict.fromkeys(("quatw", "quati", "quatj", "quatk", "mux", "muy", "muz"), "f64"),
    **dict.fromkeys(("axis_x", "axis_y", "axis_z", "occupancy", "b_factor"), "f64"),
    **dict.fromkeys(CANONICAL_U64, "u64"),
    "atom_map": "u64",
    "formal_charge": "i64",
    **dict.fromkeys(("ix", "iy", "iz"), "i32"),
    **dict.fromkeys(("free", "is_14", "exclude_14"), "bool"),
    **dict.fromkeys(("element", "type", "name", "res_name", "bead_type"), "string"),
    **dict.fromkeys(("chain", "icode", "altloc", "style"), "string"),
}

#: The relation endpoint columns, and the block they reference unless the
#: block's ``targets`` says otherwise (``docs/spec/frame.md``, row references).
ENDPOINTS: tuple[str, ...] = ("atomi", "atomj", "atomk", "atoml", "atomm")
DEFAULT_TARGET = "atoms"

#: The section a row reference may never point into: a trajectory block's row
#: count is not fixed.
_TRAJECTORY_PREFIX = "/trajectory/"


def _target(value: str) -> str:
    """A row-reference target: ``<block>`` (same container) or
    ``/<section>/<block>`` (a frame-shaped section of the same record), never
    into the trajectory."""
    if value.startswith(_TRAJECTORY_PREFIX):
        raise ValueError(
            f"target {value!r} points into the trajectory; a trajectory block is never a "
            "target (its row count is not fixed)"
        )
    return value


#: A row-reference target (``docs/spec/frame.md``, row references).
Target = Annotated[
    str,
    Field(pattern=r"^(/[^/]+/[^/]+|[^/]+)$"),
    AfterValidator(_target),
    WithJsonSchema({"type": "string", "pattern": r"^(?!/trajectory/)(/[^/]+/[^/]+|[^/]+)$"}),
]


def check_target(column: str, target: Any) -> None:
    """``target`` is a well-formed row-reference target -- what a writer checks
    before it stores one."""
    if not isinstance(target, str) or not re.fullmatch(r"(/[^/]+/[^/]+|[^/]+)", target):
        raise ValueError(f"column {column!r}: {target!r} is not a row-reference target")
    _target(target)


def check_references(
    block: str, column: ColumnModel, name: str, target: str, rows: int | None
) -> None:
    """Every non-null value of the referencing ``column`` is a row of ``target``
    (``rows`` of them; ``None`` when the target is missing)."""
    if column.values is None or column.count == 0:
        return
    if rows is None:
        raise ValueError(
            f"{block}.{name} references {target!r}, which is not there; a target exists "
            "wherever its referencing block has rows"
        )
    values = np.asarray(column.values)
    if column.validity is not None:
        values = values[np.asarray(column.validity)]
    if values.size and int(values.max()) >= rows:
        raise ValueError(
            f"{block}.{name} references row {int(values.max())} of {target!r}, which has "
            f"{rows} rows"
        )


#: The per-step meta keys with a canonical tag (``docs/spec/conventions.md``).
CANONICAL_META: dict[str, str] = dict.fromkeys(
    ("pe", "ke", "etotal", "temp", "press", "volume"), "f64"
)


def check_canonical(name: str, dtype: str, trailing: tuple[int, ...] | list[int]) -> None:
    """Refuse a canonical column key at any dtype or shape but its own."""
    expected = CANONICAL_COLUMNS.get(name)
    if expected is None:
        return
    if dtype != expected or tuple(trailing):
        raise ValueError(
            f"column {name!r} is canonical: {expected}[N] wherever it appears, found "
            f"{dtype}[N]{''.join(f'[{n}]' for n in trailing)}"
        )


class BlockModel(BaseModel):
    """Named columns sharing one count, plus an optional structural shape.

    A plain table has implicit shape ``[count]``. A volumetric block declares
    ``structural_shape = (nx, ny, nz)`` with ``nx * ny * nz == count`` -- the
    only thing that makes a flat column reshapable after a roundtrip.

    A block imposes no meaning on its column names beyond one: a
    :data:`canonical <CANONICAL_COLUMNS>` key has one dtype and shape wherever
    it appears.

    ``targets`` declares the block's row references beyond the conventional
    one (``atomi`` ... ``atomm`` into ``atoms``): column -> target, each
    column ``u64``. Whether the values are in range is the container's to
    check (:class:`FrameModel`, :class:`TrajectoryModel`,
    :class:`RecordModel`), which knows the target's row count.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    count: int = Field(ge=0)
    columns: dict[str, ColumnModel] = Field(default_factory=dict)
    structural_shape: tuple[int, ...] | None = None
    targets: dict[str, Target] | None = None

    @model_validator(mode="after")
    def _columns_share_the_count(self) -> BlockModel:
        if VALIDITY_GROUP in self.columns:
            raise ValueError(
                f"{VALIDITY_GROUP!r} names a block's validity masks; a column cannot take it"
            )
        for name, column in self.columns.items():
            if column.count != self.count:
                raise ValueError(
                    f"column {name!r} has {column.count} rows, block count is {self.count}"
                )
            check_canonical(name, column.dtype, column.shape[1:])
        _targets_are_u64_columns(
            self.targets,
            {name: (column.dtype, column.shape[1:]) for name, column in self.columns.items()},
        )
        if self.structural_shape is not None:
            product = math.prod(self.structural_shape)
            if product != self.count:
                raise ValueError(
                    f"structural shape {self.structural_shape} has product {product}, "
                    f"block count is {self.count}"
                )
        return self


def _targets_are_u64_columns(
    targets: dict[str, str] | None, columns: dict[str, tuple[str, Any]]
) -> None:
    """Every declared row reference names a ``u64[N]`` column of its block."""
    for name in targets or {}:
        if name not in columns:
            raise ValueError(f"targets names {name!r}, which is no column of the block")
        dtype, trailing = columns[name]
        if dtype != "u64" or tuple(trailing):
            raise ValueError(
                f"column {name!r} is a row reference, so u64[N]; found {dtype}"
                f"{''.join(f'[{n}]' for n in trailing)}"
            )


#: The published shapes of the cell's parts. The contract is three-dimensional:
#: ``vectors`` is ``f64[3][3]``, ``origin`` ``f64[3]``, ``boundary`` ``bool[3]``.
_VECTOR3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_MATRIX3 = {"type": "array", "items": _VECTOR3, "minItems": 3, "maxItems": 3}
_FLAGS3 = {"type": "array", "items": {"type": "boolean"}, "minItems": 3, "maxItems": 3}

BOX_NDIM = 3


def _float64(value: np.ndarray, what: str) -> np.ndarray:
    """``value`` as binary64: an integer array converts exactly, anything else
    that is not already ``f64`` (a narrow float, a bool, a string) is refused."""
    array = np.asarray(value)
    if array.dtype == np.float64:
        return array
    if array.dtype.kind in "iu":
        return array.astype("float64")
    raise ValueError(f"{what} is f64, found {array.dtype}")


class CellModel(BaseModel):
    """The geometry of a triclinic cell. Columns of ``vectors`` are the lattice
    vectors.

    What a cell's absent parts mean depends on whether there is a cell at
    all, which the owner says -- a frame's :class:`BoxModel`, or a
    trajectory's :class:`TrajectoryBoxModel` for every update at once -- so
    the owner resolves them (:func:`resolve_cell`). On its own a cell only
    holds its parts to their shapes and to ``f64``.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    vectors: Annotated[NDArray, WithJsonSchema(_MATRIX3)]
    origin: Annotated[NDArray, WithJsonSchema(_VECTOR3)] | None = None
    boundary: Annotated[tuple[bool, ...], WithJsonSchema(_FLAGS3)] | None = None

    @model_validator(mode="after")
    def _three_dimensional_f64(self) -> CellModel:
        vectors = _float64(self.vectors, "vectors")
        if vectors.shape != (BOX_NDIM, BOX_NDIM):
            raise ValueError(f"vectors must be [{BOX_NDIM}][{BOX_NDIM}], found {vectors.shape}")
        object.__setattr__(self, "vectors", vectors)
        if self.origin is not None:
            origin = _float64(self.origin, "origin")
            if origin.shape != (BOX_NDIM,):
                raise ValueError(f"origin must be [{BOX_NDIM}], found {origin.shape}")
            object.__setattr__(self, "origin", origin)
        if self.boundary is not None and len(self.boundary) != BOX_NDIM:
            raise ValueError(f"boundary must have {BOX_NDIM} flags, found {len(self.boundary)}")
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CellModel):
            return NotImplemented
        return (
            arrays_equal(self.vectors, other.vectors)
            and arrays_equal(self.origin, other.origin)
            and self.boundary == other.boundary
        )

    __hash__ = None  # type: ignore[assignment]


def resolve_cell(cell: CellModel, defined: bool) -> dict[str, Any]:
    """A cell's parts with the normative meaning of every absence filled in.

    Two readers that default an absent part differently turn one store into
    two physical systems, so absence is resolved here, once:

    * an absent ``origin`` is the coordinate origin;
    * an absent ``boundary`` is periodic on every axis -- for a defined cell;
    * an **undefined** cell (``defined`` false) has no geometry: its
      ``vectors`` are ignored and carried as the identity, and it is periodic
      on no axis -- an absent ``boundary`` is all-``False``, and a periodic
      flag on it is refused.
    """
    origin = np.zeros(BOX_NDIM, dtype="float64") if cell.origin is None else cell.origin
    if defined:
        boundary = (True,) * BOX_NDIM if cell.boundary is None else tuple(cell.boundary)
        return {"vectors": cell.vectors, "origin": origin, "boundary": boundary}
    boundary = (False,) * BOX_NDIM if cell.boundary is None else tuple(cell.boundary)
    if any(boundary):
        raise ValueError(
            f"an undefined cell is periodic on no axis; boundary {boundary} says otherwise"
        )
    return {"vectors": np.eye(BOX_NDIM), "origin": origin, "boundary": boundary}


class BoxModel(CellModel):
    """A frame's cell: its geometry plus whether there is a cell at all.

    ``cell_defined`` is not periodicity -- ``boundary`` says which axes wrap,
    ``cell_defined`` says whether there is a cell at all. Absent means
    ``True``; a writer records it only to say ``False``. An undefined cell's
    ``vectors`` mean nothing: a writer writes the identity and a reader
    ignores what it finds (:func:`resolve_cell`).
    """

    cell_defined: bool | None = None

    @model_validator(mode="after")
    def _absences_resolved(self) -> BoxModel:
        if self.cell_defined is None:
            object.__setattr__(self, "cell_defined", True)
        for name, value in resolve_cell(self, self.cell_defined).items():
            object.__setattr__(self, name, value)
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BoxModel):
            return NotImplemented
        return CellModel.__eq__(self, other) and self.cell_defined == other.cell_defined

    __hash__ = None  # type: ignore[assignment]


class FrameModel(BaseModel):
    """A map of names to blocks, plus a typed meta document and an optional box.

    A frame enforces no relationship between its blocks: block counts are
    independent and any block name is legal.

    Every ``meta`` value is typed by one of the per-step tags
    (:data:`META_TAGS`), held in ``meta_types``: a key the producer did not
    tag gets the tag it would read back as (:func:`infer_meta_tag`), and
    every value is coerced to its tag (:func:`coerce_meta_value`), so a
    validated frame carries one tag per key -- what a writer stores as the
    group's ``_meta_types`` and a reader hands back.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="forbid")

    blocks: dict[str, BlockModel] = Field(default_factory=dict)
    box: BoxModel | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    meta_types: dict[str, MetaTag] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _meta_is_typed(self) -> FrameModel:
        if META_TYPES_ATTR in self.meta:
            raise ValueError(
                f"{META_TYPES_ATTR!r} is reserved beside a frame's meta document; a meta key "
                "cannot take it"
            )
        stale = sorted(set(self.meta_types) - set(self.meta))
        if stale:
            raise ValueError(f"meta_types tags keys {stale} the meta document does not carry")
        tags = {
            key: self.meta_types.get(key) or infer_meta_tag(value)
            for key, value in self.meta.items()
        }
        meta: dict[str, Any] = {}
        for key, value in self.meta.items():
            try:
                meta[key] = coerce_meta_value(tags[key], value)
            except ValueError as exc:
                raise ValueError(f"meta key {key!r} is tagged {tags[key]!r}: {exc}") from None
        object.__setattr__(self, "meta", meta)
        object.__setattr__(self, "meta_types", tags)
        return self

    @model_validator(mode="after")
    def _references_resolve(self) -> FrameModel:
        """Every declared same-container row reference is to a block of this
        frame, and in range. (An absolute one is the record's to check.)"""
        for name, block in self.blocks.items():
            for column, target in (block.targets or {}).items():
                if target.startswith("/"):
                    continue
                tracked = self.blocks.get(target)
                check_references(
                    name,
                    block.columns[column],
                    column,
                    target,
                    None if tracked is None else tracked.count,
                )
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FrameModel):
            return NotImplemented
        return (
            self.blocks == other.blocks
            and self.box == other.box
            and self.meta_types == other.meta_types
            and jsonvalue.same(self.meta, other.meta)
        )

    __hash__ = None  # type: ignore[assignment]


#: Children of ``trajectory`` the layout owns. A block cannot take one of
#: these names -- and it is refused when the sequence is declared, not at the
#: first write, because by then the block would already have overwritten a
#: section of the index.
RESERVED_TRAJECTORY_NAMES = frozenset({"step", "time", "meta", "box"})

#: Children of a trajectory block's own group. A column cannot take one of
#: these names.
RESERVED_BLOCK_NAMES = frozenset({"offset", "step_index", VALIDITY_GROUP})


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

    ``nullable`` says the column may carry a validity mask. It is a union over
    the run -- a column masked in any frame is nullable for all of them -- and
    a frame that masks a column the declaration pins non-nullable is refused:
    landing its values without the mask would lose which rows hold nothing.

    ``precision`` is the column's declared precision (``f64`` only): on a
    trajectory the declaration is the only place it is stated, and every
    frame's values are rounded to it.
    """

    model_config = ConfigDict(
        frozen=True, from_attributes=True, json_schema_extra=_PRECISION_ON_F64
    )

    dtype: DType
    trailing: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    nullable: bool = Field(
        default=False,
        description="Whether the column may carry a validity mask; written only when true.",
    )
    precision: Precision | None = Field(
        default=None,
        description="The column's declared precision (f64 only); written only when declared.",
    )

    @model_validator(mode="after")
    def _precision_on_f64_only(self) -> SequenceColumnModel:
        _precision_on_f64(self.precision, self.dtype, "a sequence column")
        return self

    @model_serializer(mode="wrap")
    def _omit_defaults(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if not self.nullable:
            data.pop("nullable", None)
        if self.precision is None:
            data.pop("precision", None)
        return data


class SequenceBlockModel(DocumentModel):
    """One block's declaration: its columns and, when it is a grid, its shape.

    A block that declares ``structural_shape`` is a fixed-size object: every
    update of it holds exactly ``prod(structural_shape)`` rows, and a writer
    refuses one that does not.

    ``targets`` is the block's row references (``docs/spec/frame.md``): on a
    trajectory the declaration is the only place they are stated, and they
    hold on every resolved frame. Written only when set.

    ``aligned_with`` names another declared block whose rows this block's
    rows are, one for one, at every resolved frame (``docs/spec/ragged.md``,
    aligned blocks): a sparse companion of a block that changes more often.
    Declared only, never derived; written only when set.
    """

    columns: dict[str, SequenceColumnModel] = Field(default_factory=dict)
    structural_shape: tuple[int, ...] | None = None
    targets: dict[str, Target] | None = None
    aligned_with: str | None = None

    @model_validator(mode="after")
    def _targets_are_declared_u64_columns(self) -> SequenceBlockModel:
        _targets_are_u64_columns(
            self.targets,
            {name: (spec.dtype, spec.trailing) for name, spec in self.columns.items()},
        )
        return self


class SequenceSchemaModel(DocumentModel):
    """The ``trajectory/`` group attribute ``sequence_schema``.

    The set of blocks, columns, dtypes, trailing shapes and per-step meta keys
    a trajectory may carry, declared when it is created and fixed for its
    lifetime. ``blocks`` mirrors the frame blocks; ``meta`` declares each
    per-step key as ``{dtype, fill?}`` -- the tag the array's ``meta_dtype``
    attribute repeats, and the fill an omitting frame is completed with.
    """

    blocks: dict[str, SequenceBlockModel] = Field(default_factory=dict)
    meta: dict[str, MetaSeriesModel] = Field(default_factory=dict)


def declare_block(block: BlockModel) -> SequenceBlockModel:
    """The declaration a presented block implies."""
    return SequenceBlockModel(
        columns={
            name: SequenceColumnModel(
                dtype=column.dtype,
                trailing=list(column.shape[1:]),
                nullable=column.validity is not None,
                precision=column.precision,
            )
            for name, column in block.columns.items()
        },
        structural_shape=block.structural_shape,
        targets=block.targets,
    )


def same_bits(left: BlockModel, right: BlockModel) -> bool:
    """Whether two presentations of a block are one update: bit for bit, masks
    included. What earns a section a new update is any difference here."""
    if (
        left.count != right.count
        or left.structural_shape != right.structural_shape
        or left.columns.keys() != right.columns.keys()
    ):
        return False
    return all(
        column.dtype == right.columns[name].dtype
        and arrays_identical(column.values, right.columns[name].values)
        and arrays_identical(column.validity, right.columns[name].validity)
        for name, column in left.columns.items()
    )


def same_cell(left: CellModel, right: CellModel) -> bool:
    """Bit-for-bit cell equality: the predicate behind the ``box/`` index."""
    return (
        arrays_identical(left.vectors, right.vectors)
        and arrays_identical(left.origin, right.origin)
        and left.boundary == right.boundary
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
    """The cell as of one frame ordinal: its geometry, never its definedness.

    ``step_index`` is a frame **ordinal** -- a position in the sequence -- and
    never a step number. Whether there is a cell at all is the section's one
    flag (:attr:`TrajectoryBoxModel.cell_defined`), so an update cannot
    disagree with it.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    step_index: int = Field(ge=0)
    box: CellModel


class TrajectoryBoxModel(BaseModel):
    """The cell section: one cell, indexed by the ordinals it changed at.

    A fixed-cell run holds exactly one update. There is no absence marker
    here: once a run states a cell every later frame resolves to the most
    recent one, so a frame that drops its cell mid-run reads back carrying the
    previous cell.

    ``cell_defined`` is the section's flag, stated once for every update;
    each update's absent parts are resolved against it (:func:`resolve_cell`).
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
        resolved: list[BoxUpdateModel] = []
        for update in self.updates:
            cell = CellModel(**resolve_cell(update.box, self.cell_defined))
            # An update identical to the one before it is not a change: the
            # section is the list of changes, so it is dropped here once.
            if resolved and same_cell(resolved[-1].box, cell):
                continue
            resolved.append(BoxUpdateModel(step_index=update.step_index, box=cell))
        object.__setattr__(self, "updates", resolved)
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

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="forbid")

    frames: list[FrameModel] = Field(default_factory=list)
    step: list[int]
    time: list[float] | None = None
    blocks: dict[str, SequenceBlockModel] | None = None
    meta: dict[str, MetaSeriesModel] = Field(default_factory=dict)
    box: TrajectoryBoxModel | None = None
    _as_stored: bool = PrivateAttr(default=False)

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
        if self.time is not None and not self.frames:
            # A sequence of no frames cannot say whether it would have had
            # times: there is nothing on disk to say it with.
            object.__setattr__(self, "time", None)
        for ordinal, frame in enumerate(self.frames):
            for name, block in frame.blocks.items():
                if block.model_extra:
                    raise ValueError(
                        f"frame {ordinal}: block {name!r} carries attributes "
                        f"{sorted(block.model_extra)}; a trajectory block's attributes are its "
                        "section's, not one update's"
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
            for column, spec in block.columns.items():
                check_canonical(column, spec.dtype, spec.trailing)

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
                if _layout(presented) != _layout(pinned):
                    raise ValueError(
                        f"block {name!r} presents {_layout(presented)} at ordinal {ordinal}, "
                        f"declared {_layout(pinned)} -- a block presents all of its declared "
                        "columns or none of them, at the declared dtype and trailing shape"
                    )
                masked = sorted(
                    column
                    for column, spec in presented.columns.items()
                    if spec.nullable and not pinned.columns[column].nullable
                )
                if masked and stated:
                    raise ValueError(
                        f"frame {ordinal} masks columns {masked} of block {name!r}, which the "
                        "sequence declares non-nullable; landing the values without the mask "
                        "would lose which rows hold nothing"
                    )
                if masked:
                    # Derived: nullability is the union over the run.
                    declared[name] = pinned = pinned.model_copy(
                        update={
                            "columns": {
                                column: spec.model_copy(update={"nullable": True})
                                if column in masked
                                else spec
                                for column, spec in pinned.columns.items()
                            }
                        }
                    )
                for column, spec in presented.columns.items():
                    held = pinned.columns[column].precision
                    if spec.precision is None or spec.precision == held:
                        continue
                    if held is not None or stated:
                        raise ValueError(
                            f"frame {ordinal}: column {column!r} of block {name!r} states "
                            f"precision {spec.precision}, the sequence declares {held}; a "
                            "trajectory declares a column's precision once"
                        )
                    # Derived: the first stated precision is the column's.
                    declared[name] = pinned = pinned.model_copy(
                        update={
                            "columns": {
                                **pinned.columns,
                                column: pinned.columns[column].model_copy(
                                    update={"precision": spec.precision}
                                ),
                            }
                        }
                    )
                if presented.targets is not None and presented.targets != pinned.targets:
                    if pinned.targets is not None or stated:
                        raise ValueError(
                            f"frame {ordinal}: block {name!r} states targets {presented.targets}, "
                            f"the sequence declares {pinned.targets}; a trajectory declares a "
                            "block's row references once"
                        )
                    declared[name] = pinned = pinned.model_copy(
                        update={"targets": presented.targets}
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
        _alignments_are_well_formed(declared)
        object.__setattr__(self, "blocks", declared)
        # The declaration is now the only statement of each column's precision
        # (the frames give theirs up below), so it counts as stated: a model
        # validated again re-derives nothing it could no longer see.
        self.__pydantic_fields_set__.add("blocks")
        return self

    @model_validator(mode="after")
    def _the_declaration_states_what_frames_stated(self, info: ValidationInfo) -> TrajectoryModel:
        """Precision and row references are the declaration's, not a frame's.

        Every frame holds the stored values -- rounded to its column's
        declared precision -- and neither its columns' precision nor its
        blocks' ``targets``: the declaration states both for the run. A model
        built from a store (:data:`STORED`) keeps the values exactly as
        stored.
        """
        declared = self.blocks or {}
        if not any(
            spec.precision is not None
            for block in declared.values()
            for spec in block.columns.values()
        ) and not any(
            block.targets is not None for frame in self.frames for block in frame.blocks.values()
        ):
            return self
        rounding = not _as_stored(self, info)
        resolved: list[FrameModel] = []
        for frame in self.frames:
            blocks: dict[str, BlockModel] = {}
            for name, block in frame.blocks.items():
                columns = {}
                for column_name, column in block.columns.items():
                    precision = declared[name].columns[column_name].precision
                    values = column.values
                    if rounding and precision is not None and values is not None:
                        values = quantize(values, precision)
                    columns[column_name] = (
                        column
                        if values is column.values and column.precision is None
                        else column.model_copy(update={"values": values, "precision": None})
                    )
                blocks[name] = block.model_copy(update={"columns": columns, "targets": None})
            resolved.append(frame.model_copy(update={"blocks": blocks}))
        object.__setattr__(self, "frames", resolved)
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
    def _references_resolve(self) -> TrajectoryModel:
        """A declared same-container row reference holds on every resolved
        frame: its target is there and every non-null value is one of its rows."""
        for name, block in (self.blocks or {}).items():
            for column, target in (block.targets or {}).items():
                if target.startswith("/"):
                    continue
                for ordinal, frame in enumerate(self.frames):
                    referencing = frame.blocks.get(name)
                    if referencing is None:
                        continue
                    tracked = frame.blocks.get(target)
                    try:
                        check_references(
                            name,
                            referencing.columns[column],
                            column,
                            target,
                            None if tracked is None else tracked.count,
                        )
                    except ValueError as exc:
                        raise ValueError(f"ordinal {ordinal}: {exc}") from None
        return self

    @model_validator(mode="after")
    def _aligned_blocks_track_their_target(self) -> TrajectoryModel:
        """On resolved frames: wherever an aligned block is present or empty,
        its target is too, with the same row count."""
        for name, block in (self.blocks or {}).items():
            target = block.aligned_with
            if target is None:
                continue
            for ordinal, frame in enumerate(self.frames):
                aligned = frame.blocks.get(name)
                if aligned is None:
                    continue
                tracked = frame.blocks.get(target)
                if tracked is None:
                    raise ValueError(
                        f"block {name!r} is aligned with {target!r}, which is absent at ordinal "
                        f"{ordinal}; an aligned block may be absent while its target is present, "
                        "never the reverse"
                    )
                if aligned.count != tracked.count:
                    raise ValueError(
                        f"block {name!r} is aligned with {target!r} but holds {aligned.count} rows "
                        f"to its {tracked.count} at ordinal {ordinal}; a frame that changes the "
                        "target's row count restates the aligned block"
                    )
        return self

    @model_validator(mode="after")
    def _every_declared_meta_key_reaches_every_frame(self) -> TrajectoryModel:
        """Resolve the declared fills, once, the way ``BoxModel`` resolves its defaults.

        A frame that omits a declared key is an error unless that key was
        declared with a fill, which stands in for the omitted value. So after
        validation every frame carries every declared key, which is also what
        a reader hands back: the arrays hold ``nstep`` values either way.
        """
        for key, series in self.meta.items():
            canonical = CANONICAL_META.get(key)
            if canonical is not None and series.dtype != canonical:
                raise ValueError(
                    f"per-step key {key!r} is canonical: {canonical}, declared {series.dtype!r}"
                )
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
            # The declaration types a trajectory frame's meta.
            tags = {key: series.dtype for key, series in self.meta.items()}
            resolved.append(frame.model_copy(update={"meta": completed, "meta_types": tags}))
        object.__setattr__(self, "frames", resolved)
        return self


def _alignments_are_well_formed(declared: dict[str, SequenceBlockModel]) -> None:
    """An aligned block's target is another declared block that is not itself
    aligned; the aligned block is no grid, and the two share no column."""
    for name, block in declared.items():
        target = block.aligned_with
        if target is None:
            continue
        if target == name or target not in declared:
            raise ValueError(
                f"block {name!r} is aligned with {target!r}, which is no other declared block"
            )
        if declared[target].aligned_with is not None:
            raise ValueError(
                f"block {name!r} is aligned with {target!r}, which is itself aligned with "
                f"{declared[target].aligned_with!r}; alignments do not chain"
            )
        if block.structural_shape is not None:
            raise ValueError(f"aligned block {name!r} declares a structural shape")
        shared = sorted(set(block.columns) & set(declared[target].columns))
        if shared:
            raise ValueError(
                f"block {name!r} and its target {target!r} both declare columns {shared}; an "
                "aligned block's columns are its own"
            )


def _aligned_names(trajectory: TrajectoryModel | None) -> set[str]:
    """The trajectory blocks declared aligned with another."""
    if trajectory is None:
        return set()
    return {name for name, block in (trajectory.blocks or {}).items() if block.aligned_with}


def _layout(block: SequenceBlockModel) -> dict[str, tuple[str, list[int]]]:
    """A declaration's columns without their nullability: dtype and trailing shape."""
    return {name: (spec.dtype, spec.trailing) for name, spec in block.columns.items()}


def _union_nullable(
    pinned: SequenceBlockModel | None, block: SequenceBlockModel
) -> SequenceBlockModel:
    """``block``'s declaration with every column ``pinned`` holds nullable kept so."""
    if pinned is None:
        return block
    return block.model_copy(
        update={
            "columns": {
                name: spec.model_copy(
                    update={"nullable": spec.nullable or pinned.columns[name].nullable}
                )
                for name, spec in block.columns.items()
            }
        }
    )


def _refuse_reserved(name: str, columns: dict[str, Any]) -> None:
    if name in RESERVED_TRAJECTORY_NAMES:
        raise ValueError(f"{name!r} is reserved by the trajectory layout; a block cannot take it")
    taken = sorted(set(columns) & RESERVED_BLOCK_NAMES)
    if taken:
        raise ValueError(
            f"{taken} is reserved by a block's own index; "
            f"block {name!r} cannot take it for a column"
        )


class CreatorModel(DocumentModel):
    """The tool that wrote the record."""

    name: str
    version: str | None = None


class AuthorModel(DocumentModel):
    """The person or group responsible for the record."""

    name: str
    email: str | None = None


class ModuleModel(DocumentModel):
    """A shared interpretation beyond this specification, keyed by name under
    ``meta/modules``: a major/minor ``version`` plus module-specific keys."""

    version: tuple[int, int]


def _rfc3339(value: str) -> str:
    """An RFC 3339 timestamp with an explicit offset, kept as written."""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        raise ValueError(f"{value!r} is not an RFC 3339 timestamp") from None
    if "T" not in value.upper() or moment.tzinfo is None:
        raise ValueError(f"{value!r} names no instant: RFC 3339 needs a date, a time and an offset")
    return value


#: An instant: RFC 3339 with an explicit offset (``Z`` or ``+hh:mm``).
Timestamp = Annotated[
    str,
    AfterValidator(_rfc3339),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]


def revalidated[M: BaseModel](model: M) -> M:
    """``model`` run through its validators again.

    A model built around them (``model_construct``) is how a negative case
    reaches a writer; a codec that refuses what the contract refuses calls
    this first, so the one statement of the rules -- the model's -- is also
    the writer's. Only the fields that were set are handed back in, so an
    absent optional key stays absent rather than becoming an explicit null.
    """
    return type(model).model_validate(model.model_dump(exclude_unset=True))


class MetaModel(DocumentModel):
    """The record's identity document.

    ``extra="allow"`` is not convenience -- it is the preserve-the-unknown
    invariant: a reader must keep keys it does not recognize.

    Identity of a record is the ``*.mrec`` path suffix plus a Zarr root.

    ``record_id`` and ``content_hash`` are optional provenance, like
    ``creator``, ``author``, ``created_at`` and ``source``.
    """

    creator: CreatorModel | None = None
    author: AuthorModel | None = None
    created_at: Timestamp | None = None
    source: str | None = None
    modules: dict[str, ModuleModel] | None = None
    record_id: str | None = None
    content_hash: str | None = None


class ErrorModel(DocumentModel):
    """``status.error``: what failed, for a human and for a resume decision."""

    message: str
    type: str | None = None
    traceback: str | None = None


class StatusModel(DocumentModel):
    """The lifecycle document (``docs/spec/status.md``). ``state`` is required
    whenever the section exists; the other named keys are typed, and every key
    a producer adds is preserved as given."""

    state: str
    stage: str | None = None
    epoch: NonNegativeInt | None = None
    global_step: NonNegativeInt | None = None
    progress: dict[str, StrictInt | float] | None = None
    message: str | None = None
    started_at: Timestamp | None = None
    updated_at: Timestamp | None = None
    finished_at: Timestamp | None = None
    error: ErrorModel | None = None


class EngineModel(DocumentModel):
    name: str
    version: str | None = None


class MethodModel(DocumentModel):
    """The scientific / training context document (``docs/spec/method.md``).
    ``type``, ``description`` and ``engine.name`` are required whenever the
    section exists; a ``workflow`` names its stages in ``order`` and gives
    each one its own method document in ``stages``."""

    type: str
    description: str
    engine: EngineModel
    order: list[str] | None = None
    stages: dict[str, MethodModel] | None = None


class ArrayModel(BaseModel):
    """One typed array of any shape, a 0-d one included."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    dtype: DType
    shape: tuple[int, ...] = ()
    values: NDArray | None = None

    @model_validator(mode="after")
    def _values_match_declaration(self) -> ArrayModel:
        if self.values is not None:
            if tuple(self.values.shape) != self.shape:
                raise ValueError(f"values have shape {self.values.shape}, declared {self.shape}")
            carried = values_dtype(self.values)
            if carried != self.dtype:
                raise ValueError(f"values carry dtype {carried!r}, declared {self.dtype!r}")
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ArrayModel):
            return NotImplemented
        return (
            self.dtype == other.dtype
            and self.shape == other.shape
            and arrays_equal(self.values, other.values)
        )

    __hash__ = None  # type: ignore[assignment]


class ArrayNodeModel(ArrayModel):
    """An array of an unrecognised subtree: its values and its attributes."""

    attributes: dict[str, Any] = Field(default_factory=dict)


class NodeModel(BaseModel):
    """An unrecognised group, carried through verbatim.

    A reader preserves sections it does not interpret: their attributes,
    arrays and child groups come back exactly as they were read, and a writer
    lays them down again. Nothing in them is interpreted.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    attributes: dict[str, Any] = Field(default_factory=dict)
    arrays: dict[str, ArrayNodeModel] = Field(default_factory=dict)
    groups: dict[str, NodeModel] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# The forcefield section (docs/spec/forcefield.md)
#
# A JSON document -- the group's attributes -- plus one style table per
# style, each an ordinary block. Frame-shaped: a reader that knows nothing of
# force fields reads it with the frame codec and loses nothing. Units are
# stated, never converted; linking a system to it is by name and is not a
# format rule.
# ---------------------------------------------------------------------------

#: Endpoint columns of a style table, in position order.
ENDPOINT_COLUMNS: tuple[str, ...] = ("itom", "jtom", "ktom", "ltom", "mtom")

#: Arity of each known category (``docs/spec/forcefield.md``, categories).
CATEGORY_ARITY: dict[str, int] = {
    "atom": 0,
    "bond": 2,
    "angle": 3,
    "dihedral": 4,
    "improper": 4,
    "pair": 2,
    "constraint": 2,
    "virtual_site": 0,
    "drude": 2,
    "cmap": 5,
}

#: A ``cmap`` row's correction map, ``f64[T, N, N]`` with ``N >= 2``: the
#: array parameter whose shape the chapter pins further (``docs/spec/
#: forcefield.md``, rows and columns). Every other array parameter is any
#: ``f64[T, S...]``.
CMAP_GRID = "grid"

#: The values ``pair.lj/charmm``'s style parameter ``one_four`` may take: at
#: which parameters a ``special_bonds`` 1-4 pair is priced.
ONE_FOUR_VALUES: tuple[str, ...] = ("regular", "epsilon14")

#: Annotation columns of a style table: ``string``, nullable.
ANNOTATION_COLUMNS: frozenset[str] = frozenset(
    {"class", "element", "smarts", "smirks", "overrides", "desc", "doi"}
)

#: Bytes of a style name kept verbatim in its table's block name.
STYLE_UNRESERVED: frozenset[int] = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

#: The combining rules a van-der-Waals pair style may name.
MIXING_RULES: tuple[str, ...] = ("arithmetic", "geometric", "sixthpower")

#: 180/π, the one rounding of it every implementation multiplies by: an angle
#: in radians times this is the same double everywhere.
DEGREES_PER_RADIAN = 180.0 / math.pi

#: The unit presets and the unit of each quantity in them; ``None`` is a
#: quantity the preset gives no unit (reduced ``lj``). The presets are the
#: LAMMPS ``units`` styles plus ``openmm`` (OpenMM's and GROMACS's nm, kJ/mol,
#: ps). The angle is a degree in every preset, as in LAMMPS: it is the unit of
#: angle *values* (theta0, phases); a force constant is per radian whatever it
#: says.
UNIT_QUANTITIES: tuple[str, ...] = ("length", "energy", "angle", "charge", "mass", "time")
UNIT_PRESETS: dict[str, dict[str, str | None]] = {
    "real": dict(
        zip(UNIT_QUANTITIES, ("angstrom", "kcal/mol", "degree", "e", "dalton", "fs"), strict=True)
    ),
    "metal": dict(
        zip(UNIT_QUANTITIES, ("angstrom", "eV", "degree", "e", "dalton", "ps"), strict=True)
    ),
    "si": dict(zip(UNIT_QUANTITIES, ("m", "J", "degree", "C", "kg", "s"), strict=True)),
    "cgs": dict(
        zip(UNIT_QUANTITIES, ("cm", "erg", "degree", "statcoulomb", "g", "s"), strict=True)
    ),
    "electron": dict(
        zip(UNIT_QUANTITIES, ("bohr", "hartree", "degree", "e", "dalton", "fs"), strict=True)
    ),
    "micro": dict(
        zip(
            UNIT_QUANTITIES,
            (
                "micrometer",
                "picogram * micrometer**2 / microsecond**2",
                "degree",
                "picocoulomb",
                "picogram",
                "microsecond",
            ),
            strict=True,
        )
    ),
    "nano": dict(
        zip(
            UNIT_QUANTITIES,
            ("nm", "attogram * nm**2 / ns**2", "degree", "e", "attogram", "ns"),
            strict=True,
        )
    ),
    "lj": {**dict.fromkeys(UNIT_QUANTITIES), "angle": "degree"},
    "openmm": dict(
        zip(UNIT_QUANTITIES, ("nm", "kJ/mol", "degree", "e", "dalton", "ps"), strict=True)
    ),
}


def style_block_name(category: str, style: str) -> str:
    """The block a style's table lives at: ``<category>.<encoded style>``, every
    byte of the UTF-8 style outside ``A-Z a-z 0-9 - _`` written ``%XX``."""
    return f"{category}.{percent_encode(style, STYLE_UNRESERVED)}"


def parse_style_block_name(name: str) -> tuple[str, str]:
    """``(category, style)`` of a style table's block name; the inverse of
    :func:`style_block_name`, refusing any other spelling."""
    category, dot, encoded = name.partition(".")
    if not dot or not category:
        raise ValueError(f"{name!r} is no style table name (<category>.<style>)")
    style = percent_decode(encoded, STYLE_UNRESERVED)
    if style_block_name(category, style) != name:
        raise ValueError(f"{name!r} escapes a byte it keeps verbatim")
    return category, style


def _same_unit(left: str, right: str) -> bool:
    """Whether two unit strings name one unit: pint-equivalent when pint is
    installed (an optional dependency), the same string otherwise."""
    if left == right:
        return True
    try:
        import pint
    except ImportError:
        return False
    registry = _unit_registry(pint)
    try:
        a, b = registry.Quantity(1.0, left), registry.Quantity(1.0, right)
        return a.dimensionality == b.dimensionality and math.isclose(
            a.to(b.units).magnitude, 1.0, rel_tol=1e-12
        )
    except Exception:  # an unparseable unit is not equivalent to anything
        return False


_REGISTRY: list[Any] = []


def _unit_registry(pint: Any) -> Any:
    if not _REGISTRY:
        _REGISTRY.append(pint.UnitRegistry())
    return _REGISTRY[0]


Category = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
EndpointKey = Literal["type", "class", "smirks"]
ParamValue = Annotated[float, Field(allow_inf_nan=False)] | str
Weight = Annotated[float, Field(allow_inf_nan=False)]


class ForceFieldUnitsModel(DocumentModel):
    """``forcefield.units``: a preset, the unit of each quantity, or both.

    The numbers of the section are in these units and a reader never
    converts them. A quantity stated beside a preset is the preset's own
    unit (pint-equivalent).
    """

    model_config = ConfigDict(
        json_schema_extra={
            "anyOf": [{"required": [key]} for key in ("preset", *UNIT_QUANTITIES)],
        }
    )

    preset: (
        Literal["real", "metal", "si", "cgs", "electron", "micro", "nano", "lj", "openmm"] | None
    ) = None
    length: str | None = None
    energy: str | None = None
    angle: str | None = None
    charge: str | None = None
    mass: str | None = None
    time: str | None = None

    @model_validator(mode="after")
    def _stated_and_consistent(self) -> ForceFieldUnitsModel:
        stated = {q: getattr(self, q) for q in UNIT_QUANTITIES if getattr(self, q) is not None}
        if self.preset is None and not stated:
            raise ValueError("units states a preset or at least one quantity")
        if self.preset is not None:
            table = UNIT_PRESETS[self.preset]
            for quantity, unit in stated.items():
                expected = table[quantity]
                if expected is None or not _same_unit(unit, expected):
                    raise ValueError(
                        f"units: {quantity} {unit!r} disagrees with preset {self.preset!r} "
                        f"({expected or 'no unit'})"
                    )
        return self


class ForceFieldSourceModel(DocumentModel):
    """``forcefield.source``: where the parameters came from."""

    format: str
    uri: str | None = None
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None


class SpecialBondsModel(BaseModel):
    """``forcefield.special_bonds``: the 1-2 / 1-3 / 1-4 weights of the
    van-der-Waals (``lj``) and electrostatic (``coul``) pair styles."""

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="forbid")

    lj: tuple[Weight, Weight, Weight]
    coul: tuple[Weight, Weight, Weight]


class StyleModel(DocumentModel):
    """One entry of ``forcefield.styles``: a functional form and its table.

    The table is the block :attr:`block` -- a function of ``(category,
    style)``, so the two can never disagree. ``params`` and ``endpoint_key``
    are written only when they say something (non-empty, not ``"type"``).
    """

    category: Category
    style: Annotated[str, Field(min_length=1)]
    params: dict[str, ParamValue] = Field(default_factory=dict)
    expression: str | None = None
    endpoint_key: EndpointKey = "type"

    @model_validator(mode="after")
    def _reserved_params(self) -> StyleModel:
        special = self.params.get("special")
        if special is not None and special not in ("lj", "coul"):
            raise ValueError(f"params.special is 'lj' or 'coul', found {special!r}")
        mixing = self.params.get("mixing")
        if mixing is not None and mixing not in MIXING_RULES:
            raise ValueError(f"params.mixing is one of {MIXING_RULES}, found {mixing!r}")
        one_four = self.params.get("one_four")
        if (
            (self.category, self.style) == ("pair", "lj/charmm")
            and one_four is not None
            and one_four not in ONE_FOUR_VALUES
        ):
            raise ValueError(
                f"pair.lj/charmm params.one_four is one of {ONE_FOUR_VALUES}, found {one_four!r}"
            )
        return self

    @model_serializer(mode="wrap")
    def _only_what_it_says(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for name in type(self).model_fields:
            if getattr(self, name) is None:
                data.pop(name, None)
        if not self.params:
            data.pop("params", None)
        if self.endpoint_key == "type":
            data.pop("endpoint_key", None)
        return data

    @property
    def block(self) -> str:
        """The block name of this style's table."""
        return style_block_name(self.category, self.style)

    @property
    def arity(self) -> int | None:
        """How many endpoints a row names, for a known category."""
        return CATEGORY_ARITY.get(self.category)


def _check_style_table(style: StyleModel, table: BlockModel, class_keyed: bool) -> None:
    """A style's table holds the rows the chapter says it does."""
    where = f"table {style.block!r}"
    if table.structural_shape is not None:
        raise ValueError(f"{where} is a table of types; it declares no structural shape")
    name = table.columns.get("name")
    if name is None:
        raise ValueError(f"{where} has no name column")
    if name.dtype != "string" or name.validity is not None or name.shape[1:]:
        raise ValueError(
            f"{where}: name is a string[T] never null, found {name.dtype}{list(name.shape[1:])}"
        )
    names = [] if name.values is None else [str(value) for value in name.values.tolist()]
    if len(set(names)) != len(names):
        raise ValueError(f"{where}: type names are unique, found {sorted(names)}")

    present = [column for column in ENDPOINT_COLUMNS if column in table.columns]
    if style.endpoint_key == "smirks":
        smirks = table.columns.get("smirks")
        if present or smirks is None or smirks.dtype != "string" or smirks.validity is not None:
            raise ValueError(
                f"{where} is smirks-keyed: no endpoint columns, and a smirks column never null"
            )
    elif style.arity is not None:
        expected = list(ENDPOINT_COLUMNS[: style.arity])
        if present != expected:
            raise ValueError(
                f"{where}: a {style.category} row names endpoints {expected}, found {present}"
            )
    elif present != list(ENDPOINT_COLUMNS[: len(present)]):
        raise ValueError(f"{where}: endpoint columns {present} are no prefix of itom..mtom")
    for endpoint in present:
        column = table.columns[endpoint]
        if column.dtype != "string" or column.validity is not None or column.shape[1:]:
            raise ValueError(f"{where}: endpoint {endpoint} is a string[T] never null")

    for column_name, column in table.columns.items():
        if column_name == "name" or column_name in ENDPOINT_COLUMNS:
            continue
        if style.category == "cmap" and column_name == CMAP_GRID:
            _check_cmap_grid(where, column)
            continue
        canonical = CANONICAL_COLUMNS.get(column_name)
        if column_name in ANNOTATION_COLUMNS:
            allowed: tuple[str, ...] = ("string",)
        elif canonical is not None:
            allowed = (canonical,)
        else:
            allowed = ("f64", "string")
            if column.dtype == "f64" and column.shape[1:]:
                _check_array_param(where, column_name, column)
                continue
        if column.dtype not in allowed or column.shape[1:] or column.precision is not None:
            raise ValueError(
                f"{where}: parameter {column_name!r} is {' or '.join(allowed)}[T], exact, found "
                f"{column.dtype}{list(column.shape[1:]) or ''}"
                + (" with a declared precision" if column.precision is not None else "")
            )
    if class_keyed and style.category == "atom" and "class" not in table.columns:
        raise ValueError(
            f"{where}: a class-keyed style links through atom classes; no class column"
        )
    # Linking rule 3: a pair table prices each unordered pair of types once.
    if style.category == "pair" and present == ["itom", "jtom"]:
        _check_pair_restatements(where, table, names)


def _check_array_param(where: str, name: str, column: ColumnModel) -> None:
    """An array parameter: ``f64[T, S...]``, every trailing axis at least 1
    long, no precision, every value of a non-null row finite. One shape for
    every row -- a column has one shape."""
    trailing = column.shape[1:]
    if column.dtype != "f64" or not all(axis >= 1 for axis in trailing):
        raise ValueError(
            f"{where}: array parameter {name!r} is f64[T, S...] with every S >= 1, found "
            f"{column.dtype}{list(trailing)}"
        )
    if column.precision is not None:
        raise ValueError(f"{where}: array parameter {name!r} is exact, found a declared precision")
    _check_finite_rows(where, f"array parameter {name!r}", column)


def _check_finite_rows(where: str, what: str, column: ColumnModel) -> None:
    """Every value of a non-null row of an array column is finite."""
    if column.values is None:
        return
    values = np.asarray(column.values)
    rows = np.isfinite(values).reshape(values.shape[0], -1).all(axis=1)
    if column.validity is not None:
        rows |= ~np.asarray(column.validity)
    if not rows.all():
        raise ValueError(f"{where}: {what} of row {int(np.argmin(rows))} holds a non-finite value")


def _check_cmap_grid(where: str, column: ColumnModel) -> None:
    """A ``cmap`` table's grid: an array parameter of shape ``f64[T, N, N]``,
    ``N >= 2``, with no precision, every value of a non-null row finite."""
    trailing = column.shape[1:]
    square = len(trailing) == 2 and trailing[0] == trailing[1] and trailing[0] >= 2
    if column.dtype != "f64" or not square or column.precision is not None:
        raise ValueError(
            f"{where}: the cmap grid is f64[T, N, N] with N >= 2 and no precision, found "
            f"{column.dtype}{list(trailing)}"
            + (" with a declared precision" if column.precision is not None else "")
        )
    _check_finite_rows(where, "the cmap grid", column)


def _cells(column: ColumnModel, count: int) -> list[Any]:
    """A 1-D column's values row by row, ``None`` where the row is null."""
    values = [None] * count if column.values is None else column.values.tolist()
    if column.validity is None:
        return values
    validity = column.validity.tolist()
    return [value if valid else None for value, valid in zip(values, validity, strict=True)]


def _check_pair_restatements(where: str, table: BlockModel, names: list[str]) -> None:
    """A pair table prices each unordered ``{itom, jtom}`` once: rows restating
    a pair, in either order, carry equal parameters (null equal only to null);
    ``name`` and the annotation columns are no parameters."""
    count = table.count
    itom, jtom = (_cells(table.columns[end], count) for end in ("itom", "jtom"))
    params = {
        column_name: _cells(column, count)
        for column_name, column in table.columns.items()
        if column_name != "name"
        and column_name not in ENDPOINT_COLUMNS
        and column_name not in ANNOTATION_COLUMNS
    }
    first_row: dict[tuple[str, str], int] = {}
    for row, ends in enumerate(zip(itom, jtom, strict=True)):
        pair = (min(ends), max(ends))
        first = first_row.setdefault(pair, row)
        if first == row:
            continue
        differ = sorted(name for name, cells in params.items() if cells[first] != cells[row])
        if differ:
            raise ValueError(
                f"{where}: rows {names[first]!r} and {names[row]!r} both price the pair "
                f"{{{pair[0]!r}, {pair[1]!r}}} and differ in {differ}"
            )


class ForceFieldModel(DocumentModel):
    """The ``forcefield`` section: the document and one table per style.

    Every field but ``tables`` is the document -- the group's attribute map,
    unknown keys preserved (``extra="allow"``). ``tables`` maps a block name to
    its style table; a table no style names is kept as unknown content.
    Linking a system's types to these rows is by name and is never refused
    here (``docs/spec/forcefield.md``, linking a system).
    """

    name: str
    units: ForceFieldUnitsModel
    source: ForceFieldSourceModel | None = None
    special_bonds: SpecialBondsModel | None = None
    styles: list[StyleModel] = Field(default_factory=list)
    tables: dict[str, BlockModel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_table_per_style(self) -> ForceFieldModel:
        seen: set[tuple[str, str]] = set()
        for style in self.styles:
            key = (style.category, style.style)
            if key in seen:
                raise ValueError(f"style {style.category}/{style.style} is listed twice")
            seen.add(key)
        class_keyed = any(style.endpoint_key == "class" for style in self.styles)
        for style in self.styles:
            table = self.tables.get(style.block)
            if table is None:
                raise ValueError(
                    f"style {style.category}/{style.style} has no table {style.block!r}"
                )
            _check_style_table(style, table, class_keyed)
        return self

    def document(self) -> dict[str, Any]:
        """The document as the group attribute map stores it: every field but
        ``tables``, extra keys included, plain and finite."""
        return jsonvalue.check_document(self.model_dump(mode="json", exclude={"tables"}))


#: The root sections of which a record must carry at least one beside ``meta``.
SUBSTANTIVE_SECTIONS: tuple[str, ...] = ("frame", "system", "trajectory", "forcefield", "status")


class RecordModel(BaseModel):
    """The record root.

    ``meta`` is always present (an empty document is a valid one), plus at
    least one of ``frame``, ``system``, ``trajectory``, ``forcefield`` or
    ``status`` -- a record of ``meta`` and ``forcefield`` alone is a
    force-field package. Each of
    those is a valid **sole** section beside ``meta``: a trajectory-only
    record is conforming and a reader must not require a frame beside it,
    because frames may embed full blocks including topology.

    ``observables`` is the section
    (:class:`molrec.observables.model.ObservablesModel`). ``metrics``
    -- the catalog document, the dense series and the live WAL of
    ``docs/spec/metrics.md`` -- is carried verbatim as a :class:`NodeModel`:
    molrec does not interpret run-local monitoring, it only never loses it.
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
    forcefield: ForceFieldModel | None = None
    status: StatusModel | None = None
    method: MethodModel | None = None
    metrics: NodeModel | None = None
    observables: _observables.ObservablesModel | None = None

    @model_validator(mode="after")
    def _unknown_sections_are_subtrees(self) -> RecordModel:
        """An extra key is a root section the contract does not define: a
        group, kept as the :class:`NodeModel` it was read as."""
        extra = self.__pydantic_extra__ or {}
        for name, value in extra.items():
            extra[name] = NodeModel.model_validate(value)
        return self

    @model_validator(mode="after")
    def _system_and_trajectory_align(self) -> RecordModel:
        """A ``system`` block and the ``trajectory`` block of the same name are
        aligned 1:1 by row order: every update has the system block's row
        count, and an ``id`` column both carry is equal row for row."""
        if self.system is None or self.trajectory is None:
            return self
        _aligned_apart_from_system(self.system, self.trajectory)
        for name, fixed in self.system.blocks.items():
            for ordinal, frame in enumerate(self.trajectory.frames):
                update = frame.blocks.get(name)
                if update is None:
                    continue
                if update.count != fixed.count:
                    raise ValueError(
                        f"trajectory block {name!r} has {update.count} rows at ordinal {ordinal}, "
                        f"system block {fixed.count}; blocks sharing a name align 1:1 by row"
                    )
                ids = update.columns.get("id"), fixed.columns.get("id")
                if None not in ids and ids[0] != ids[1]:
                    raise ValueError(
                        f"block {name!r}: the id column differs between system and trajectory at "
                        f"ordinal {ordinal}; blocks sharing a name align row for row"
                    )
        return self

    @model_validator(mode="after")
    def _absolute_references_resolve(self) -> RecordModel:
        _check_absolute_references(self)
        return self

    @model_validator(mode="after")
    def _has_a_section(self) -> RecordModel:
        if all(getattr(self, section) is None for section in SUBSTANTIVE_SECTIONS):
            raise ValueError(f"a record needs at least one of {', '.join(SUBSTANTIVE_SECTIONS)}")
        return self


def _check_absolute_references(record: RecordModel) -> None:
    """Every absolute row reference (``/<section>/<block>``) into a present
    frame-shaped section is to a block of it, and in range -- from a frame or
    system block, and from every resolved frame of a trajectory block."""
    sections: dict[str, FrameModel | None] = {"frame": record.frame, "system": record.system}

    def rows(target: str) -> tuple[bool, int | None]:
        section, block = target[1:].split("/", 1)
        frame = sections.get(section)
        if frame is None:
            return False, None
        tracked = frame.blocks.get(block)
        return True, None if tracked is None else tracked.count

    sources: list[tuple[str, BlockModel, dict[str, str]]] = []
    for section, frame in sections.items():
        for name, block in (frame.blocks if frame is not None else {}).items():
            sources.append((f"{section}/{name}", block, block.targets or {}))
    if record.trajectory is not None:
        for name, declared in (record.trajectory.blocks or {}).items():
            for frame in record.trajectory.frames:
                if name in frame.blocks:
                    sources.append(
                        (f"trajectory/{name}", frame.blocks[name], declared.targets or {})
                    )
    for where, block, targets in sources:
        for column, target in targets.items():
            if not target.startswith("/"):
                continue
            present, count = rows(target)
            if present:
                check_references(where, block.columns[column], column, target, count)


def _aligned_apart_from_system(system: FrameModel, trajectory: TrajectoryModel) -> None:
    """An aligned trajectory block never shares a name with a ``system`` block
    (its target may: the target's row count is then the system's)."""
    clash = sorted(_aligned_names(trajectory) & set(system.blocks))
    if clash:
        raise ValueError(
            f"aligned trajectory blocks {clash} share a name with system blocks; an aligned "
            "block is the trajectory's own"
        )


#: The collection index columns a binding owns, in the order the LMDB binding
#: writes them; a collection's own index columns may not take these names
#: (``docs/spec/lmdb.md``). A tuple, not a set: a writer that iterated a set of
#: strings would lay the index out in a different order on every run.
RESERVED_INDEX_COLUMNS: tuple[str, ...] = ("first_frame", "n_frames", "n_atoms", "has_trajectory")


class CollectionMetaModel(DocumentModel):
    """The collection's document. ``units`` is required; other keys are kept.

    ``units`` maps a quantity (``length``, ``energy``, ``force``, ``charge``,
    ``mass``, ``time``) to a unit string. It is the only place a collection's
    numbers get a unit: columns and per-step tags carry none.
    """

    units: dict[str, str]


class CollectionModel(BaseModel):
    """Many records under one declaration (``docs/spec/collection.md``).

    Each record is an ordinary :class:`RecordModel` restricted to ``meta``,
    ``system`` and ``trajectory``. Every record's trajectory uses
    ``sequence_schema`` -- stated, or derived from the first record that has a
    trajectory. ``index`` is a block of one row per record whose columns the
    writer derived from the records; it is handed back, never recomputed.
    ``forcefield`` is the one force field every record links into.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="forbid")

    meta: CollectionMetaModel
    sequence_schema: SequenceSchemaModel | None = None
    index: BlockModel | None = None
    forcefield: ForceFieldModel | None = None
    records: list[RecordModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _records_are_collection_records(self) -> CollectionModel:
        for r, record in enumerate(self.records):
            extra = [
                section
                for section in ("frame", "forcefield", "status", "method", "metrics", "observables")
                if getattr(record, section) is not None
            ]
            if extra:
                raise ValueError(
                    f"record {r} carries {extra}; a collection record holds meta, system and "
                    "trajectory only (its force field is the collection's)"
                )
            if record.system is None and record.trajectory is None:
                raise ValueError(f"record {r} has neither system nor trajectory")
        return self

    @model_validator(mode="after")
    def _one_declaration(self, info: ValidationInfo) -> CollectionModel:
        """Every record's trajectory uses the collection's one declaration.

        A record's frames may present a **subset** of it -- a record that
        never carries ``bonds`` is still a record of a collection that
        declares them -- but nothing outside it, and the per-step ``meta``
        declaration (tags and fills, a NaN fill equal to a NaN fill) is the
        collection's exactly. Unstated, the declaration is the union of the
        records' blocks, which must agree on every column they share.
        Afterwards every record's trajectory states the collection's blocks,
        which is what a reader hands back.
        """
        trajectories = [
            (r, record.trajectory)
            for r, record in enumerate(self.records)
            if record.trajectory is not None
        ]
        schema = self.sequence_schema
        if schema is None and trajectories:
            blocks: dict[str, SequenceBlockModel] = {}
            for r, trajectory in trajectories:
                for name, block in (trajectory.blocks or {}).items():
                    if name in blocks and (
                        _layout(blocks[name]) != _layout(block)
                        or blocks[name].aligned_with != block.aligned_with
                    ):
                        raise ValueError(
                            f"record {r} declares block {name!r} as {_layout(block)}, an earlier "
                            f"record as {_layout(blocks[name])}; a collection has one declaration"
                        )
                    blocks[name] = _union_nullable(blocks.get(name), block)
            schema = SequenceSchemaModel(blocks=blocks, meta=trajectories[0][1].meta)

        records = list(self.records)
        for r, trajectory in trajectories:
            assert schema is not None
            if trajectory.meta != schema.meta:
                raise ValueError(
                    f"record {r} declares its per-step meta as {trajectory.meta}, the collection "
                    f"as {schema.meta}; every record in a collection uses one declaration"
                )
            try:
                held = TrajectoryModel.model_validate(
                    {
                        **trajectory.model_dump(exclude_unset=True),
                        "blocks": schema.blocks,
                    },
                    context=info.context,
                )
            except ValueError as exc:
                raise ValueError(
                    f"record {r} presents what the collection's declaration does not: {exc}"
                ) from None
            records[r] = self.records[r].model_copy(update={"trajectory": held})
        object.__setattr__(self, "sequence_schema", schema)
        object.__setattr__(self, "records", records)
        return self

    @model_validator(mode="after")
    def _shared_blocks_split_their_columns(self) -> CollectionModel:
        """In a collection a reader presents a system block and the trajectory
        block of the same name as one block whose columns are the union, so a
        column is time-independent or not -- never both."""
        for r, record in enumerate(self.records):
            if record.system is None or record.trajectory is None:
                continue
            try:
                _aligned_apart_from_system(record.system, record.trajectory)
                _check_absolute_references(record)
            except ValueError as exc:
                raise ValueError(f"record {r}: {exc}") from None
            for name, fixed in record.system.blocks.items():
                for frame in record.trajectory.frames:
                    update = frame.blocks.get(name)
                    shared = set() if update is None else set(update.columns) & set(fixed.columns)
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
        reserved = sorted(set(RESERVED_INDEX_COLUMNS) & set(self.index.columns))
        if reserved:
            raise ValueError(f"index columns {reserved} are reserved for the binding")
        return self


# The record root holds the observables section, which
# :mod:`molrec.observables.model` owns. That module builds on this one
# (``DocumentModel``, ``ArrayModel``), so it is imported once this one is
# complete and the two models that reach the section are finished here.
from molrec.observables import model as _observables  # noqa: E402

RecordModel.model_rebuild()
CollectionModel.model_rebuild()
