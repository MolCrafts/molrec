"""Where modules announce their suites, benches, and bindings.

Importing a module package registers what it offers, so the orchestrator can
build the (module x backend) matrix without hard-coding any of them.
"""

from __future__ import annotations

from molrec.binding import Binding


class Registry:
    def __init__(self) -> None:
        self._suites: dict[str, type] = {}
        self._benches: dict[str, type] = {}
        self._bindings: dict[tuple[str, str], type[Binding]] = {}

    def suite(self, cls: type) -> type:
        self._suites[cls.module] = cls
        return cls

    def bench(self, cls: type) -> type:
        self._benches[cls.module] = cls
        return cls

    def binding(self, cls: type[Binding]) -> type[Binding]:
        self._bindings[(cls.module, cls.backend)] = cls
        return cls

    def suite_for(self, module: str) -> type | None:
        return self._suites.get(module)

    def bench_for(self, module: str) -> type | None:
        return self._benches.get(module)

    def bindings_for(self, module: str) -> dict[str, type[Binding]]:
        return {
            backend: cls
            for (registered, backend), cls in self._bindings.items()
            if registered == module
        }

    def modules(self, *, drafts: bool = False) -> tuple[str, ...]:
        """The registered modules; a ``draft/`` one only when ``drafts`` is set.

        A draft is a proposal for a later version of the contract, so a run
        that names no modules must not judge an implementation of this one
        by it. Name a draft explicitly to run it.
        """
        return tuple(
            sorted(name for name in self._suites if drafts or not name.startswith(DRAFT_PREFIX))
        )


#: The prefix a draft module's name carries (``draft/observables``).
DRAFT_PREFIX = "draft/"

REGISTRY = Registry()
