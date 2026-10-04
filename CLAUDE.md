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
This repository owns **specification prose and fixtures**.

## Architecture

- **Record:** one root. Column / Block / Frame / Box are how it holds array
  data. A trajectory is a record section.
- **Conventions:** domain names (`atoms`, `atomi`/`atomj`, `system`,
  `status`, `metrics`, …) follow molpy's Frame/Block interchange scheme.
- **Reference binding:** one Zarr V3 root — live directory `*.mrec/` *is*
  that root; packed form is `*.mrec.zip`. Array groups + document sections
  as **group attributes**; live metrics = append-only JSONL text buffer
  (dense Zarr series + optional `metrics/metrics.jsonl` WAL). Trajectory
  encoding is the ragged CSR layout (`docs/spec/ragged.md`). Binding
  starts at `docs/spec/zarr.md`.

Reference implementation of containers + Zarr I/O: `MolCrafts/molrs`.
Consumers: molpy, molnex, molexp, molvis, molhub — they adopt the contract.

## Spec hygiene

- Version key `meta["molrec_version"]` (integer, currently 1): **writers always
  stamp it** (molrec's own codecs included); readers validate it only when
  present (absent = pre-1 store, read best-effort; `null` or newer = refuse).
  Identity = `*.mrec` suffix + Zarr root; writers always create `meta/`.
- Scientific paths are `*.mrec/` / `*.mrec.zip`. Host metrics stay on the
  filename-gated `*.mlp.*` surface (live WAL `*.mlp.jsonl`; leftover
  `*.mlp.zarr` is ignored).
- Cell contract name: `Box` / `box`.
- v1 `observables/` is the kind-based layout in `docs/spec/observables.md`
  (matches molrs; `src/molrec/observables/`, models in `core/model.py`). The
  dims-based model in `src/molrec/draft/observables/` is a **v2 draft**
  (`schema/draft/observables/`, conformance module `draft/observables`, never
  run unless named); adopting it needs a `molrec_version` bump.
- `system` is strictly frame-shaped (flat blocks, no `parameters` child);
  force-field parameters: see `docs/spec/forcefield.md`. How a job ran lives
  under `method`.
- Keep section chapters aligned with `docs/spec/storage.md` and
  `docs/spec/zarr.md`: documents are Zarr group attributes; metrics JSONL
  is an append buffer.
