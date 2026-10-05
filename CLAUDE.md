---
mol_project:
  name: molrec
  language: python
  stage: experimental
  build:
    install: "uv sync --locked --extra dev"
    check: "uvx ruff@0.16.5 format --check . && uvx ruff@0.16.5 check ."
    test: "uv run --locked pytest -q"
    test_single: "uv run --locked pytest -q tests/<file>.py::<test>"
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
This repository owns the **specification prose** (`docs/spec/*.md`,
normative), the **Python package** `molrec` that states the same contract as
code, and the **fixtures**:

- `src/molrec/core/model.py` — the pydantic models that *are* the contract
  (record, frame, block, column, cell, trajectory, collection, observables,
  documents). `schema/` is generated from them: `python -m
  molrec.schema_export schema` after any model change (a test fails on
  drift, and on any schema file no model produces).
- `src/molrec/core/bindings/` — the reference codecs: **Zarr V3** (`zarr.py`:
  bare frame, record, trajectory, force field; the arbiter the conformance
  suite reads and writes through) and **LMDB** (`lmdb.py`: a collection of
  records in one file). `src/molrec/observables/` — the v1 observables codec.
- `src/molrec/*suite*.py`, `core/suite.py` — the **conformance suite**:
  cases per module (`core`, `record`, `trajectory`, `collection`,
  `forcefield`, `observables`; drafts only when named). An implementation writes an
  adapter (two methods per module); `tests/molrs_adapter.py` is molrs's.
- `fixtures/` — the run-minimal text golden and `fixtures/schema/` (a valid
  and an invalid instance per published schema).

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
- **Collections:** many records under one trajectory declaration
  (`docs/spec/collection.md`), bound to one LMDB file (`docs/spec/lmdb.md`).

Reference implementation of containers + Zarr I/O: `MolCrafts/molrs`.
Consumers: molpy, molnex, molexp, molvis, molhub — they adopt the contract.

## Commands

- Pure suite (no molrs, nothing compiles): `uv run --locked --extra test
  pytest -q -m "not molrs"`. This is what the pre-push hook runs.
- Lint: `uvx ruff@0.16.5 format --check . && uvx ruff@0.16.5 check .`.
- Layout chapter: `docs/layout.md`'s trees are generated from the codecs by
  `scripts/layout_examples.py`; after a codec or layout change run it with
  `--write` (`tests/test_layout_doc.py` fails on drift).
- Full suite against molrs: `uv sync --locked --extra dev` builds molrs from
  `../molrs/molrs-python` (Rust) — **only on a build machine, never a login
  node** — then `MOLREC_REQUIRE_MOLRS=1 uv run --locked pytest -q`. On the
  cluster: take a compute allocation, build a wheel there with `maturin
  build --release -o <node-local dir> --manifest-path
  ../molrs/molrs-python/Cargo.toml` (`CARGO_TARGET_DIR` node-local), install
  it with this package's deps into a node-local venv, and run
  `MOLREC_REQUIRE_MOLRS=1 PYTHONPATH=src python -m pytest -q` there.
- A Rust change in `../molrs` is not seen by `uv sync` on its own:
  `uv sync --extra dev --reinstall-package molcrafts-molrs`.

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
- `system` is strictly frame-shaped (flat blocks, no `parameters` child).
  Force-field parameters in the `forcefield` section
  (`docs/spec/forcefield.md`, frame-shaped: document attrs + one block per
  style; LMDB key `ff`); how a job ran in `method`.
- Keep section chapters aligned with `docs/spec/storage.md` and
  `docs/spec/zarr.md`: documents are Zarr group attributes; metrics JSONL
  is an append buffer.
