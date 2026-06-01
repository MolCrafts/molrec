# MolRec

MolRec is a backend-neutral specification that defines what a molecular record means.

This documentation is written for developers. It defines the semantics of each component — not one mandatory implementation or storage format.

## What problem does MolRec solve?

Atomistic simulation data is scattered across dozens of file formats (PDB, XYZ, LAMMPS, VASP, etc.), each with its own conventions for storing atoms, cells, trajectories, and computed quantities. MolRec provides a **single semantic model** that makes records self-describing and interoperable:

- A record always states **what** each dataset means, not just its shape.
- Metadata is mandatory where it matters — you never have to guess whether an array is an energy, a force, or a charge density.
- The model covers classical MD, ML potentials, electronic structure, and multi-stage workflows.

## Record structure

```text
/
+-- meta                  required    record-level metadata
+-- frame                 required    canonical snapshot
|   +-- <collections>                   atoms, bonds, angles, ...
|   +-- <grids>                         volumetric data (charge density, ...)
|   +-- box                             simulation cell
+-- trajectory            optional    time-series of frames
+-- observables           optional    derived quantities (scalar, vector, grid)
+-- status                optional    execution state and progress
+-- metrics               optional    append-oriented runtime measurements
+-- method                optional    scientific context
+-- parameters            optional    workflow parameters
```

## Core concepts

### Frame

The canonical snapshot of the system. Contains **named collections** (atoms, bonds, angles, beads, fragments, ...), optional **grids** (volumetric fields), and an optional **box** (simulation cell).

Frame is not restricted to atoms. Any entity set with a count and aligned per-entity arrays is a valid collection.
If a collection stores positions, MolRec accepts either packed Cartesian vectors or split-axis
coordinate triplets. For atom-like split-axis data, both `x/y/z` and `xu/yu/zu` are legal
coordinate triplets; the spec does not require one to be synthesized from the other.

### Box

The simulation cell lives on **frame** as the `box` property. Each frame carries its own cell vectors, origin, and periodic boundary conditions.

For trajectories, each frame stores its own box — supporting both fixed-cell and variable-cell simulations naturally.

### Trajectory

A logical list of frame-like snapshots, packed into aligned arrays grouped by collection. Trajectories are **collection-based, not atoms-only** — bonds, angles, and any named collection can evolve over time.

### Observables

Derived or reported quantities, each stored as a `name` / `meta.<name>` pair. MolRec defines three observable data kinds:

| Kind | Example | Data |
|------|---------|------|
| **Scalar** | total energy, temperature | `Column` (1-D array) |
| **Vector** | dipole moment, momentum | `Column` (N-D array) |
| **Grid** | charge density, spin density | `Grid` (volumetric field) |

Every observable must carry explicit metadata: `kind`, `description`, `time_dependent`, and optionally `unit`, `axes`, `sampling`, `domain`.

### Status

Current execution state for the record. Stores lifecycle state, stage, progress counters, task
status, and current error summaries. The convention follows MolNex-style `TrainState` keys such as
`stage`, `epoch`, and `global_step`.

### Metrics

Append-oriented runtime measurements such as `train/loss`, `eval/MAE`,
`performance/step_per_second`, and `gpu/alloc_gib`. The convention follows Molexp's run-local
metric event model with typed records, stable keys, optional steps, wall-time timestamps, and tags.

### Grid

A data structure representing values on a uniform 3-D spatial grid. Defined by `dim`, `origin`, `cell`, `pbc`, and one or more named scalar arrays. Grid appears in two places:

- **In frame**: as part of the canonical snapshot (e.g., `frame["chgcar"]`).
- **In observables**: as `ObservableKind::Grid`, carrying semantic metadata (description, unit, etc.).

### Method

Typed scientific context describing how the record was produced. Supports `classical`, `ml`, `electronic_structure`, `workflow`, and custom types.

## Reading guide

| Chapter | What it covers |
|---------|---------------|
| [Overview](spec/overview.md) | Core ideas, design decisions, normative invariants |
| [Meta](spec/meta.md) | Record-level metadata, versioning, audit trail |
| [Frame](spec/frame.md) | Canonical collections, tuple collections, box |
| [Trajectory](spec/trajectory.md) | Packed time-series, canonical vs dynamic mode |
| [Observables](spec/observables.md) | Observable pairing, metadata contract |
| [Status](spec/status.md) | Execution state, stage, progress, task status |
| [Metrics](spec/metrics.md) | Append-oriented runtime measurements |
| [Types](spec/types.md) | Data kinds (scalar, vector, grid, field, table), sampling, domains |
| [Method](spec/method.md) | Method schemas (classical, ML, electronic structure, workflow) |
