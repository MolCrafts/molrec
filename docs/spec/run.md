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

| Section | Role | Spec |
|---------|------|------|
| `method` | Scientific / training context | [Method](method.md) |
| `status` | Lifecycle state, stage, progress, errors | [Status](status.md) |
| `metrics` | Append-oriented run-local curves and counters | [Metrics](metrics.md) |

### Observables vs metrics

- **`observables`** — scientific quantities that are part of the *interpreted*
  result of the record (e.g. radial distribution, spectrum).
- **`metrics`** — run-local monitoring (loss, lr, wall time, throughput).

Do not put training loss series under `observables` solely because they are
numeric. Do not put published scientific series only under `metrics`.

## Minimum Run-shaped record

A **Run**-shaped record requires:

- `meta` (always)
- `status` (with at least `status/state` when the section exists)

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
| Failed job for resume | `meta` + `status` (+ `status/error`) + `method` |
| Eval pass | `meta` + `status` (stage=`eval`) + `metrics` + optional `observables` |

## Pointers into existing chapters

This chapter does **not** replace the field tables in status / metrics /
method. It indexes them as one surface:

1. Write lifecycle with [Status](status.md).
2. Append measurements with [Metrics](metrics.md) — **JSONL** live stream
   (`metrics/metrics.jsonl`), not Zarr append.
3. Describe the scientific setup with [Method](method.md).
4. Place the package under the [Record](record.md) root.

## Minimal filesystem Run package (reference)

A non-Zarr Run-shaped package that tools can discover without a Zarr reader:

```text
<record-root>/
├── meta/meta.json          # record_schema_version, creator, …
├── status/status.json      # state (required when status exists), stage, …
└── metrics/
    ├── metrics.jsonl       # append-only stream (authoritative)
    └── index.json          # optional derived
```

Producers (training frameworks, workflow runners) SHOULD write this shape so
experiment UIs can match on `metrics/metrics.jsonl` and open the package as a
MolRec Run without importing the producer.

## See also

- [Record](record.md) — minimum shapes including Run
- [Overview](overview.md)
