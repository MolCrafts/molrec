"""molrec -- the MolCrafts record contract.

molrec is a *specification* plus the machinery to hold implementations to it.
It is not a container library: there is no ``Frame`` you build a molecule
with, no block algebra, no compute. Those belong to implementations.

What is here:

* **Models** (``FrameModel``, ``BlockModel``, ...) -- pydantic models that
  *are* the specification. The JSON Schema published for other languages is
  generated from them.
* **Stores and bindings** -- one per (module x backend) pair. Zarr is one
  backend, not the backend; metrics land in JSONL, datasets in tables.
* **Adapters** -- the only thing an implementation author writes. Two methods
  per module, no assertions; refusals are typed (:class:`Refusal`).
* **Suites** -- the conformance harness and the benchmark harness, side by
  side, driven by the same adapter.

Usage::

    class MolrsRecordAdapter(molrec.RecordAdapter):
        backends = ("zarr",)
        refusal_types = (ValueError,)  # what molrs refuses malformed input with

        def write(self, model, store):
            molrs.io.write_mrec(store.uri, self._build(model.frame), meta=...)

        def read(self, store):
            return {
                "meta": molrs.io.read_mrec_meta(store.uri),
                "frame": self._describe(molrs.io.read_mrec(store.uri)),
            }

    class Molrs(molrec.Implementation):
        name    = "molrs"
        version = molrs.__version__
        record  = MolrsRecordAdapter()

    molrec.ConformanceSuite(Molrs()).run().report()
    molrec.BenchmarkSuite(Molrs()).run().report()

Comparison is always at the model level, never on bytes: chunk size, codec,
compression and attribute order are legitimate implementation freedom, so two
conforming stores *should* differ byte for byte.
"""

from __future__ import annotations

from molrec.adapter import Adapter, Implementation
from molrec.arrays import NDArray
from molrec.bench import Bench, BenchmarkSuite, BenchReport, Timing, Workload
from molrec.binding import Binding, Codec
from molrec.case import Case
from molrec.compare import diff
from molrec.core import (
    BlockModel,
    BlockState,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    ColumnModel,
    FrameAdapter,
    FrameModel,
    FrameStore,
    MetaModel,
    MetaSeriesModel,
    MethodModel,
    RecordAdapter,
    RecordModel,
    RecordStore,
    StatusModel,
    TrajectoryAdapter,
    TrajectoryBoxModel,
    TrajectoryModel,
    TrajectoryStore,
)
from molrec.draft import observables as _draft_observables  # noqa: F401  (registers)
from molrec.observables import (
    ArrayModel,
    ObservableAdapter,
    ObservableMetaModel,
    ObservableModel,
    ObservablesModel,
    ObservableStore,
)
from molrec.ref import Ref
from molrec.refusal import Refusal
from molrec.registry import REGISTRY
from molrec.report import CaseResult, Report, Violation
from molrec.sequence_schema import (
    SequenceBlockModel,
    SequenceColumnModel,
    SequenceSchemaModel,
)
from molrec.store import Store
from molrec.suite import ConformanceSuite, Suite

__version__ = "0.1.0"

__all__ = [
    "REGISTRY",
    "Adapter",
    "Bench",
    "BenchReport",
    "BenchmarkSuite",
    "Binding",
    "BlockModel",
    "BlockState",
    "BoxModel",
    "BoxUpdateModel",
    "CellModel",
    "Case",
    "CaseResult",
    "Codec",
    "ColumnModel",
    "ConformanceSuite",
    "FrameAdapter",
    "FrameModel",
    "FrameStore",
    "Implementation",
    "MetaModel",
    "MetaSeriesModel",
    "MethodModel",
    "NDArray",
    "RecordAdapter",
    "RecordModel",
    "RecordStore",
    "Report",
    "SequenceBlockModel",
    "SequenceColumnModel",
    "SequenceSchemaModel",
    "StatusModel",
    "Store",
    "TrajectoryAdapter",
    "TrajectoryBoxModel",
    "TrajectoryModel",
    "TrajectoryStore",
    "ArrayModel",
    "ObservableAdapter",
    "ObservableMetaModel",
    "ObservableModel",
    "ObservableStore",
    "ObservablesModel",
    "Ref",
    "Refusal",
    "Suite",
    "Timing",
    "Violation",
    "Workload",
    "diff",
    "__version__",
]
