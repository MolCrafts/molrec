"""The models' own rules: the optional version key, the per-step tag set, and
the three block states of a trajectory.

Mirrors ``src/molrec/core/model.py``.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from molrec.core.model import (
    META_TAGS,
    MOLREC_VERSION,
    BlockModel,
    BlockState,
    ColumnModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    RecordModel,
    SequenceBlockModel,
    SequenceColumnModel,
    StatusModel,
    TrajectoryModel,
    coerce_meta_value,
    meta_tag_parts,
    stamp_version,
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
    def test_an_absent_version_is_a_pre_1_store(self) -> None:
        assert MetaModel().molrec_version is None
        assert MetaModel.model_validate({}).molrec_version is None

    def test_accepts_version_one(self) -> None:
        assert MetaModel(molrec_version=1).molrec_version == 1

    @pytest.mark.parametrize("bad", [0, 2, None, "1", 1.0, True])
    def test_a_present_version_is_validated(self, bad: object) -> None:
        with pytest.raises(ValidationError, match="molrec_version"):
            MetaModel.model_validate({"molrec_version": bad})

    def test_writers_stamp_the_version_and_keep_a_producer_one(self) -> None:
        assert stamp_version({}) == {"molrec_version": MOLREC_VERSION}
        assert stamp_version({"molrec_version": 1, "x": 2}) == {"molrec_version": 1, "x": 2}

    def test_the_published_schema_forbids_null(self) -> None:
        schema = MetaModel.model_json_schema()["properties"]["molrec_version"]
        assert schema["type"] == "integer" and "default" not in schema

    def test_preserves_unknown_keys(self) -> None:
        meta = MetaModel.model_validate({"x_vendor_local": "kept"})
        assert meta.model_extra == {"x_vendor_local": "kept"}

    def test_provenance_is_typed(self) -> None:
        meta = MetaModel.model_validate(
            {
                "creator": {"name": "molrs", "version": "0.14"},
                "modules": {"qm": {"version": [1, 0]}},
            }
        )
        assert meta.creator is not None and meta.creator.name == "molrs"
        assert meta.modules is not None and meta.modules["qm"].version == (1, 0)


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
    """S1: present / empty / absent, with omission carrying forward."""

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
        """S4: the shape is pinned, and BlockModel pins the count to the shape."""
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

        meta = MetaModel.model_validate({"molrec_version": 1, "x_reviewed": None})
        assert document(meta) == {"molrec_version": 1, "x_reviewed": None}
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
