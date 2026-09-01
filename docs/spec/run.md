# Run surface

The run surface is how MolRec represents training jobs, simulations in
flight, and multi-stage workflows as records.

```text
method   →  what method / engine / model is running
status   →  where execution is now
metrics  →  append-only measurements along the way
```

`method`

Scientific or training context. See [Method](method.md). In the reference
binding: group attributes.

`status`

Lifecycle state, stage, progress, errors. See [Status](status.md). In the
reference binding: group attributes.

`metrics`

Append-oriented run-local curves and counters. See [Metrics](metrics.md).
In the reference binding: JSONL text buffer, densified to Zarr series.

Observables are scientific quantities that are part of the interpreted
result of the record. Metrics are run-local monitoring. Training loss
belongs under `metrics`; a published series belongs under `observables`.

A run-shaped record requires `meta` and `status` (with at least
`status.state` when the section exists). It should include at least one of
`metrics` or `method`. `frame` and `system` are optional.

Typical compositions: an ML training job is `meta` + `method` + `status` +
`metrics`; an MD production monitor may add `trajectory`; a failed job for
resume is `meta` + `status` (+ `status.error`) + `method`.

A host (a molexp run directory) keeps lifecycle in host files and metrics
on `*.mlp.*` — see [Root layout](storage.md). `status/` and `meta/` are
record groups.
