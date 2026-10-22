"""Declared precision: the one rounding a writer applies (``docs/spec/frame.md``).

An ``f64`` column may declare an absolute tolerance ``p``. The writer stores
every value rounded to the **quantum** ``q`` -- the largest power of two not
above ``p`` -- with round-half-to-even, so the discarded low mantissa bits are
zeros a byte shuffle and a lossless compressor remove. Both steps are exact in
binary64 (``q`` is a power of two), so two writers storage the same bits.

A reader does nothing with ``p``: it returns the stored values exactly.
"""

from __future__ import annotations

import math

import numpy as np

#: The bounds of a declared precision: they keep ``q`` a normal binary64 and
#: ``x / q`` exact.
PRECISION_MIN: float = 2.0**-1000
PRECISION_MAX: float = 2.0**1000

#: Above ``2**52 * q`` every binary64 is already an integer multiple of ``q``.
_EXACT = 2.0**52


def check_precision(precision: float) -> float:
    """``precision`` if it is a finite binary64 in ``[2**-1000, 2**1000]``."""
    value = float(precision)
    if not (math.isfinite(value) and PRECISION_MIN <= value <= PRECISION_MAX):
        raise ValueError(
            f"a precision is a finite number in [2**-1000, 2**1000], found {precision!r}"
        )
    return value


def quantum(precision: float) -> float:
    """``2**(e-1)`` for ``precision = m * 2**e``, ``0.5 <= m < 1`` (:func:`math.frexp`):
    the largest power of two not above ``precision``."""
    _, exponent = math.frexp(check_precision(precision))
    return math.ldexp(1.0, exponent - 1)


def quantize(values: np.ndarray, precision: float) -> np.ndarray:
    """``stored(x)`` of the declared-precision rule, elementwise, as ``float64``.

    NaN, the infinities and any ``|x| >= 2**52 * q`` are kept as they are;
    every other value becomes ``roundTiesToEven(x / q) * q``. ``np.round`` is
    round-half-to-even, and ``x / q`` and ``k * q`` are exact.
    """
    q = quantum(precision)
    array = np.asarray(values, dtype="float64")
    with np.errstate(invalid="ignore", over="ignore"):
        rounded = np.round(array / q) * q
        keep = ~np.isfinite(array) | (np.abs(array) >= _EXACT * q)
    return np.where(keep, array, rounded)


def on_grid(values: np.ndarray, precision: float) -> bool:
    """Whether every finite value is an integer multiple of ``quantum(precision)``
    -- the check a validator runs; a reader never does."""
    array = np.asarray(values, dtype="float64")
    return bool(np.array_equal(quantize(array, precision), array, equal_nan=True))
