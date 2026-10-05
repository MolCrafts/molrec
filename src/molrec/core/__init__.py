"""Containers and the record root.

Importing this package registers the core suite, bench, and bindings.
"""

from molrec.core import bench as _bench  # noqa: F401
from molrec.core import bindings as _bindings  # noqa: F401
from molrec.core import ffsuite as _ffsuite  # noqa: F401
from molrec.core import suite as _suite  # noqa: F401
from molrec.core.adapter import (
    CollectionAdapter,
    ForceFieldAdapter,
    FrameAdapter,
    RecordAdapter,
    TrajectoryAdapter,
)
from molrec.core.model import (
    DTYPES,
    META_TAGS,
    BlockModel,
    BlockState,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    DType,
    ForceFieldModel,
    ForceFieldSourceModel,
    ForceFieldUnitsModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    MetaTag,
    MethodModel,
    RecordModel,
    SequenceBlockModel,
    SequenceColumnModel,
    SequenceSchemaModel,
    SpecialBondsModel,
    StatusModel,
    StyleModel,
    TrajectoryBoxModel,
    TrajectoryModel,
)
from molrec.core.store import (
    CollectionStore,
    ForceFieldStore,
    FrameStore,
    RecordStore,
    TrajectoryStore,
)

__all__ = [
    "DTYPES",
    "META_TAGS",
    "BlockModel",
    "BlockState",
    "BoxModel",
    "BoxUpdateModel",
    "CellModel",
    "CollectionAdapter",
    "CollectionMetaModel",
    "CollectionModel",
    "CollectionStore",
    "ColumnModel",
    "DType",
    "ForceFieldAdapter",
    "ForceFieldModel",
    "ForceFieldSourceModel",
    "ForceFieldStore",
    "ForceFieldUnitsModel",
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
    "SpecialBondsModel",
    "StatusModel",
    "StyleModel",
    "TrajectoryAdapter",
    "TrajectoryBoxModel",
    "TrajectoryModel",
    "TrajectoryStore",
]
