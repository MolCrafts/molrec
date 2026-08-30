# Meta

## Purpose

`meta` is the **required** record section for identity, schema version, and
lightweight provenance. Every conforming record has a `meta` section.

It is not free-form dump space for scientific results (those belong in
`frame` / `trajectory` / `observables`) or for live counters (those belong in
`status` / `metrics`).

Physical form: **Zarr group attributes** on `meta/` — see [Storage](storage.md).
The logical document is one JSON object; it is not a sibling `meta.json` file.

## Structure

```text
meta
+-- record_schema_version: number     # required — sole schema version (integer ≥ 1)
+-- (format_name: string)             # record format brand: "mrec"
+-- (creator)
|   +-- name: string
|   +-- (version: string)
+-- (author)
|   +-- name: string
|   +-- (email: string)
+-- (created_at: string)              # ISO-8601
+-- (source: string)
+-- (audit)
|   \-- ...                           # provenance tree
\-- (modules)
    \-- <module>
        +-- version: [major, minor]
        \-- ...
```

Field types are plain JSON (not L1 Column arrays).

## Required fields

| Key | Rule |
|-----|------|
| `record_schema_version` | **MUST** be present on every new record. Integer. Current value: **1**. Sole schema version for layout + L1 encoding. |

There is **no** parallel `frame_schema_version` and **no** separate
`meta.version` major/minor pair for the record layout. Older drafts that used
`version: [major, minor]` as the layout version are retired; do not dual-read.

## Reserved keys

These keys are owned by the contract (and by the reference Zarr writer), not by
producers inventing alternate meanings:

| Key | Meaning |
|-----|---------|
| `record_schema_version` | Schema version integer (starts at 1) |
| `format_name` | Record format brand, not a binding id or storage discriminator. Optional at L2. For the reference binding **MUST** be **`mrec`**. Never a product name (`molpy-zarr`, `MolStore`, …). |

When writing the Zarr reference binding, `format_name` **MUST** be set to
`mrec`. Readers of that binding **MUST** reject a missing value and any other
string, including the retired `"molrec"`. Producers MAY add any other keys
under `meta` freely.

## Recommended fields

| Key | Meaning |
|-----|---------|
| `creator.name` | Tool or package that wrote the record |
| `creator.version` | Creator version string |
| `author.name` | Human or org responsible for the content |
| `author.email` | Optional contact |
| `created_at` | ISO-8601 creation timestamp |
| `source` | Upstream dataset, path, or URI |

## Audit

Optional `meta.audit` holds provenance and traceability:

- source dataset or file
- workflow identifier
- conversion history
- commit / revision id
- additional timestamps

The audit subtree is extensible; no closed schema is required.

## Modules

`meta.modules` declares optional extensions that refine record meaning.

Each module entry is keyed by module name and SHOULD carry a major/minor
`version` pair documenting the extension contract. Custom method types and
custom metric types point here for their parse rules (see [Method](method.md),
[Metrics](metrics.md)).

## Example

Minimal attribute object (stored on the `meta/` Zarr group):

```json
{
  "record_schema_version": 1,
  "format_name": "mrec",
  "creator": {
    "name": "molrec-fixtures",
    "version": "0.0.0"
  },
  "created_at": "2026-08-04T00:00:00+00:00"
}
```

Golden payload: `fixtures/run-minimal/attrs/meta.json`.

## See also

- [Record](record.md) — versioning rules and minimum shapes
- [Storage](storage.md) — documents as Zarr attributes
- [Run surface](run.md) — Run packages that only need meta + status + metrics
