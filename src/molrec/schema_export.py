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
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    ColumnModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    RecordModel,
    TrajectoryBoxModel,
    TrajectoryModel,
)
from molrec.observables.model import (
    Array,
    ObservableModel,
    ObservablesModel,
    Source,
)
from molrec.ref import Ref
from molrec.report import Violation
from molrec.sequence_schema import SequenceSchemaModel

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
        RecordModel,
    ),
    # DRAFT — the dims-based observables redesign (v2 proposal). The v1
    # record `observables/` contract is the kind-based layout in
    # docs/spec/observables.md, implemented by molrs; adopting this model
    # is a normative change and requires a `molrec_version` bump.
    "draft/observables": (Array, Source, ObservableModel, ObservablesModel),
    "binding": (SequenceSchemaModel,),
    "ref": (Ref,),
    "report": (Violation,),
}


def filename(model: type[BaseModel]) -> str:
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
    return written


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("schema")
    for path in export(root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
