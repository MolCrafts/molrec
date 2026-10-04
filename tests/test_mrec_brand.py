"""Public-API scenario: the ``*.mrec`` path brand and the optional version key.

``molrec_version`` is optional during development: writers do not emit it, a
reader that finds it present requires an integer ``>= 1``. A fixture that
carries one therefore carries a valid one, and none of the retired keys.

Pytest collects ``tests/`` only; there is no ``regressions/`` tree.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_run_minimal_fixture_carries_a_valid_optional_version() -> None:
    meta = json.loads((REPO / "fixtures/run-minimal/attrs/meta.json").read_text())
    version = meta.get("molrec_version")
    assert version is None or (isinstance(version, int) and version >= 1)
    assert "format_name" not in meta
    assert "record_schema_version" not in meta


def test_fixtures_readme_lists_only_fixtures_that_exist() -> None:
    text = (REPO / "fixtures/README.md").read_text()
    listed = {
        line.split("`")[1].removeprefix("fixtures/").strip("/")
        for line in text.splitlines()
        if line.startswith("| `fixtures/")
    }
    on_disk = {p.name for p in (REPO / "fixtures").iterdir() if p.is_dir()}
    assert listed == on_disk


def test_storage_spec_names_mrec_zip() -> None:
    text = (REPO / "docs/spec/chunking.md").read_text()
    assert "*.mrec.zip" in text or ".mrec.zip" in text
