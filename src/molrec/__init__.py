"""molrec -- the MolCrafts record contract.

molrec is a *specification* plus the machinery to hold implementations to it.
It is not a container library: there is no ``Frame`` you build a molecule
with, no block algebra, no compute. Those belong to implementations.

What is here:

* **Models** (:mod:`molrec.core.model`, :mod:`molrec.observables.model`) --
  pydantic models that *are* the specification. The JSON Schema published
  for other languages is generated from them.
* **Stores and bindings** -- one per (module x backend) pair: the Zarr V3
  record root (frames, records, trajectories, observables) and LMDB
  (collections, trajectories).
* **Adapters** -- the only thing an implementation author writes. Two methods
  per module, no assertions; refusals are typed
  (:class:`~molrec.refusal.Refusal`).
* **Suites** -- the conformance harness and the benchmark harness, side by
  side, driven by the same adapter.

Usage::

    class MolrsRecordAdapter(molrec.core.adapter.RecordAdapter):
        backends = ("zarr",)
        refusal_types = (ValueError,)  # what molrs refuses malformed input with

        def write(self, model, store):
            molrs.io.write_mrec(store.uri, self._build(model.frame), meta=...)

        def read(self, store):
            return {
                "meta": molrs.io.read_mrec_meta(store.uri),
                "frame": self._describe(molrs.io.read_mrec(store.uri)),
            }

    class Molrs(molrec.adapter.Implementation):
        name    = "molrs"
        version = importlib.metadata.version("molcrafts-molrs")
        record  = MolrsRecordAdapter()

    molrec.suite.ConformanceSuite(Molrs()).run().report()
    molrec.bench.BenchmarkSuite(Molrs()).run().report()

Every symbol has one public path, its owner module's
(``molrec.suite.ConformanceSuite``, ``molrec.core.model.FrameModel``); the
package root holds the subsystems and ``__version__`` only.

Comparison is always at the model level, never on bytes: chunk size, codec,
compression and attribute order are legitimate implementation freedom, so two
conforming stores *should* differ byte for byte.
"""

from __future__ import annotations

# Importing a subsystem registers its suites, benches and bindings.
from molrec import (
    adapter,
    arrays,
    bench,
    binding,
    case,
    chunking,
    compare,
    core,
    draft,
    jsonvalue,
    observables,
    precision,
    ref,
    refusal,
    registry,
    report,
    safe_name,
    store,
    suite,
)
from molrec.draft import observables as _draft_observables  # noqa: F401  (registers)

#: The one place the package version is written; ``pyproject.toml`` reads it
#: from here (``[tool.hatch.version]``).
__version__ = "0.2.0"

__all__ = [
    "__version__",
    "adapter",
    "arrays",
    "bench",
    "binding",
    "case",
    "chunking",
    "compare",
    "core",
    "draft",
    "jsonvalue",
    "observables",
    "precision",
    "ref",
    "refusal",
    "registry",
    "report",
    "safe_name",
    "store",
    "suite",
]
