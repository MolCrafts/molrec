"""The v1 ``observables`` section: named results, each a kind plus an array.

Importing this package registers the observables suite and binding. The
dims-based redesign is the draft in :mod:`molrec.draft.observables`.
"""

from molrec.core.model import (
    KNOWN_KINDS,
    ArrayModel,
    ObservableMetaModel,
    ObservableModel,
    ObservablesModel,
)
from molrec.observables import bindings as _bindings  # noqa: F401
from molrec.observables import suite as _suite  # noqa: F401
from molrec.observables.adapter import ObservableAdapter
from molrec.observables.store import ObservableStore

__all__ = [
    "KNOWN_KINDS",
    "ArrayModel",
    "ObservableAdapter",
    "ObservableMetaModel",
    "ObservableModel",
    "ObservableStore",
    "ObservablesModel",
]
