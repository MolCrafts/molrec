"""Observable names are slash-separated; array names cannot be.

``train/loss`` and ``structure/rdf`` have to become array names, and a spec
that referred to a ``safe_name`` function without defining one would get two
manglings from two implementations and stores neither could read.

The rule: percent-encode every byte outside ``[A-Za-z0-9._-]`` as ``%XX``
with uppercase hex. Total, reversible, a dozen lines in any language.
"""

from __future__ import annotations

import string

_UNRESERVED = frozenset(string.ascii_letters + string.digits + "._-")


def safe_name(name: str) -> str:
    """``train/loss`` -> ``train%2Floss``."""
    encoded: list[str] = []
    for byte in name.encode("utf-8"):
        character = chr(byte)
        encoded.append(character if character in _UNRESERVED else f"%{byte:02X}")
    return "".join(encoded)


def original_name(encoded: str) -> str:
    """The inverse of :func:`safe_name`."""
    raw = bytearray()
    index = 0
    while index < len(encoded):
        if encoded[index] == "%":
            raw.append(int(encoded[index + 1 : index + 3], 16))
            index += 3
            continue
        raw.extend(encoded[index].encode("utf-8"))
        index += 1
    return raw.decode("utf-8")
