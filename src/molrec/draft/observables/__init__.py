"""Observables: named quantities as functions of their coordinates.

DRAFT (a proposal) — the record's ``observables/`` contract is the
kind-based layout in ``docs/spec/observables.md``; see the note in
:mod:`molrec.draft.observables.model`.

Each symbol is its owner module's (:mod:`~molrec.draft.observables.model`,
``adapter``, ``store``; the safe-name codec is :mod:`molrec.safe_name`'s).
Importing this package registers the observables suite, bench, and bindings.
"""

from molrec.draft.observables import adapter, bench, bindings, model, store, suite

__all__ = ["adapter", "bench", "bindings", "model", "store", "suite"]
