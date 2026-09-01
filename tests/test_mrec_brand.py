"""Public-API scenario: ``*.mrec`` path brand and ``molrec_version``.

Pytest collects ``tests/`` only; there is no ``regressions/`` tree.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_run_minimal_fixture_stamps_molrec_version() -> None:
    meta = json.loads((REPO / "fixtures/run-minimal/attrs/meta.json").read_text())
    assert meta["molrec_version"] == 1
    assert "format_name" not in meta
    assert "record_schema_version" not in meta


def test_storage_spec_names_mrec_zip() -> None:
    text = (REPO / "docs/spec/chunking.md").read_text()
    assert "*.mrec.zip" in text or ".mrec.zip" in text
