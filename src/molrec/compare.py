"""Model comparison -- never byte comparison.

Chunk size, codec, compression level, attribute key order and sharding are
all legitimate implementation freedom: two conforming stores *should* differ
at the byte level. So conformance is judged where the contract actually lives
-- on the model a conforming reader reconstructs.

The walk yields located violations rather than a bare ``False``, because
someone fixing a file wants the whole list, not one round trip per field.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from pydantic import BaseModel

from molrec.arrays import arrays_equal
from molrec.report import Violation


def diff(expected: Any, actual: Any, path: str = "") -> tuple[Violation, ...]:
    """Every way ``actual`` departs from ``expected``."""
    if isinstance(expected, BaseModel):
        return _diff_model(expected, actual, path)
    if isinstance(expected, Mapping):
        return _diff_mapping(expected, actual, path)
    # An array on either side has to be routed here. An implementation that
    # supplies a value where the model has none is as much a difference as one
    # that drops a value, and `None == ndarray` is a ValueError rather than an
    # answer.
    if isinstance(expected, np.ndarray) or isinstance(actual, np.ndarray):
        return _diff_array(expected, actual, path)
    if isinstance(expected, (list, tuple)):
        return _diff_sequence(expected, actual, path)
    return _diff_scalar(expected, actual, path)


def lookup(value: Any, name: str, default: Any = None) -> Any:
    """``value.name`` or ``value[name]`` -- however the duck spells it -- else ``default``."""
    try:
        return getattr(value, name)
    except AttributeError:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return default


def _at(path: str, key: Any) -> str:
    return f"{path}/{key}" if path else f"/{key}"


def _diff_model(expected: BaseModel, actual: Any, path: str) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for name in type(expected).model_fields:
        want = getattr(expected, name)
        try:
            got = getattr(actual, name)
        except AttributeError:
            if isinstance(actual, Mapping) and name in actual:
                got = actual[name]
            elif want is None:
                # Absent is how a duck says "none here" -- a record without a
                # status section, a series without a fill. Only a field the
                # model actually holds has to be handed back.
                continue
            else:
                found.append(Violation(kind="missing_field", path=_at(path, name), detail="absent"))
                continue
        found.extend(diff(want, got, _at(path, name)))
    found.extend(_diff_extras(expected, actual, path))
    return tuple(found)


def _extras(value: Any, declared: frozenset[str]) -> dict[str, Any]:
    """The unknown keys a value carries -- the ones ``model_fields`` misses."""
    if isinstance(value, BaseModel):
        return dict(value.__pydantic_extra__ or {})
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if key not in declared}
    return {}


def _diff_extras(expected: BaseModel, actual: Any, path: str) -> tuple[Violation, ...]:
    """Hold ``extra="allow"`` to what it promises.

    Unknown keys live in ``__pydantic_extra__``, never in ``model_fields``, so
    the field walk above goes straight past the very keys the contract exists
    to protect -- ``MetaModel`` calls ``extra="allow"`` "the preserve-the-
    unknown invariant", and without this an implementation could drop every
    one of them and still pass.

    Compared in both directions, for the reason ``_diff_mapping`` already
    gives: a lost key and an invented key are equally a roundtrip failure.
    """
    declared = frozenset(type(expected).model_fields)
    return _diff_mapping(_extras(expected, declared), _extras(actual, declared), path)


def _diff_mapping(expected: Mapping, actual: Any, path: str) -> tuple[Violation, ...]:
    if not isinstance(actual, Mapping):
        return (
            Violation(
                kind="wrong_type",
                path=path,
                detail=f"expected a mapping, found {type(actual).__name__}",
            ),
        )

    found: list[Violation] = []
    for key, want in expected.items():
        if key not in actual:
            found.append(Violation(kind="missing_key", path=_at(path, key), detail="absent"))
            continue
        found.extend(diff(want, actual[key], _at(path, key)))

    # Invariant 8 runs the other way too: an implementation must not invent
    # content, and an unexpected key is as much a roundtrip failure as a lost
    # one.
    for key in actual:
        if key not in expected:
            found.append(
                Violation(kind="unexpected_key", path=_at(path, key), detail="not in the model")
            )
    return tuple(found)


def _diff_array(expected: Any, actual: Any, path: str) -> tuple[Violation, ...]:
    if expected is None:
        return (
            Violation(
                kind="unexpected_values",
                path=path,
                detail="the model carries nothing here",
            ),
        )
    if actual is None:
        return (Violation(kind="missing_values", path=path, detail="no array"),)
    if not isinstance(expected, np.ndarray):
        # The model holds plain values here (a per-step vector, a fill) and
        # the implementation handed back an array. The plain values carry no
        # numpy dtype to hold the array to, so it is judged element by
        # element, each scalar's type included.
        return diff(expected, np.asarray(actual).tolist(), path)
    try:
        got = actual if isinstance(actual, np.ndarray) else np.asarray(actual)
    except (TypeError, ValueError) as exc:
        return (Violation(kind="wrong_type", path=path, detail=f"not an array: {exc}"),)
    if got.shape != expected.shape:
        return (
            Violation(
                kind="wrong_shape",
                path=path,
                detail=f"expected {expected.shape}, found {got.shape}",
            ),
        )
    if _element_type(got.dtype) != _element_type(expected.dtype):
        return (
            Violation(
                kind="wrong_type",
                path=path,
                detail=f"expected {expected.dtype}, found {got.dtype}",
            ),
        )
    if not arrays_equal(expected, got):
        return (Violation(kind="value_mismatch", path=path, detail="array contents differ"),)
    return ()


def _element_type(dtype: np.dtype) -> str:
    """The width-exact element type of an array -- every numpy string spelling is one."""
    return "string" if dtype.kind in ("U", "T", "O", "S") else dtype.name


def _equal(expected: Any, actual: Any) -> bool:
    """Equality that survives whatever an adapter hands back.

    A duck may return a numpy scalar, a masked value, or an object whose
    ``__eq__`` raises. None of that is a reason for the harness to crash --
    an answer it cannot compute is simply "not equal".
    """
    try:
        return bool(expected == actual)
    except (ValueError, TypeError):
        return False


def _diff_sequence(expected: Any, actual: Any, path: str) -> tuple[Violation, ...]:
    if actual is None or isinstance(actual, (str, bytes, Mapping)):
        return (
            Violation(
                kind="wrong_type",
                path=path,
                detail=f"expected a sequence, found {type(actual).__name__}",
            ),
        )
    try:
        got = list(actual)
    except TypeError:
        return (
            Violation(
                kind="wrong_type",
                path=path,
                detail=f"expected a sequence, found {type(actual).__name__}",
            ),
        )
    want = list(expected)
    if len(got) != len(want):
        return (
            Violation(
                kind="wrong_length",
                path=path,
                detail=f"expected {len(want)}, found {len(got)}",
            ),
        )
    found: list[Violation] = []
    for index, (want_item, got_item) in enumerate(zip(want, got, strict=True)):
        found.extend(diff(want_item, got_item, _at(path, index)))
    return tuple(found)


def _scalar_type(value: Any) -> str | None:
    """The contract-level type of a scalar, or ``None`` for anything else.

    ``bool`` is not an ``int`` here and an ``int`` is not a ``float``: Python
    says ``1 == True == 1.0``, and an equality that agrees would let an
    implementation turn a flag into a count or a count into a measurement
    without a word. numpy scalars are their Python kind.
    """
    if value is None:
        return "null"
    if isinstance(value, (bool, np.bool_)):
        return "bool"
    if isinstance(value, (int, np.integer)):
        return "int"
    if isinstance(value, (float, np.floating)):
        return "float"
    if isinstance(value, (complex, np.complexfloating)):
        return "complex"
    if isinstance(value, (str, np.str_)):
        return "string"
    if isinstance(value, bytes):
        return "bytes"
    return None


def _both_nan(expected: Any, actual: Any) -> bool:
    """NaN is not equal to itself, but a round trip that kept a NaN kept it."""
    try:
        return bool(np.isnan(expected)) and bool(np.isnan(actual))
    except (TypeError, ValueError):
        return False


def _diff_scalar(expected: Any, actual: Any, path: str) -> tuple[Violation, ...]:
    want, got = _scalar_type(expected), _scalar_type(actual)
    if want is not None and got is not None and want != got:
        return (
            Violation(
                kind="wrong_type",
                path=path,
                detail=f"expected {want} {expected!r}, found {got} {actual!r}",
            ),
        )
    if want in ("float", "complex") and _both_nan(expected, actual):
        return ()
    if _equal(expected, actual):
        return ()
    return (
        Violation(
            kind="value_mismatch", path=path, detail=f"expected {expected!r}, found {actual!r}"
        ),
    )
