"""Every published schema is exercised: at least one instance it must accept,
at least one it must refuse, and no schema file that no model produces.

The fixtures under ``fixtures/schema/<schema path>/`` are named
``valid-*.json`` and ``invalid-*.json``. A schema that drifted from the
models fails ``test_schema_export``; one that drifted from what it is meant
to accept or refuse fails here, in the language-neutral artifact itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from molrec.schema_export import PUBLISHED, filename

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "schema"
FIXTURES = REPO / "fixtures" / "schema"

#: Every schema file the models produce, as a path relative to ``schema/``.
PRODUCED = sorted(
    f"{module}/{filename(model)}" for module, models in PUBLISHED.items() for model in models
)


def _fixtures(schema: str, kind: str) -> list[Path]:
    directory = FIXTURES / schema.removesuffix(".schema.json")
    return sorted(directory.glob(f"{kind}-*.json"))


def _validator(schema: str) -> jsonschema.protocols.Validator:
    document = json.loads((SCHEMA / schema).read_text())
    validator = jsonschema.validators.validator_for(document)
    validator.check_schema(document)
    return validator(document)


def test_every_schema_file_is_produced_by_a_model() -> None:
    on_disk = sorted(str(path.relative_to(SCHEMA)) for path in SCHEMA.rglob("*.schema.json"))
    assert on_disk == PRODUCED, "schema/ holds a file no model produces, or misses one"


def test_every_fixture_names_a_published_schema() -> None:
    directories = {str(path.parent.relative_to(FIXTURES)) for path in FIXTURES.rglob("*.json")}
    assert directories == {schema.removesuffix(".schema.json") for schema in PRODUCED}


@pytest.mark.parametrize("schema", PRODUCED)
def test_the_schema_accepts_its_valid_fixtures(schema: str) -> None:
    valid = _fixtures(schema, "valid")
    assert valid, f"{schema} has no valid fixture"
    validator = _validator(schema)
    for path in valid:
        errors = list(validator.iter_errors(json.loads(path.read_text())))
        assert not errors, f"{path.name}: {errors[0].message}"


@pytest.mark.parametrize("schema", PRODUCED)
def test_the_schema_refuses_its_invalid_fixtures(schema: str) -> None:
    invalid = _fixtures(schema, "invalid")
    assert invalid, f"{schema} has no invalid fixture"
    validator = _validator(schema)
    for path in invalid:
        assert not validator.is_valid(json.loads(path.read_text())), f"{path.name} was accepted"


@pytest.mark.parametrize(
    ("document", "schema"),
    [("meta.json", "core/meta.schema.json"), ("status.json", "core/status.schema.json")],
)
def test_the_run_minimal_documents_are_valid(document: str, schema: str) -> None:
    instance = json.loads((REPO / "fixtures/run-minimal/attrs" / document).read_text())
    _validator(schema).validate(instance)
