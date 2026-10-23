"""The models' own rules: the meta document, the per-step tag set, and
the three block states of a trajectory.

Mirrors ``src/molrec/core/model.py``.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from molrec.core.model import (
    META_TAGS,
    BlockModel,
    BlockState,
    BoxModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    ForceFieldModel,
    ForceFieldUnitsModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    RecordModel,
    SequenceBlockModel,
    SequenceColumnModel,
    StatusModel,
    StyleModel,
    TrajectoryModel,
    UnitsModel,
    coerce_meta_value,
    meta_tag_parts,
    require_stated_units,
)


def _x(*values: float) -> BlockModel:
    array = np.array(values, dtype="float64")
    return BlockModel(
        count=len(values), columns={"x": ColumnModel(dtype="f64", shape=array.shape, values=array)}
    )


def _bonds(count: int) -> BlockModel:
    return BlockModel(
        count=count,
        columns={
            "atomi": ColumnModel(
                dtype="u64", shape=(count,), values=np.arange(count, dtype="uint64")
            ),
            "atomj": ColumnModel(
                dtype="u64", shape=(count,), values=np.arange(1, count + 1, dtype="uint64")
            ),
        },
    )


class TestMetaModel:
    def test_preserves_unknown_keys(self) -> None:
        meta = MetaModel.model_validate({"x_vendor_local": "kept"})
        assert meta.model_extra == {"x_vendor_local": "kept"}

    def test_provenance_is_typed(self) -> None:
        meta = MetaModel.model_validate(
            {
                "creator": {"name": "molrs", "version": "0.14"},
                "modules": {"qm": {"spec": "https://example.org/qm"}},
            }
        )
        assert meta.creator is not None and meta.creator.name == "molrs"
        assert meta.modules is not None and meta.modules["qm"].spec == "https://example.org/qm"


class TestRecordModel:
    def test_status_alone_is_a_record(self) -> None:
        record = RecordModel(meta=MetaModel(), status=StatusModel(state="running"))
        assert record.status is not None and record.status.state == "running"

    def test_meta_alone_is_not(self) -> None:
        with pytest.raises(ValidationError, match="at least one of"):
            RecordModel(meta=MetaModel())


class TestMetaTags:
    def test_the_set_is_the_reference_implementations_sixteen(self) -> None:
        assert META_TAGS == (
            "bool", "i32", "i64", "u32", "u64", "f64", "string", "json",
            "bool3", "i32x3", "i64x3", "u32x3", "u64x3", "f64x3", "f64x6", "f64x9",
        )  # fmt: skip

    def test_parts(self) -> None:
        assert meta_tag_parts("f64x3") == ("f64", (3,))
        assert meta_tag_parts("bool3") == ("bool", (3,))
        assert meta_tag_parts("json") == ("string", ())
        with pytest.raises(ValueError, match="closed set"):
            meta_tag_parts("i64x6")

    @pytest.mark.parametrize(
        ("tag", "value", "coerced"),
        [
            ("f64", 1, 1.0),
            ("f64", np.float64(0.5), 0.5),
            ("i32", np.int64(-3), -3),
            ("u64", 2**64 - 1, 2**64 - 1),
            ("f64x3", (1, 2, 3), [1.0, 2.0, 3.0]),
            ("bool3", np.array([True, False, True]), [True, False, True]),
            ("json", {"a": [1, None]}, {"a": [1, None]}),
        ],
    )
    def test_a_value_is_coerced_to_its_tag(self, tag: str, value: object, coerced: object) -> None:
        result = coerce_meta_value(tag, value)
        assert result == coerced and type(result) is type(coerced)

    @pytest.mark.parametrize(
        ("tag", "value"),
        [
            ("i64", 1.0),
            ("i32", 2**31),
            ("u32", -1),
            ("bool", 1),
            ("f64", True),
            ("f64x3", [1.0, 2.0]),
            ("i32x3", [1, 2, 3, 4]),
            ("string", 3),
            ("json", float("nan")),
        ],
    )
    def test_a_value_that_is_not_one_of_its_tag_is_refused(self, tag: str, value: object) -> None:
        with pytest.raises(ValueError):
            coerce_meta_value(tag, value)

    def test_a_fill_is_declared_by_stating_it(self) -> None:
        assert MetaSeriesModel(dtype="json", fill=None).has_fill
        assert not MetaSeriesModel(dtype="json").has_fill
        assert MetaSeriesModel(dtype="json", fill=None) != MetaSeriesModel(dtype="json")
        assert MetaSeriesModel(dtype="json", fill=None).model_dump(mode="json") == {
            "dtype": "json",
            "fill": None,
        }
        with pytest.raises(ValidationError):
            MetaSeriesModel(dtype="f64", fill=None)

    def test_a_fill_round_trips_through_its_json_form(self) -> None:
        nan = MetaSeriesModel(dtype="f64", fill=float("nan"))
        assert nan.model_dump(mode="json") == {"dtype": "f64", "fill": "NaN"}
        assert MetaSeriesModel.model_validate(nan.model_dump(mode="json")) == nan
        big = MetaSeriesModel(dtype="u64x3", fill=[2**64 - 1, 0, 1])
        assert big.model_dump(mode="json")["fill"] == ["18446744073709551615", 0, 1]
        assert MetaSeriesModel.model_validate(big.model_dump(mode="json")) == big

    def test_frame_values_are_coerced_on_the_way_in(self) -> None:
        trajectory = TrajectoryModel(
            frames=[FrameModel(meta={"pe": 1, "com": (0, 0, 1)})],
            step=[0],
            meta={"pe": MetaSeriesModel(dtype="f64"), "com": MetaSeriesModel(dtype="f64x3")},
        )
        assert trajectory.frames[0].meta == {"pe": 1.0, "com": [0.0, 0.0, 1.0]}
        assert type(trajectory.frames[0].meta["pe"]) is float
        with pytest.raises(ValidationError, match="declared"):
            TrajectoryModel(
                frames=[FrameModel(meta={"pe": 1.5})],
                step=[0],
                meta={"pe": MetaSeriesModel(dtype="i64")},
            )

    def test_json_is_a_meta_tag_not_a_column_dtype(self) -> None:
        assert MetaSeriesModel(dtype="json").element_dtype == "string"
        with pytest.raises(ValidationError):
            ColumnModel(dtype="json", shape=(1,))
        with pytest.raises(ValidationError):
            SequenceColumnModel(dtype="json")


class TestBlockStates:
    """Present / empty / absent, with omission carrying forward.

    ``docs/spec/ragged.md#the-three-states-of-a-block``.
    """

    def test_omitted_block_carries_forward(self) -> None:
        trajectory = TrajectoryModel(
            frames=[
                FrameModel(blocks={"atoms": _x(0.0), "bonds": _bonds(2)}),
                FrameModel(blocks={"atoms": _x(1.0)}),
            ],
            step=[0, 1],
        )
        assert trajectory.state_of("bonds", 1) is BlockState.PRESENT
        assert trajectory.frames[1].blocks["bonds"] == _bonds(2)

    def test_zero_row_update_is_present_and_empty(self) -> None:
        trajectory = TrajectoryModel(
            frames=[
                FrameModel(blocks={"atoms": _x(0.0), "bonds": _bonds(2)}),
                FrameModel(blocks={"atoms": _x(1.0), "bonds": _bonds(0)}),
                FrameModel(blocks={"atoms": _x(2.0)}),
            ],
            step=[0, 1, 2],
        )
        assert [trajectory.state_of("bonds", i) for i in range(3)] == [
            BlockState.PRESENT,
            BlockState.EMPTY,
            BlockState.EMPTY,
        ]
        assert set(trajectory.frames[2].blocks["bonds"].columns) == {"atomi", "atomj"}

    def test_absent_only_before_the_first_update(self) -> None:
        trajectory = TrajectoryModel(
            frames=[
                FrameModel(blocks={"atoms": _x(0.0)}),
                FrameModel(blocks={"atoms": _x(1.0), "bonds": _bonds(1)}),
                FrameModel(blocks={"atoms": _x(2.0)}),
            ],
            step=[0, 1, 2],
        )
        assert [trajectory.state_of("bonds", i) for i in range(3)] == [
            BlockState.ABSENT,
            BlockState.PRESENT,
            BlockState.PRESENT,
        ]
        assert "bonds" not in trajectory.frames[0].blocks

    def test_the_declaration_is_derived_or_held_to(self) -> None:
        derived = TrajectoryModel(frames=[FrameModel(blocks={"atoms": _x(0.0)})], step=[0])
        assert derived.blocks == {
            "atoms": SequenceBlockModel(columns={"x": SequenceColumnModel(dtype="f64")})
        }
        with pytest.raises(ValidationError, match="never declared"):
            TrajectoryModel(
                frames=[FrameModel(blocks={"atoms": _x(0.0)})],
                step=[0],
                blocks={"bonds": SequenceBlockModel()},
            )

    def test_structural_shape_fixes_the_row_count(self) -> None:
        """A grid's row count is fixed: the shape is pinned, and BlockModel pins the count to it.

        ``docs/spec/ragged.md#per-block-sparse-updates-csr``.
        """
        grid = BlockModel(
            count=8,
            structural_shape=(2, 2, 2),
            columns={"rho": ColumnModel(dtype="f64", shape=(8,), values=np.zeros(8))},
        )
        bigger = BlockModel(
            count=27,
            structural_shape=(3, 3, 3),
            columns={"rho": ColumnModel(dtype="f64", shape=(27,), values=np.zeros(27))},
        )
        with pytest.raises(ValidationError, match="row count is fixed"):
            TrajectoryModel(
                frames=[
                    FrameModel(blocks={"density": grid}),
                    FrameModel(blocks={"density": bigger}),
                ],
                step=[0, 1],
            )


class TestValidity:
    def test_an_all_true_mask_is_no_mask(self) -> None:
        values = np.zeros(3)
        column = ColumnModel(dtype="f64", shape=(3,), values=values, validity=np.ones(3, bool))
        assert column.validity is None
        assert column == ColumnModel(dtype="f64", shape=(3,), values=values)

    def test_a_mask_is_one_bool_per_row(self) -> None:
        with pytest.raises(ValidationError, match="one flag per row"):
            ColumnModel(dtype="f64", shape=(3,), validity=np.array([True, False]))
        with pytest.raises(ValidationError, match="bool"):
            ColumnModel(dtype="f64", shape=(2,), validity=np.array([1, 0]))

    def test_masks_are_content(self) -> None:
        values = np.zeros(2)
        holed = ColumnModel(dtype="f64", shape=(2,), values=values, validity=np.array([1, 0], bool))
        assert holed != ColumnModel(dtype="f64", shape=(2,), values=values)

    def test_validity_is_a_reserved_column_name(self) -> None:
        with pytest.raises(ValidationError, match="_validity"):
            BlockModel(count=0, columns={"_validity": ColumnModel(dtype="bool", shape=(0,))})

    def test_nullability_is_a_union_over_the_run(self) -> None:
        def block(validity: list[bool] | None) -> BlockModel:
            return BlockModel(
                count=2,
                columns={
                    "q": ColumnModel(
                        dtype="f64",
                        shape=(2,),
                        values=np.zeros(2),
                        validity=None if validity is None else np.array(validity),
                    )
                },
            )

        trajectory = TrajectoryModel(
            frames=[
                FrameModel(blocks={"atoms": block(None)}),
                FrameModel(blocks={"atoms": block([True, False])}),
            ],
            step=[0, 1],
        )
        assert trajectory.blocks is not None
        assert trajectory.blocks["atoms"].columns["q"].nullable
        with pytest.raises(ValidationError, match="non-nullable"):
            TrajectoryModel(
                frames=[FrameModel(blocks={"atoms": block([True, False])})],
                step=[0],
                blocks={
                    "atoms": SequenceBlockModel(columns={"q": SequenceColumnModel(dtype="f64")})
                },
            )

    def test_nullable_is_written_only_when_true(self) -> None:
        assert SequenceColumnModel(dtype="f64").model_dump(mode="json") == {
            "dtype": "f64",
            "trailing": [],
        }
        assert SequenceColumnModel(dtype="f64", nullable=True).model_dump(mode="json")["nullable"]


class TestCanonicalDtypes:
    @pytest.mark.parametrize(
        ("name", "dtype"), [("atomi", "u32"), ("atomm", "i64"), ("id", "i64"), ("x", "i64")]
    )
    def test_a_canonical_key_has_one_dtype(self, name: str, dtype: str) -> None:
        from molrec.core.model import NUMPY_DTYPE

        values = np.zeros(2, dtype=NUMPY_DTYPE[dtype])
        with pytest.raises(ValidationError, match="canonical"):
            BlockModel(count=2, columns={name: ColumnModel(dtype=dtype, shape=(2,), values=values)})

    def test_a_canonical_key_has_no_trailing_axes(self) -> None:
        with pytest.raises(ValidationError, match="canonical"):
            BlockModel(count=2, columns={"x": ColumnModel(dtype="f64", shape=(2, 3))})

    def test_a_canonical_per_step_key_is_f64(self) -> None:
        with pytest.raises(ValidationError, match="canonical"):
            TrajectoryModel(
                frames=[FrameModel(meta={"pe": 1})],
                step=[0],
                meta={"pe": MetaSeriesModel(dtype="i64")},
            )


class TestUndefinedCell:
    def test_an_undefined_cell_carries_the_identity(self) -> None:
        from molrec.core.model import BoxModel

        box = BoxModel(vectors=np.zeros((3, 3)), cell_defined=False)
        assert np.array_equal(box.vectors, np.eye(3))
        assert box.boundary == (False, False, False)

    def test_an_undefined_cell_is_periodic_on_no_axis(self) -> None:
        from molrec.core.model import BoxModel

        with pytest.raises(ValidationError, match="periodic on no axis"):
            BoxModel(vectors=np.eye(3), boundary=(True, False, False), cell_defined=False)

    def test_a_cell_is_f64(self) -> None:
        from molrec.core.model import BoxModel

        with pytest.raises(ValidationError, match="f64"):
            BoxModel(vectors=np.eye(3, dtype="float32"))
        assert BoxModel(vectors=np.eye(3, dtype="int64")).vectors.dtype == np.float64

    def test_an_update_has_no_flag_of_its_own(self) -> None:
        from molrec.core.model import BoxUpdateModel, CellModel, TrajectoryBoxModel

        assert "cell_defined" not in BoxUpdateModel.model_fields["box"].annotation.model_fields
        section = TrajectoryBoxModel(
            cell_defined=False,
            updates=[BoxUpdateModel(step_index=0, box=CellModel(vectors=np.zeros((3, 3))))],
        )
        assert np.array_equal(section.updates[0].box.vectors, np.eye(3))
        assert section.updates[0].box.boundary == (False, False, False)


class TestPreservation:
    def test_a_document_keeps_a_null_valued_unknown_key(self) -> None:
        from molrec.core.model import document

        meta = MetaModel.model_validate({"x_vendor": 1, "x_reviewed": None})
        assert document(meta) == {"x_vendor": 1, "x_reviewed": None}
        assert document(MetaModel()) == {}

    def test_a_document_refuses_nan(self) -> None:
        from molrec.core.model import document

        with pytest.raises(ValueError, match="finite JSON"):
            document(StatusModel.model_validate({"state": "running", "loss": float("nan")}))

    def test_containers_forbid_what_no_binding_stores(self) -> None:
        with pytest.raises(ValidationError):
            FrameModel.model_validate({"blocks": {}, "x_vendor": 1})
        with pytest.raises(ValidationError):
            TrajectoryModel.model_validate({"frames": [], "step": [], "x_vendor": 1})

    def test_an_unknown_root_section_is_a_subtree(self) -> None:
        from molrec.core.model import NodeModel

        record = RecordModel.model_validate(
            {"meta": {}, "status": {"state": "ok"}, "x_vendor": {"attributes": {"a": 1}}}
        )
        assert record.model_extra == {"x_vendor": NodeModel(attributes={"a": 1})}


class TestArrays:
    @pytest.mark.parametrize("values", [np.array([b"a", b"b"]), np.array([1, "a"], dtype=object)])
    def test_bytes_and_mixed_objects_are_no_column(self, values: np.ndarray) -> None:
        with pytest.raises(ValidationError):
            ColumnModel(dtype="string", shape=(2,), values=values)

    def test_an_object_array_of_str_is_a_string_column(self) -> None:
        values = np.array(["a", "b"], dtype=object)
        assert ColumnModel(dtype="string", shape=(2,), values=values).dtype == "string"

    def test_dedup_is_bitwise(self) -> None:
        from molrec.core.model import same_bits

        def block(value: float) -> BlockModel:
            return BlockModel(
                count=1,
                columns={"q": ColumnModel(dtype="f64", shape=(1,), values=np.array([value]))},
            )

        assert same_bits(block(float("nan")), block(float("nan")))
        assert not same_bits(block(0.0), block(-0.0))


class TestRecordAlignment:
    def test_a_trajectory_block_has_the_system_row_count(self) -> None:
        system = FrameModel(blocks={"atoms": _x(0.0, 1.0)})
        trajectory = TrajectoryModel(frames=[FrameModel(blocks={"atoms": _x(0.0)})], step=[0])
        with pytest.raises(ValidationError, match="align 1:1"):
            RecordModel(meta=MetaModel(), system=system, trajectory=trajectory)


class TestRunDocuments:
    @pytest.mark.parametrize("stamp", ["2026-08-04T12:00:00", "2026-08-04", "yesterday"])
    def test_a_timestamp_names_an_instant(self, stamp: str) -> None:
        with pytest.raises(ValidationError, match="RFC 3339|instant"):
            StatusModel(state="running", started_at=stamp)

    def test_a_timestamp_is_kept_as_written(self) -> None:
        stamp = "2026-08-04T12:00:00.5Z"
        assert StatusModel(state="running", started_at=stamp).started_at == stamp

    def test_counters_are_non_negative_integers(self) -> None:
        with pytest.raises(ValidationError):
            StatusModel(state="running", epoch=-1)


class TestTypedFrameMeta:
    def test_an_untagged_key_takes_its_inferred_tag(self) -> None:
        frame = FrameModel(
            meta={"b": True, "i": -3, "u": 2**63, "w": 2**64, "f": 1.0, "s": "NaN", "j": [1]}
        )
        assert frame.meta_types == {
            "b": "bool",
            "i": "i64",
            "u": "u64",
            "w": "f64",
            "f": "f64",
            "s": "string",
            "j": "json",
        }
        assert frame.meta["w"] == float(2**64)

    def test_a_value_is_held_to_its_tag(self) -> None:
        assert FrameModel(meta={"t": 1}, meta_types={"t": "f64"}).meta["t"] == 1.0
        with pytest.raises(ValidationError, match="tagged 'i32'"):
            FrameModel(meta={"n": 1.5}, meta_types={"n": "i32"})
        with pytest.raises(ValidationError, match="tagged 'json'"):
            FrameModel(meta={"d": {"x": float("nan")}}, meta_types={"d": "json"})

    def test_the_tag_map_is_reserved_and_strict(self) -> None:
        with pytest.raises(ValidationError, match="reserved"):
            FrameModel(meta={"_meta_types": {}})
        with pytest.raises(ValidationError, match="does not carry"):
            FrameModel(meta={}, meta_types={"gone": "f64"})

    def test_nan_equals_nan_and_tags_are_content(self) -> None:
        nan = FrameModel(meta={"e": float("nan")})
        assert nan == FrameModel(meta={"e": float("nan")})
        assert FrameModel(meta={"n": 1}, meta_types={"n": "i32"}) != FrameModel(meta={"n": 1})

    def test_a_trajectory_frame_is_typed_by_the_declaration(self) -> None:
        frame = FrameModel(meta={"n": 1})
        model = TrajectoryModel(frames=[frame], step=[0], meta={"n": MetaSeriesModel(dtype="i32")})
        assert model.frames[0].meta_types == {"n": "i32"}


class TestRowReferences:
    @staticmethod
    def _members(target: str, beads: list[int]) -> BlockModel:
        values = np.array(beads, dtype="uint64")
        return BlockModel(
            count=len(beads),
            columns={"ibead": ColumnModel(dtype="u64", shape=values.shape, values=values)},
            targets={"ibead": target},
        )

    def test_a_target_is_a_block_or_a_section_block(self) -> None:
        self._members("atoms", [0])
        self._members("/frame/atoms", [0])
        for bad in ("/trajectory/atoms", "/frame", "a/b", ""):
            with pytest.raises(ValidationError):
                self._members(bad, [0])

    def test_a_reference_is_a_u64_column_of_the_block(self) -> None:
        values = np.array([0], dtype="int64")
        with pytest.raises(ValidationError, match="u64"):
            BlockModel(
                count=1,
                columns={"host": ColumnModel(dtype="i64", shape=(1,), values=values)},
                targets={"host": "atoms"},
            )
        with pytest.raises(ValidationError, match="no column"):
            BlockModel(count=0, targets={"host": "atoms"})

    def test_a_null_row_references_nothing(self) -> None:
        values = np.array([0, 99], dtype="uint64")
        members = BlockModel(
            count=2,
            columns={
                "ibead": ColumnModel(
                    dtype="u64", shape=(2,), values=values, validity=np.array([True, False])
                )
            },
            targets={"ibead": "atoms"},
        )
        FrameModel(blocks={"atoms": BlockModel(count=1), "members": members})

    def test_an_empty_referencing_block_needs_no_target(self) -> None:
        FrameModel(blocks={"members": self._members("sites", [])})
        with pytest.raises(ValidationError, match="not there"):
            FrameModel(blocks={"members": self._members("sites", [0])})


def _f64(name: str, value: float = 0.0) -> BlockModel:
    array = np.array([value])
    return BlockModel(
        count=1, columns={name: ColumnModel(dtype="f64", shape=array.shape, values=array)}
    )


def _f64_unit(name: str, unit: str, value: float = 0.0) -> BlockModel:
    array = np.array([value])
    return BlockModel(
        count=1,
        columns={name: ColumnModel(dtype="f64", shape=array.shape, values=array, unit=unit)},
    )


class TestUnitsModel:
    """Record and collection units: one stated system, no silent defaults.

    ``require_stated_units`` is the record-level check. ``RecordModel`` does
    not call it; ``CollectionModel`` does.
    """

    @staticmethod
    def _frame(frame: FrameModel) -> RecordModel:
        return RecordModel(meta=MetaModel(), frame=frame)

    def test_element_only_collection_needs_no_units(self) -> None:
        record = RecordModel(
            meta=MetaModel(),
            system=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=1,
                        columns={
                            "element": ColumnModel(
                                dtype="string", shape=(1,), values=np.array(["O"])
                            )
                        },
                    )
                }
            ),
        )
        require_stated_units(record, None)
        collection = CollectionModel(meta=CollectionMetaModel(), records=[record])
        assert collection.meta.units is None
        assert collection.records[0].system is not None
        element = collection.records[0].system.blocks["atoms"].columns["element"]
        assert element.values is not None and element.values.tolist() == ["O"]

    def test_units_model_keeps_nine_fields_and_unknown_keys(self) -> None:
        units = UnitsModel.model_validate(
            {
                "length": "angstrom",
                "energy": "kcal/mol",
                "force": "kcal/mol/angstrom",
                "angle": "degree",
                "charge": "e",
                "mass": "amu",
                "time": "fs",
                "pressure": "atm",
                "temperature": "kelvin",
                "note": "kept",
            }
        )
        assert units.length == "angstrom"
        assert units.energy == "kcal/mol"
        assert units.force == "kcal/mol/angstrom"
        assert units.angle == "degree"
        assert units.charge == "e"
        assert units.mass == "amu"
        assert units.time == "fs"
        assert units.pressure == "atm"
        assert units.temperature == "kelvin"
        assert units.model_extra is not None and units.model_extra["note"] == "kept"

    def test_meta_preserves_an_unknown_key_beside_units(self) -> None:
        meta = MetaModel.model_validate({"units": {"length": "angstrom"}, "x_vendor": 1})
        assert meta.units is not None and meta.units.length == "angstrom"
        assert meta.model_extra == {"x_vendor": 1}

    def test_x_requires_length(self) -> None:
        record = self._frame(FrameModel(blocks={"atoms": _x(0.0)}))
        with pytest.raises(ValueError, match="length"):
            require_stated_units(record, None)
        with pytest.raises(ValueError, match="length"):
            require_stated_units(record, UnitsModel(energy="kcal/mol"))

    def test_y_requires_length(self) -> None:
        record = self._frame(FrameModel(blocks={"atoms": _f64("y")}))
        with pytest.raises(ValueError, match="length"):
            require_stated_units(record, None)

    def test_z_requires_length(self) -> None:
        record = self._frame(FrameModel(blocks={"atoms": _f64("z")}))
        with pytest.raises(ValueError, match="length"):
            require_stated_units(record, None)

    def test_pe_requires_energy(self) -> None:
        record = self._frame(FrameModel(meta={"pe": 1.0}))
        with pytest.raises(ValueError, match="energy"):
            require_stated_units(record, None)
        with pytest.raises(ValueError, match="energy"):
            require_stated_units(record, UnitsModel(length="angstrom"))

    def test_ke_requires_energy(self) -> None:
        record = self._frame(FrameModel(meta={"ke": 1.0}))
        with pytest.raises(ValueError, match="energy"):
            require_stated_units(record, None)

    def test_etotal_requires_energy(self) -> None:
        record = self._frame(FrameModel(meta={"etotal": 1.0}))
        with pytest.raises(ValueError, match="energy"):
            require_stated_units(record, None)

    def test_force_columns_require_force(self) -> None:
        for name in ("fx", "fy", "fz"):
            record = self._frame(FrameModel(blocks={"atoms": _f64(name)}))
            with pytest.raises(ValueError, match="force"):
                require_stated_units(record, None)

    def test_time_requires_time(self) -> None:
        record = RecordModel(
            meta=MetaModel(),
            trajectory=TrajectoryModel(frames=[FrameModel()], step=[0], time=[0.0]),
        )
        with pytest.raises(ValueError, match="time"):
            require_stated_units(record, None)

    def test_press_requires_pressure(self) -> None:
        record = self._frame(FrameModel(meta={"press": 1.0}))
        with pytest.raises(ValueError, match="pressure"):
            require_stated_units(record, None)

    def test_temp_requires_temperature(self) -> None:
        record = self._frame(FrameModel(meta={"temp": 300.0}))
        with pytest.raises(ValueError, match="temperature"):
            require_stated_units(record, None)

    def test_mass_requires_mass(self) -> None:
        block = _f64("mass", 1.0)
        assert block.columns["mass"].unit is None
        record = self._frame(FrameModel(blocks={"atoms": block}))
        with pytest.raises(ValueError, match="mass"):
            require_stated_units(record, None)
        assert record.frame is not None
        assert record.frame.blocks["atoms"].columns["mass"].unit != "amu"

    def test_charge_requires_charge(self) -> None:
        block = _f64("charge", 1.0)
        assert block.columns["charge"].unit is None
        record = self._frame(FrameModel(blocks={"atoms": block}))
        with pytest.raises(ValueError, match="charge"):
            require_stated_units(record, None)
        assert record.frame is not None
        assert record.frame.blocks["atoms"].columns["charge"].unit != "e"

    def test_declared_trajectory_column_counts_with_zero_frames(self) -> None:
        record = RecordModel(
            meta=MetaModel(),
            trajectory=TrajectoryModel(
                frames=[],
                step=[],
                blocks={
                    "atoms": SequenceBlockModel(columns={"x": SequenceColumnModel(dtype="f64")})
                },
            ),
        )
        with pytest.raises(ValueError, match="length"):
            require_stated_units(record, None)

    def test_energy_charge_volume_meta_keys_do_not_trigger(self) -> None:
        for key in ("energy", "charge", "volume"):
            require_stated_units(self._frame(FrameModel(meta={key: 1.0})), None)
        require_stated_units(self._frame(FrameModel(blocks={"atoms": _f64("vx")})), None)
        boxed = self._frame(FrameModel(box=BoxModel(vectors=np.eye(3))))
        require_stated_units(boxed, None)

    def test_column_unit_does_not_satisfy_length(self) -> None:
        array = np.array([0.0])
        stated = ColumnModel(dtype="f64", shape=array.shape, values=array, unit="nm")
        bare = ColumnModel(dtype="f64", shape=array.shape, values=array)
        assert stated != bare
        record = self._frame(
            FrameModel(blocks={"atoms": BlockModel(count=1, columns={"x": stated})})
        )
        with pytest.raises(ValueError, match="length"):
            require_stated_units(record, None)

    def test_member_must_not_restate_units(self) -> None:
        system = FrameModel(blocks={"atoms": _x(0.0)})
        units = UnitsModel(length="angstrom")
        restated = (
            MetaModel.model_validate({"units": {"length": "angstrom"}}),
            MetaModel(units=UnitsModel()),
        )
        for meta in restated:
            with pytest.raises(ValidationError):
                CollectionModel(
                    meta=CollectionMetaModel(units=units),
                    records=[RecordModel(meta=meta, system=system)],
                )
        kept = CollectionModel(
            meta=CollectionMetaModel(units=units),
            records=[RecordModel(meta=MetaModel(), system=system)],
        )
        assert kept.records[0].meta.units is None

    def test_frame_meta_units_is_not_the_unit_system(self) -> None:
        record = self._frame(
            FrameModel(blocks={"atoms": _x(0.0)}, meta={"units": {"length": "nm"}})
        )
        with pytest.raises(ValueError, match="length"):
            require_stated_units(record, None)
        assert record.frame is not None and "units" in record.frame.meta
        quiet = self._frame(FrameModel(meta={"units": {"length": "nm"}}))
        require_stated_units(quiet, None)
        assert quiet.frame is not None and "units" in quiet.frame.meta

    def test_forcefield_column_unit_is_refused(self) -> None:
        assert "force" not in ForceFieldUnitsModel.model_fields
        assert "pressure" not in ForceFieldUnitsModel.model_fields
        assert "temperature" not in ForceFieldUnitsModel.model_fields
        names = np.array(["CT"])
        sigma = np.array([0.1])
        with pytest.raises(ValidationError):
            ForceFieldModel(
                name="test",
                units=ForceFieldUnitsModel(preset="real"),
                styles=[StyleModel(category="atom", style="full")],
                tables={
                    "atom.full": BlockModel(
                        count=1,
                        columns={
                            "name": ColumnModel(dtype="string", shape=(1,), values=names),
                            "sigma": ColumnModel(dtype="f64", shape=(1,), values=sigma, unit="nm"),
                        },
                    )
                },
            )

    def test_trajectory_column_unit_is_one_string(self) -> None:
        with pytest.raises(ValidationError):
            TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _f64_unit("x", "nm", 0.0)}),
                    FrameModel(blocks={"atoms": _f64_unit("x", "angstrom", 1.0)}),
                ],
                step=[0, 1],
            )
        trajectory = TrajectoryModel(
            frames=[
                FrameModel(blocks={"atoms": _f64_unit("x", "nm", 0.0)}),
                FrameModel(blocks={"atoms": _f64("x", 1.0)}),
            ],
            step=[0, 1],
        )
        for frame in trajectory.frames:
            assert frame.blocks["atoms"].columns["x"].unit == "nm"

    def test_mass_and_charge_are_not_defaulted(self) -> None:
        assert _f64("mass", 1.0).columns["mass"].unit is None
        assert _f64("charge", 1.0).columns["charge"].unit is None
