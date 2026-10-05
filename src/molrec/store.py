"""Store -- where one serialization lands.

A Store is created, reused, and destroyed by the suite. An adapter only uses
it; it never manages the lifecycle, never builds a path, never cleans up.

Two axes:

* **module axis** -- ``FrameStore`` / ``TrajectoryStore`` / ``RecordStore``
  / ``CollectionStore`` / ``ObservableStore``. Different modules have
  genuinely different access semantics (an array tree is not an append-only
  stream), so each declares its own abstract base.

* **backend axis** -- ``ZarrStore`` subclasses, ``LmdbCollectionStore``, the
  draft's ``JsonlObservableStore``. The handle is backend-specific and typed,
  so there is deliberately no universal handle on the base to paper over the
  difference.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar


class Store(ABC):
    """One serialization target, owned by the suite."""

    backend: ClassVar[str]

    @abstractmethod
    def clear(self) -> None:
        """Drop all content so the suite can reuse this store for the next case."""

    def close(self) -> None:
        """Release backend resources. No-op unless a backend needs it."""
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} backend={self.backend!r}>"
