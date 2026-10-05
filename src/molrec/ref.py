"""Ref -- a pointer from one record into another.

Without it every section is an island: a derived quantity cannot say what it
was derived from, a system cannot cite the parameter set it was typed with,
and a dataset cannot point at the configurations it indexes. One small type
turns a pile of sections into a graph.

``hash`` is optional but strongly recommended. A URI says *where* something
was; a content hash says *what* it was, and only the second survives a file
being moved, regenerated, or silently edited.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from molrec.core.model import DocumentModel

RefKind = Literal["record", "section", "frame", "block", "observable", "sample"]


class Ref(DocumentModel):
    """A resolvable pointer.

    ``select`` narrows the target: ``{"frame": 12}`` for one frame of a
    trajectory, ``{"rows": [0, 5]}`` for part of a block. Its keys are the
    target kind's business, not this type's.
    """

    uri: str = Field(min_length=1)
    hash: str | None = None
    kind: RefKind | None = None
    select: dict[str, Any] = Field(default_factory=dict)
