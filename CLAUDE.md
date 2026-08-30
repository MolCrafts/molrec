---
mol_project:
  name: molrec
  language: markdown
  stage: experimental
  build:
    install: "true"
    check: "true"
    test: "true"
    test_single: "true"
  arch:
    style: docs-first
    rules_section: "## Architecture"
  doc:
    style: plain
  science:
    required: false
  notes_path: .claude/notes/
  specs_path: .claude/specs/
---

# CLAUDE.md

MolRec is the **backend-neutral record contract** for the MolCrafts ecosystem.
This repository owns **specification prose and fixtures**, not a store product
named MolStore.

## Architecture

- **L0–L2 (normative):** vocabulary, containers (Column / Block / Frame), Record root.
- **L3 (conventions):** domain sections (`system`, `trajectory`, `status`, `metrics`, …).
- **L4 (binding):** one Zarr V3 root — live directory `*.mrec/` *is* that
  root; packed form is `*.mrec.zip`. Array groups + document sections as
  **group attributes**; live metrics = append-only JSONL text buffer
  (dense Zarr series + optional `metrics/metrics.jsonl` WAL). Spec:
  `docs/spec/storage.md`. molrec does not ship
  a `MolStore` class.

Reference implementation of containers + Zarr I/O: `MolCrafts/molrs`.
Consumers: molpy, molnex, molexp, molvis, molhub — they adopt the contract, they
do not invent parallel store names.

## Spec hygiene

- Sole schema key: `meta.record_schema_version` (integer, starts at 1).
- Record format brand: `meta.format_name` is `mrec` (not a binding id);
  scientific paths are `*.mrec/` / `*.mrec.zip` — **MUST NOT** use
  `.zarr` / `.zarr.zip`. Host metrics stay `*.mlp.zarr`
  (`format_name=molmetrics`).
- No `frame_schema_version`, no layout `meta.version` dual-key.
- Cell contract name: `Box` / `box` only (not `simbox`).
- No root `parameters/`; parameters under `system/parameters` or `method`.
- Keep section chapters aligned with `docs/spec/storage.md`: documents are Zarr
  attributes (not sibling `.json` stores); metrics JSONL is only an append
  buffer; no nested metrics array trees or columnar `String[]` document trees.
