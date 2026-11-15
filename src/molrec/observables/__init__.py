"""The ``observables`` section: named results, each a kind plus an array.

Each symbol is its owner module's: the models in
:mod:`molrec.observables.model`, the adapter in
:mod:`molrec.observables.adapter`, the storage in
:mod:`molrec.observables.storage`. Importing this package registers the
observables suite and binding. The dims-based redesign is the draft in
:mod:`molrec.draft.observables`.
"""

from molrec.observables import adapter, bindings, model, storage, suite

__all__ = ["adapter", "bindings", "model", "storage", "suite"]
