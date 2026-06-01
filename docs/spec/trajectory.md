# Trajectory

## Purpose

`trajectory` stores a packed list of frames.

Conceptually:

```text
trajectory == [frame_0, frame_1, frame_2, ...]
```

Physically, these frames are stored as aligned arrays grouped by collection. This preserves
frame-like semantics without requiring literal storage as repeated frame objects.

## Structure

```text
trajectory
\-- meta
|   +-- ntimestep: Integer[]
|   +-- storage: String[] = "packed_collections"
\-- (step: Integer[ntimestep])
\-- (time: Float[ntimestep])
\-- (atoms)
|   \-- meta
|   |   +-- count_mode: String[] = "canonical" | "dynamic"
|   |   +-- (target: String[] = "/frame/atoms")
|   |   +-- (max_count: Integer[])
|   |   +-- (count: Integer[ntimestep])
|   \-- (mask: Bool[ntimestep][M])
|   \-- (id: Integer[ntimestep][M])
|   \-- (position: Float[ntimestep][M][ndim])
|   \-- (velocity: Float[ntimestep][M][ndim])
|   \-- (charge: Float[ntimestep][M])
|   \-- ...
\-- (bonds)
|   \-- meta
|   |   +-- count_mode: String[] = "canonical" | "dynamic"
|   |   +-- (target: String[] = "/frame/bonds")
|   |   +-- (max_count: Integer[])
|   |   +-- (count: Integer[ntimestep])
|   \-- (mask: Bool[ntimestep][M])
|   \-- (index: Integer[ntimestep][M][2])
|   \-- (order: Float[ntimestep][M])
|   \-- ...
\-- (custom_collection)
|   \-- ...
\-- ...
```

`M` denotes the entity-axis storage size for a collection. In canonical mode, `M` equals the count
of the referenced frame collection. In dynamic mode, `M` equals `max_count`.

## Required metadata

- `trajectory/meta/ntimestep`
- `trajectory/meta/storage`

Rules:

- every trajectory collection has a `meta/count_mode`
- every trajectory dataset has leading axis `ntimestep`
- each trajectory collection defines the meaning of its entity axis through `count_mode` and, when
  relevant, `target`

## Logical list, packed storage

MolRec treats `trajectory` as a logical list of frame-like snapshots. Writers should normally store
that list in packed collection arrays rather than as repeated nested frame objects.

This keeps:

- I/O efficient for common slices such as `position[:, :, :]`
- metadata deduplicated across timesteps
- trajectory semantics close to in-memory frame objects

The storage model therefore does not imply larger files than a specialized trajectory backend. It
only constrains how the arrays should be interpreted.

## Collection modes

### Canonical mode

A canonical trajectory collection reuses the entity order of a frame collection.

Required metadata:

- `meta/count_mode = "canonical"`
- `meta/target = "/frame/<collection>"`

Typical shapes:

- `Float[ntimestep][count]`
- `Float[ntimestep][count][ndim]`
- `Integer[ntimestep][count][arity]`

This mode is appropriate for fixed-composition trajectories and any collection with stable entity
alignment across time.

When a trajectory collection stores positions, MolRec accepts either packed Cartesian vectors or
split-axis Cartesian triplets at each timestep. For atom-like split-axis trajectory data, both
`x/y/z` and `xu/yu/zu` are legal coordinate triplets, and readers do not need to synthesize one
from the other.

### Dynamic mode

A dynamic trajectory collection allows the active entity set to vary with timestep.

Required metadata:

- `meta/count_mode = "dynamic"`
- `meta/max_count`
- `meta/count[ntimestep]`

Required companion datasets:

- `mask[ntimestep][max_count]`

Strongly recommended companion datasets:

- `id[ntimestep][max_count]` for persistent entity identity
- `index[ntimestep][max_count][arity]` for dynamic tuple collections

Dynamic mode is appropriate for changing composition, changing topology, insertion or deletion
workflows, adaptive-resolution methods, and any trajectory where a canonical entity alignment alone
is insufficient.

## Shared timestep axes

The optional arrays:

- `step[ntimestep]`
- `time[ntimestep]`

provide the shared indexing for the packed list of frames.

`step` is appropriate for discrete iteration indices.

`time` is appropriate when physical time exists.

The root-level `box` group may also use this same timestep axis when `box/meta/time_dependent =
true`.

## Scope

This chapter defines frame-like trajectory collections with a shared leading timestep axis.

Quantities that are not part of the evolving frame-like state, such as reduced scientific
statistics, spectra, or free-energy surfaces, belong in `observables`. Run-local monitoring values
and convergence traces belong in `metrics`.
