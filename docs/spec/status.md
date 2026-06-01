# Status

## Purpose

`status` stores execution state for a record.

It is intended for monitoring, resume decisions, and UI summaries. It is not the place for
scientific result arrays. Result arrays belong in `frame`, `trajectory`, `observables`, or
`metrics`, depending on their semantics.

The convention follows the MolNex `TrainState` pattern: a small set of reserved progress keys plus
namespaced extension fields.

## Structure

```text
status
+-- state: String[]
+-- (stage: String[])
+-- (epoch: Integer[])
+-- (global_step: Integer[])
+-- (steps_since_last_eval: Integer[])
+-- (message: String[])
+-- (started_at: String[])
+-- (updated_at: String[])
+-- (finished_at: String[])
+-- (progress)
|   +-- ...
+-- (history)
|   \-- <event_id>
|       +-- state: String[]
|       +-- (stage: String[])
|       +-- timestamp: String[]
|       +-- (message: String[])
|       \-- ...
+-- (tasks)
|   \-- <task_id>
|       +-- state: String[]
|       +-- (stage: String[])
|       +-- (progress)
|       \-- ...
+-- (error)
|   +-- type: String[]
|   +-- message: String[]
|   +-- (timestamp: String[])
|   \-- ...
+-- ...
```

`status/state` is required whenever `status` exists.

## Lifecycle states

MolRec recommends the following lowercase lifecycle vocabulary:

| State | Meaning |
|-------|---------|
| `pending` | Created but not started |
| `running` | Currently executing |
| `succeeded` | Finished successfully |
| `failed` | Finished with an error |
| `cancelled` | Stopped by user or scheduler request |
| `skipped` | Intentionally not executed |

Writers may preserve custom states, but readers should treat unknown states as terminal only if a
module specification declares them terminal.

## Stages

`status/stage` describes the current execution phase, independent of lifecycle state.

MolRec reserves the MolNex stage vocabulary:

- `train`
- `eval`
- `test`
- `predict`

Additional stages such as `prepare`, `simulate`, `relax`, or `analyze` are valid when they are
documented by `method` or a declared module.

## Progress keys

`status` stores small counters needed for monitoring and resume decisions.

The reserved MolNex-compatible keys live directly under `status`:

- `epoch`: current epoch index, zero-based when training semantics apply
- `global_step`: monotonically increasing step counter across the run
- `steps_since_last_eval`: step counter since the last evaluation pass

Writers may add more counters under `status/progress`, but they should use clear names and avoid
reusing the reserved keys with different meanings.

## History

`status/history` is an optional ordered event log.

Each event should include:

- `state`
- `timestamp`

Each event may include:

- `stage`
- `message`
- producer-specific fields

History is append-oriented. Updating the current `status/state` does not require rewriting previous
events.

## Task status

`status/tasks/<task_id>` stores per-task or per-stage state when a record comes from a workflow.

Task IDs should match identifiers used in `method/stages`, workflow assets, or the producing
engine. A task status has the same basic fields as the root status:

- `state`
- optional `stage`
- optional `progress`
- optional `message`

## Relationship to metrics

Status fields are a compact current-state snapshot. Metrics are an append-oriented measurement
stream.

Examples:

- `status/global_step = 4000` says where execution is now.
- `metrics` records `train/loss` at many steps.
- `status/state = "failed"` says the run failed.
- `status/error/message` stores the current error summary.

## Rule

The core rule is:

> `status` records lifecycle and progress state; measurements over time belong in `metrics`.
