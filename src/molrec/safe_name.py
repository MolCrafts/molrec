"""Percent-encoding: the one codec behind every name a key cannot be verbatim.

Two names need it. A metrics series key is slash-separated and has to become
one array name under ``metrics/series/`` (its *safe name*); a force-field
style (``lj/cut``) has to become part of its table's block name
(``pair.lj%2Fcut``). A spec that referred to a mangling without defining one
would get two manglings from two implementations and stores neither could
read, so both are the same rule over a different set of bytes kept verbatim:
every byte of the UTF-8 text outside the set is written ``%XX`` with
uppercase hex.

The series rule (``docs/spec/metrics.md``) keeps ``[A-Za-z0-9._-]``. A result
Zarr would refuse as a node name -- ``.``, ``..``, or one starting with
``__`` -- has its first byte escaped too. Total over non-empty keys,
reversible, a dozen lines in any language.
"""

from __future__ import annotations

import string

#: The bytes a series key keeps verbatim in its safe name.
SERIES_UNRESERVED: frozenset[int] = frozenset(
    (string.ascii_letters + string.digits + "._-").encode("ascii")
)

_HEX = frozenset("0123456789ABCDEF")


def percent_encode(text: str, unreserved: frozenset[int]) -> str:
    """``text`` with every byte of its UTF-8 outside ``unreserved`` written
    ``%XX`` (uppercase hex)."""
    return "".join(
        chr(byte) if byte in unreserved else f"%{byte:02X}" for byte in text.encode("utf-8")
    )


def percent_decode(encoded: str, unreserved: frozenset[int]) -> str:
    """The inverse of :func:`percent_encode`: every ``%XX`` (uppercase hex) is
    one byte and every other character must be a byte of ``unreserved``. A
    malformed escape, or a character that should have been escaped, is
    refused. Whether a byte of ``unreserved`` was escaped needlessly is the
    caller's rule (a safe name escapes one on purpose)."""
    raw = bytearray()
    index = 0
    while index < len(encoded):
        char = encoded[index]
        if char == "%":
            digits = encoded[index + 1 : index + 3]
            if len(digits) != 2 or not set(digits) <= _HEX:
                raise ValueError(f"{encoded!r}: {encoded[index : index + 3]!r} is no %XX escape")
            raw.append(int(digits, 16))
            index += 3
            continue
        if not char.isascii() or ord(char) not in unreserved:
            raise ValueError(f"{encoded!r}: {char!r} is written as a %XX escape")
        raw.append(ord(char))
        index += 1
    return raw.decode("utf-8")


def safe_name(name: str) -> str:
    """``train/loss`` -> ``train%2Floss``; ``.`` -> ``%2E``; ``__x`` -> ``%5F_x``."""
    if not name:
        raise ValueError("the empty string is not a series key")
    encoded = percent_encode(name, SERIES_UNRESERVED)
    if encoded in (".", "..") or encoded.startswith("__"):
        encoded = f"%{ord(encoded[0]):02X}{encoded[1:]}"
    return encoded


def original_name(encoded: str) -> str:
    """The inverse of :func:`safe_name`; a malformed escape is refused."""
    return percent_decode(encoded, SERIES_UNRESERVED)
