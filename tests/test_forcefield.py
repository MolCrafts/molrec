"""The forcefield section's own rules: block names, units, the document, and
the layout the reference codec writes (``docs/spec/forcefield.md``)."""

from __future__ import annotations

import numpy as np
import pytest
import zarr
from pydantic import ValidationError

from molrec.core.bindings.zarr import ZarrForceFieldCodec, ZarrForceFieldStore
from molrec.core.ffsuite import (
    atoms,
    cmap,
    cmap_grid,
    forcefield,
    round_trip_forcefield,
    style,
    table,
)
from molrec.core.model import (
    UNIT_PRESETS,
    UNIT_QUANTITIES,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    ForceFieldModel,
    ForceFieldUnitsModel,
    MetaModel,
    RecordModel,
    StyleModel,
    parse_style_block_name,
    style_block_name,
)


class TestBlockNames:
    @pytest.mark.parametrize(
        ("category", "style_name", "block"),
        [
            ("bond", "harmonic", "bond.harmonic"),
            ("pair", "lj/cut/coul/long", "pair.lj%2Fcut%2Fcoul%2Flong"),
            ("dihedral", "multi/harmonic", "dihedral.multi%2Fharmonic"),
            ("pair", "lj.cut", "pair.lj%2Ecut"),
            ("bond", "fene-x_2", "bond.fene-x_2"),
            ("bond", "Å", "bond.%C3%85"),
        ],
    )
    def test_the_name_is_a_function_of_category_and_style(
        self, category: str, style_name: str, block: str
    ) -> None:
        assert style_block_name(category, style_name) == block
        assert parse_style_block_name(block) == (category, style_name)

    @pytest.mark.parametrize(
        "bad", ["bond", ".harmonic", "pair.lj/cut", "pair.lj%2fcut", "pair.lj%2", "bond.%68armonic"]
    )
    def test_any_other_spelling_is_refused(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_style_block_name(bad)


class TestDocument:
    def test_units_state_something(self) -> None:
        with pytest.raises(ValidationError, match="preset or at least one quantity"):
            ForceFieldUnitsModel()
        ForceFieldUnitsModel(preset="lj")
        ForceFieldUnitsModel(length="nm")

    def test_a_quantity_beside_a_preset_is_the_presets(self) -> None:
        ForceFieldUnitsModel(preset="real", energy="kcal/mol", angle="degree")
        with pytest.raises(ValidationError, match="disagrees"):
            ForceFieldUnitsModel(preset="real", energy="kJ/mol")
        with pytest.raises(ValidationError, match="disagrees"):
            ForceFieldUnitsModel(preset="lj", length="angstrom")

    @pytest.mark.parametrize("preset", sorted(UNIT_PRESETS))
    def test_every_preset_states_angle_values_in_degrees(self, preset: str) -> None:
        ForceFieldUnitsModel(preset=preset, angle="degree")
        with pytest.raises(ValidationError, match="angle 'radian' disagrees"):
            ForceFieldUnitsModel(preset=preset, angle="radian")

    def test_without_a_preset_the_angle_is_as_stated(self) -> None:
        ForceFieldUnitsModel(length="nm", energy="kJ/mol", angle="degree")

    def test_reserved_style_params(self) -> None:
        StyleModel(category="pair", style="lj/cut", params={"mixing": "sixthpower"})
        with pytest.raises(ValidationError, match="mixing"):
            StyleModel(category="pair", style="lj/cut", params={"mixing": "lorentz"})
        with pytest.raises(ValidationError, match="special"):
            StyleModel(category="pair", style="x", params={"special": "both"})

    def test_the_document_is_every_field_but_the_tables(self) -> None:
        document = round_trip_forcefield().document()
        assert "tables" not in document
        assert document["special_bonds"] == {"lj": [0.0, 0.0, 0.5], "coul": [0.0, 0.0, 0.8333]}
        # A style writes params / endpoint_key only when they say something.
        assert document["styles"][0] == {"category": "atom", "style": "full"}
        assert document["styles"][5]["params"] == {"mixing": "geometric", "cutoff": 10.0}

    def test_a_table_no_style_names_is_kept(self) -> None:
        model = forcefield([atoms(["A"])])
        extra = model.model_copy(update={"tables": {**model.tables, "x.y": table(["n"])}})
        assert set(type(model).model_validate(extra.model_dump()).tables) == {"atom.full", "x.y"}


class TestPlacement:
    def test_a_forcefield_is_a_record_on_its_own(self) -> None:
        RecordModel(meta=MetaModel(), forcefield=forcefield([atoms(["A"])]))

    def test_a_collection_record_carries_none_of_its_own(self) -> None:
        record = RecordModel(meta=MetaModel(), forcefield=forcefield([atoms(["A"])]))
        with pytest.raises(ValidationError, match="force field is the collection"):
            CollectionModel(meta=CollectionMetaModel(units={}), records=[record])


def test_the_tables_are_block_groups_at_their_names(tmp_path) -> None:
    model = forcefield(
        [(style("pair", "lj/cut/coul/long"), table(["A"], itom=["A"], jtom=["A"], epsilon=[1.0]))]
    )
    store = ZarrForceFieldStore(tmp_path / "ff.mrec")
    ZarrForceFieldCodec().write(model, store)
    root = zarr.open_group(store=store.path, mode="r")
    assert dict(root["meta"].attrs) == {}
    group = root["forcefield"]
    assert dict(group.attrs)["name"] == "test"
    assert [name for name, _ in group.groups()] == ["pair.lj%2Fcut%2Fcoul%2Flong"]
    assert ZarrForceFieldCodec().read(store) == model


def _nullable(values: list[float], validity: list[bool]) -> ColumnModel:
    return ColumnModel(
        dtype="f64", shape=(len(values),), values=np.array(values), validity=np.array(validity)
    )


class TestPairRows:
    """Rule 3 of linking: a pair table prices each unordered pair once."""

    @staticmethod
    def _pair(**columns) -> None:
        names = [f"r{i}" for i in range(len(columns["itom"]))]
        forcefield([(style("pair", "lj/cut"), table(names, **columns))])

    def test_a_cross_row_and_its_equal_restatements_are_one_row(self) -> None:
        self._pair(
            itom=["A", "B", "A", "B", "A"],
            jtom=["A", "B", "B", "A", "B"],
            epsilon=[0.1, 0.4, 0.9, 0.9, 0.9],
            sigma=[3.0, 3.6, 2.0, 2.0, 2.0],
        )

    @pytest.mark.parametrize(("itom", "jtom"), [(["A", "A"], ["B", "B"]), (["A", "B"], ["B", "A"])])
    def test_a_restatement_with_other_parameters_is_refused(
        self, itom: list[str], jtom: list[str]
    ) -> None:
        with pytest.raises(ValidationError, match=r"'r0' and 'r1' both price .* \['epsilon'\]"):
            self._pair(itom=itom, jtom=jtom, epsilon=[0.9, 0.8], sigma=[2.0, 2.0])

    def test_a_cross_row_may_leave_a_parameter_to_mixing(self) -> None:
        """A GROMACS [ pairtypes ] row: lj/charmm's 1-4 parameters only."""
        forcefield(
            [
                (
                    style("pair", "lj/charmm"),
                    table(
                        ["A", "A-B"],
                        itom=["A", "A"],
                        jtom=["A", "B"],
                        epsilon=_nullable([0.1, 0.0], [True, False]),
                        epsilon14=_nullable([0.0, 0.05], [False, True]),
                    ),
                )
            ]
        )

    def test_an_unknown_category_is_not_pair_resolved(self) -> None:
        """A category the contract does not define is preserved as given: it
        declares no arity and its rows are not resolved as pair rows, so two
        rows restating one unordered pair with other parameters stand."""
        rows = table(["r0", "r1"], itom=["A", "B"], jtom=["B", "A"], epsilon=[0.9, 0.8])
        model = forcefield([(style("x_pairs", "lj/cut"), rows)])
        assert model.styles[0].arity is None
        assert model.tables[model.styles[0].block] == rows

    def test_a_null_differs_from_a_value(self) -> None:
        with pytest.raises(ValidationError, match=r"differ in \['shift'\]"):
            self._pair(
                itom=["A", "B"],
                jtom=["B", "A"],
                epsilon=[0.9, 0.9],
                shift=_nullable([1.0, 0.0], [True, False]),
            )
        self._pair(itom=["A", "B"], jtom=["B", "A"], shift=_nullable([1.0, 2.0], [False, False]))

    def test_name_and_annotations_are_no_parameters(self) -> None:
        self._pair(itom=["A", "B"], jtom=["B", "A"], epsilon=[0.9, 0.9], desc=["NBFIX", "copy"])

    def test_other_categories_may_restate_endpoints(self) -> None:
        forcefield(
            [
                (
                    style("bond", "harmonic"),
                    table(["b1", "b2"], itom=["A", "B"], jtom=["B", "A"], k=[1.0, 2.0]),
                )
            ]
        )


def _grid_column(values: np.ndarray, **fields) -> ColumnModel:
    array = np.asarray(values)
    dtype = "string" if array.dtype.kind == "U" else "f64"
    return ColumnModel(dtype=dtype, shape=array.shape, values=array, **fields)


def _with_grid(grid: ColumnModel) -> ForceFieldModel:
    """A force field of one ``cmap`` table whose ``grid`` column is ``grid``."""
    cmap_style, rows = cmap(np.zeros((grid.count, 2, 2)))
    rows = rows.model_copy(update={"columns": {**rows.columns, "grid": grid}})
    return forcefield([(cmap_style, rows)])


class TestCmapGrid:
    """The trailing-axis exception: a ``cmap`` table's grid is ``f64[T, N, N]``."""

    @pytest.mark.parametrize("n", [2, 24])
    def test_a_square_grid_of_any_size_from_two(self, n: int) -> None:
        _with_grid(_grid_column(np.stack([cmap_grid(n, 0.1), cmap_grid(n, 0.2)])))

    @pytest.mark.parametrize(
        ("values", "why"),
        [
            (np.zeros((2, 3, 4)), "not square"),
            (np.zeros((2, 1, 1)), "N < 2"),
            (np.zeros((2, 4)), "one trailing axis"),
            (np.zeros(2), "no trailing axes"),
            (np.zeros((2, 2, 2, 2)), "three trailing axes"),
            (np.array(["24x24", "24x24"]), "a string"),
        ],
    )
    def test_a_malformed_grid_is_refused(self, values: np.ndarray, why: str) -> None:
        with pytest.raises(ValidationError, match="the cmap grid is f64"):
            _with_grid(_grid_column(values))

    def test_a_grid_declares_no_precision(self) -> None:
        with pytest.raises(ValidationError, match="with a declared precision"):
            _with_grid(_grid_column(np.zeros((2, 2, 2)), precision=0.5))

    def test_a_non_null_row_is_finite_and_a_null_one_is_not_read(self) -> None:
        values = np.zeros((2, 2, 2))
        values[1, 0, 1] = np.inf
        with pytest.raises(ValidationError, match="row 1 holds a non-finite value"):
            _with_grid(_grid_column(values))
        _with_grid(_grid_column(values, validity=np.array([True, False])))

    def test_another_cmap_column_is_any_array_parameter(self) -> None:
        cmap_style, rows = cmap(np.zeros((2, 2, 2)))
        other = _grid_column(np.zeros((2, 3)))
        rows = rows.model_copy(update={"columns": {**rows.columns, "other": other}})
        forcefield([(cmap_style, rows)])

    def test_a_cmap_row_names_five_endpoints(self) -> None:
        cmap_style, rows = cmap(np.zeros((1, 2, 2)))
        rows = rows.model_copy(
            update={"columns": {k: v for k, v in rows.columns.items() if k != "mtom"}}
        )
        with pytest.raises(ValidationError, match="a cmap row names endpoints"):
            forcefield([(cmap_style, rows)])

    def test_an_unknown_category_may_name_mtom_as_its_fifth_endpoint(self) -> None:
        ends = {column: ["C"] for column in ("itom", "jtom", "ktom", "ltom", "mtom")}
        forcefield([(style("cross_term", "example"), table(["c"], **ends))])
        del ends["ltom"]
        with pytest.raises(ValidationError, match="no prefix of itom..mtom"):
            forcefield([(style("cross_term", "example"), table(["c"], **ends))])

    def test_the_grid_round_trips_through_zarr_bit_for_bit(self, tmp_path) -> None:
        grids = np.stack([cmap_grid(24, 0.1), cmap_grid(24, -0.35)])
        model = forcefield([cmap(grids)])
        store = ZarrForceFieldStore(tmp_path / "cmap.mrec")
        ZarrForceFieldCodec().write(model, store)
        array = zarr.open_group(store=store.path, mode="r")["forcefield/cmap.charmm/grid"]
        assert array.shape == (2, 24, 24)
        back = ZarrForceFieldCodec().read(store)
        assert back == model
        assert back.tables["cmap.charmm"].columns["grid"].values.tobytes() == grids.tobytes()


class TestArrayParams:
    """Any parameter may be an ``f64[T, S...]`` column of one shape."""

    @staticmethod
    def _bond(column: ColumnModel, category: str = "bond") -> ForceFieldModel:
        rows = table(["a", "b"], itom=["C", "N"], jtom=["N", "C"], knots=column)
        return forcefield([(style(category, "spline"), rows)])

    @pytest.mark.parametrize("shape", [(2, 1), (2, 5), (2, 2, 3), (2, 3, 1, 2)])
    def test_any_trailing_shape_in_any_category(self, shape: tuple[int, ...]) -> None:
        for category in ("bond", "dihedral", "cross_term"):
            ends = {
                c: ["C", "N"]
                for c in ("itom", "jtom", "ktom", "ltom")[: 4 if category == "dihedral" else 2]
            }
            rows = table(["a", "b"], **ends, knots=_grid_column(np.ones(shape)))
            forcefield([(style(category, "spline"), rows)])

    def test_an_axis_of_length_zero_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="every S >= 1"):
            self._bond(_grid_column(np.zeros((2, 0))))

    def test_a_string_array_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="parameter 'knots'"):
            self._bond(_grid_column(np.array([["a", "b"], ["c", "d"]])))

    def test_an_array_declares_no_precision(self) -> None:
        with pytest.raises(ValidationError, match="found a declared precision"):
            self._bond(_grid_column(np.zeros((2, 2)), precision=0.5))

    def test_a_non_null_row_is_finite_and_a_null_one_is_not_read(self) -> None:
        values = np.zeros((2, 2, 2))
        values[0, 1, 1] = np.nan
        with pytest.raises(ValidationError, match="row 0 holds a non-finite value"):
            self._bond(_grid_column(values))
        self._bond(_grid_column(values, validity=np.array([False, True])))

    def test_annotations_and_endpoints_have_no_trailing_axes(self) -> None:
        for name in ("desc", "itom"):
            rows = table(["a", "b"], itom=["C", "N"], jtom=["N", "C"])
            column = _grid_column(np.array([["x", "y"], ["z", "w"]]))
            rows = rows.model_copy(update={"columns": {**rows.columns, name: column}})
            with pytest.raises(ValidationError):
                forcefield([(style("bond", "spline"), rows)])

    def test_the_array_round_trips_through_zarr_bit_for_bit(self, tmp_path) -> None:
        values = np.arange(12, dtype="float64").reshape(2, 2, 3) / 7.0
        model = self._bond(_grid_column(values))
        store = ZarrForceFieldStore(tmp_path / "arrays.mrec")
        ZarrForceFieldCodec().write(model, store)
        back = ZarrForceFieldCodec().read(store)
        assert back == model
        assert back.tables["bond.spline"].columns["knots"].values.tobytes() == values.tobytes()


class TestOneFour:
    """``pair.lj/charmm``'s ``one_four`` is ``regular`` or ``epsilon14``."""

    @pytest.mark.parametrize("value", ["regular", "epsilon14"])
    def test_the_two_values(self, value: str) -> None:
        StyleModel(category="pair", style="lj/charmm", params={"one_four": value})

    def test_another_value_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="one_four is one of"):
            StyleModel(category="pair", style="lj/charmm", params={"one_four": "both"})

    def test_other_styles_may_use_the_name_freely(self) -> None:
        StyleModel(category="pair", style="custom", params={"one_four": "both"})


def test_molrs_reads_a_cmap_grid_as_a_cmap_type(tmp_path, molrs) -> None:
    """A cmap table molrec's codec writes is a ``molrs.ff.forcefield.CmapType`` per row,
    its ``grid`` a float64 numpy array equal bit for bit."""
    grids = np.stack([cmap_grid(24, 0.1), cmap_grid(24, -0.35)])
    model = forcefield([atoms(["C", "NH1", "CT1"], mass=[12.011, 14.007, 12.011]), cmap(grids)])
    store = ZarrForceFieldStore(tmp_path / "cmap.mrec")
    ZarrForceFieldCodec().write(model, store)

    ff = molrs.io.read_mrec_forcefield(store.path).to_forcefield()
    style_ = ff.get_style("cmap", "charmm")
    assert isinstance(style_, molrs.ff.forcefield.CmapStyle)
    types = sorted(style_.get_types(), key=lambda t: t.name)
    assert [t.name for t in types] == ["cmap0", "cmap1"]
    for row, cmap_type in enumerate(types):
        assert isinstance(cmap_type, molrs.ff.forcefield.CmapType)
        ends = [t.name for t in cmap_type.endpoints]
        expected = model.tables["cmap.charmm"].columns
        assert ends == [
            str(expected[c].values[row]) for c in ("itom", "jtom", "ktom", "ltom", "mtom")
        ]
        grid = cmap_type["grid"]
        assert isinstance(grid, np.ndarray) and grid.dtype == np.float64
        assert grid.tobytes() == grids[row].tobytes()

    # And back: molrs's section of the force field holds the same table.
    table_ = molrs.io.mrec.ForceFieldSection.from_forcefield(ff).table("cmap", "charmm")
    assert np.asarray(table_["grid"]).tobytes() == grids.tobytes()


#: How the record spells each unit molrs's ``UnitPreset`` names by its unit
#: registry's expression (``None``: a reduced ``lj`` unit, which the record
#: states no unit for). One record spelling per registry name, so a molrs
#: preset that changes a unit changes the spelling it is compared as.
_RECORD_SPELLING: dict[str, str | None] = {
    "angstrom": "angstrom",
    "nanometer": "nm",
    "micrometer": "micrometer",
    "meter": "m",
    "centimeter": "cm",
    "bohr": "bohr",
    "kilocalorie_per_mole": "kcal/mol",
    "kilojoule_per_mole": "kJ/mol",
    "electron_volt": "eV",
    "joule": "J",
    "erg": "erg",
    "hartree": "hartree",
    "picogram * micrometer ** 2 / microsecond ** 2": "picogram * micrometer**2 / microsecond**2",
    "attogram * nanometer ** 2 / nanosecond ** 2": "attogram * nm**2 / ns**2",
    "elementary_charge": "e",
    "coulomb": "C",
    "statcoulomb": "statcoulomb",
    "picocoulomb": "picocoulomb",
    "gram_per_mole": "dalton",
    "amu": "dalton",
    "kilogram": "kg",
    "gram": "g",
    "picogram": "picogram",
    "attogram": "attogram",
    "femtosecond": "fs",
    "picosecond": "ps",
    "nanosecond": "ns",
    "microsecond": "microsecond",
    "second": "s",
    **dict.fromkeys(("lj_sigma", "lj_epsilon", "lj_charge", "lj_mass", "lj_tau")),
}


def test_every_molrs_preset_is_the_molrec_table(molrs) -> None:
    """molrec's preset table is the implementation-neutral one; every unit
    preset molrs ships names the same units in it, quantity by quantity
    (molrs states no angle unit: every preset's angle is the degree)."""
    names = molrs.core.UnitPreset.names()
    assert sorted(names) == sorted(UNIT_PRESETS)
    for name in names:
        preset = molrs.core.UnitPreset(name)
        stated = {
            quantity: _RECORD_SPELLING[getattr(preset, quantity)()]
            for quantity in UNIT_QUANTITIES
            if quantity != "angle"
        }
        assert stated == {q: u for q, u in UNIT_PRESETS[name].items() if q != "angle"}, name
        assert UNIT_PRESETS[name]["angle"] == "degree"
