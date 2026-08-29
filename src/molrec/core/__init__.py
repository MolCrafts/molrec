"""L0-L2: the containers and the record root.

Importing this package registers the core suite, bench, and bindings.
"""

from molrec.core import bench as _bench  # noqa: F401
from molrec.core import bindings as _bindings  # noqa: F401
from molrec.core import suite as _suite  # noqa: F401
from molrec.core.adapter import FrameAdapter, RecordAdapter, TrajectoryAdapter
from molrec.core.model import (
    DTYPES,
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    ColumnModel,
    DType,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    RecordModel,
    TrajectoryBoxModel,
    TrajectoryModel,
)
from molrec.core.store import FrameStore, RecordStore, TrajectoryStore

__all__ = [
    "DTYPES",
    "BlockModel",
    "BoxModel",
    "BoxUpdateModel",
    "ColumnModel",
    "DType",
    "FrameAdapter",
    "FrameModel",
    "FrameStore",
    "MetaModel",
    "MetaSeriesModel",
    "RecordAdapter",
    "RecordModel",
    "RecordStore",
    "TrajectoryAdapter",
    "TrajectoryBoxModel",
    "TrajectoryModel",
    "TrajectoryStore",
]
