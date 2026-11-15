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
| `value` | number | for `scalar`, one `f64`: a finite JSON number, or the string `"NaN"` / `"Infinity"` / `"-Infinity"` for a non-finite measurement ([typed JSON values](conventions.md#typed-json-values)); for a custom type, whatever JSON its module defines |
| `tags` | object, optional | free-form labels, preserved |

A series is the events of one `key`, in the order they were logged. Within a
series, two events with the same `step` are one point: **the later one
wins** (a resumed run that re-logs step 100 replaces the earlier value).
The point **stays where the first event with that step put it**: the later
event replaces its value, wall-clock time and tags in place, and the order of
the series' other points does not move. A diverged run's `NaN` is a value
like any other: it is a point, and it replaces or is replaced under the same
rule.

A series is **stepped or not, as a whole**: every event of one `key` carries
a `step`, or none does. A writer refuses an event that would mix the two in
one series, and a reader refuses a series that does. Events of a series
without steps are never merged: each is a point.

Every event of one `key` has the same `type`; a writer refuses an event
whose type differs from the series'.

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
  log order after the duplicate-step rule above; a non-finite value is
  stored as the `f64` it is. `steps/` and `wall_time/` hold the matching
  per-point step (`i64`) and time (`string`), aligned index for index; a
  series with no steps has no `steps/` array.
- **Only `scalar` series are densified.** An event of a custom type, and the
  `tags` of any event, have no dense form: they live in the WAL alone. A
  writer that densifies therefore keeps `metrics/metrics.jsonl` whenever it
  holds either, and a reader that wants them reads the WAL — the whole of
  it, below the watermark included, since for these the dense series hold
  nothing. A record with no WAL has scalar series without tags and nothing
  else.
- The array name is the series key's **safe name**: every byte of the UTF-8
  key outside `[A-Za-z0-9._-]` becomes `%XX` with uppercase hex (`train/loss`
  → `train%2Floss`). The encoding is total and reversible. Because a safe
  name is one [node name](frame.md#names) it must also not be one Zarr
  forbids: a key that is `.`, `..` or `zarr.json`, or that would start with
  `__`, has its first byte escaped too (`.` → `%2E`, `..` → `%2E.`,
  `zarr.json` → `%7Aarr.json`, `__x` → `%5F_x`), and a reader decodes it back
  the same way. The empty string is not a series key. The encoding keeps
  letter case, so two keys that differ only in the case of their ASCII
  letters (`train/Loss`, `train/loss`) are not two series of one record: a
  writer refuses the second.

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
  the watermark the dense series are authoritative for scalar curves; WAL
  lines past it are newer and a reader appends them, under the same
  duplicate-step rule. A catalog without `wal` covers no WAL: the dense
  series are the whole record.
- The WAL beside a watermark is at least as long as the watermark says, and
  its first `bytes` bytes end in `\n`. A WAL that is **shorter**, or that is
  absent while its dense series exist, has lost lines the series already
  hold: the dense series stand, the reader reports the WAL as truncated and
  merges nothing from it, and a writer that reopens the record rewrites the
  watermark to the WAL it finds before it appends (a missing WAL: no `wal`
  key).
- Other keys are preserved.

The live WAL is specified in [Metrics WAL](metrics-wal.md).
