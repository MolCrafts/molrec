"""Shared fixtures.

The reference implementation is reached through a fixture, and only the
tests that judge molrs use it. The codec-only tests never touch it, so a
missing or broken molrs build cannot hide them behind a skip or a collection
error.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def molrs():
    """``molrs``, or a skip when it is not installed at all.

    Installed but stale (built before the rulings the suite now judges) is
    not a skip: those tests run and go red until molrs is rebuilt.
    """
    return pytest.importorskip("molrs")


@pytest.fixture(scope="session")
def molrs_implementation(molrs):
    """The molrs adapters, from the sibling module pytest puts on ``sys.path``."""
    import molrs_adapter

    return molrs_adapter.Molrs()
