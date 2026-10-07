"""Adapter bases for the core module."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from molrec.adapter import Adapter
from molrec.core.model import (
    CollectionModel,
    ForceFieldModel,
    FrameModel,
    RecordModel,
    TrajectoryModel,
)
from molrec.core.storage import (
    CollectionStorage,
    ForceFieldStorage,
    FrameStorage,
    RecordStorage,
    TrajectoryStorage,
)


class FrameAdapter(Adapter):
    """Implement this to have your frame serialization judged.

        class MyFrameAdapter(molrec.core.adapter.FrameAdapter):
            backends = ("zarr",)
            refusal_types = (ValueError,)

            def write(self, model, storage):
                mylib.write_mrec_frame(self._build(model), storage.uri)

            def read(self, storage):
                return self._describe(mylib.read_mrec_frame(storage.uri))

    ``read`` may return any duck shaped like ``FrameModel``. This door is a
    bare frame at a storage root; an implementation that only writes whole
    records (molrs: ``molrs.io.write_mrec_frame`` / ``read_mrec_frame``) is judged on the
    same frame cases through :class:`RecordAdapter`, which runs each of them
    inside a record.
    """

    module: ClassVar[str] = "core"

    @abstractmethod
    def write(self, model: FrameModel, storage: FrameStorage) -> None: ...

    @abstractmethod
    def read(self, storage: FrameStorage) -> Any: ...


class TrajectoryAdapter(Adapter):
    """Same contract for a sequence of frames.

    What ``read`` hands back is the *logical* sequence -- the frames, their
    step numbers, their cell updates. How an implementation indexed them on
    disk is its own business and is never compared.
    """

    module: ClassVar[str] = "trajectory"

    @abstractmethod
    def write(self, model: TrajectoryModel, storage: TrajectoryStorage) -> None: ...

    @abstractmethod
    def read(self, storage: TrajectoryStorage) -> Any: ...


class RecordAdapter(Adapter):
    """Same contract, one level up: the whole record root."""

    module: ClassVar[str] = "record"

    @abstractmethod
    def write(self, model: RecordModel, storage: RecordStorage) -> None: ...

    @abstractmethod
    def read(self, storage: RecordStorage) -> Any: ...


class CollectionAdapter(Adapter):
    """Same contract for many records under one declaration."""

    module: ClassVar[str] = "collection"

    @abstractmethod
    def write(self, model: CollectionModel, storage: CollectionStorage) -> None: ...

    @abstractmethod
    def read(self, storage: CollectionStorage) -> Any: ...


class ForceFieldAdapter(Adapter):
    """Same contract for a force field: the ``forcefield`` section beside a
    stamped ``meta`` (``docs/spec/forcefield.md``)."""

    module: ClassVar[str] = "forcefield"

    @abstractmethod
    def write(self, model: ForceFieldModel, storage: ForceFieldStorage) -> None: ...

    @abstractmethod
    def read(self, storage: ForceFieldStorage) -> Any: ...
