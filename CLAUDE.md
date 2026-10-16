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
  records in one file). `src/molrec/observables/` — the observables codec.
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
  pytest -q -m "not molrs"`.
- Lint: `uvx ruff@0.16.5 format --check . && uvx ruff@0.16.5 check .`.
- Layout chapter: `docs/layout.md`'s trees are generated from the codecs by
  `scripts/layout_examples.py`; after a codec or layout change run it with
  `--write` (`tests/test_layout_doc.py` fails on drift).
- Full suite against molrs, exactly as CI runs it (molrs built from the
  commit `.github/partners.env` declares, in a layout of its own -- never your
  `../molrs` working tree):
  `scripts/partners.py run -- env MOLREC_REQUIRE_MOLRS=1 uv run --locked
  --python 3.12 --extra dev python -X warn_default_encoding -m pytest -q`. It compiles molrs: **only on a build
  machine, never a login node** (the pre-push hook dispatches it for you).
- Relocking against molrs (when the declared molrs changed its version or
  its dependencies and `uv lock --check` fails): `scripts/partners.py run -- sh -c
  'uv lock && cp uv.lock "$PARTNERS_SOURCE/"'`, in a commit of its own.

## Hooks

`prek install` (or `pre-commit install`) installs both hook types from
`.pre-commit-config.yaml`; every CI job has a hook running the same command.
**Never `git commit --no-verify` / `git push --no-verify`**, and never merge
a red PR.

- **pre-commit** (staged files, cheap, in place): file hygiene
  (whitespace, EOF, yaml/toml/json, merge markers, large files) and ruff.
- **pre-push**: the same hygiene hooks on `--all-files` (as lint.yml `lint / hooks`
  runs them); `scripts/partners.py check` (every partner in
  `.github/partners.env` resolves, no path source CI cannot resolve, no
  workflow spelling a partner commit of its own); `uv lock --check` and the
  bare `import molrec`, both against the resolved molrs; the
  docs build (`zensical build --clean --strict` in a fresh `.[docs]` env, as
  Cloudflare Pages builds it; on docs/src/zensical.toml/pyproject changes);
  and the full suite with `MOLREC_REQUIRE_MOLRS=1` against a molrs wheel
  built from the resolved commit.
- **Dispatch:** the full suite compiles molrs, so its entry goes through
  `scripts/hook-run.sh`, which hands the command to `$MOLCRAFTS_HOOK_RUNNER`
  when that is set and it is not already inside a Slurm job. On the MolCrafts
  cluster the shared `core.hooksPath` sets it to `.build-alloc/hookrun`, which
  runs the command on a compute node (allocation `$USER-hooks`; fails after
  20 min without a node, never passes). Everything else runs in place, so a
  commit never waits for Slurm. Elsewhere nothing sets the variable and every
  hook runs locally. `$MOLCRAFTS_PARTNER_CACHE`, when set, keeps the molrs
  checkout and its build between pushes.

## Partners

`.github/partners.env` declares each partner (`MOLRS_REPOSITORY`,
`MOLRS_REF`) and the molcrafts-ci commit that resolves them (`CI_REF`, a full
SHA). The resolver is molcrafts-ci's `molcrafts_ci.partners`, one
implementation for CI and the hooks: the workflows reach it through
`MolCrafts/molcrafts-ci/actions/setup-partners@<CI_REF>` (into `../molrs`),
the hooks through `scripts/partners.py`, a thin wrapper that runs it at
`CI_REF` (`check`, `fetch`, `run --`). `partners.py check` fails when a
workflow's `uses: MolCrafts/molcrafts-ci/actions/...@` names any other
commit, so moving to a new molcrafts-ci is one commit that changes `CI_REF`
and every action ref together. `scripts/partners.py` is molrs's wrapper
(only ruff's formatting differs); resolver logic never grows here.

`MOLRS_REF` is used exactly as written -- a branch, tag or full commit. There
is no same-named-branch matching and no sibling-clone fallback: the branch
being built never changes which molrs is fetched. On `dev`, `MOLRS_REF=dev`.

A change to the contract between molrec and molrs (molrs's adapter, the
conformance suite) lands as two pull requests into `dev` that pin each other
by full commit, never by skipping a gate:

- molrs's `partners.env` pins `MOLREC_REF` at the molrec commit that carries
  the adapter change;
- molrec's pins `MOLRS_REF` at the molrs pull request's head (MolCrafts/molrs
  serves a pull request's commits), in a commit of its own, relocked if the
  metadata moved.

Merge both once green (never a red one), with merge commits so the pinned
commits stay on `dev`, then set `MOLRS_REF` back to `dev` on molrec `dev`.

`uv.lock` records molrs's package metadata (version, dependencies), never a
commit, and every gate is `--locked`; when the declared molrs moves that
metadata, relock (see Commands). A release (a tag on `master`) names a molrs
tag or commit as `MOLRS_REF` in its release commit, so it is checked against a
fixed molrs; `dev` returns to `MOLRS_REF=dev` when `master` is merged back.

## Spec hygiene

- No version key, no migration: before 1.0 a record carries no schema
  version and no reader converts or refuses an old layout. A `meta` key the
  spec does not name is preserved verbatim, like any unknown key; `meta`
  comes back as stored. Identity = `*.mrec` suffix + Zarr root; writers
  always create `meta/`.
- Scientific paths are `*.mrec/` / `*.mrec.zip`. Host metrics stay on the
  filename-gated `*.mlp.*` surface (live WAL `*.mlp.jsonl`).
- Cell contract name: `Box` / `box`.
- `observables/` is the kind-based layout in `docs/spec/observables.md`
  (matches molrs; `src/molrec/observables/`, models in `core/model.py`). The
  dims-based model in `src/molrec/draft/observables/` is a **draft**
  (`schema/draft/observables/`, conformance module `draft/observables`, never
  run unless named); adopting it is a normative change to `observables/`.
- `system` is strictly frame-shaped (flat blocks, no `parameters` child).
  Force-field parameters in the `forcefield` section
  (`docs/spec/forcefield.md`, frame-shaped: document attrs + one block per
  style; LMDB key `ff`); how a job ran in `method`.
- Keep section chapters aligned with `docs/spec/storage.md` and
  `docs/spec/zarr.md`: documents are Zarr group attributes; metrics JSONL
  is an append buffer.

## CI

One workflow per kind of work. Every push of any branch runs `lint`, `test`
and `docs`, on a fork as on MolCrafts. A pull request into `dev`, `master` or
`main` runs them again, except one inside a fork (its push already ran the
full tier). molrec publishes nothing, so
there is no `release.yml` or `nightly.yml`.

| workflow | feature-branch push to MolCrafts | everything else: any push to a fork, `dev`/`master`/`main`, pull requests, tags, dispatches | upstream only |
| --- | --- | --- | --- |
| `lint.yml` | `lint / hooks` (commit hooks on every file, partners, `uv lock --check`), `lint / workflows` (`check-workflows`) | same | — |
| `test.yml` | fast: `test / python (ubuntu-latest)` (bare import + the full suite against molrs) | full: `test / python` on Linux, macOS and Windows | — |
| `docs.yml` | `docs / build` (zensical `--strict`) | same | Cloudflare Pages deploys the site from MolCrafts |

So a fork branch gets the full tier on its push: push to your fork, wait for
green, then open the pull request into MolCrafts `dev`. The
`require-green-ci` (`dev`) and `protect-master` rulesets require the full
tier's jobs and `test / context`. Every workflow's first job,
`<file> / context`, runs `MolCrafts/molcrafts-ci/actions/ci-context@<CI_REF>`,
which decides the tier, fork vs upstream and the pull-request dedup; the other
jobs read its outputs. Shared setup is molcrafts-ci's
`MolCrafts/molcrafts-ci/actions/<name>@<CI_REF>` (`setup-rust`,
`setup-python`, `setup-partners`), every ref the full `CI_REF` commit from
`.github/partners.env` (see Partners).
