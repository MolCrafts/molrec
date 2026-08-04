# Meta

## Purpose

`meta` stores record-level metadata. It is a recommended record section — a
convention layered on the general model (see [Overview](overview.md)).

This includes both descriptive metadata and audit-like metadata about authorship and creation.

## Structure

```text
meta
+-- version: Integer[2]
\-- author
|   +-- name: String[]
|   +-- (email: String[])
\-- creator
|   +-- name: String[]
|   +-- (version: String[])
\-- (created_at: String[])
\-- (source: String[])
\-- (audit)
|   \-- ...
\-- (modules)
|   \-- <module>
|       +-- version: Integer[2]
|       \-- ...
```

## Required fields

- `version`
- `author/name`
- `creator/name`

`version` stores the major and minor version of the MolRec specification.

## Audit information

The optional `meta/audit` subtree is reserved for provenance and traceability information.

Examples:

- source dataset or file
- workflow identifier
- conversion history
- commit or revision identifier
- timestamps

The exact audit schema is extensible.

## Modules

`meta/modules` declares optional extensions that refine the meaning of the record.

Module entries are identified by:

- a module name
- a major/minor version
