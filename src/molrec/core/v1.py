"""Reading a ``molrec_version`` 1 store under version 2.

Version 2 changed what some stored numbers of the force-field IR mean (it
adopts LAMMPS's definitions: harmonic ``k`` without the ½, angle values in
degrees, ``bond morse`` ``d0``). A reader never reads a version-1 store as
version 2: it converts every changed number exactly, or refuses the store.
A store without ``molrec_version`` predates version 1 and is read by the
same rules. The rules are ``docs/spec/forcefield.md``, "Reading a version-1
record"; this module is their executable statement, which the reference
codecs run on every read door.

:class:`V1Upgrade` is built from the store's ``forcefield`` section *as
stored* -- it says which style each relation row is -- and converts the
section (:meth:`V1Upgrade.forcefield`) and every frame
(:meth:`V1Upgrade.frame`). ``meta`` is never touched: a reader hands it back
as stored.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from molrec.core.model import (
    ANNOTATION_COLUMNS,
    ENDPOINT_COLUMNS,
    UNIT_PRESETS,
    BlockModel,
    ColumnModel,
    FrameModel,
    TrajectoryModel,
    style_block_name,
)

#: 180/π, the one rounding of it every implementation multiplies by: an angle
#: value in radians times this is the same double everywhere.
DEGREES_PER_RADIAN = 180.0 / math.pi

_TERM = re.compile(r"^(k|periodicity|phase)[0-9]+$")


class V1Refusal(ValueError):
    """A version-1 store with no exact version-2 form."""

    def __init__(self, message: str) -> None:
        super().__init__(f"molrec_version 1 record: {message}")


def read_version(meta: dict[str, Any]) -> int:
    """The version a store's sections are read under: its ``molrec_version``,
    or ``1`` when the key is absent (a store written before version 1). The
    key itself is validated by :class:`~molrec.core.model.MetaModel`."""
    version = meta.get("molrec_version")
    return 1 if version is None else int(version)


# -- the rules ---------------------------------------------------------------

#: Styles whose numbers mean the same in both versions, beyond every style of
#: a non-angular category (``atom``, ``pair``, ``cmap``, ...).
_UNCHANGED = {
    ("bond", "class2"),
    ("bond", "mmff_bond"),
    ("bond", "uff_bond"),
    ("angle", "mmff_stbn"),
    ("dihedral", "opls"),
    ("dihedral", "rb"),
    ("dihedral", "harmonic"),
    ("dihedral", "multi/harmonic"),
    ("dihedral", "mmff_torsion"),
    ("dihedral", "uff_torsion"),
    ("improper", "cvff"),
}

_CONVERTED = {
    ("bond", "harmonic"),
    ("drude", "harmonic"),
    ("bond", "morse"),
    ("angle", "harmonic"),
    ("angle", "class2"),
    ("angle", "mmff_angle"),
    ("angle", "uff_angle"),
    ("dihedral", "periodic"),
    ("dihedral", "charmm"),
    ("dihedral", "class2"),
    ("improper", "harmonic"),
    ("improper", "periodic"),
    ("improper", "trefoil"),
    ("pair", "morse"),
    ("pair", "thole"),
}

#: Out-of-plane styles whose version-1 rows listed the centre second.
_CENTRE_SECOND = {("improper", "mmff_oop"), ("improper", "uff_inversion")}

#: Styles version 2 names otherwise.
_RENAMED = {("dihedral", "fourier"): "periodic"}

_ANGULAR = {"angle", "dihedral", "improper"}

_PAIR14 = (
    "version 1 priced 1-4 pairs from a pair14 table, unweighted; version 2 has no "
    "force-field form for that (per-pair overrides on the system's pairs rows are one)"
)


def _rule(category: str, style: str) -> str:
    """``converted``, ``renamed``, ``unchanged``, ``refused`` or ``unknown``."""
    key = (category, style)
    if key in _CONVERTED or key in _CENTRE_SECOND:
        return "converted"
    if key in _RENAMED:
        return "renamed"
    if category == "pair14":
        return "refused"
    if key in _UNCHANGED or category not in _ANGULAR:
        return "unchanged"
    return "unknown"


def _version2_style(category: str, style: str) -> str:
    return _RENAMED.get((category, style), style)


def _is_angle_value(column: str) -> bool:
    return column in {"theta0", "chi0", "phase", "phi1", "phi2", "phi3"} or bool(
        re.fullmatch(r"phase[0-9]+", column)
    )


#: A conversion: ``("scale", half, per_angle)``, ``("angle",)`` or
#: ``("rename", to)``.
Conv = tuple[Any, ...]


def _column_conv(category: str, style: str, column: str) -> Conv | None:
    key = (category, style)
    if key in {("bond", "harmonic"), ("drude", "harmonic")} and column == "k":
        return ("scale", True, 0)
    if key == ("bond", "morse") and column == "D":
        return ("rename", "d0")
    if key == ("angle", "harmonic") and column == "k":
        return ("scale", True, 2)
    if key == ("angle", "class2") and column in {"k2", "k3", "k4"}:
        return ("scale", False, int(column[1]))
    if key == ("improper", "harmonic") and column == "k":
        return ("scale", False, 2)
    if key == ("improper", "periodic") and _TERM.match(column):
        raise V1Refusal(
            f"improper periodic column {column!r} is a term of a multi-term improper; "
            "version 2's improper periodic is one term"
        )
    if (
        (
            column == "theta0"
            and category == "angle"
            and style in {"harmonic", "class2", "mmff_angle", "uff_angle"}
        )
        or (key == ("improper", "harmonic") and column == "chi0")
        or (key in {("dihedral", "charmm"), ("improper", "periodic")} and column == "phase")
        or (key == ("dihedral", "class2") and column in {"phi1", "phi2", "phi3"})
        or (
            key in {("dihedral", "periodic"), ("improper", "trefoil")}
            and re.fullmatch(r"phase[0-9]*", column)
        )
    ):
        return ("angle",)
    if key == ("pair", "morse") and column == "D0":
        return ("rename", "d0")
    if key == ("pair", "thole") and column == "a_thole":
        return ("rename", "damp")
    return None


_ANGLE_UNITS = {
    "radian": "radian",
    "radians": "radian",
    "rad": "radian",
    "degree": "degree",
    "degrees": "degree",
    "deg": "degree",
}


# -- columns -------------------------------------------------------------------


def _valid(column: ColumnModel, row: int) -> bool:
    return column.validity is None or bool(column.validity[row])


def _converted(column: ColumnModel, conv: Conv, unit: str | None, rows: list[int]) -> ColumnModel:
    if column.dtype != "f64" or column.values is None:
        raise V1Refusal(f"a converted parameter is an f64 column, found {column.dtype}")
    values = np.array(column.values, dtype="float64", copy=True)
    for row in rows:
        if not _valid(column, row):
            continue
        x = float(values[row])
        if conv[0] == "scale":
            _, half, per_angle = conv
            if half:
                x = x * 0.5
            if unit == "degree":
                for _ in range(per_angle):
                    x = x * DEGREES_PER_RADIAN
        elif conv[0] == "angle":
            if unit == "radian":
                x = x * DEGREES_PER_RADIAN
        values[row] = x
    return column.model_copy(update={"values": values})


def _swapped(block: BlockModel, a: str, b: str, rows: list[int]) -> BlockModel:
    if a not in block.columns or b not in block.columns:
        return block
    first = np.array(block.columns[a].values, copy=True)
    second = np.array(block.columns[b].values, copy=True)
    for row in rows:
        first[row], second[row] = second[row], first[row]
    columns = dict(block.columns)
    columns[a] = block.columns[a].model_copy(update={"values": first})
    columns[b] = block.columns[b].model_copy(update={"values": second})
    return block.model_copy(update={"columns": columns})


def _renamed(block: BlockModel, old: str, new: str, where: str) -> BlockModel:
    if new in block.columns:
        raise V1Refusal(f"{where} holds both {old!r} and {new!r}")
    columns = {new if name == old else name: column for name, column in block.columns.items()}
    return block.model_copy(update={"columns": columns})


def _strings(column: ColumnModel | None, row: int) -> str | None:
    if column is None or column.dtype != "string" or not _valid(column, row):
        return None
    return str(column.values[row])


class V1Upgrade:
    """The conversion of one version-1 store, from its ``forcefield`` section
    as stored (``document`` and ``tables``; both ``None`` when the store has
    none)."""

    def __init__(
        self,
        document: dict[str, Any] | None = None,
        tables: dict[str, BlockModel] | None = None,
    ) -> None:
        self.unit: str | None = "radian"
        self.tables: list[tuple[str, str, set[str]]] = []
        if document is None:
            return
        units = document.get("units") if isinstance(document.get("units"), dict) else {}
        stated = units.get("angle")
        preset = units.get("preset") if units.get("preset") in UNIT_PRESETS else None
        if stated is not None:
            if stated not in _ANGLE_UNITS:
                raise V1Refusal(
                    f"units.angle {stated!r}: this reader converts the radian and the degree"
                )
            self.unit = _ANGLE_UNITS[stated]
            if preset is not None and self.unit != "radian":
                raise V1Refusal(
                    f"units.angle {stated!r} disagrees with preset {preset!r}, whose "
                    "version-1 angle is the radian"
                )
        elif preset is None:
            self.unit = None
        for entry in document.get("styles") or []:
            category, style = entry.get("category"), entry.get("style")
            table = (tables or {}).get(style_block_name(category, style))
            names = set()
            if table is not None and "name" in table.columns:
                names = {str(name) for name in table.columns["name"].values}
            self.tables.append((category, style, names))

    # -- the section -----------------------------------------------------------

    def forcefield(
        self, document: dict[str, Any], tables: dict[str, BlockModel]
    ) -> tuple[dict[str, Any], dict[str, BlockModel]]:
        """The version-2 document and tables of the version-1 section."""
        document = dict(document)
        if self.unit is not None and isinstance(document.get("units"), dict):
            document["units"] = {**document["units"], "angle": "degree"}
        tables = dict(tables)
        styles = []
        for entry in document.get("styles") or []:
            entry = dict(entry)
            category, style = entry["category"], entry["style"]
            block = style_block_name(category, style)
            rule = _rule(category, style)
            renamed_from = None
            if rule == "renamed":
                new = _version2_style(category, style)
                target = style_block_name(category, new)
                if target in tables:
                    raise V1Refusal(
                        f"{category}/{style} is {category}/{new}, which the force field also holds"
                    )
                renamed_from, style, block = block, new, target
                rule = _rule(category, style)
                if renamed_from in tables:
                    tables = {
                        (target if name == renamed_from else name): table
                        for name, table in tables.items()
                    }
            table = tables.get(block)
            has_params = bool(entry.get("params")) or (
                table is not None
                and any(
                    name != "name"
                    and name not in ENDPOINT_COLUMNS
                    and name not in ANNOTATION_COLUMNS
                    for name in table.columns
                )
            )
            if rule == "refused":
                raise V1Refusal(f"{category}/{style}: {_PAIR14}")
            if rule == "unknown" and (has_params or entry.get("expression") is not None):
                raise V1Refusal(
                    f"{category}/{style} is no style this reader knows; its angle values and "
                    "per-angle constants cannot be told apart from its other numbers"
                )
            if rule == "converted":
                if entry.get("expression") is not None:
                    raise V1Refusal(
                        f"{category}/{style} carries an expression in version 1's meaning of "
                        "its parameters"
                    )
                if table is not None:
                    tables[block] = self._table(category, style, table)
            entry["style"] = style
            styles.append(entry)
        if "styles" in document:
            document["styles"] = styles
        return document, tables

    def _table(self, category: str, style: str, table: BlockModel) -> BlockModel:
        rows = list(range(table.count))
        for column in list(table.columns):
            conv = _column_conv(category, style, column)
            if conv is None:
                continue
            if conv[0] == "rename":
                table = _renamed(table, column, conv[1], f"{category}/{style}")
            else:
                columns = dict(table.columns)
                columns[column] = _converted(table.columns[column], conv, self.unit, rows)
                table = table.model_copy(update={"columns": columns})
        if (category, style) in _CENTRE_SECOND:
            table = _swapped(table, "itom", "jtom", rows)
        return table

    # -- frames ----------------------------------------------------------------

    def frame(self, frame: FrameModel) -> FrameModel:
        """The version-2 form of a version-1 frame: its relation blocks."""
        blocks = dict(frame.blocks)
        for name, category in (
            ("bonds", "bond"),
            ("angles", "angle"),
            ("dihedrals", "dihedral"),
            ("impropers", "improper"),
            ("drudes", "drude"),
            ("constraints", "constraint"),
        ):
            if name in blocks:
                blocks[name] = self._relation(name, category, blocks[name])
        return frame.model_copy(update={"blocks": blocks})

    def trajectory(self, trajectory: TrajectoryModel) -> TrajectoryModel:
        """Every frame of a version-1 trajectory, converted."""
        return trajectory.model_copy(
            update={"frames": [self.frame(frame) for frame in trajectory.frames]}
        )

    def _resolve(self, category: str, style: str | None, name: str | None) -> list[str]:
        if style is not None:
            return [style]
        return [s for c, s, names in self.tables if c == category and name in names]

    def _effective(self, category: str, style: str, column: str) -> Conv | None:
        conv = (
            _column_conv(category, style, column) if _rule(category, style) == "converted" else None
        )
        # A constant per radian under a radian unit is no conversion at all.
        if (
            conv is not None
            and conv[0] == "scale"
            and not conv[1]
            and (conv[2] == 0 or self.unit != "degree")
        ):
            return None
        return conv

    def _relation(self, block_name: str, category: str, block: BlockModel) -> BlockModel:
        resolved = [
            [
                _version2_style(category, s)
                for s in self._resolve(
                    category,
                    _strings(block.columns.get("style"), row),
                    _strings(block.columns.get("type"), row),
                )
            ]
            for row in range(block.count)
        ]
        for column in list(block.columns):
            if column in {"type", "type_id", "style"} or column.startswith("atom"):
                continue
            groups: dict[Conv, list[int]] = {}
            for row, styles in enumerate(resolved):
                if not _valid(block.columns[column], row):
                    continue
                if _is_angle_value(column):
                    conv: Conv | None = ("angle",)
                else:
                    convs = [self._effective(category, s, column) for s in styles]
                    if any(c != convs[0] for c in convs):
                        raise V1Refusal(
                            f"{block_name} row {row}: its styles {styles} read column "
                            f"{column!r} differently"
                        )
                    conv = convs[0] if convs else None
                if conv is None:
                    continue
                if conv[0] == "rename":
                    raise V1Refusal(
                        f"{block_name} column {column!r} is {conv[1]!r} in version 2; a "
                        "relation column is not renamed row by row"
                    )
                groups.setdefault(conv, []).append(row)
            for conv, rows in groups.items():
                columns = dict(block.columns)
                columns[column] = _converted(block.columns[column], conv, self.unit, rows)
                block = block.model_copy(update={"columns": columns})

        if "style" in block.columns and block.columns["style"].dtype == "string":
            styles = np.array(
                [_version2_style(category, str(s)) for s in block.columns["style"].values]
            )
            if not np.array_equal(styles, block.columns["style"].values):
                columns = dict(block.columns)
                columns["style"] = block.columns["style"].model_copy(update={"values": styles})
                block = block.model_copy(update={"columns": columns})

        if category == "improper":
            centre_second = []
            for row, styles in enumerate(resolved):
                if not styles:
                    swaps = any(
                        key in block.columns and _valid(block.columns[key], row)
                        for key in ("koop", "K")
                    )
                else:
                    flags = [(category, s) in _CENTRE_SECOND for s in styles]
                    if any(flags) and not all(flags):
                        raise V1Refusal(
                            f"{block_name} row {row}: its styles {styles} put the centre in "
                            "different places"
                        )
                    swaps = any(flags)
                if swaps:
                    centre_second.append(row)
            if centre_second:
                block = _swapped(block, "atomi", "atomj", centre_second)
        return block
