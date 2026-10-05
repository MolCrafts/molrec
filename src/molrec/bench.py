"""The benchmark harness -- shoulder to shoulder with the conformance one.

Same adapter, same models, same (module x backend) matrix. A workload is just
a large model instance, so nothing has to be written twice to measure what
was already proven correct.

A standard without numbers is a wish, so the report carries throughput next
to whatever external baseline the module declares.
"""

from __future__ import annotations

import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from molrec.adapter import Adapter, Implementation
from molrec.binding import Binding
from molrec.registry import REGISTRY


class Workload(BaseModel):
    """One measured payload."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str
    model: Any
    nbytes: int
    baseline: str = ""


class Timing(BaseModel):
    model_config = ConfigDict(frozen=True)

    workload_id: str
    module: str
    backend: str
    direction: str
    seconds: float
    nbytes: int
    baseline: str = ""

    @property
    def mb_per_second(self) -> float:
        if self.seconds <= 0:
            return float("inf")
        return self.nbytes / self.seconds / 1e6


class BenchReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    implementation: str
    version: str
    timings: tuple[Timing, ...] = ()

    def table(self) -> str:
        lines = [f"molrec benchmark -- {self.implementation} {self.version}"]
        lines.append(f"  {'workload':<32} {'backend':<10} {'dir':<6} {'MB/s':>10}  baseline")
        for timing in self.timings:
            lines.append(
                f"  {timing.workload_id:<32} {timing.backend:<10} {timing.direction:<6} "
                f"{timing.mb_per_second:>10.1f}  {timing.baseline}"
            )
        return "\n".join(lines)

    def report(self) -> None:
        print(self.table())


class Bench(ABC):
    """One module's workloads."""

    module: ClassVar[str]

    @abstractmethod
    def workloads(self) -> Iterable[Workload]: ...

    def run(self, adapter: Adapter, binding: Binding, workdir: Path) -> list[Timing]:
        timings: list[Timing] = []
        for workload in self.workloads():
            store = binding.new_store(workdir / f"{workload.id}.bench")

            started = time.perf_counter()
            adapter.write(workload.model, store)
            timings.append(self._timing(workload, binding, "write", time.perf_counter() - started))

            started = time.perf_counter()
            adapter.read(store)
            timings.append(self._timing(workload, binding, "read", time.perf_counter() - started))
        return timings

    def _timing(
        self, workload: Workload, binding: Binding, direction: str, seconds: float
    ) -> Timing:
        return Timing(
            workload_id=workload.id,
            module=self.module,
            backend=binding.backend,
            direction=direction,
            seconds=seconds,
            nbytes=workload.nbytes,
            baseline=workload.baseline,
        )


class BenchmarkSuite:
    """Runs an implementation's benchmarks over the matrix it claims."""

    def __init__(
        self,
        implementation: Implementation,
        modules: Sequence[str] | None = None,
        backends: Sequence[str] | None = None,
    ) -> None:
        self._implementation = implementation
        self._modules = tuple(modules) if modules else REGISTRY.modules()
        self._backends = tuple(backends) if backends else None

    def run(self) -> BenchReport:
        adapters = self._implementation.adapters()
        timings: list[Timing] = []

        with tempfile.TemporaryDirectory(prefix="molrec-bench-") as tmp:
            workdir = Path(tmp)
            for module in self._modules:
                bench_type = REGISTRY.bench_for(module)
                adapter = adapters.get(module)
                if bench_type is None or adapter is None:
                    continue
                bench = bench_type()
                for backend, binding_type in sorted(REGISTRY.bindings_for(module).items()):
                    if backend not in adapter.backends:
                        continue
                    if self._backends and backend not in self._backends:
                        continue
                    room = workdir / module / backend
                    room.mkdir(parents=True, exist_ok=True)
                    timings.extend(bench.run(adapter, binding_type(), room))

        return BenchReport(
            implementation=self._implementation.name,
            version=self._implementation.version,
            timings=tuple(timings),
        )
