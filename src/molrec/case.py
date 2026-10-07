"""Case -- one conformance example."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Case[M: BaseModel](BaseModel):
    """A model instance plus what it is meant to catch.

    ``expect_violation`` marks a negative case: the implementation is required
    to reject the input, and a run that quietly accepts it fails. Building one
    usually means ``model_construct()``, since the models enforce the very
    invariant the case is trying to break.

    ``rejects_on`` says which door must refuse. ``"read"`` (the default): the
    official codec lays the content down and the implementation must refuse
    to read it. ``"write"``: the implementation must refuse to write it at all
    -- the right direction for a rule the layout places on the writer, such as
    a reserved name refused at declaration or a step number that does not
    increase.

    ``tamper`` runs after the codec has written a read-direction case, on the
    storage itself. It is how something the models cannot express -- a
    non-monotonic ``offset``, a float column narrowed to binary32 -- reaches
    the reader under test.

    ``expected`` is what a conforming reader hands back from the storage this
    case lays down, when that is not ``model`` itself: a tamper may remove
    what the codec wrote. ``None`` means ``model``.

    ``directions`` scopes a positive case to the directions it can honestly
    run in: a storage only a tamper can produce has no write direction.

    ``backends`` scopes a case to the backends it can honestly run on. Not
    every backend carries every payload -- a dense numeric series cannot hold
    an image reference -- and pretending otherwise would either fail a
    conforming implementation or force a backend to grow an encoding the spec
    never asked for. Empty means every backend.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str
    model: M
    exercises: str = ""
    expect_violation: str = ""
    rejects_on: Literal["read", "write"] = "read"
    tamper: Callable[[Any], None] | None = None
    backends: tuple[str, ...] = ()
    expected: M | None = None
    directions: tuple[Literal["write", "read"], ...] = ("write", "read")

    @property
    def judged_against(self) -> M:
        """The model a reader's answer is compared with."""
        return self.model if self.expected is None else self.expected

    def applies_to(self, backend: str) -> bool:
        return not self.backends or backend in self.backends
