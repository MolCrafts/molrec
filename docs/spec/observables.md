# Observables

## Purpose

`observables` stores arbitrary recorded quantities.

An observable is always represented by a pair:

- `observables/<name>`
- `observables/meta/<name>`

This pairing is mandatory.

## Structure

```text
observables
\-- meta
|   \-- <name>
|       +-- kind: String[]
|       +-- description: String[]
|       +-- (unit: String[])
|       +-- (axes: String[A])
|       +-- time_dependent: Bool[]
|       +-- (sampling: String[])
|       +-- (domain: String[])
|       +-- (target: String[])
|       \-- ...
\-- <name>: <type>[...]
\-- ...
```

For every observable dataset `observables/<name>`, the metadata entry `observables/meta/<name>` must
exist.

## Why metadata is mandatory

MolRec does not try to infer the meaning of an observable only from:

- the dataset name
- the dataset shape
- the implementation that wrote it

The meaning must be stated explicitly in metadata.

## Common metadata fields

The following fields form the minimum metadata contract for `observables/meta/<name>`:

- `kind`: required for every observable
- `description`: required for every observable
- `time_dependent`: required for every observable
- `axes`: required whenever the data rank is greater than zero
- `unit`: required whenever the stored values have a physical unit
- `sampling`: required whenever the values sample time, entities, grids, or point sets
- `domain`: required whenever the values live on a named domain rather than the whole record
- `target`: required whenever the meaning depends on alignment to another subtree or collection

## Data kinds

MolRec defines the common observable data kinds and their required metadata in [Types](types.md).

If a writer introduces a custom observable kind, its parse rules must be documented in
[Types](types.md) or in a module declared under `meta/modules`.

## Relationship to metrics

`observables` and `metrics` are intentionally separate.

Use `observables` when a value is part of the interpreted scientific record. Use `metrics` when a
value is a run-local measurement stream for monitoring, diagnostics, or training curves.

A writer may mirror a scientific value into `metrics` for live display, but the observable remains
the authoritative scientific value.

## Time dependence

Time dependence is described in metadata, not inferred solely from shape.

Typical patterns:

- `Float[]` with `time_dependent = false`
- `Float[ntimestep]` with `time_dependent = true`
- `Float[ntimestep][3][3]` with `time_dependent = true`

If `time_dependent = true`, the leading logical axis should be named `timestep` unless a documented
module defines a different convention.

## Rule

The core rule is:

> observable data are never standalone; they are always defined together with `meta.<name>`.
