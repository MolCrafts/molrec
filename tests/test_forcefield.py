"""The forcefield section's own rules: block names, units, the document, and
the layout the reference codec writes (``docs/spec/forcefield.md``)."""

from __future__ import annotations

import pytest
import zarr
from pydantic import ValidationError

from molrec.core.bindings.zarr import ZarrForceFieldCodec, ZarrForceFieldStore
from molrec.core.ffsuite import atoms, forcefield, round_trip_forcefield, style, table
from molrec.core.model import (
    CollectionMetaModel,
    CollectionModel,
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
