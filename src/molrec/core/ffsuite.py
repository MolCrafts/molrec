"""What the ``forcefield`` section is pinned down by (``docs/spec/forcefield.md``).

The positive cases are round trips of the section: its document, every style
table at its block name, absent parameters as nulls, units exactly as stated.
The negative cases are the chapter's refusals on read: the codec lays a
malformed section down and the reader must refuse it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, ClassVar

import numpy as np

from molrec.case import Case
from molrec.core.model import (
    ENDPOINT_COLUMNS,
    BlockModel,
    ColumnModel,
    ForceFieldModel,
    ForceFieldSourceModel,
    ForceFieldUnitsModel,
    SpecialBondsModel,
    StyleModel,
)
from molrec.registry import REGISTRY
from molrec.suite import Suite


def _strings(values: list[str], validity: list[bool] | None = None) -> ColumnModel:
    array = np.array(values, dtype=str) if values else np.array([], dtype="<U1")
    return ColumnModel(
        dtype="string",
        shape=(len(values),),
        values=array,
        validity=None if validity is None else np.array(validity),
    )


def _floats(values: list[float], validity: list[bool] | None = None) -> ColumnModel:
    return ColumnModel(
        dtype="f64",
        shape=(len(values),),
        values=np.array(values, dtype="float64"),
        validity=None if validity is None else np.array(validity),
    )


def _grids(values: np.ndarray) -> ColumnModel:
    """An ``f64[T, ...]`` column: one array per row."""
    array = np.asarray(values, dtype="float64")
    return ColumnModel(dtype="f64", shape=array.shape, values=array)


def cmap_grid(n: int, scale: float) -> np.ndarray:
    """An ``n x n`` correction grid whose values are no short decimals."""
    return scale * np.arange(n * n, dtype="float64").reshape(n, n) / 3.0 - 0.7


def cmap(grids: np.ndarray) -> tuple[StyleModel, BlockModel]:
    """A ``cmap charmm`` style of one row per grid, ``cmap0``, ``cmap1``, ...:
    row ``r`` names the backbone types C-NH1-CT1-C-NH1-C from position ``r``."""
    backbone = ["C", "NH1", "CT1"] * 3
    count = len(grids)
    endpoints = {
        column: [backbone[row + i] for row in range(count)]
        for i, column in enumerate(ENDPOINT_COLUMNS)
    }
    names = [f"cmap{row}" for row in range(count)]
    return style("cmap", "charmm"), table(names, **endpoints, grid=_grids(grids))


def no_rows(arity: int) -> BlockModel:
    """The table of a style with no rows (charges from atoms, or per-instance)."""
    return table([], **{column: _strings([]) for column in ENDPOINT_COLUMNS[:arity]})


def table(names: list[str], **columns: ColumnModel | list[Any]) -> BlockModel:
    """A style table: ``name`` plus columns; a list of str is a string column,
    any other list an ``f64`` one."""
    built = {"name": _strings(names)}
    for key, column in columns.items():
        if isinstance(column, ColumnModel):
            built[key] = column
        elif column and all(isinstance(value, str) for value in column):
            built[key] = _strings(column)
        else:
            built[key] = _floats(column)
    return BlockModel(count=len(names), columns=built)


def forcefield(styles: list[tuple[StyleModel, BlockModel]], **document: Any) -> ForceFieldModel:
    """A force field of ``(style, table)`` pairs; ``document`` defaults to a
    ``real``-unit field named ``test``."""
    document.setdefault("name", "test")
    document.setdefault("units", ForceFieldUnitsModel(preset="real"))
    return ForceFieldModel(
        **document,
        styles=[style for style, _ in styles],
        tables={style.block: rows for style, rows in styles},
    )


def style(category: str, name: str, **fields: Any) -> StyleModel:
    return StyleModel(category=category, style=name, **fields)


def atoms(names: list[str], **columns: ColumnModel | list[Any]) -> tuple[StyleModel, BlockModel]:
    return style("atom", "full"), table(names, **columns)


def _unvalidated(model: ForceFieldModel, **changes: Any) -> ForceFieldModel:
    """``model`` with ``changes``, built around the validators."""
    fields = {name: getattr(model, name) for name in type(model).model_fields}
    fields.update(changes)
    return ForceFieldModel.model_construct(**fields)


def round_trip_forcefield() -> ForceFieldModel:
    """The ``ff-round-trip`` field: every common category, two pair styles,
    in the registry's conventions (LAMMPS's un-halved ``K``, degrees)."""
    types = ["CT", "HC", "OH"]
    return forcefield(
        [
            atoms(
                types,
                mass=[12.011, 1.008, 15.999],
                charge=[-0.18, 0.06, -0.683],
                element=["C", "H", "O"],
                **{"class": ["CT", "HC", "OH"]},
            ),
            (
                style("bond", "harmonic"),
                table(
                    ["CT-HC", "CT-OH"],
                    itom=["CT", "CT"],
                    jtom=["HC", "OH"],
                    k=[340.0, 320.0],
                    r0=[1.09, 1.41],
                ),
            ),
            (
                style("angle", "harmonic"),
                table(
                    ["HC-CT-HC"], itom=["HC"], jtom=["CT"], ktom=["HC"], k=[33.0], theta0=[107.8]
                ),
            ),
            (
                style("dihedral", "periodic"),
                table(
                    ["HC-CT-OH-HO"],
                    itom=["HC"],
                    jtom=["CT"],
                    ktom=["OH"],
                    ltom=["HO"],
                    k1=[0.0],
                    periodicity1=[1.0],
                    phase1=[0.0],
                    k2=[0.45],
                    periodicity2=[3.0],
                    phase2=[180.0],
                ),
            ),
            (
                style("improper", "harmonic"),
                table(
                    ["CT-HC-HC-OH"],
                    itom=["CT"],
                    jtom=["HC"],
                    ktom=["HC"],
                    ltom=["OH"],
                    k=[10.5],
                    chi0=[35.26],
                ),
            ),
            (
                style("pair", "lj/cut", params={"mixing": "geometric", "cutoff": 10.0}),
                table(
                    ["CT", "HC", "OH", "CT-OH"],
                    itom=["CT", "HC", "OH", "CT"],
                    jtom=["CT", "HC", "OH", "OH"],
                    epsilon=[0.066, 0.03, 0.17, 0.1],
                    sigma=[3.5, 2.5, 3.12, 3.3],
                ),
            ),
            (style("pair", "coul/long/pme", params={"cutoff": 10.0}), no_rows(2)),
        ],
        special_bonds=SpecialBondsModel(lj=(0.0, 0.0, 0.5), coul=(0.0, 0.0, 0.8333)),
        source=ForceFieldSourceModel(format="openmm-xml", sha256="0" * 63 + "1"),
    )


@REGISTRY.suite
class ForceFieldSuite(Suite):
    module: ClassVar[str] = "forcefield"
    model_type: ClassVar[type[ForceFieldModel]] = ForceFieldModel

    def cases(self) -> Iterable[Case]:
        yield from self._positive_cases()
        yield from self._refusals()

    def _positive_cases(self) -> Iterable[Case]:
        yield Case(
            id="ff-minimal",
            exercises="a name, units and one atom style round-trip",
            model=forcefield([atoms(["CT", "HC"], mass=[12.011, 1.008])], name="minimal"),
        )

        yield Case(
            id="ff-round-trip",
            exercises="atom, bond, angle, multi-term dihedral, improper, two pair styles with "
            "mixing, special_bonds and source round-trip exactly",
            model=round_trip_forcefield(),
        )

        dihedral = style("dihedral", "periodic")
        yield Case(
            id="ff-wildcard-endpoints",
            exercises="the empty string is the wildcard endpoint, and it survives",
            model=forcefield(
                [
                    atoms(["CT"]),
                    (
                        dihedral,
                        table(
                            ["X-CT-CT-X"],
                            itom=[""],
                            jtom=["CT"],
                            ktom=["CT"],
                            ltom=[""],
                            k=[0.15],
                            periodicity=[3.0],
                            phase=[0.0],
                        ),
                    ),
                ]
            ),
        )

        yield Case(
            id="ff-absent-params",
            exercises="a parameter some rows lack is null there (a validity mask), not filled",
            model=forcefield(
                [
                    (
                        dihedral,
                        table(
                            ["a", "b"],
                            itom=["CT", "HC"],
                            jtom=["CT", "CT"],
                            ktom=["CT", "CT"],
                            ltom=["CT", "HC"],
                            k1=[0.2, 0.15],
                            periodicity1=[1.0, 3.0],
                            phase1=[0.0, 0.0],
                            k2=_floats([0.25, 0.0], [True, False]),
                            periodicity2=_floats([2.0, 0.0], [True, False]),
                            phase2=_floats([180.0, 0.0], [True, False]),
                        ),
                    )
                ]
            ),
        )

        yield Case(
            id="ff-string-params",
            exercises="class, element, smarts and a non-canonical string parameter survive",
            model=forcefield(
                [
                    atoms(
                        ["opls_135", "opls_140"],
                        element=["C", "H"],
                        smarts=["[C;X4](C)(H)(H)H", "H[C;X4]"],
                        ptype=["A", "A"],
                        overrides=_strings(["", "opls_135"], [False, True]),
                        **{"class": ["CT", "HC"]},
                    )
                ]
            ),
        )

        coul = style("pair", "lj/cut/coul/long", params={"cutoff": 12.0})
        yield Case(
            id="ff-style-name-encoding",
            exercises="the style lj/cut/coul/long lives at the block pair.lj%2Fcut%2Fcoul%2Flong",
            model=forcefield(
                [(coul, table(["CT"], itom=["CT"], jtom=["CT"], epsilon=[0.066], sigma=[3.5]))]
            ),
        )

        yield Case(
            id="ff-pair-cross-rows",
            exercises="a cross row (itom != jtom) under a name that is no endpoint spelling, and "
            "a reversed restatement of it with equal parameters, survive beside the self rows",
            model=forcefield(
                [
                    atoms(["A", "B"], mass=[12.0, 16.0]),
                    (
                        style("pair", "lj/cut", params={"mixing": "arithmetic"}),
                        table(
                            ["A", "B", "nbfix-1", "nbfix-1-restated"],
                            itom=["A", "B", "B", "A"],
                            jtom=["A", "B", "A", "B"],
                            epsilon=[0.1, 0.4, 0.9, 0.9],
                            sigma=[3.0, 3.6, 2.0, 2.0],
                        ),
                    ),
                ]
            ),
        )

        yield Case(
            id="ff-hybrid-styles",
            exercises="two bond styles of one category both define CT-HC",
            model=forcefield(
                [
                    (
                        style("bond", "harmonic"),
                        table(["CT-HC"], itom=["CT"], jtom=["HC"], k=[340.0], r0=[1.09]),
                    ),
                    (
                        style("bond", "morse"),
                        table(
                            ["CT-HC"], itom=["CT"], jtom=["HC"], d0=[105.0], alpha=[1.8], r0=[1.09]
                        ),
                    ),
                ]
            ),
        )

        yield Case(
            id="ff-per-instance-style",
            exercises="a style with a table of no rows declares a per-instance style (its "
            "parameters are relation columns)",
            model=forcefield([(style("bond", "mmff_bond"), no_rows(2))]),
        )

        yield Case(
            id="ff-unknown-style-with-expression",
            exercises="an unregistered style and its expression are preserved verbatim",
            model=forcefield(
                [
                    (
                        style(
                            "bond",
                            "fene",
                            expression="-0.5*K*R0^2*log(1-(r/R0)^2) + "
                            "4*epsilon*((sigma/r)^12-(sigma/r)^6) + epsilon",
                        ),
                        table(
                            ["b"],
                            itom=["B"],
                            jtom=["B"],
                            K=[30.0],
                            R0=[1.5],
                            epsilon=[1.0],
                            sigma=[1.0],
                        ),
                    )
                ],
                units=ForceFieldUnitsModel(preset="lj"),
            ),
        )

        yield Case(
            id="ff-unknown-category",
            exercises="a category outside the chapter's table is preserved; its arity is its "
            "endpoint prefix",
            model=forcefield(
                [
                    (
                        style("cross_term", "example"),
                        table(
                            ["C-N-CA-C"],
                            itom=["C"],
                            jtom=["NH1"],
                            ktom=["CT1"],
                            ltom=["C"],
                            coefficients=["0.1,0.2"],
                        ),
                    )
                ]
            ),
        )

        yield Case(
            id="ff-cmap-grid",
            exercises="a cmap table names five endpoints, itom..mtom, and its f64[T, N, N] grid "
            "comes back bit for bit",
            model=forcefield(
                [
                    atoms(["C", "NH1", "CT1"], mass=[12.011, 14.007, 12.011]),
                    cmap(np.stack([cmap_grid(24, 0.1), cmap_grid(24, -0.35)])),
                ]
            ),
        )

        yield Case(
            id="ff-angle-charmm",
            exercises="angle charmm (LAMMPS's Urey-Bradley angle: k, theta0 in degrees, k_ub, "
            "r_ub) beside dihedral charmm with its 1-4 weight w",
            model=forcefield(
                [
                    atoms(["CT1", "HA", "NH1"], mass=[12.011, 1.008, 14.007]),
                    (
                        style("angle", "charmm"),
                        table(
                            ["HA-CT1-HA", "NH1-CT1-HA"],
                            itom=["HA", "NH1"],
                            jtom=["CT1", "CT1"],
                            ktom=["HA", "HA"],
                            k=[35.5, 48.0],
                            theta0=[108.4, 108.0],
                            k_ub=_floats([5.4, 0.0], [True, False]),
                            r_ub=_floats([1.802, 0.0], [True, False]),
                        ),
                    ),
                    (
                        style("dihedral", "charmm"),
                        table(
                            ["X-CT1-NH1-X", "HA-CT1-CT1-HA"],
                            itom=["", "HA"],
                            jtom=["CT1", "CT1"],
                            ktom=["NH1", "CT1"],
                            ltom=["", "HA"],
                            k=[0.0, 0.2],
                            periodicity=[1.0, 3.0],
                            phase=[0.0, 180.0],
                            w=[1.0, 0.5],
                        ),
                    ),
                ],
                special_bonds=SpecialBondsModel(lj=(0.0, 0.0, 0.0), coul=(0.0, 0.0, 0.0)),
            ),
        )

        yield Case(
            id="ff-pair-lj-charmm",
            exercises="pair lj/charmm: self rows that carry or leave null epsilon14/sigma14, and "
            "a cross row that carries only them (a GROMACS [ pairtypes ] row)",
            model=forcefield(
                [
                    atoms(["CT1", "HA", "NH1"], mass=[12.011, 1.008, 14.007]),
                    (
                        style("pair", "lj/charmm", params={"mixing": "arithmetic", "cutoff": 12.0}),
                        table(
                            ["CT1", "HA", "NH1", "CT1-NH1-14"],
                            itom=["CT1", "HA", "NH1", "CT1"],
                            jtom=["CT1", "HA", "NH1", "NH1"],
                            epsilon=_floats([0.02, 0.022, 0.2, 0.0], [True, True, True, False]),
                            sigma=_floats([4.0538, 2.3876, 3.2963, 0.0], [True, True, True, False]),
                            epsilon14=_floats([0.01, 0.0, 0.0, 0.0447], [True, False, False, True]),
                            sigma14=_floats([3.3854, 0.0, 0.0, 3.3409], [True, False, False, True]),
                        ),
                    ),
                    (style("pair", "coul/cut", params={"cutoff": 12.0}), no_rows(2)),
                ],
                special_bonds=SpecialBondsModel(lj=(0.0, 0.0, 0.0), coul=(0.0, 0.0, 0.0)),
            ),
        )

        yield Case(
            id="ff-units-preserved",
            exercises="numbers in nm and kJ/mol come back bit for bit, never converted",
            model=forcefield(
                [
                    (
                        style("bond", "harmonic"),
                        table(["CT-HC"], itom=["CT"], jtom=["HC"], r0=[0.1090], k=[142256.0]),
                    )
                ],
                units=ForceFieldUnitsModel(length="nm", energy="kJ/mol", angle="degree"),
            ),
        )

        yield Case(
            id="ff-lj-preset",
            exercises="reduced units: preset lj with no quantity strings",
            model=forcefield(
                [
                    (
                        style("pair", "lj/cut"),
                        table(["A"], itom=["A"], jtom=["A"], epsilon=[1.0], sigma=[1.0]),
                    )
                ],
                units=ForceFieldUnitsModel(preset="lj"),
            ),
        )

        yield Case(
            id="ff-smirks-keyed",
            exercises="a smirks-keyed table carries no endpoint columns; each row's smirks "
            "assigns it",
            model=forcefield(
                [
                    (
                        style("bond", "harmonic", endpoint_key="smirks"),
                        table(
                            ["b1", "b2"],
                            smirks=["[#6X4:1]-[#6X4:2]", "[#6X4:1]-[#1:2]"],
                            r0=[1.527, 1.09],
                            k=[310.0, 370.0],
                        ),
                    )
                ],
                units=ForceFieldUnitsModel(length="angstrom", energy="kcal/mol", angle="degree"),
                source=ForceFieldSourceModel(format="offxml", uri="openff-2.1.0.offxml"),
            ),
        )

        yield Case(
            id="ff-without-special-bonds",
            exercises="no special_bonds reads back as none -- absence is not a default",
            model=forcefield([atoms(["A"], mass=[1.0])]),
        )

        extended = forcefield([atoms(["A"], mass=[1.0])], aromaticity_model="OEAroModel_MDL")
        yield Case(
            id="ff-document-keys-preserved",
            exercises="a document key the chapter does not name is preserved",
            model=extended.model_copy(
                update={
                    "tables": {
                        **extended.tables,
                        "notes.free%20text": table(["n"], text=["kept as unknown content"]),
                    }
                }
            ),
        )

    def _refusals(self) -> Iterable[Case]:
        base = forcefield(
            [
                atoms(["CT", "HC"], mass=[12.011, 1.008]),
                (
                    style("bond", "harmonic"),
                    table(["CT-HC"], itom=["CT"], jtom=["HC"], k=[340.0], r0=[1.09]),
                ),
            ]
        )
        bond = base.styles[1]
        bonds = base.tables[bond.block]

        def broken_table(**columns: ColumnModel) -> dict[str, BlockModel]:
            rows = next(iter(columns.values())).count
            return {
                **base.tables,
                bond.block: BlockModel.model_construct(
                    count=rows, columns=columns, structural_shape=None, targets=None
                ),
            }

        lj = style("pair", "lj/cut")
        cmap_style, cmap_table = cmap(np.zeros((1, 2, 2)))

        def _cmap_rows(grids: np.ndarray) -> BlockModel:
            return BlockModel.model_construct(
                count=cmap_table.count,
                columns={**cmap_table.columns, "grid": _grids(grids)},
                structural_shape=None,
                targets=None,
            )

        nonfinite = cmap_grid(2, 1.0)[None].copy()
        nonfinite[0, 1, 0] = np.nan
        refusals: list[tuple[str, str, ForceFieldModel]] = [
            (
                "reject-ff-no-units",
                "units states a preset or at least one quantity",
                _unvalidated(base, units=ForceFieldUnitsModel.model_construct()),
            ),
            (
                "reject-ff-units-conflict",
                "a quantity beside a preset is the preset's own: real with kJ/mol is refused",
                _unvalidated(
                    base,
                    units=ForceFieldUnitsModel.model_construct(preset="real", energy="kJ/mol"),
                ),
            ),
            (
                "reject-ff-radian-angle-unit",
                "every preset's angle is the degree: angle radian beside preset real is refused "
                "(a section in the radian convention says so, and is not read as degrees)",
                _unvalidated(
                    base,
                    units=ForceFieldUnitsModel.model_construct(
                        preset="real", length="angstrom", energy="kcal/mol", angle="radian"
                    ),
                ),
            ),
            (
                "reject-ff-duplicate-style",
                "a (category, style) pair appears once",
                _unvalidated(base, styles=[*base.styles, bond]),
            ),
            (
                "reject-ff-missing-table",
                "every style has its table",
                _unvalidated(
                    base, tables={k: v for k, v in base.tables.items() if k != bond.block}
                ),
            ),
            (
                "reject-ff-duplicate-type-name",
                "type names are unique within a table",
                _unvalidated(
                    base,
                    tables=broken_table(
                        name=_strings(["CT-HC", "CT-HC"]),
                        itom=_strings(["CT", "CT"]),
                        jtom=_strings(["HC", "HC"]),
                    ),
                ),
            ),
            (
                "reject-ff-wrong-arity",
                "a bond row names exactly itom and jtom",
                _unvalidated(
                    base,
                    tables=broken_table(
                        name=_strings(["CT-HC"]), itom=_strings(["CT"]), k=_floats([340.0])
                    ),
                ),
            ),
            (
                "reject-ff-param-dtype",
                "a parameter is f64 or string; an i64 periodicity is refused",
                _unvalidated(
                    base,
                    tables=broken_table(
                        **bonds.columns,
                        n=ColumnModel(dtype="i64", shape=(1,), values=np.array([3])),
                    ),
                ),
            ),
            (
                "reject-ff-null-name",
                "a row's name is never null",
                _unvalidated(
                    base,
                    tables=broken_table(**{**bonds.columns, "name": _strings(["CT-HC"], [False])}),
                ),
            ),
            (
                "reject-ff-class-key-without-class",
                "a class-keyed style links through atom classes: every atom table carries class",
                _unvalidated(
                    base,
                    styles=[base.styles[0], bond.model_copy(update={"endpoint_key": "class"})],
                ),
            ),
            (
                "reject-ff-pair-conflict",
                "a pair table prices each unordered {itom, jtom} once: B-A restating A-B with "
                "another epsilon is refused",
                _unvalidated(
                    base,
                    styles=[*base.styles, lj],
                    tables={
                        **base.tables,
                        lj.block: table(
                            ["A", "B", "A-B", "B-A"],
                            itom=["A", "B", "A", "B"],
                            jtom=["A", "B", "B", "A"],
                            epsilon=[0.1, 0.4, 0.9, 0.8],
                            sigma=[3.0, 3.6, 2.0, 2.0],
                        ),
                    },
                ),
            ),
            (
                "reject-ff-cmap-grid-shape",
                "a cmap grid is f64[T, N, N]: a non-square f64[T, 3, 4] grid is refused",
                _unvalidated(
                    base,
                    styles=[*base.styles, cmap_style],
                    tables={**base.tables, cmap_style.block: _cmap_rows(np.zeros((1, 3, 4)))},
                ),
            ),
            (
                "reject-ff-cmap-grid-nonfinite",
                "every value of a non-null cmap grid row is finite: a NaN is refused",
                _unvalidated(
                    base,
                    styles=[*base.styles, cmap_style],
                    tables={**base.tables, cmap_style.block: _cmap_rows(nonfinite)},
                ),
            ),
            (
                "reject-ff-grid-outside-cmap",
                "only a cmap table's grid has trailing axes: a bond table's f64[T, 2, 2] grid "
                "is refused",
                _unvalidated(
                    base,
                    tables=broken_table(**bonds.columns, grid=_grids(np.zeros((1, 2, 2)))),
                ),
            ),
        ]
        for case_id, why, model in refusals:
            yield Case(id=case_id, exercises=why, expect_violation="bad_forcefield", model=model)


__all__ = [
    "ForceFieldSuite",
    "cmap",
    "cmap_grid",
    "forcefield",
    "no_rows",
    "round_trip_forcefield",
    "style",
    "table",
]
