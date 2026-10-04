"""Shared fixtures.

The reference implementation is reached through a fixture, and only the
tests that judge molrs use it. The codec-only tests never touch it, so a
missing or broken molrs build cannot hide them behind a skip or a collection
error.
"""

from __future__ import annotations

import importlib
import os

import pytest

#: Set (to ``1``) where molrs must be judged -- CI sets it. There, a missing
#: or unimportable molrs is a failure, not a skip that turns the run green.
REQUIRE_MOLRS = os.environ.get("MOLREC_REQUIRE_MOLRS") == "1"


@pytest.fixture(scope="session")
def molrs():
    """``molrs``, or a skip when it is not installed at all.

    Installed but stale (built before the rulings the suite now judges) is
    not a skip: those tests run and go red until molrs is rebuilt. With
    ``MOLREC_REQUIRE_MOLRS=1`` an absent molrs is not a skip either.
    """
    if REQUIRE_MOLRS:
        try:
            return importlib.import_module("molrs")
        except ImportError as exc:
            pytest.fail(f"MOLREC_REQUIRE_MOLRS=1 but molrs cannot be imported: {exc}")
    return pytest.importorskip("molrs")


@pytest.fixture(scope="session")
def molrs_implementation(molrs):
    """The molrs adapters, from the sibling module pytest puts on ``sys.path``."""
    import molrs_adapter

    return molrs_adapter.Molrs()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every test that reaches molrs is marked ``molrs``, so ``-m "not molrs"``
    runs the rest without building the reference implementation."""
    for item in items:
        if {"molrs", "molrs_implementation"} & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.molrs)
