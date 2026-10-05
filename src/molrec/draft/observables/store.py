"""Store bases for the observables module.

Append semantics while a run is live, dense arrays once it has settled --
which is why this module has two backends rather than one.
"""

from __future__ import annotations

from molrec.store import Store


class ObservableStore(Store):
    """Where one observables section lands."""
