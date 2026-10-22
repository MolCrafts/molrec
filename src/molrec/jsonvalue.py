"""Typed values in JSON -- the one encoding every binding uses.

JSON has no NaN, no infinity, no complex number, and a reader in a language
whose numbers are binary64 (JavaScript, a wasm viewer) silently rounds an
integer beyond 2^53. A value whose dtype is known -- a per-step ``fill`` in
``sequence_schema``, a per-step value in an LMDB frame header, a value in an
observables WAL row -- is therefore written in a fixed form
(``docs/spec/conventions.md``, typed JSON values):

* ``f64``: a finite value is a JSON number; NaN, +inf and -inf are the strings
  ``"NaN"``, ``"Infinity"`` and ``"-Infinity"``;
* ``c64`` / ``c128``: a two-element array ``[re, im]``, each part an ``f64``;
* an integer whose magnitude exceeds 2^53 is its decimal string; any other
  integer is a JSON number;
* ``bool`` and ``string`` are themselves; a ``json`` value is the document,
  which must itself be finite JSON.

A reader accepts exactly those forms (and an exact JSON integer beyond 2^53,
which is what a writer in a language with 64-bit integers may emit) and
refuses everything else -- a ``null`` where a number is declared is a broken
value, not a NaN. Every document is serialized with ``allow_nan=False``.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

#: The largest integer magnitude every JSON reader holds exactly.
SAFE_INTEGER = 2**53

_NONFINITE = {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}

#: The inclusive range of each integer dtype.
INTEGER_RANGE: dict[str, tuple[int, int]] = {
    **{f"i{bits}": (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) for bits in (8, 16, 32, 64)},
    **{f"u{bits}": (0, 2**bits - 1) for bits in (8, 16, 32, 64)},
}


def plain(value: Any) -> Any:
    """``value`` with every numpy scalar and array turned into its Python twin."""
    if isinstance(value, np.ndarray):
        return [plain(item) for item in value.tolist()] if value.ndim else plain(value.item())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def dumps(document: Any) -> str:
    """One JSON document, compact, never carrying a NaN token."""
    return json.dumps(plain(document), separators=(",", ":"), allow_nan=False)


def check_document(document: Any) -> Any:
    """A ``json`` value: plain, finite JSON, or a ``ValueError``."""
    value = plain(document)
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not a finite JSON document: {exc}") from None
    return value


def coerce(element: str, value: Any) -> Any:
    """``value`` as the Python scalar ``element`` (a column dtype) holds, exactly.

    Refuses rather than rounds: a bool is not an integer, a float is not an
    integer, and an integer outside the dtype's range is not that dtype.
    """
    value = plain(value)
    if element == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"expected a bool, found {value!r}")
        return value
    if element == "string":
        if not isinstance(value, str):
            raise ValueError(f"expected a string, found {value!r}")
        return value
    if element in INTEGER_RANGE:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"expected an integer for {element}, found {value!r}")
        low, high = INTEGER_RANGE[element]
        if not low <= value <= high:
            raise ValueError(f"{value} is out of range for {element}")
        return value
    if element == "f64":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"expected a number for f64, found {value!r}")
        return float(value)
    if element in ("c64", "c128"):
        if isinstance(value, bool) or not isinstance(value, (int, float, complex)):
            raise ValueError(f"expected a number for {element}, found {value!r}")
        return complex(value)
    raise ValueError(f"no element dtype {element!r}")


def encode(element: str, value: Any) -> Any:
    """The JSON form of one ``element`` value (see the module docstring)."""
    value = coerce(element, value)
    if element == "f64":
        return _encode_float(value)
    if element in ("c64", "c128"):
        return [_encode_float(value.real), _encode_float(value.imag)]
    if element in INTEGER_RANGE and abs(value) > SAFE_INTEGER:
        return str(value)
    return value


def decode(element: str, raw: Any) -> Any:
    """The inverse of :func:`encode`; refuses any other form."""
    if element == "f64":
        return _decode_float(raw)
    if element in ("c64", "c128"):
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError(f"{element} is [re, im] in JSON, found {raw!r}")
        return complex(_decode_float(raw[0]), _decode_float(raw[1]))
    if element in INTEGER_RANGE and isinstance(raw, str):
        if not raw.lstrip("-").isdigit():
            raise ValueError(f"{raw!r} is not a decimal integer")
        raw = int(raw)
    return coerce(element, raw)


def same(left: Any, right: Any) -> bool:
    """Value equality that holds a NaN equal to a NaN and a bool apart from an int.

    The comparison a declaration needs: a fill of NaN declared twice is one
    declaration, and a fill of ``True`` is not a fill of ``1``.
    """
    left, right = plain(left), plain(right)
    if type(left) is not type(right):
        return False
    if isinstance(left, float):
        return left == right or (math.isnan(left) and math.isnan(right))
    if isinstance(left, complex):
        return same(left.real, right.real) and same(left.imag, right.imag)
    if isinstance(left, list):
        return len(left) == len(right) and all(map(same, left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same(left[k], right[k]) for k in left)
    return left == right


def _encode_float(value: float) -> Any:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def _decode_float(raw: Any) -> float:
    if isinstance(raw, str):
        if raw not in _NONFINITE:
            raise ValueError(f"{raw!r} is not a number; non-finite f64 is NaN / Infinity")
        return _NONFINITE[raw]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"expected a number for f64, found {raw!r}")
    return float(raw)
