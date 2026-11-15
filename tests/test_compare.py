"""What ``molrec.compare.diff`` must catch. Mirrors ``src/molrec/compare.py``.

``_diff_model`` walks ``type(expected).model_fields``. Every model that
carries unknown content is ``extra="allow"`` -- ``MetaModel``,
``RecordModel``, ``FrameModel``, ``BlockModel`` -- and an extra key lives in
``__pydantic_extra__``, never in ``model_fields``. So the keys the contract
exists to protect are the exact keys a naive comparator does not look at:
``MetaModel``'s docstring calls ``extra="allow"`` "the preserve-the-unknown
invariant", and ``RecordSuite``'s ``meta-unknown-keys-preserved`` case is
built from an unknown ``x_vendor_local`` key -- without ``_diff_extras`` an
implementation could drop it and still pass that case.

The unknown key used here is ``x_tool``: ``creator`` is a declared field of
``MetaModel`` now, so it would be walked as a field, not as an extra.

``_diff_mapping`` already states the rule these tests hold models to, in both
directions (``compare.py:60-85``): a lost key and an invented key are equally
a round-trip failure.
"""

from __future__ import annotations

import numpy as np

import molrec


def _meta(**extras: object) -> molrec.core.model.MetaModel:
    """A valid meta document plus whatever unknown keys the case needs."""
    return molrec.core.model.MetaModel.model_validate({**extras})


def test_an_extra_key_whose_value_changed_is_a_violation() -> None:
    violations = molrec.compare.diff(_meta(x_tool="molrec-suite"), _meta(x_tool="somebody-else"))

    assert [v.path for v in violations] == ["/x_tool"]


def test_a_dropped_extra_key_is_a_violation() -> None:
    """ "A reader must keep keys it does not recognize" -- with teeth."""
    violations = molrec.compare.diff(_meta(x_tool="molrec-suite"), _meta())

    assert [v.path for v in violations] == ["/x_tool"]


def test_an_invented_extra_key_is_a_violation() -> None:
    """An implementation must not manufacture content either."""
    violations = molrec.compare.diff(_meta(), _meta(x_vendor_local="invented"))

    assert [v.path for v in violations] == ["/x_vendor_local"]


def test_identical_extras_are_not_a_violation() -> None:
    """The guard on the fix: a key that did survive must stay silent."""
    assert molrec.compare.diff(_meta(x_tool="molrec-suite"), _meta(x_tool="molrec-suite")) == ()


def test_an_extra_key_below_the_root_is_reached() -> None:
    """The suite compares records, not bare metas, so the walk has to recurse."""
    expected = molrec.core.model.RecordModel(
        meta=_meta(x_tool={"name": "molrec-suite", "version": "0.1.0"}),
        frame=molrec.core.model.FrameModel(),
    )
    actual = molrec.core.model.RecordModel(meta=_meta(), frame=molrec.core.model.FrameModel())

    assert [v.path for v in molrec.compare.diff(expected, actual)] == ["/meta/x_tool"]


# ---------------------------------------------------------------------------
# Arrays and scalars: no crash on a list, and no type laundering through ==.
# ---------------------------------------------------------------------------


def test_a_list_in_the_model_against_an_array_does_not_crash() -> None:
    """A per-step vector is a list in the model and often an array from a reader."""
    assert molrec.compare.diff([0.0, 0.5, 1.0], np.array([0.0, 0.5, 1.0])) == ()
    assert [v.kind for v in molrec.compare.diff([0.0, 0.5, 1.0], np.array([0.0, 0.5, 2.0]))] == [
        "value_mismatch"
    ]


def test_a_list_in_the_model_holds_an_array_to_its_element_types() -> None:
    assert [v.kind for v in molrec.compare.diff([True, False], np.array([1, 0]))] == [
        "wrong_type",
        "wrong_type",
    ]


def test_an_array_of_another_width_is_a_violation() -> None:
    expected = np.array([1, 2], dtype="int32")
    [violation] = molrec.compare.diff(expected, expected.astype("int64"))
    assert violation.kind == "wrong_type"


def test_an_array_as_a_list_of_another_shape_is_a_violation() -> None:
    [violation] = molrec.compare.diff(np.zeros((2, 3)), [[0.0, 0.0, 0.0]])
    assert violation.kind == "wrong_shape"


def test_every_string_spelling_is_one_element_type() -> None:
    assert molrec.compare.diff(np.array(["H", "O"]), np.array(["H", "O"], dtype=object)) == ()


def test_nan_equals_nan() -> None:
    assert molrec.compare.diff(float("nan"), float("nan")) == ()
    assert molrec.compare.diff({"t": float("nan")}, {"t": np.float64("nan")}) == ()


def test_bool_int_and_float_are_distinct() -> None:
    assert [v.kind for v in molrec.compare.diff(1, True)] == ["wrong_type"]
    assert [v.kind for v in molrec.compare.diff(True, 1)] == ["wrong_type"]
    assert [v.kind for v in molrec.compare.diff(1, 1.0)] == ["wrong_type"]
    assert [v.kind for v in molrec.compare.diff(1.0, 1)] == ["wrong_type"]
    assert [v.kind for v in molrec.compare.diff("1", 1)] == ["wrong_type"]


def test_numpy_scalars_are_their_python_kind() -> None:
    assert molrec.compare.diff(3, np.int32(3)) == ()
    assert molrec.compare.diff(0.5, np.float64(0.5)) == ()
    assert molrec.compare.diff(True, np.bool_(True)) == ()


def test_a_meta_document_keeps_its_value_types() -> None:
    expected = molrec.core.model.FrameModel(meta={"source": {"tool": "molrec", "run": 3}})
    actual = {
        "blocks": {},
        "box": None,
        "meta": {"source": {"tool": "molrec", "run": 3.0}},
        "meta_types": {"source": "json"},
    }
    assert [v.path for v in molrec.compare.diff(expected, actual)] == ["/meta/source/run"]


def test_a_mapping_duck_is_read_by_key() -> None:
    """``values`` is a column field and also a ``dict`` method; the key must win."""
    expected = molrec.core.model.ColumnModel(
        dtype="f64", shape=(3,), values=np.array([0.0, 1.5, 3.0])
    )
    duck = {"dtype": "f64", "shape": (3,), "values": np.array([0.0, 1.5, 3.0])}
    assert molrec.compare.diff(expected, duck) == ()


def test_a_field_absent_from_a_duck_is_missing_unless_the_model_holds_none() -> None:
    expected = molrec.core.model.BoxModel(vectors=np.eye(3))
    duck = {"vectors": np.eye(3), "boundary": (True, True, True), "cell_defined": True}
    assert [(v.kind, v.path) for v in molrec.compare.diff(expected, duck)] == [
        ("missing_field", "/origin")
    ]
    assert (
        molrec.compare.diff(
            molrec.core.model.FrameModel(), {"blocks": {}, "meta": {}, "meta_types": {}}
        )
        == ()
    )
