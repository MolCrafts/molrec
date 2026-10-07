"""Adapter base for the observables module."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from molrec.adapter import Adapter
from molrec.observables.model import (
    ObservablesModel,
)
from molrec.observables.storage import ObservableStorage


class ObservableAdapter(Adapter):
    """Implement this to have your ``observables`` section judged.

    The storage is a record root holding ``meta`` and ``observables``; ``read``
    hands back something shaped like :class:`ObservablesModel`.
    """

    module: ClassVar[str] = "observables"

    @abstractmethod
    def write(self, model: ObservablesModel, storage: ObservableStorage) -> None: ...

    @abstractmethod
    def read(self, storage: ObservableStorage) -> Any: ...
