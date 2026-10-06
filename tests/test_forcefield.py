"""The forcefield section's own rules: block names, units, the document, and
the layout the reference codec writes (``docs/spec/forcefield.md``)."""

from __future__ import annotations

import numpy as np
import pytest
import zarr
from pydantic import ValidationError

from molrec.core.bindings.zarr import ZarrForceFieldCodec, ZarrForceFieldStore
from molrec.core.ffsuite import atoms, forcefield, round_trip_forcefield, style, table
from molrec.core.model import (
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
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
        ForceFieldUnitsModel(preset="real", energy="kcal/mol", angle="radian")
        with pytest.raises(ValidationError, match="disagrees"):
            ForceFieldUnitsModel(preset="real", energy="kJ/mol")
        with pytest.raises(ValidationError, match="disagrees"):
            ForceFieldUnitsModel(preset="lj", length="angstrom")

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
    assert root["meta"].attrs["molrec_version"] == 1
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
    def _pair(category: str = "pair", **columns) -> None:
        names = [f"r{i}" for i in range(len(columns["itom"]))]
        forcefield([(style(category, "lj/cut"), table(names, **columns))])

    def test_a_cross_row_and_its_equal_restatements_are_one_row(self) -> None:
        self._pair(
            itom=["A", "B", "A", "B", "A"],
            jtom=["A", "B", "B", "A", "B"],
            epsilon=[0.1, 0.4, 0.9, 0.9, 0.9],
            sigma=[3.0, 3.6, 2.0, 2.0, 2.0],
        )

    @pytest.mark.parametrize("category", ["pair", "pair14"])
    @pytest.mark.parametrize(("itom", "jtom"), [(["A", "A"], ["B", "B"]), (["A", "B"], ["B", "A"])])
    def test_a_restatement_with_other_parameters_is_refused(
        self, category: str, itom: list[str], jtom: list[str]
    ) -> None:
        with pytest.raises(ValidationError, match=r"'r0' and 'r1' both price .* \['epsilon'\]"):
            self._pair(category, itom=itom, jtom=jtom, epsilon=[0.9, 0.8], sigma=[2.0, 2.0])

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
