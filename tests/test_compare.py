"""What ``molrec.diff`` must catch. Mirrors ``src/molrec/compare.py``.

``_diff_model`` (``compare.py:44-57``) walks ``type(expected).model_fields``.
Every model that carries unknown content is ``extra="allow"`` -- ``MetaModel``,
``RecordModel``, ``FrameModel``, ``BlockModel`` -- and an extra key lives in
``__pydantic_extra__``, never in ``model_fields``. So the keys the contract
exists to protect are the exact keys the comparator does not look at:
``MetaModel``'s docstring calls ``extra="allow"`` "the preserve-the-unknown
invariant", and ``RecordSuite``'s ``meta-unknown-keys-preserved`` case
(``core/suite.py:344``) is built from ``creator`` and ``x_vendor_local``
alone -- so today an implementation may drop both and still pass that case.

``_diff_mapping`` already states the rule these tests hold models to, in both
directions (``compare.py:60-85``): a lost key and an invented key are equally
a round-trip failure.
"""

from __future__ import annotations

import molrec


def _meta(**extras: object) -> molrec.MetaModel:
    """A valid meta document plus whatever unknown keys the case needs."""
    return molrec.MetaModel.model_validate({"molrec_version": 1, **extras})


def test_an_extra_key_whose_value_changed_is_a_violation() -> None:
    violations = molrec.diff(_meta(creator="molrec-suite"), _meta(creator="somebody-else"))

    assert [v.path for v in violations] == ["/creator"]


def test_a_dropped_extra_key_is_a_violation() -> None:
    """ "A reader must keep keys it does not recognize" -- with teeth."""
    violations = molrec.diff(_meta(creator="molrec-suite"), _meta())

    assert [v.path for v in violations] == ["/creator"]


def test_an_invented_extra_key_is_a_violation() -> None:
    """An implementation must not manufacture content either."""
    violations = molrec.diff(_meta(), _meta(x_vendor_local="invented"))

    assert [v.path for v in violations] == ["/x_vendor_local"]


def test_identical_extras_are_not_a_violation() -> None:
    """The guard on the fix: a key that did survive must stay silent."""
    assert molrec.diff(_meta(creator="molrec-suite"), _meta(creator="molrec-suite")) == ()


def test_an_extra_key_below_the_root_is_reached() -> None:
    """The suite compares records, not bare metas, so the walk has to recurse."""
    expected = molrec.RecordModel(
        meta=_meta(creator={"name": "molrec-suite", "version": "0.1.0"}),
        frame=molrec.FrameModel(),
    )
    actual = molrec.RecordModel(meta=_meta(), frame=molrec.FrameModel())

    assert [v.path for v in molrec.diff(expected, actual)] == ["/meta/creator"]
