# Metrics group

Run-local measurements (training curves, validation scores, performance
counters) are stored in the `metrics` group. They are a dense series catalog
of named series of points. Published scientific series belong under
[Observables](observables.md).

Each logical event has a type, a slash-separated series key, a wall-clock
time, a value, and optionally a step and tags.

The closed source of truth for curves is dense float64 Zarr series under
`metrics/series/<safe_name>`. A series key is slash-separated
(`train/loss`) and an array name cannot be, so the array name is the
*safe name*: percent-encode every byte outside `[A-Za-z0-9._-]` as `%XX`
with uppercase hex (`train/loss` → `train%2Floss`). The encoding is total
and reversible; readers decode it back to the key.

Live append uses an append-only JSONL WAL (`metrics/metrics.jsonl`).
Writers append; historical events stay.

The physical layout of the WAL, compact keys, and densified series is
specified in [Metrics WAL](metrics-wal.md).
