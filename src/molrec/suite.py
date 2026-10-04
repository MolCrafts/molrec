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

Only a *refusal* passes a negative case (see :mod:`molrec.refusal`): an
adapter that raises for any other reason -- an unimplemented door, a missing
attribute -- is reported as ``error``, and so is a case the harness could not
prepare. Nothing passes by proxy.
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
from molrec.refusal import as_refusal
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
            if case.id in adapter.unsupported:
                results.append(
                    self._result(
                        case, binding, "", status="skip", message=adapter.unsupported[case.id]
                    )
                )
                continue
            if case.expect_violation:
                if case.rejects_on == "write":
                    results.append(self._rejects_on_write(case, adapter, binding, workdir))
                else:
                    results.append(self._rejects(case, adapter, binding, codec, workdir))
                continue
            if "write" in case.directions:
                results.append(self._write_direction(case, adapter, binding, codec, workdir))
            if "read" in case.directions:
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

    def _error(self, case: Case, binding: Binding, direction: str, why: str) -> CaseResult:
        return self._result(case, binding, direction, status="error", message=why)

    def _fail(self, case: Case, binding: Binding, direction: str, *found: Violation) -> CaseResult:
        return self._result(case, binding, direction, status="fail", violations=found)

    def _verdict(self, case: Case, binding: Binding, direction: str, actual: Any) -> CaseResult:
        """Compare, and let a comparison that crashes cost one case rather than the run."""
        try:
            violations = self.compare(case.judged_against, actual)
        except Exception as exc:
            return self._error(case, binding, direction, f"comparison crashed: {_why(exc)}")
        return self._result(
            case,
            binding,
            direction,
            status="fail" if violations else "pass",
            violations=violations,
        )

    def _raised(
        self, case: Case, adapter: Adapter, binding: Binding, direction: str, exc: Exception
    ) -> CaseResult:
        """An adapter raised on a *positive* case.

        A refusal of conforming content is a conformance failure; anything
        else the adapter raises is a defect.
        """
        refusal = as_refusal(exc, adapter.refusal_types)
        if refusal is None:
            return self._error(case, binding, direction, _why(exc))
        return self._fail(
            case,
            binding,
            direction,
            Violation(kind="refused", detail=f"conforming input refused: {_why(exc)}"),
        )

    def _judged(
        self, case: Case, adapter: Adapter, binding: Binding, direction: str, exc: Exception
    ) -> CaseResult:
        """An adapter raised on a *negative* case: was it the refusal asked for?"""
        refusal = as_refusal(exc, adapter.refusal_types)
        if refusal is None:
            return self._error(case, binding, direction, f"not a refusal: {_why(exc)}")
        if refusal.kind and refusal.kind != case.expect_violation:
            return self._fail(
                case,
                binding,
                direction,
                Violation(
                    kind="wrong_refusal",
                    detail=f"expected {case.expect_violation}, refused as {refusal.kind}: "
                    f"{refusal}",
                ),
            )
        return self._result(case, binding, direction, status="pass", message=_why(exc))

    def _write_direction(
        self, case: Case, adapter: Adapter, binding: Binding, codec: Codec, workdir: Path
    ) -> CaseResult:
        try:
            store = binding.new_store(workdir / f"{case.id}.write")
        except Exception as exc:
            return self._error(case, binding, "write", f"could not prepare the case: {_why(exc)}")
        try:
            adapter.write(case.model, store)
        except Exception as exc:
            return self._raised(case, adapter, binding, "write", exc)
        try:
            recovered = codec.read(store)
        except Exception as exc:
            return self._fail(
                case,
                binding,
                "write",
                Violation(
                    kind="unreadable",
                    detail=f"the official codec cannot read what was written: {_why(exc)}",
                ),
            )

        return self._verdict(case, binding, "write", recovered)

    def _read_direction(
        self, case: Case, adapter: Adapter, binding: Binding, codec: Codec, workdir: Path
    ) -> CaseResult:
        try:
            store = binding.new_store(workdir / f"{case.id}.read")
            codec.write(case.model, store)
            if case.tamper is not None:
                case.tamper(store)
        except Exception as exc:
            return self._error(case, binding, "read", f"could not prepare the case: {_why(exc)}")
        try:
            returned = adapter.read(store)
        except Exception as exc:
            return self._raised(case, adapter, binding, "read", exc)

        # What the reader returned is compared *as returned*. Validating it
        # into the model first would let the model's own normalizers -- the
        # box defaults, carried-forward blocks, declared fills, the section's
        # cell_defined -- supply on the reader's behalf exactly the values a
        # broken reader drops.
        verdict = self._verdict(case, binding, "read", returned)
        if verdict.status != "pass":
            return verdict

        # The adapter may return any duck -- a dict, a dataclass, its own
        # native object. Failing to be shaped like the model is itself a
        # conformance failure, not a harness error.
        try:
            self.model_type.model_validate(returned, from_attributes=True)
        except ValidationError as exc:
            return self._fail(
                case, binding, "read", Violation(kind="model_mismatch", detail=str(exc))
            )
        return verdict

    def _rejects(
        self, case: Case, adapter: Adapter, binding: Binding, codec: Codec, workdir: Path
    ) -> CaseResult:
        """Lay the malformed content down, then require the implementation to refuse it.

        The content is laid down by the official codec and, for what the
        models cannot express, the case's ``tamper`` hook. Either one failing
        means the implementation was never shown the malformation, so that is
        a harness ``error`` -- never a pass by proxy.
        """
        try:
            store = binding.new_store(workdir / f"{case.id}.reject")
            codec.write(case.model, store)
        except Exception as exc:
            return self._error(
                case, binding, "read", f"could not lay the malformed store down: {_why(exc)}"
            )
        if case.tamper is not None:
            try:
                case.tamper(store)
            except Exception as exc:
                return self._error(case, binding, "read", f"tamper failed: {_why(exc)}")
        try:
            adapter.read(store)
        except Exception as exc:
            return self._judged(case, adapter, binding, "read", exc)
        return self._fail(
            case,
            binding,
            "read",
            Violation(kind="not_rejected", detail=f"expected {case.expect_violation}"),
        )

    def _rejects_on_write(
        self, case: Case, adapter: Adapter, binding: Binding, workdir: Path
    ) -> CaseResult:
        try:
            store = binding.new_store(workdir / f"{case.id}.reject")
        except Exception as exc:
            return self._error(case, binding, "write", f"could not prepare the case: {_why(exc)}")
        try:
            adapter.write(case.model, store)
        except Exception as exc:
            return self._judged(case, adapter, binding, "write", exc)
        return self._fail(
            case,
            binding,
            "write",
            Violation(kind="not_rejected", detail=f"expected {case.expect_violation}"),
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

        if not adapter.backends:
            return [
                CaseResult(
                    case_id="*",
                    module=module,
                    backend="",
                    status="error",
                    message=f"{type(adapter).__name__} declares no backends -- it can run nothing",
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
