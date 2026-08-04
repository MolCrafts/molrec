# Observables

## Purpose

`observables` is a recommended record section for named derived or reported
quantities that are part of the interpreted scientific record — a total energy, a
dipole moment, a per-atom charge. It is a convention layered on the general model
(see [Overview](overview.md)); a record need not carry one.

**Not the same as metrics.** Run-local monitoring series (training loss, step
time, throughput) belong under [Metrics](metrics.md) as part of the
[run surface](run.md). Observables are scientific results a reader would treat as
part of the chemistry/physics payload, not job telemetry.

Each observable is a pair:

- `observables/<name>` — the data, a column (see [Types](types.md));
- `observables/meta/<name>` — its semantic metadata.

When the section is present the pairing is mandatory: observable data are never
standalone.

## Structure

```text
observables
\-- meta
|   \-- <name>
|       +-- kind: String[]            # "scalar" | "vector"
|       +-- description: String[]
|       +-- time_dependent: Bool[]
|       +-- (unit: String[])
|       +-- (axes: String[A])
|       \-- (target: String[])
\-- <name>: <dtype>[...]
\-- ...
```

## Kinds

MolRec defines two observable kinds:

| Kind | Meaning | Typical shape |
|------|---------|---------------|
| `scalar` | one value per sample | `[]` or `[ntimestep]` |
| `vector` | an ordered tuple of components per sample | `[ncomp]` or `[ntimestep][ncomp]` |

Higher-rank data (tensors), volumetric fields, and tables are expressed with the
same two kinds plus `axes` metadata naming the trailing axes. A producer that
needs a distinct kind declares it in a module under `meta/modules`.

## Metadata

Required for every observable:

- `kind`
- `description`
- `time_dependent`

Recommended when applicable:

- `unit` — physical unit of the values;
- `axes` — names of the trailing axes when the rank is greater than zero;
- `target` — the block an entity-aligned observable indexes (e.g.
  `/frame/atoms`).

## Time dependence

Time dependence is stated in metadata, not inferred from shape. When
`time_dependent = true`, the leading axis is the trajectory axis (named
`timestep` by convention).

## Relationship to metrics

Use `observables` for values that are part of the interpreted scientific record;
use [metrics](metrics.md) for run-local monitoring streams. A writer may mirror a
value into metrics for live display, but the observable remains the authoritative
scientific value.
