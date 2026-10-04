"""Observables: named quantities as functions of their coordinates.

DRAFT (v2 proposal) — the v1 record ``observables/`` contract is the
kind-based layout in ``docs/spec/observables.md``; see the note in
:mod:`molrec.draft.observables.model`.

Importing this package registers the observables suite, bench, and bindings.
"""

from molrec.draft.observables import bench as _bench  # noqa: F401
from molrec.draft.observables import bindings as _bindings  # noqa: F401
from molrec.draft.observables import suite as _suite  # noqa: F401
from molrec.draft.observables.adapter import ObservableAdapter
from molrec.draft.observables.model import (
    Array,
    ObservableModel,
    ObservablesModel,
    Source,
)
from molrec.draft.observables.store import ObservableStore
from molrec.safe_name import original_name, safe_name

__all__ = [
    "Array",
    "ObservableAdapter",
    "ObservableModel",
    "ObservableStore",
    "ObservablesModel",
    "Source",
    "original_name",
    "safe_name",
]
