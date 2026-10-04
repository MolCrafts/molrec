"""Containers and the record root.

Importing this package registers the core suite, bench, and bindings.
"""

from molrec.core import bench as _bench  # noqa: F401
from molrec.core import bindings as _bindings  # noqa: F401
from molrec.core import suite as _suite  # noqa: F401
from molrec.core.adapter import CollectionAdapter, FrameAdapter, RecordAdapter, TrajectoryAdapter
from molrec.core.model import (
    DTYPES,
    META_TAGS,
    BlockModel,
    BlockState,
    BoxModel,
    BoxUpdateModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    DType,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    MetaTag,
    MethodModel,
    RecordModel,
    SequenceBlockModel,
    SequenceColumnModel,
    SequenceSchemaModel,
    StatusModel,
    TrajectoryBoxModel,
    TrajectoryModel,
)
from molrec.core.store import CollectionStore, FrameStore, RecordStore, TrajectoryStore

__all__ = [
    "DTYPES",
    "META_TAGS",
    "BlockModel",
    "BlockState",
    "BoxModel",
    "BoxUpdateModel",
    "CollectionAdapter",
    "CollectionMetaModel",
    "CollectionModel",
    "CollectionStore",
    "ColumnModel",
    "DType",
    "FrameAdapter",
    "FrameModel",
    "FrameStore",
    "MetaModel",
    "MetaSeriesModel",
    "MetaTag",
    "MethodModel",
    "RecordAdapter",
    "RecordModel",
    "RecordStore",
    "SequenceBlockModel",
    "SequenceColumnModel",
    "SequenceSchemaModel",
    "StatusModel",
    "TrajectoryAdapter",
    "TrajectoryBoxModel",
    "TrajectoryModel",
    "TrajectoryStore",
]
