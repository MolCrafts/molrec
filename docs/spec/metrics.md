# Metrics

## Purpose

`metrics` stores append-oriented runtime measurements.

It is designed for training curves, validation scores, performance counters, diagnostics, and other
run-local values that are useful while a record is being produced. The convention follows Molexp's
run-local metrics stream while staying backend-neutral.

Metrics are not the same as `observables`. Use `observables` for scientific quantities that are part
of the interpreted record. Use `metrics` for monitoring and execution-local measurements.

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

A JSONL backend may use the compact Molexp field names:

| Logical field | Compact field |
|---------------|---------------|
| `type` | `t` |
| `key` | `k` |
| `step` | `s` |
| `wall_time` | `w` |
| `value` | `v` |
| `tags` | `tags` |

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
