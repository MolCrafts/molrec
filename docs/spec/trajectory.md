# Trajectory

## Purpose

`trajectory` is an ordered sequence of frames — the time evolution of the system.
It is a recommended record section built on the general model: each element is a
[frame](frame.md), carried alongside two optional index arrays.

```text
trajectory == [frame_0, frame_1, frame_2, ...]
```

The canonical entity remains the frame; a trajectory adds ordering and indexing,
not new structure.

## Logical model

```text
trajectory
+-- frames: [Frame]                 # ordered frame-like states
+-- (step: Integer[nstep])          # discrete iteration indices
\-- (time: Float[nstep])            # physical time values
```

Rules:

- `step` and `time`, when present, are aligned to the frame order (length
  `nstep`).
- Each frame carries its own [box](frame.md#box), so fixed-cell and variable-cell
  runs are both natural.
- A record **MAY** omit `system/` and still carry `trajectory/` (frames may embed
  full blocks, including topology).
- When both `system/` and `trajectory/` are present, trajectory **SHOULD** update
  **state only** (coordinates, instantaneous properties, instantaneous box) and
  not restate topology held in `system/`.

## Packed storage (convention)

Storing a trajectory as a literal list of frame objects duplicates metadata every
step. By convention a writer instead packs the sequence into per-block arrays
with a leading time axis:

```text
trajectory
\-- atoms
|   +-- x: Float[nstep][count]
|   \-- ...
\-- bonds
    +-- atomi: UInt[nstep][count]
    \-- ...
```

This is a storage convention (see
[Conventions](conventions.md#trajectory-packing)), not a change to the logical
model — the packed arrays still mean an ordered list of frames. A block whose
entity set changes over time may add a per-step `count` and a `mask` array marking
active entities; fixed-composition blocks need neither.

## Scope

Evolving frame-like state belongs in `trajectory`. Reduced scientific statistics
(spectra, free-energy surfaces) belong in [observables](observables.md); run-local
monitoring belongs in [metrics](metrics.md).
