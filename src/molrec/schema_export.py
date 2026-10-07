"""Export the models as JSON Schema.

The pydantic classes are the authoring tool; the generated ``schema/`` tree
is the normative, language-neutral artifact. Otherwise the contract would
merely have moved from living in one language's source to living in
another's -- which is the problem this repository exists to fix.

    python -m molrec.schema_export schema/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from molrec.core.model import (
    CANONICAL_COLUMNS,
    ArrayModel,
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    ForceFieldModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    MethodModel,
    RecordModel,
    SequenceSchemaModel,
    StatusModel,
    TrajectoryBoxModel,
    TrajectoryModel,
)
from molrec.draft.observables import model as draft
from molrec.observables.model import (
    ObservableMetaModel,
    ObservableModel,
    ObservablesModel,
)
from molrec.ref import Ref
from molrec.report import Violation

#: module -> the models it publishes.
PUBLISHED: dict[str, tuple[type[BaseModel], ...]] = {
    "core": (
        ColumnModel,
        BlockModel,
        CellModel,
        BoxModel,
        FrameModel,
        MetaSeriesModel,
        BoxUpdateModel,
        TrajectoryBoxModel,
        TrajectoryModel,
        MetaModel,
        StatusModel,
        MethodModel,
        RecordModel,
        CollectionMetaModel,
        CollectionModel,
        # The section, its document parts as $defs (units, source, special
        # bonds, styles) and the style tables as blocks.
        ForceFieldModel,
    ),
    # The `observables/` section: the kind-based layout molrs writes.
    "observables": (ArrayModel, ObservableMetaModel, ObservableModel, ObservablesModel),
    # DRAFT -- the dims-based redesign; adopting it is a normative change
    # to the `observables/` section.
    "draft/observables": (
        draft.Array,
        draft.Source,
        draft.ObservableModel,
        draft.ObservablesModel,
    ),
    "binding": (SequenceSchemaModel,),
    "ref": (Ref,),
    "report": (Violation,),
}


#: The canonical column vocabulary (``docs/spec/conventions.md``, canonical
#: dtypes) as ``{key: dtype}`` -- the table another implementation's own
#: vocabulary is gated against. Generated from the models, like the schemas.
VOCABULARY = "core/vocabulary.json"


#: A schema whose file is named for its section rather than its class.
_SECTION_NAMES: dict[type[BaseModel], str] = {ForceFieldModel: "forcefield"}


def filename(model: type[BaseModel]) -> str:
    if model in _SECTION_NAMES:
        return f"{_SECTION_NAMES[model]}.schema.json"
    name = model.__name__.removesuffix("Model")
    return "".join(f"-{c.lower()}" if c.isupper() else c for c in name).lstrip("-") + ".schema.json"


def export(root: Path) -> list[Path]:
    written: list[Path] = []
    for module, models in PUBLISHED.items():
        directory = root / module
        directory.mkdir(parents=True, exist_ok=True)
        for model in models:
            target = directory / filename(model)
            schema = model.model_json_schema()
            target.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
            written.append(target)
    vocabulary = root / VOCABULARY
    vocabulary.write_text(json.dumps(CANONICAL_COLUMNS, indent=2, sort_keys=True) + "\n")
    written.append(vocabulary)
    return written


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("schema")
    for path in export(root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
