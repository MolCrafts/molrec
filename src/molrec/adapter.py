"""Adapter -- the only thing an implementation author writes.

Two methods per module, and both directions are exercised:

* ``write(model, storage)`` -- build your own object from the model, serialize
  it your way. The suite then reads the storage back with the official codec.
* ``read(storage)`` -- the suite wrote a canonical storage with the official
  codec; hand back something shaped like the model.

``read`` may return anything duck-compatible: a dict, a dataclass, your own
native object. It is compared *as returned*, before any model validation
could fill a default, carry a block forward or resolve a fill on its behalf:
a reader hands back every value the model holds (a field the model holds as
``None`` may be left out). Only then is it validated with
``from_attributes=True``. What it must *not* do is assert -- every assertion
belongs to the suite.

A negative case is passed only by a *refusal*: a :class:`~molrec.refusal.Refusal`, or
an exception of a type the adapter declares in ``refusal_types``. Any other
exception is a defect and is reported as ``error``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from molrec.storage import Storage


class Adapter(ABC):
    """Bridge between one implementation and one module of the contract."""

    module: ClassVar[str]
    backends: ClassVar[tuple[str, ...]] = ()
    #: The native exception types the implementation refuses malformed input
    #: with (``(ValueError,)`` for most Python bindings). The harness counts
    #: them, and :class:`~molrec.refusal.Refusal`, as a refusal; nothing else.
    refusal_types: ClassVar[tuple[type[Exception], ...]] = ()
    #: Case ids this adapter declares out of its implementation's scope, each
    #: with the reason (the API the implementation lacks). The harness reports
    #: them as ``skip`` with that reason -- never as a pass -- and judges every
    #: other case. A case id prefixed by a module's own wrapping (``frame/``
    #: in the record suite) is matched as written.
    unsupported: ClassVar[dict[str, str]] = {}

    @abstractmethod
    def write(self, model: BaseModel, storage: Storage) -> None:
        """Serialize ``model`` into ``storage`` using the implementation."""

    @abstractmethod
    def read(self, storage: Storage) -> Any:
        """Read ``storage`` and return something shaped like the module's model."""


class Implementation:
    """An implementation's identity plus the adapters it provides.

    Declare adapters as class attributes. A module with no adapter is skipped
    wholesale -- an implementation is never penalized for scope it never
    claimed.

        class Molrs(Implementation):
            name    = "molrs"
            version = importlib.metadata.version("molcrafts-molrs")
            record  = MolrsRecordAdapter()
    """

    name: ClassVar[str] = "unnamed"
    version: ClassVar[str] = "0"

    def adapters(self) -> dict[str, Adapter]:
        """Collect declared adapters, keyed by module. Subclass wins over base."""
        found: dict[str, Adapter] = {}
        for klass in type(self).__mro__:
            for value in vars(klass).values():
                if isinstance(value, Adapter):
                    found.setdefault(value.module, value)
        return found
