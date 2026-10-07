"""Containers and the record root.

Each symbol is its owner module's: the models in :mod:`molrec.core.model`,
the adapters in :mod:`molrec.core.adapter`, the storage classes in
:mod:`molrec.core.storage`. Importing this package registers the core suite,
bench, and bindings.
"""

from molrec.core import adapter, bench, bindings, ffsuite, model, storage, suite

__all__ = ["adapter", "bench", "bindings", "ffsuite", "model", "storage", "suite"]
