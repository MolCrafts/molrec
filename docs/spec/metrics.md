# Metrics

## Purpose

`metrics` stores append-oriented runtime measurements. It is part of the **run
surface** (with [Status](status.md) and [Method](method.md)) — see
[Run surface](run.md).

It is a recommended record section — a convention layered on the general model
(see [Overview](overview.md)), not part of the core model.

It is designed for training curves, validation scores, performance counters, diagnostics, and other
run-local values that are useful while a record is being produced. The convention follows Molexp's
run-local metrics stream while staying backend-neutral.

**Observables vs metrics.** Use [Observables](observables.md) for scientific
quantities that are part of the *interpreted* record (e.g. a published RDF).
Use `metrics` for run-local monitoring (loss, learning rate, wall time). Do not
store training loss only under `observables` solely because it is numeric.

## Structure

```text
metrics
\-- records
|   \-- <record_id>
|       +-- type: String[]
|       +-- key: String[]
|       +-- (step: Float[])
|       +-- wall_time: String[]
|       +-- value: <metric-value>
|       +-- (tags)
|       \-- ...
\-- (index)
    +-- line_count: Integer[]
    +-- series_count: Integer[]
    \-- series
        \-- <key>
            +-- type: String[]
            +-- count: Integer[]
            +-- (latest_step: Float[])
            +-- (latest_timestamp: String[])
            +-- (latest_value)
```

The logical fields are `type`, `key`, `step`, `wall_time`, `value`, and `tags`.

## JSONL reference binding (append path)

The **authoritative on-disk binding for live metrics** is append-only **JSONL**,
not Zarr. High-frequency writers (training steps, MD monitors) MUST append one
JSON object per line. Chunked array stores (including Zarr) are a poor fit for
per-step scalar append: they force chunk realignment, metadata churn, and make
crash recovery harder than a line-oriented log.

### Physical layout

```text
metrics/
├── metrics.jsonl    # authoritative stream (one metric record per line)
└── index.json       # optional, derived summary (rebuildable)
```

When the MolRec package is the openable record root, those paths are
`<record-root>/metrics/metrics.jsonl` and `<record-root>/metrics/index.json`.
A host that uses the record root as its run directory (e.g. molexp) may keep
the same relative paths under the run dir.

### Compact field names

JSONL writers use the compact keys (shared with molexp):

| Logical field | Compact field |
|---------------|---------------|
| `type` | `t` |
| `key` | `k` |
| `step` | `s` |
| `wall_time` | `w` |
| `value` | `v` |
| `tags` | `tags` |

Example line:

```json
{"t":"scalar","k":"train/loss","s":120,"w":"2026-08-04T12:00:00","v":0.42}
```

Encoding rules:

- UTF-8 text, one JSON object per line, terminated by `\n`
- omit keys whose value would be JSON `null` (optional fields may be absent)
- writers MUST NOT rewrite or delete historical lines
- readers MUST skip blank lines; malformed lines SHOULD be counted and skipped
- `metrics.jsonl` is the source of truth; `index.json` is never authoritative

### Derived index

`metrics/index.json` (when present) is a rebuildable summary. Recommended shape:

```json
{
  "line_count": 3,
  "series_count": 2,
  "series": {
    "train/loss": {
      "type": "scalar",
      "count": 2,
      "latest_step": 2,
      "latest_timestamp": "2026-08-04T12:00:01"
    }
  }
}
```

Writers MAY rebuild the index on flush / close rather than on every append.

### Relationship to Zarr / hybrid roots

- **Live append** → JSONL under `metrics/` as above.
- **Closed snapshot** (optional): a pure Zarr aggregate MAY store a small
  metrics *summary* as group attributes for tooling that only opens Zarr.
  That summary is not a substitute for the stream; consumers that need the
  curve MUST read `metrics.jsonl` when it exists.
- A single record root MAY be **hybrid**: frame / trajectory / large arrays in
  Zarr groups, and `metrics/` as a filesystem JSONL sibling section.

See [Record](record.md) (backend binding) and [Run surface](run.md).

## Metric records

Every metric record must include:

- `type`
- `key`
- `wall_time`
- `value`

Optional fields:

- `step`
- `tags`

Rules:

- `key` must be a non-empty string.
- `step`, if present, must be a finite number.
- `wall_time` should be an ISO-8601 timestamp string.
- `tags`, if present, must be a JSON-compatible object.
- records are append-oriented; writers should not mutate historical records.

## Metric types

MolRec reserves the Molexp-compatible type vocabulary:

| Type | Value contract |
|------|----------------|
| `scalar` | finite number |
| `histogram` | object with numeric `bins` and numeric `counts` arrays |
| `text` | string |
| `image_ref` | object with `path` string and optional `caption` |
| `json` | any JSON-compatible value |

Custom metric types are allowed when a module declares their parse rules.

## Key namespace

Metric keys should be stable slash-separated names.

Recommended namespaces follow the MolNex `TrainState` convention:

- `train/*` for training metrics such as `train/loss`
- `eval/*` for validation or evaluation metrics such as `eval/MAE`
- `test/*` for held-out test metrics
- `performance/*` for runtime counters such as `performance/step_per_second`
- `gpu/*` for device counters such as `gpu/alloc_gib`

Keys are case-sensitive. Writers should not use display labels as keys; labels can be stored in
metadata or tags.

## Index

`metrics/index` is optional and derived.

It may summarize the metric stream for fast listing:

- total record count
- number of distinct series
- per-key type
- per-key count
- latest step
- latest timestamp
- latest scalar value when applicable

Readers must not treat an index as authoritative if the underlying metric records are available.
Backends may rebuild the index from the record stream.

## Relationship to status

Metrics capture values over time. Status captures the current lifecycle and progress state.

Examples:

- `metrics` records `train/loss` at steps 1, 2, 3, ...
- `status/global_step` stores the current step.
- `metrics` records `performance/step_per_second`.
- `status/state` stores whether execution is `running`, `succeeded`, or `failed`.

## Relationship to observables

If a value is needed to interpret the scientific record, store it in `observables`.

If the same value is also useful for live monitoring, a writer may mirror it into `metrics`, but the
observable remains the authoritative scientific value.

## Rule

The core rule is:

> `metrics` is an append-oriented measurement stream keyed by stable names; it is not a replacement
> for `observables`.
