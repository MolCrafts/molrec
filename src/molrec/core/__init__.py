"""L0-L2: the containers and the record root.

Importing this package registers the core suite, bench, and bindings.
"""

from molrec.core import bench as _bench  # noqa: F401
from molrec.core import bindings as _bindings  # noqa: F401
from molrec.core import suite as _suite  # noqa: F401
from molrec.core.adapter import FrameAdapter, RecordAdapter
from molrec.core.model import (
    DTYPES,
    BlockModel,
    BoxModel,
    ColumnModel,
    DType,
    ForceFieldModel,
    FrameModel,
    MeshModel,
    MetaModel,
    RecordModel,
    UnitsModel,
)
from molrec.core.store import FrameStore, RecordStore

__all__ = [
    "DTYPES",
    "BlockModel",
    "BoxModel",
    "ColumnModel",
    "DType",
    "ForceFieldModel",
    "FrameAdapter",
    "FrameModel",
    "FrameStore",
    "MeshModel",
    "MetaModel",
    "RecordAdapter",
    "RecordModel",
    "RecordStore",
    "UnitsModel",
]
