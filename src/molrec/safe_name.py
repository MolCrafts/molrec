"""Series keys are slash-separated; array names cannot be.

``train/loss`` has to become an array name under ``metrics/series/``, and a
spec that referred to a mangling without defining one would get two manglings
from two implementations and stores neither could read.

The rule (``docs/spec/metrics.md``): percent-encode every byte outside
``[A-Za-z0-9._-]`` as ``%XX`` with uppercase hex. A result Zarr would refuse
as a node name -- ``.``, ``..``, or one starting with ``__`` -- has its first
byte escaped too. Total over non-empty keys, reversible, a dozen lines in any
language.
"""

from __future__ import annotations

import string

_UNRESERVED = frozenset(string.ascii_letters + string.digits + "._-")


def safe_name(name: str) -> str:
    """``train/loss`` -> ``train%2Floss``; ``.`` -> ``%2E``; ``__x`` -> ``%5F_x``."""
    if not name:
        raise ValueError("the empty string is not a series key")
    encoded = [
        character if character in _UNRESERVED else f"%{byte:02X}"
        for byte in name.encode("utf-8")
        for character in (chr(byte),)
    ]
    joined = "".join(encoded)
    if joined in (".", "..") or joined.startswith("__"):
        encoded[0] = f"%{ord(encoded[0]):02X}"
    return "".join(encoded)


def original_name(encoded: str) -> str:
    """The inverse of :func:`safe_name`; a malformed escape is refused."""
    raw = bytearray()
    index = 0
    while index < len(encoded):
        if encoded[index] == "%":
            digits = encoded[index + 1 : index + 3]
            if len(digits) != 2 or not all(c in string.hexdigits for c in digits):
                raise ValueError(f"{encoded!r}: bad %-escape at {index}")
            raw.append(int(digits, 16))
            index += 3
            continue
        raw.extend(encoded[index].encode("utf-8"))
        index += 1
    return raw.decode("utf-8")
