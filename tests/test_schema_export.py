"""The generated schema tree is the normative artifact, so it must not drift.

If regeneration produces a diff, the committed schemas no longer describe the
models -- and a Julia or Go implementer reading them would be implementing
something that no longer exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from molrec.core.model import CANONICAL_COLUMNS, DTYPES
from molrec.schema_export import PUBLISHED, VOCABULARY, export

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "schema"


def test_regenerating_matches_what_is_committed(tmp_path):
    for generated in export(tmp_path):
        committed = SCHEMA / generated.relative_to(tmp_path)
        assert committed.exists(), f"{committed} is missing -- run python -m molrec.schema_export"
        assert committed.read_text(encoding="utf-8") == generated.read_text(encoding="utf-8"), (
            f"{committed} is stale -- run python -m molrec.schema_export"
        )


def test_every_published_model_lands_on_disk(tmp_path):
    expected = sum(len(models) for models in PUBLISHED.values())
    # ... plus the canonical vocabulary.
    assert len(export(tmp_path)) == expected + 1


def test_the_vocabulary_is_the_canonical_table():
    committed = json.loads((SCHEMA / VOCABULARY).read_text(encoding="utf-8"))
    assert committed == CANONICAL_COLUMNS
    assert set(committed.values()) <= set(DTYPES)


def test_committed_schemas_are_valid_json_objects():
    files = list(SCHEMA.rglob("*.schema.json"))
    assert files, "nothing was exported"
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        if "$ref" in document:  # a recursive model publishes its root as a $def
            document = document["$defs"][document["$ref"].rsplit("/", 1)[1]]
        assert document["type"] == "object"
        assert "properties" in document
