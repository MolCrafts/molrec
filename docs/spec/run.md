# Run surface

## Purpose

The **run surface** is how MolRec represents training jobs, simulations in
flight, and multi-stage workflows as Records — not as ad-hoc log files and not
as a store product.

It is the triangle:

```text
method   →  what method / engine / model is running
status   →  where execution is now (lifecycle + progress)
metrics  →  append-only measurements along the way
```

Together they let molnex, molexp, molq, and analysis tools share one lifecycle
and metrics vocabulary.

## Section roles

| Section | Role | Spec | Physical (L4) |
|---------|------|------|----------------|
| `method` | Scientific / training context | [Method](method.md) | Zarr group attributes |
| `status` | Lifecycle state, stage, progress, errors | [Status](status.md) | Zarr group attributes |
| `metrics` | Append-oriented run-local curves and counters | [Metrics](metrics.md) | JSONL text buffer (+ optional Zarr summary) |

### Observables vs metrics

- **`observables`** — scientific quantities that are part of the *interpreted*
  result of the record (e.g. radial distribution, spectrum).
- **`metrics`** — run-local monitoring (loss, lr, wall time, throughput).

Do not put training loss series under `observables` solely because they are
numeric. Do not put published scientific series only under `metrics`.

## Minimum Run-shaped record

A **Run**-shaped record requires:

- `meta` (always)
- `status` (with at least `status.state` when the section exists)

and SHOULD include at least one of:

- `metrics`
- `method`

A Run-shaped record **does not require** `frame` or `system`. Attach those when
the run also materializes structures or a defined chemical system.

## Typical compositions

| Scenario | Sections |
|----------|----------|
| ML training job | `meta` + `method` + `status` + `metrics` |
| MD production run monitor | `meta` + `method` + `status` + `metrics` + optional `trajectory` |
| Failed job for resume | `meta` + `status` (+ `status.error`) + `method` |
| Eval pass | `meta` + `status` (stage=`eval`) + `metrics` + optional `observables` |

## Pointers into existing chapters

This chapter does **not** replace the field tables in status / metrics /
method. It indexes them as one surface:

1. Write lifecycle with [Status](status.md) → Zarr `status/` attributes.
2. Append measurements with [Metrics](metrics.md) → **JSONL WAL**
   (`metrics/metrics.jsonl` on a Record; `<stem>.mlp.jsonl` on a host),
   densified into Zarr series on flush (not per-step Zarr chunk append).
3. Describe the scientific setup with [Method](method.md) → Zarr `method/`
   attributes.
4. Place everything under one [Record](record.md) Zarr root ([Storage](storage.md)).

## Minimal Run root (reference)

Still a **Zarr root** — not a loose tree of `.json` files:

```text
<record-root>/                 # Zarr V3
├── meta/                      # attrs: record_schema_version, creator, …
├── status/                    # attrs: state (required), stage, …
├── method/                    # attrs: type, engine, …  (optional)
└── metrics/
    ├── (attrs)                # catalog / closed summary
    ├── series/…               # dense arrays after densify
    └── metrics.jsonl          # live WAL when metrics exist
```

Producers of a **Record** SHOULD write this shape so tools open one Zarr
package and prefer dense series (tail the WAL only while live). Attribute
payloads and the WAL golden: `fixtures/run-minimal/`.

A **host** (molexp Run) is not this tree. It keeps lifecycle in host files
and metrics on `*.mlp.*` — see [Storage](storage.md) host layout. Do not
treat `ops/run.json` as `status/` or `run.json` as `meta/`.

## See also

- [Record](record.md) — minimum shapes including Run
- [Storage](storage.md) — Zarr root + metrics WAL
- [Overview](overview.md)
