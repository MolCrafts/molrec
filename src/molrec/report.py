"""Conformance and benchmark results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Status = Literal["pass", "fail", "skip", "error"]

#: Every kind the harness emits, and nothing else. ``compare.py`` produces the
#: located field differences; ``suite.py`` produces ``model_mismatch`` (the
#: implementation's duck did not validate as the model) and ``not_rejected``
#: (a negative case was accepted).
ViolationKind = Literal[
    "missing_field",
    "missing_key",
    "unexpected_key",
    "missing_values",
    "unexpected_values",
    "wrong_type",
    "wrong_shape",
    "wrong_length",
    "value_mismatch",
    "model_mismatch",
    "not_rejected",
]


class Violation(BaseModel):
    """One named conformance failure.

    ``kind`` is drawn from a closed vocabulary so expected-violation cases can
    be compared exactly, and so implementations in other languages can report
    the same names.
    """

    model_config = ConfigDict(frozen=True)

    kind: ViolationKind
    path: str = ""
    detail: str = ""

    def __str__(self) -> str:
        where = f" {self.path}" if self.path else ""
        why = f" -- {self.detail}" if self.detail else ""
        return f"{self.kind}{where}{why}"


class CaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    module: str
    backend: str
    direction: Literal["write", "read", ""] = ""
    status: Status
    violations: tuple[Violation, ...] = ()
    message: str = ""


class Report(BaseModel):
    model_config = ConfigDict(frozen=True)

    implementation: str
    version: str
    results: tuple[CaseResult, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(r.status in ("fail", "error") for r in self.results)

    @property
    def failures(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if r.status in ("fail", "error"))

    def table(self) -> str:
        lines = [f"molrec conformance -- {self.implementation} {self.version}"]
        seen: dict[tuple[str, str], list[CaseResult]] = {}
        for result in self.results:
            seen.setdefault((result.module, result.backend), []).append(result)

        for module, backend in sorted(seen):
            group = seen[(module, backend)]
            passed = sum(1 for r in group if r.status == "pass")
            skipped = [r for r in group if r.status == "skip"]
            label = f"[{backend}]" if backend else "--"
            if skipped and len(skipped) == len(group):
                lines.append(f"  {module:<12} {label:<10}  SKIP  {skipped[0].message}")
                continue
            lines.append(f"  {module:<12} {label:<10}  {passed}/{len(group)}")
            for result in group:
                if result.status in ("fail", "error"):
                    detail = result.message or "; ".join(str(v) for v in result.violations)
                    lines.append(f"      FAIL {result.case_id:<28} {detail}")
        return "\n".join(lines)

    def report(self) -> None:
        print(self.table())
