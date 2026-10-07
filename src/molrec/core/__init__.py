"""Containers and the record root.

Each symbol is its owner module's: the models in :mod:`molrec.core.model`,
the adapters in :mod:`molrec.core.adapter`, the stores in
:mod:`molrec.core.store`. Importing this package registers the core suite,
bench, and bindings.
"""

from molrec.core import adapter, bench, bindings, ffsuite, model, store, suite, v1

__all__ = ["adapter", "bench", "bindings", "ffsuite", "model", "store", "suite", "v1"]
