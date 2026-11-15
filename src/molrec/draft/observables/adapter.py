"""Adapter base for the observables module."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from molrec.adapter import Adapter
from molrec.draft.observables.model import ObservablesModel
from molrec.draft.observables.storage import ObservableStorage


class ObservableAdapter(Adapter):
    """Implement this to have your observables judged.

    Declare every backend you support; the suite runs the module once per
    backend and scopes out the cases that backend cannot honestly carry.
    """

    module: ClassVar[str] = "draft/observables"

    @abstractmethod
    def write(self, model: ObservablesModel, storage: ObservableStorage) -> None: ...

    @abstractmethod
    def read(self, storage: ObservableStorage) -> Any: ...
