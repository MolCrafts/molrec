"""Refusal -- the one exception a negative case accepts as an answer.

A negative case asks an implementation to *refuse* malformed input. Counting
any exception as that refusal makes the suite unfalsifiable: an adapter whose
``read`` and ``write`` raise ``NotImplementedError`` would pass every negative
case it was handed. So a refusal is typed:

* raise :class:`Refusal` (optionally with the ``kind`` the case expects, from
  the same vocabulary as ``Case.expect_violation``), or
* declare the native exception types the implementation refuses with on the
  adapter (``refusal_types = (ValueError,)``) and let the harness translate
  them with :func:`as_refusal`.

Anything else an adapter raises is a defect, reported as ``error`` and never
as ``pass``. The exceptions in :data:`DEFECTS` are defects even when declared:
they say the adapter or the implementation is broken, not that the input was.
"""

from __future__ import annotations


class Refusal(Exception):
    """An implementation deliberately refused its input.

    ``kind`` names the rule the input broke, in the vocabulary of
    ``Case.expect_violation`` (``"reserved_block_name"``,
    ``"step_not_increasing"``, ...). When it is given, the suite holds it to
    the case's expectation; a refusal for the wrong reason is a failure.
    """

    def __init__(self, message: str = "", *, kind: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind


#: Exceptions that signal a broken adapter or implementation, never a refusal:
#: a missing attribute, an unimplemented door, a failed internal assertion, a
#: wrongly typed call. Declaring one of them in ``refusal_types`` does not
#: turn it into a refusal.
DEFECTS: tuple[type[BaseException], ...] = (
    AssertionError,
    AttributeError,
    ImportError,
    MemoryError,
    NameError,
    NotImplementedError,
    RecursionError,
    SyntaxError,
    TypeError,
)


def as_refusal(
    exc: BaseException, declared: tuple[type[BaseException], ...] = ()
) -> Refusal | None:
    """``exc`` as a :class:`Refusal`, or ``None`` when it is not one.

    A :class:`Refusal` is itself. An exception of a type in ``declared`` (and
    not in :data:`DEFECTS`) becomes a kind-less refusal carrying its message.
    Everything else is not a refusal.
    """
    if isinstance(exc, Refusal):
        return exc
    if isinstance(exc, DEFECTS) or not declared or not isinstance(exc, declared):
        return None
    refusal = Refusal(f"{type(exc).__name__}: {exc}")
    refusal.__cause__ = exc
    return refusal
