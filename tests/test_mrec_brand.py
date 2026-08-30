"""Public-API scenario: mrec format brand on fixtures and the storage contract.

Pytest collects ``tests/`` only; there is no ``regressions/`` tree.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_run_minimal_fixture_stamps_mrec_brand() -> None:
    meta = json.loads((REPO / "fixtures/run-minimal/attrs/meta.json").read_text())
    assert meta["format_name"] == "mrec"
    assert meta["record_schema_version"] == 1


def test_storage_spec_names_mrec_zip() -> None:
    text = (REPO / "docs/spec/storage.md").read_text()
    assert "*.mrec.zip" in text or ".mrec.zip" in text
