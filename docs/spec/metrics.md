# Metrics group

Run-local measurements (training curves, validation scores, performance
counters) are stored in the `metrics` group. Published scientific series
belong under [Observables](observables.md).

## Events

Each logical event has a type, a slash-separated series key, a wall-clock
time, a value, and optionally a step and tags:

| Field | Type | Meaning |
|-------|------|---------|
| `type` | string | `scalar` for a number; a custom type names a module under `meta/modules` |
| `key` | string | the series key, slash-separated (`train/loss`) |
| `step` | integer, optional | the producer's iteration counter |
| `wall_time` | string | when the event happened: [RFC 3339](https://www.rfc-editor.org/rfc/rfc3339) **with an explicit offset** (`2026-08-04T12:00:00Z`, `…+02:00`) |
| `value` | number | for `scalar`, a finite JSON number |
| `tags` | object, optional | free-form labels, preserved |

A series is the events of one `key`, in the order they were logged. Within a
series, two events with the same `step` are one point: **the later one
wins** (a resumed run that re-logs step 100 replaces the earlier value).
Events without a `step` are never merged.

## The closed form: dense series

```text
metrics
 +-- (catalog document)                  the group's attributes
 \-- series
 |    \-- <safe_name>: f64[n]            one value per point
 \-- (steps)
 |    \-- (<safe_name>: i64[n])          the point's step, when the series has steps
 \-- (wall_time)
 |    \-- (<safe_name>: string[n])       the point's RFC 3339 time
 \-- (metrics.jsonl)                     the live WAL, a plain file (not a Zarr node)
```

- `metrics/series/<safe_name>` holds one `f64` per point of the series, in
  log order after the duplicate-step rule above. `steps/` and `wall_time/`
  hold the matching per-point step (`i64`) and time (`string`), aligned
  index for index; a series with no steps has no `steps/` array.
- The array name is the series key's **safe name**: every byte of the UTF-8
  key outside `[A-Za-z0-9._-]` becomes `%XX` with uppercase hex (`train/loss`
  → `train%2Floss`). The encoding is total and reversible. Because a safe
  name is one node name it must also not be one Zarr forbids: a key that is
  `.` or `..`, or that would start with `__`, has its first byte escaped too
  (`.` → `%2E`, `..` → `%2E.`, `__x` → `%5F_x`), and a reader decodes it back
  the same way. The empty string is not a series key.

## The catalog

The `metrics/` group attributes are the catalog document:

```json
{
  "wal": { "lines": 3, "bytes": 233 },
  "series": {
    "train/loss": { "type": "scalar", "count": 2, "latest_step": 2,
                    "latest_timestamp": "2026-08-04T00:00:02+00:00" }
  }
}
```

- `series` names every densified series: its `type`, its point `count`, and
  the step and time of its last point (`null` when it has none).
- `wal` is the **watermark**: the dense series hold exactly the first
  `lines` complete lines (`bytes` bytes) of `metrics/metrics.jsonl`. Up to
  the watermark the dense series are authoritative; WAL lines past it are
  newer and a reader appends them, under the same duplicate-step rule. A
  catalog without `wal` covers no WAL: the dense series are the whole
  record.
- Other keys are preserved.

The live WAL is specified in [Metrics WAL](metrics-wal.md).
