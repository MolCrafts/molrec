"""Observables: named quantities as functions of their coordinates.

DRAFT (v2 proposal) — the v1 record ``observables/`` contract is the
kind-based layout in ``docs/spec/observables.md``; see the note in
:mod:`molrec.observables.model`.

Importing this package registers the observables suite, bench, and bindings.
"""

from molrec.observables import bench as _bench  # noqa: F401
from molrec.observables import bindings as _bindings  # noqa: F401
from molrec.observables import suite as _suite  # noqa: F401
from molrec.observables.adapter import ObservableAdapter
from molrec.observables.model import (
    Array,
    ObservableModel,
    ObservablesModel,
    Source,
)
from molrec.observables.safe_name import original_name, safe_name
from molrec.observables.store import ObservableStore

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
