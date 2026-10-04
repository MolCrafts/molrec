"""Adapter bases for the core module."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from molrec.adapter import Adapter
from molrec.core.model import CollectionModel, FrameModel, RecordModel, TrajectoryModel
from molrec.core.store import CollectionStore, FrameStore, RecordStore, TrajectoryStore


class FrameAdapter(Adapter):
    """Implement this to have your frame serialization judged.

        class MolrsFrameAdapter(molrec.FrameAdapter):
            backends = ("zarr",)

            def write(self, model, store):
                molrs.write_frame(self._build(model), store.uri)

            def read(self, store):
                return self._describe(molrs.read_frame(store.uri))

    ``read`` may return any duck shaped like ``FrameModel``.
    """

    module: ClassVar[str] = "core"

    @abstractmethod
    def write(self, model: FrameModel, store: FrameStore) -> None: ...

    @abstractmethod
    def read(self, store: FrameStore) -> Any: ...


class TrajectoryAdapter(Adapter):
    """Same contract for a sequence of frames.

    What ``read`` hands back is the *logical* sequence -- the frames, their
    step numbers, their cell updates. How an implementation indexed them on
    disk is its own business and is never compared.
    """

    module: ClassVar[str] = "trajectory"

    @abstractmethod
    def write(self, model: TrajectoryModel, store: TrajectoryStore) -> None: ...

    @abstractmethod
    def read(self, store: TrajectoryStore) -> Any: ...


class RecordAdapter(Adapter):
    """Same contract, one level up: the whole record root."""

    module: ClassVar[str] = "record"

    @abstractmethod
    def write(self, model: RecordModel, store: RecordStore) -> None: ...

    @abstractmethod
    def read(self, store: RecordStore) -> Any: ...


class CollectionAdapter(Adapter):
    """Same contract for many records under one declaration."""

    module: ClassVar[str] = "collection"

    @abstractmethod
    def write(self, model: CollectionModel, store: CollectionStore) -> None: ...

    @abstractmethod
    def read(self, store: CollectionStore) -> Any: ...
