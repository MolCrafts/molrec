# Metrics

## Purpose

`metrics` stores **run-local** measurements (training curves, validation
scores, performance counters). It is part of the **run surface** (with
[Status](status.md) and [Method](method.md)) — see [Run surface](run.md).

It is a recommended record section: a convention layered on the general model
([Overview](overview.md)), not part of L0–L2.

**Not the same as observables.** Scientific results that are part of the
interpreted chemistry/physics payload belong under [Observables](observables.md).
Do not put training loss only under `observables` solely because it is numeric.
Do not put published scientific series only under `metrics`.

## Logical model

`metrics` is a **dense series catalog** — named series of points, not a
columnar L1 table and not a nested `records/<id>/` tree.

Each **logical event** (for live append and interchange dialects) has:

| Logical field | Required | Meaning |
|---------------|----------|---------|
| `type` | yes | Metric type (`scalar`, `histogram`, …) |
| `key` | yes | Stable slash-separated series name |
| `wall_time` | yes | ISO-8601 timestamp string |
| `value` | yes | Payload; shape depends on `type` |
| `step` | no | Finite number (training / sim step) |
| `tags` | no | JSON object of free-form tags |

Rules:

- `key` MUST be a non-empty string.
- `step`, if present, MUST be a finite number.
- Live append is ordered: writers MUST NOT mutate or delete historical events
  in the WAL.
- The **closed source of truth** for curves is the **dense Zarr binding**
  (per-series arrays), not the WAL.

Foreign dialects (event JSONL, CSV, LAMMPS thermo, TensorBoard, …) are
**equal sources**. Hosts normalize them into this model; they are not alternate
SoTs.

## Physical binding (reference)

Full root rules: [Storage](storage.md).

### Dense Zarr SoT (closed / densified)

Inside the one record root:

```text
metrics/                     # group attributes = the catalog below
  series/
    <safe_name>/             # f64 values [n]
    <safe_name>__steps/      # optional f64 [n]
    <safe_name>__wall/       # optional f64 unix seconds [n]
  metrics.jsonl              # live WAL, not an array
```

`<safe_name>` is the percent-encoding in [Storage](storage.md): `train/loss`
is stored as `train%2Floss`. The catalog key is the original name.

Catalog attributes on the `metrics/` group:

| Attribute | Meaning |
|-----------|---------|
| `series` | map of original key → `{type, count, array, steps_array?, wall_array?}` |
| `series_count` | number of keys |
| `point_count` | total scalar points |

The catalog has no `format_name` and no version of its own. The record's
`meta.record_schema_version` covers it. There is no `metrics/zarr/` store.

Consumers that need the curve read the dense arrays when `series/` exists.

### Live WAL (append-only text)

High-frequency append is a poor fit for per-step Zarr chunk realignment. Live
writes use a plain UTF-8 **JSONL WAL** beside the dense store:

```text
metrics/metrics.jsonl
```

- One JSON object per line, terminated by `\n`
- omit keys whose value would be JSON `null`
- writers MUST NOT rewrite or delete historical lines
- readers MUST skip blank lines; malformed lines SHOULD be counted and skipped
- **not** the closed SoT: on flush / close, writers densify into Zarr

Compact field names (WAL dialect only):

| Logical field | Compact key |
|---------------|-------------|
| `type` | `t` |
| `key` | `k` |
| `step` | `s` |
| `wall_time` | `w` |
| `value` | `v` |
| `tags` | `tags` |

Example lines:

```json
{"t":"scalar","k":"train/loss","s":1,"w":"2026-08-04T00:00:01+00:00","v":0.5}
{"t":"scalar","k":"train/loss","s":2,"w":"2026-08-04T00:00:02+00:00","v":0.25}
```

### Closed summary vs dense store vs WAL

| Artifact | Authoritative for curves? | When |
|----------|---------------------------|------|
| `metrics/series/` | **Yes** when present | After densify / close |
| `metrics/metrics.jsonl` | Live only; fallback if no dense store | During a run; pre-flush |
| Group attributes summary only | No — listing aid | Optional |

There is **no** first-class `metrics/index.json` in the reference binding;
hosts MAY keep a rebuildable listing cache.

## Metric types

| Type | Value contract |
|------|----------------|
| `scalar` | finite number |
| `histogram` | object with numeric `bins` and numeric `counts` arrays |
| `text` | string |
| `image_ref` | object with `path` string and optional `caption` |
| `json` | any JSON-compatible value |

Scalar series densify to `f64` arrays. `__steps` is the event's `step` as
`f64`. `__wall` is `wall_time` converted from ISO-8601 to Unix seconds as
`f64`. The WAL keeps the ISO string; the dense array keeps the number. Both
are that one conversion, not two clocks.

`histogram`, `text`, `image_ref`, and `json` stay in the WAL until a dense
encoding for them is added. They are not a second source of truth for scalar
curves.

## Key namespace

Keys should be stable slash-separated names. Recommended namespaces (MolNex
`TrainState` convention):

| Prefix | Use |
|--------|-----|
| `train/*` | training metrics (`train/loss`) |
| `eval/*` | validation (`eval/MAE`) |
| `test/*` | held-out test |
| `performance/*` | runtime counters (`performance/step_per_second`) |
| `gpu/*` | device counters (`gpu/alloc_gib`) |

Keys are case-sensitive. Writers should not use display labels as keys; put
labels in tags or surrounding metadata.

## Relationship to status

| Section | Role |
|---------|------|
| `metrics` | values over time (many points) — dense Zarr + optional WAL |
| `status` | current lifecycle / progress snapshot — **Zarr attributes** |

## Rule

> `metrics` is a dense series catalog (Zarr arrays) with an optional JSONL WAL
> for live append; foreign logs are dialects, not alternate SoTs. It is not a
> replacement for `observables`.
