"""Storage bases for the observables module.

Append semantics while a run is live, dense arrays once it has settled --
which is why this module has two backends rather than one.
"""

from __future__ import annotations

from molrec.storage import Storage


class ObservableStorage(Storage):
    """Where one observables section lands."""
