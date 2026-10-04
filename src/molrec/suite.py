"""The conformance harness.

Every assertion lives here. An adapter author writes two methods and never
writes ``assert`` -- which is the point: the contract is what the suite
checks, not what each implementation remembers to check about itself.

Each positive case runs in both directions:

* **write** -- the implementation writes, the official codec reads. Catches
  information loss and layout the codec cannot interpret.
* **read** -- the official codec writes, the implementation reads. Catches an
  implementation that only understands the layout it happens to emit, which
  is exactly how two implementations end up unable to open each other's
  files.

Negative cases run in one direction each. A read-direction negative lays down
malformed content with the codec (optionally tampering with the store
afterwards) and requires the implementation to refuse it; a write-direction
negative hands the implementation a model the contract forbids and requires
it to refuse to write.
"""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from molrec.adapter import Adapter, Implementation
from molrec.binding import Binding, Codec
from molrec.case import Case
from molrec.compare import diff
from molrec.registry import REGISTRY
from molrec.report import CaseResult, Report, Violation


class Suite(ABC):
    """One module's cases plus its comparison rules."""

    module: ClassVar[str]
    model_type: ClassVar[type[BaseModel]]

    @abstractmethod
    def cases(self) -> Iterable[Case]:
        """The examples this module is pinned down by."""

    def compare(self, expected: BaseModel, actual: Any) -> tuple[Violation, ...]:
        """Override to report module-specific violations instead of field diffs."""
        return diff(expected, actual)

    def run(self, adapter: Adapter, binding: Binding, workdir: Path) -> list[CaseResult]:
        codec = binding.codec()
        results: list[CaseResult] = []
        for case in self.cases():
            if not case.applies_to(binding.backend):
                continue
            if case.expect_violation:
                if case.rejects_on == "write":
                    results.append(self._rejects_on_write(case, adapter, binding, workdir))
                else:
                    results.append(self._rejects(case, adapter, binding, codec, workdir))
                continue
            results.append(self._write_direction(case, adapter, binding, codec, workdir))
            results.append(self._read_direction(case, adapter, binding, codec, workdir))
        return results

    def _result(self, case: Case, binding: Binding, direction: str, **kwargs: Any) -> CaseResult:
        return CaseResult(
            case_id=case.id,
            module=self.module,
            backend=binding.backend,
            direction=direction,
            **kwargs,
        )

    def _write_direction(
        self, case: Case, adapter: Adapter, binding: Binding, codec: Codec, workdir: Path
    ) -> CaseResult:
        try:
            store = binding.new_store(workdir / f"{case.id}.write")
            adapter.write(case.model, store)
            recovered = codec.read(store)
        except Exception as exc:  # an implementation crash is a conformance failure
            return self._result(case, binding, "write", status="error", message=_why(exc))

        violations = self.compare(case.model, recovered)
        return self._result(
            case,
            binding,
            "write",
            status="fail" if violations else "pass",
            violations=violations,
        )

    def _read_direction(
        self, case: Case, adapter: Adapter, binding: Binding, codec: Codec, workdir: Path
    ) -> CaseResult:
        try:
            store = binding.new_store(workdir / f"{case.id}.read")
            codec.write(case.model, store)
            returned = adapter.read(store)
        except Exception as exc:
            return self._result(case, binding, "read", status="error", message=_why(exc))

        # The adapter may return any duck -- a dict, a dataclass, its own
        # native object. Failing to be shaped like the model is itself a
        # conformance failure, not a harness error.
        try:
            recovered = self.model_type.model_validate(returned, from_attributes=True)
        except ValidationError as exc:
            return self._result(
                case,
                binding,
                "read",
                status="fail",
                violations=(Violation(kind="model_mismatch", detail=str(exc)),),
            )

        violations = self.compare(case.model, recovered)
        return self._result(
            case,
            binding,
            "read",
            status="fail" if violations else "pass",
            violations=violations,
        )

    def _rejects(
        self, case: Case, adapter: Adapter, binding: Binding, codec: Codec, workdir: Path
    ) -> CaseResult:
        try:
            store = binding.new_store(workdir / f"{case.id}.reject")
            codec.write(case.model, store)
        except Exception as exc:
            # The codec would not lay the malformed content down at all. That
            # is a refusal too, just one step earlier than the case expected.
            return self._result(case, binding, "read", status="pass", message=_why(exc))
        if case.tamper is not None:
            case.tamper(store)
        try:
            adapter.read(store)
        except Exception:
            return self._result(case, binding, "read", status="pass")
        return self._result(
            case,
            binding,
            "read",
            status="fail",
            violations=(
                Violation(kind="not_rejected", detail=f"expected {case.expect_violation}"),
            ),
        )

    def _rejects_on_write(
        self, case: Case, adapter: Adapter, binding: Binding, workdir: Path
    ) -> CaseResult:
        try:
            store = binding.new_store(workdir / f"{case.id}.reject")
            adapter.write(case.model, store)
        except Exception:
            return self._result(case, binding, "write", status="pass")
        return self._result(
            case,
            binding,
            "write",
            status="fail",
            violations=(
                Violation(kind="not_rejected", detail=f"expected {case.expect_violation}"),
            ),
        )


def _why(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


class ConformanceSuite:
    """Runs an implementation across the (module x backend) matrix it claims."""

    def __init__(
        self,
        implementation: Implementation,
        modules: Sequence[str] | None = None,
        backends: Sequence[str] | None = None,
    ) -> None:
        self._implementation = implementation
        self._modules = tuple(modules) if modules else REGISTRY.modules()
        self._backends = tuple(backends) if backends else None

    def run(self) -> Report:
        adapters = self._implementation.adapters()
        results: list[CaseResult] = []

        with tempfile.TemporaryDirectory(prefix="molrec-") as tmp:
            workdir = Path(tmp)
            for module in self._modules:
                results.extend(self._run_module(module, adapters, workdir))

        return Report(
            implementation=self._implementation.name,
            version=self._implementation.version,
            results=tuple(results),
        )

    def _run_module(
        self, module: str, adapters: dict[str, Adapter], workdir: Path
    ) -> list[CaseResult]:
        suite_type = REGISTRY.suite_for(module)
        if suite_type is None:
            return []

        adapter = adapters.get(module)
        if adapter is None:
            return [
                CaseResult(
                    case_id="*",
                    module=module,
                    backend="",
                    status="skip",
                    message="no adapter declared",
                )
            ]

        suite = suite_type()
        results: list[CaseResult] = []
        for backend, binding_type in sorted(REGISTRY.bindings_for(module).items()):
            if backend not in adapter.backends:
                continue
            if self._backends and backend not in self._backends:
                continue
            room = workdir / module / backend
            room.mkdir(parents=True, exist_ok=True)
            results.extend(suite.run(adapter, binding_type(), room))

        if not results:
            results.append(
                CaseResult(
                    case_id="*",
                    module=module,
                    backend="",
                    status="skip",
                    message=f"no binding for declared backends {list(adapter.backends)}",
                )
            )
        return results
