"""L0-L2 models: Column, Block, Box, Frame, Meta, Record.

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

    #: ``None`` means every row is present. A mask is one flag per row, not a
    #: sentinel stored in the value array: the value under a false flag is filler.
    validity: tuple[bool, ...] | None = None

    @model_validator(mode="after")
    def _values_match_declaration(self) -> ColumnModel:
        if self.validity is not None and len(self.validity) != self.shape[0]:
            raise ValueError(
                f"validity has {len(self.validity)} flags, column count is {self.shape[0]}"
            )
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
        if (
            self.dtype != other.dtype
            or self.shape != other.shape
            or self.validity != other.validity
        ):
            return False
        return arrays_equal(self.values, other.values)

    __hash__ = None  # type: ignore[assignment]


#: Record spellings of the built-in unit presets. ``lj`` states only the angle
#: unit; its other quantities are reduced scales named by the preset itself.
PRESET_UNITS: dict[str, dict[str, str]] = {
    "real": {
        "length": "angstrom",
        "energy": "kcal/mol",
        "time": "fs",
        "mass": "dalton",
        "charge": "e",
        "angle": "degree",
    },
    "metal": {
        "length": "angstrom",
        "energy": "eV",
        "time": "ps",
        "mass": "dalton",
        "charge": "e",
        "angle": "degree",
    },
    "si": {
        "length": "m",
        "energy": "J",
        "time": "s",
        "mass": "kg",
        "charge": "C",
        "angle": "degree",
    },
    "cgs": {
        "length": "cm",
        "energy": "erg",
        "time": "s",
        "mass": "g",
        "charge": "statcoulomb",
        "angle": "degree",
    },
    "electron": {
        "length": "bohr",
        "energy": "hartree",
        "time": "fs",
        "mass": "dalton",
        "charge": "e",
        "angle": "degree",
    },
    "micro": {
        "length": "micrometer",
        "energy": "picogram * micrometer**2 / microsecond**2",
        "time": "microsecond",
        "mass": "picogram",
        "charge": "picocoulomb",
        "angle": "degree",
    },
    "nano": {
        "length": "nm",
        "energy": "attogram * nm**2 / ns**2",
        "time": "ns",
        "mass": "attogram",
        "charge": "e",
        "angle": "degree",
    },
    "lj": {"angle": "degree"},
    "openmm": {
        "length": "nm",
        "energy": "kJ/mol",
        "time": "ps",
        "mass": "dalton",
        "charge": "e",
        "angle": "degree",
    },
}

UNIT_QUANTITIES: tuple[str, ...] = ("length", "energy", "time", "mass", "charge", "angle")


class UnitsModel(BaseModel):
    """One unit system: a preset, explicit quantities, or both when they agree.

    Angle values are degrees in every built-in preset. A force constant per
    radian is a parameter dimension (``E/A^2``), not a second angle unit.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    preset: str | None = None
    length: str | None = None
    energy: str | None = None
    time: str | None = None
    mass: str | None = None
    charge: str | None = None
    angle: str | None = None

    @model_validator(mode="after")
    def _matches_preset(self) -> UnitsModel:
        stated = {
            quantity: getattr(self, quantity)
            for quantity in UNIT_QUANTITIES
            if getattr(self, quantity) is not None
        }
        if self.preset is None and not stated:
            raise ValueError("units need a preset or at least one quantity")
        if self.preset is None:
            return self
        table = PRESET_UNITS.get(self.preset)
        if table is None:
            known = ", ".join(PRESET_UNITS)
            raise ValueError(f"unknown units preset {self.preset!r}; known presets: {known}")
        for quantity, unit in stated.items():
            expected = table.get(quantity)
            if expected is None:
                raise ValueError(f"preset {self.preset!r} states no {quantity}")
            if unit != expected:
                raise ValueError(
                    f"preset {self.preset!r} measures {quantity} in {expected!r}, found {unit!r}"
                )
        return self


class MeshModel(BaseModel):
    """Voxel edges of a regular grid, the geometry of molrs ``RegularGrid``.

    Columns of ``vectors`` are the edge of one voxel along each axis.
    ``origin`` is the corner of voxel 0. Where the stored value sits, corner
    or center, is the block's ``sample``, not this geometry. ``unit`` is a
    length override; absent means ``meta.units`` length.
    """

    model_config = ConfigDict(frozen=True)

    origin: NDArray
    vectors: NDArray
    boundary: tuple[bool, ...] | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _f64_axes(self) -> MeshModel:
        if dtype_of(self.origin.dtype) != "f64" or dtype_of(self.vectors.dtype) != "f64":
            raise ValueError("mesh origin and vectors are f64")
        shape = tuple(self.vectors.shape)
        if len(shape) != 2 or shape[0] != shape[1]:
            raise ValueError(f"mesh vectors must be [ndim][ndim], found {shape}")
        ndim = shape[0]
        if tuple(self.origin.shape) != (ndim,):
            raise ValueError(f"mesh origin must be [{ndim}], found {tuple(self.origin.shape)}")
        if self.boundary is not None and len(self.boundary) != ndim:
            raise ValueError(f"mesh boundary must have {ndim} flags, found {len(self.boundary)}")
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MeshModel):
            return NotImplemented
        return (
            arrays_equal(self.origin, other.origin)
            and arrays_equal(self.vectors, other.vectors)
            and self.boundary == other.boundary
            and self.unit == other.unit
        )

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
    #: Where a volumetric sample sits inside its voxel. Required together
    #: with ``structural_shape``. ``corner`` is the cube-file node;
    #: ``center`` is the voxel centre molrs density grids use.
    sample: Literal["corner", "center"] | None = None
    mesh: MeshModel | None = None

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
            if self.sample is None:
                raise ValueError("a block with structural_shape states sample: corner or center")
        elif self.sample is not None:
            raise ValueError("sample is set on a block with no structural_shape")
        if self.mesh is not None:
            rank = 0 if self.structural_shape is None else len(self.structural_shape)
            ndim = int(self.mesh.vectors.shape[0])
            if rank != ndim:
                raise ValueError(f"mesh ndim is {ndim} and structural_shape rank is {rank}")
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


class MetaModel(BaseModel):
    """The record's identity document.

    ``extra="allow"`` is not convenience -- it is the preserve-the-unknown
    invariant: a reader must keep keys it does not recognize.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    record_schema_version: int = Field(ge=1)
    format_name: Literal["molrec"] | None = None
    record_id: str | None = None
    content_hash: str | None = None
    #: Unit system of geometry in this record: coordinates, the box, a block
    #: mesh, and ``trajectory.time``. Absent means those arrays state no unit.
    units: UnitsModel | None = None


_ENDPOINTS: tuple[str, ...] = ("itom", "jtom", "ktom", "ltom", "mtom")

#: Endpoint count of a built-in force-field category.
CATEGORY_ARITY: dict[str, int] = {
    "atom": 0,
    "bond": 2,
    "angle": 3,
    "dihedral": 4,
    "improper": 4,
    "pair": 2,
    "cmap": 5,
    "constraint": 2,
    "drude": 2,
    "virtual_site": 0,
}

#: Built-in styles whose parameters live on the system rows, not in the type table.
PER_INSTANCE_STYLES: frozenset[tuple[str, str]] = frozenset(
    {
        ("bond", "mmff_bond"),
        ("bond", "uff_bond"),
        ("angle", "mmff_angle"),
        ("angle", "mmff_stbn"),
        ("angle", "uff_angle"),
        ("dihedral", "mmff_torsion"),
        ("dihedral", "uff_torsion"),
        ("improper", "mmff_oop"),
        ("improper", "uff_inversion"),
        ("pair", "coul/cut"),
        ("pair", "coul/charmm"),
        ("pair", "coul/long/pme"),
        ("pair", "uff_lj"),
        ("pair", "mmff_vdw"),
    }
)

#: Stored endpoint order: index of the central atom. Other impropers state ``center``.
IMPROPER_CENTER: dict[str, int] = {
    "harmonic": 0,
    "cvff": 0,
    "periodic": 2,
    "mmff_oop": 0,
    "uff_inversion": 0,
}

_STYLE_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def style_block_name(category: str, style: str) -> str:
    """``(bond, harmonic)`` → ``bond.harmonic``; ``lj/cut`` → ``pair.lj%2Fcut``."""
    encoded: list[str] = []
    for byte in style.encode("utf-8"):
        character = chr(byte)
        if character in _STYLE_UNRESERVED:
            encoded.append(character)
        else:
            encoded.append(f"%{byte:02X}")
    return f"{category}.{''.join(encoded)}"


class SpecialBondsModel(BaseModel):
    """1-2 / 1-3 / 1-4 scale weights, van der Waals and Coulomb separately."""

    model_config = ConfigDict(frozen=True)

    lj: tuple[float, float, float]
    coul: tuple[float, float, float]


class StyleEntryModel(BaseModel):
    """One ``(category, style)`` in document order."""

    model_config = ConfigDict(frozen=True, extra="allow")

    category: str
    style: str
    params: dict[str, Any] = Field(default_factory=dict)
    expression: str | None = None
    endpoint_key: Literal["type", "class", "smirks"] = "type"
    center: int | None = None
    dims: dict[str, str] | None = None
    source: Literal["type_rows", "per_instance"] | None = None
    defaults: dict[str, Any] | None = None
    arity: int | None = None
    coordinate: str | None = None
    order: Literal["reversible", "ordered", "unordered"] | None = None


class ForceFieldModel(BaseModel):
    """The ``forcefield/`` section: a document plus one block per style.

    ``tables`` is keyed by :func:`style_block_name`. Rules that need the style
    registry's parameter lists live in the force-field chapter; this model
    checks the shape a reader needs before it prices anything.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    name: str = Field(min_length=1)
    units: UnitsModel
    special_bonds: SpecialBondsModel | None = None
    styles: list[StyleEntryModel] = Field(default_factory=list)
    tables: dict[str, BlockModel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _styles_match_tables(self) -> ForceFieldModel:
        seen: set[tuple[str, str]] = set()
        names_by_category: dict[str, set[str]] = {}
        for entry in self.styles:
            key = (entry.category, entry.style)
            if key in seen:
                raise ValueError(f"style {entry.category}/{entry.style} is listed twice")
            seen.add(key)
            if entry.category not in CATEGORY_ARITY and entry.arity is None:
                raise ValueError(
                    f"style {entry.category}/{entry.style} is outside the built-in "
                    "categories and states no arity"
                )
            if entry.category == "improper":
                builtin = IMPROPER_CENTER.get(entry.style)
                if builtin is not None and entry.center not in (None, builtin):
                    raise ValueError(
                        f"improper {entry.style} stores its center at endpoint {builtin}, "
                        f"found {entry.center}"
                    )
                if builtin is None and entry.center is None:
                    raise ValueError(f"improper {entry.style} states no center")
            block_name = style_block_name(entry.category, entry.style)
            table = self.tables.get(block_name)
            if table is None:
                raise ValueError(f"style {entry.category}/{entry.style} has no table {block_name}")
            _check_style_table(entry, table)
            if _is_type_rows(entry):
                taken = names_by_category.setdefault(entry.category, set())
                for label in _type_names(table):
                    if label in taken:
                        raise ValueError(
                            f"type {label!r} is defined twice in category {entry.category!r}"
                        )
                    taken.add(label)
        return self


def _is_type_rows(entry: StyleEntryModel) -> bool:
    if entry.source == "per_instance":
        return False
    if entry.source == "type_rows":
        return True
    return (entry.category, entry.style) not in PER_INSTANCE_STYLES


def _type_names(table: BlockModel) -> list[str]:
    column = table.columns.get("name")
    if column is None or column.values is None:
        return []
    return [str(value) for value in column.values.reshape(-1)]


def _check_style_table(entry: StyleEntryModel, table: BlockModel) -> None:
    name = table.columns.get("name")
    if name is None or name.dtype != "string":
        raise ValueError(f"{entry.category}/{entry.style} table needs a string name column")
    labels = _type_names(table)
    if len(labels) != len(set(labels)):
        raise ValueError(f"{entry.category}/{entry.style} repeats a type name")
    arity = CATEGORY_ARITY.get(entry.category, entry.arity)
    if arity is None:
        raise ValueError(f"{entry.category}/{entry.style} has no arity")
    if entry.endpoint_key == "smirks":
        smirks = table.columns.get("smirks")
        if smirks is None or smirks.dtype != "string":
            raise ValueError(
                f"{entry.category}/{entry.style} with endpoint_key smirks needs a smirks column"
            )
        return
    for index, endpoint in enumerate(_ENDPOINTS):
        column = table.columns.get(endpoint)
        if index < arity:
            if column is None or column.dtype != "string":
                raise ValueError(f"{entry.category}/{entry.style} needs string endpoint {endpoint}")
        elif column is not None:
            raise ValueError(
                f"{entry.category}/{entry.style} has endpoint {endpoint} past arity {arity}"
            )


class RecordModel(BaseModel):
    """The record root.

    ``meta`` is always required, plus at least one other section. This module
    owns ``frame`` and ``system``. Document sections it does not model
    (``status``, ``method``, and any section a later module adds) ride in
    ``extra`` and are part of the record: a run is ``meta`` plus ``status``
    and has no frame.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    meta: MetaModel
    frame: FrameModel | None = None
    system: FrameModel | None = None
    forcefield: ForceFieldModel | None = None

    @model_validator(mode="after")
    def _has_a_section(self) -> RecordModel:
        extra = self.__pydantic_extra__ or {}
        if self.frame is None and self.system is None and self.forcefield is None and not extra:
            raise ValueError(
                "a record needs meta and at least one other section "
                "(frame, system, trajectory, status, forcefield, or another preserved section)"
            )
        meta_preset = self.meta.units.preset if self.meta.units is not None else None
        ff_preset = self.forcefield.units.preset if self.forcefield is not None else None
        if meta_preset is not None and ff_preset is not None and meta_preset != ff_preset:
            raise ValueError(
                f"meta.units.preset is {meta_preset!r} and forcefield.units.preset is {ff_preset!r}"
            )
        return self
