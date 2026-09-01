# Status group

Execution lifecycle for a record is stored in the `status` group. It is used
for monitoring, resume decisions, and UI summaries. Scientific result
arrays live on `frame`, `trajectory`, or `observables`; time series of
measurements live on `metrics`.

In the reference binding the contents are group attributes (one JSON
object). `status.state` is required whenever the group exists.

```text
status
 +-- state: string[]
 +-- (stage: string[])
 +-- (epoch)
 +-- (global_step)
 +-- (message: string[])
 +-- (started_at: string[])
 +-- (updated_at: string[])
 +-- (finished_at: string[])
 +-- (error)
 \-- ...
```

`state`

Lowercase lifecycle: `pending`, `running`, `succeeded`, `failed`,
`cancelled`, `skipped`. Writers may preserve custom states.

`stage`

Current execution phase, independent of lifecycle state (e.g. `train`,
`eval`, `simulate`).

`epoch`, `global_step`

Reserved counters. Extra counters go under `status.progress` with clear
names.

A run-shaped record is `meta` plus `status`, optionally with `metrics` and
`method`. `frame` is optional. See [Run surface](run.md).
