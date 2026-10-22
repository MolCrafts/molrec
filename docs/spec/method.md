# Method

## Purpose

`method` stores the **scientific / training context** needed to interpret a
record. It is part of the **run surface** (with [Status](status.md) and
[Metrics](metrics.md)) — see [Run surface](run.md).

It is a recommended record section: a convention layered on the general model
([Overview](overview.md)).

It answers:

- what class of method produced this record
- which engine wrote it
- which engine produced it
- which settings the operator wants recorded beside the data

`method` is an open JSON document. It does not select a schema, and readers
do not branch on `method.type`. Result arrays stay in `frame`, `trajectory`,
or `observables`. Force-field tables stay in `forcefield/`. A name inside
`method` is narrative; it is not a second copy of those tables.

Physical form: **Zarr group attributes** on `method/` — see
[Storage](storage.md). The logical document is one JSON object.

## Structure

```text
method
+-- (description: string)
+-- (engine)
|   +-- name: string
|   \-- (version: string)
+-- (order: string[])
\-- (stages)
    \-- <stage_id>
        +-- (description: string)
        \-- ...
```

Field types are plain JSON. The tree is a recommendation. A producer may
add keys, and may omit every key above.

## Document

No key is required for the section to exist. Recommended keys, when the
producer has them:

| Key | Meaning |
|-----|---------|
| `description` | What this run is |
| `engine.name` | Tool that produced it |
| `engine.version` | That tool's version |
| `order` | Stage ids, in order |
| `stages.<id>` | Narrative for one stage: description, engine, whatever else belongs there |

`stages.<id>.type` is a label inside that narrative. It does not change
which record sections exist or how they are parsed. Unknown keys are
preserved. Result arrays stay in `frame`, `trajectory`, or `observables`.

## Example

```json
{
  "description": "Geometry relaxation followed by a single-point evaluation",
  "engine": { "name": "MolFlow" },
  "order": ["relax", "single_point"],
  "stages": {
    "relax": {
      "description": "Pre-relaxation",
      "force_field": "GAFF"
    },
    "single_point": {
      "description": "Single-point evaluation",
      "functional": "PBE",
      "basis": "def2-SVP"
    }
  }
}
```
