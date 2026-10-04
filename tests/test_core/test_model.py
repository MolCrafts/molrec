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
