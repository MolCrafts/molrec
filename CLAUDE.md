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
- **L4 (binding):** Zarr V3 reference layout — implementation lives in molrs; molrec does not ship a `MolStore` class.

Reference implementation of containers + Zarr I/O: `MolCrafts/molrs`.
Consumers: molpy, molnex, molexp, molvis, molhub — they adopt the contract, they
do not invent parallel store names.
