# Trajectory

## Purpose

`trajectory` is an ordered sequence of frames — the time evolution of the system.
It is a recommended record section built on the general model: each element is a
[frame](frame.md), carried alongside a step index and an optional time index.

```text
trajectory == [frame_0, frame_1, frame_2, ...]
```

The canonical entity remains the frame. A trajectory adds ordering, indexing, and
a storage form that writes a section again only when that section changes.

## Logical model

```text
trajectory
+-- frames: [Frame]                 # ordered frame-like states
+-- step: Integer[nstep]            # discrete iteration indices
\-- (time: Float[nstep])            # physical time values
```

Rules:

- `step` and `time` are aligned to the frame order (length `nstep`).
- `step` is written by every conforming writer; `time` is optional and
  **all-or-nothing** — a run either supplies a time for every frame or for none.
- Each frame carries its own [box](frame.md#box), so fixed-cell and variable-cell
  runs are both natural.
- A record **MAY** omit `system/` and still carry `trajectory/` (frames may embed
  full blocks, including topology).
- When both `system/` and `trajectory/` are present, trajectory **SHOULD** update
  **state only** (coordinates, instantaneous properties, instantaneous box) and
  not restate topology held in `system/`.

## Frame ordinals and step numbers

Two integers index a trajectory, and they are not the same one:

- the **frame ordinal** `i` is a frame's position in the sequence,
  `0 <= i < nstep`;
- the **step number** is the value stored at `step[i]` — the producer's own
  iteration counter. It may start anywhere and may skip values; it is strictly
  increasing along the sequence.

`trajectory/step` is the only array that holds step numbers. Every index array in
the layout below (`step_index`) holds frame **ordinals**.

## Reference layout (Zarr)

`trajectory/` is a group of sections. Dense per-step data (`step`, `time`,
`meta/<key>`) has one row per frame; everything else — the cell and each block —
carries its own sparse index of the ordinals at which it changed.

```text
trajectory/                             group
+-- step        Int[nstep]              always written; the commit marker
+-- (time)      Float[nstep]            only when the writer supplies times
+-- (meta)/
|   \-- <key>   <typed>[nstep] or [nstep][3|6|9]   attr molrs_meta_dtype
+-- (box)/                              optional attr cell_defined (Bool)
|   +-- step_index  UInt[n_updates]     frame ordinals
|   +-- vectors     Float[n_updates][3][3]
|   +-- origin      Float[n_updates][3]
|   \-- boundary    Bool[n_updates][3]
\-- <block>/                            attr structural_shape when declared
    +-- step_index  UInt[n_updates]     frame ordinals
    +-- offset      UInt[n_updates+1]   CSR row pointer, offset[0] == 0
    \-- <column>    <dtype>[total_rows][...trailing]
```

The physical binding of these arrays (chunking, sharding, compression; live
directory `*.mrec/` as the Zarr V3 root; packed `*.mrec.zip`) is
[Storage](storage.md).

### `step` and `time`

`step` is always written, and it is written **last**: a writer lands every other
array of a commit before extending `step`, so `nstep` is the number of frames
that are fully on disk. A reader therefore takes `nstep` from `step`, and a crash
between two writes of one commit costs the uncommitted frames and nothing else.

`time` exists only when the run supplied times. It is all-or-nothing: a sequence
that starts without times cannot gain them later, and vice versa.

### Per-step metadata

Frame metadata that varies per step lands as one typed array per key under
`trajectory/meta/`, of shape `[nstep]` for a scalar or `[nstep][3|6|9]` for a
fixed vector. Each array carries the attribute `molrs_meta_dtype`, whose value is
the exact dtype tag of the values it holds (`f64`, `i32`, `u64x3`, `f64x6`,
`bool3`, `string`, `json`, …). The array's own dtype and this tag are what make
the value exact; there is no string round trip.

A meta key is declared once, when the sequence is created. A frame that **omits a
declared key** is an error unless that key was declared with an explicit fill
value. **There is no implicit `NaN`** — a gap a producer did not declare is
refused rather than invented.

The fill is a **writer-side declaration**. Its value is materialized into the
array at the omitting step, and **no attribute records that choice**:
`molrs_meta_dtype` is the only attribute a meta array carries. A reader therefore
**cannot** distinguish a filled value from one the producer supplied, and does
not need to — at that step, both are simply the value. The declaration itself
does not survive the round trip: a conforming reader hands back the values and no
fill, and a conformance suite must not require one back.

### The cell

`box/` is one section, updated whenever the cell changes. Update `j` holds the
cell matrix (`vectors[j]`, lattice vectors as columns), its origin (`origin[j]`)
and its per-axis periodic flags (`boundary[j]`), at frame ordinal
`step_index[j]`. A fixed-cell run therefore writes exactly one update.

The group **MAY** carry the boolean attribute `cell_defined`. Absent means
`true`: every store predating the attribute holds a defined cell, so a writer
emits it only to record `false` (see [Conventions](conventions.md#box)).

### Block sections

Each block of the frames is one group under `trajectory/`, holding the rows that
block contributed across the whole run, in Compressed Sparse Row (CSR) form:

- `step_index[j]` — the frame ordinal at which update `j` was landed.
- `offset` — the row pointer, one entry longer than `step_index`, with
  `offset[0] == 0`. Update `j` owns rows `offset[j] .. offset[j+1]` of every
  column. Row **counts** are never stored; they are `diff(offset)`, so the two
  cannot disagree.
- `<column>` — the block's columns, each of shape `[total_rows][...trailing]`,
  where `total_rows == offset[n_updates]` and the trailing axes are the
  per-entity structure of [Types](types.md#column-shape).

A block that declares a [structural shape](types.md#block-structural-shape)
mirrors it onto its group as the attribute `structural_shape`.

The set of blocks, columns, dtypes and trailing shapes is **declared when the
sequence is created** and fixed for its lifetime; a later frame may present a
subset of it, never anything outside it. A run that decides halfway through to
record a new column needs a new store. The reference writer pins that declaration
as the `trajectory/` group attribute `molrs_sequence_schema` and requires it when
reopening a sequence.

## Resolving a frame

To read block `B` at frame ordinal `i`, binary-search `B/step_index` for the
largest entry `<= i`. That entry is update `j`, and the frame's rows are
`offset[j] .. offset[j+1]` of each column. **No entry `<= i` means the block does
not exist at that frame** — absence, not an empty block.

The cell resolves the same way on `box/step_index`, minus the row range: the
frame's cell is update `j` itself.

Resolution therefore costs a binary search over a section's **changes**, not over
the run length.

## Reserved names

Two small namespaces are owned by the layout:

| Namespace | Reserved names | Owner |
|-----------|----------------|-------|
| Children of `trajectory/` | `step`, `time`, `meta`, `box` | the sequence itself |
| Children of a block group | `offset`, `step_index` | that block's index |

A block named `step` / `time` / `meta` / `box`, or a column named `offset` /
`step_index`, is rejected when the sequence is declared — not at the first write.

## Sparsity is block-level

A frame may omit a whole block; that is how the layout expresses a heterogeneous
run. It may **not** omit one column of a block it presents: all columns of a
block share one CSR row range, so a missing column has no representation and is
an error naming it.

Absence is encoded as a **zero-row update**: a block that was present and then
goes away gets an update of zero rows at the ordinal it disappears, and any
zero-row update reads back as absent. The consequence is worth stating rather
than discovering — **a block that is genuinely present with zero rows is
indistinguishable from an absent one.**

`box/` has no `offset` and therefore no absence marker: once a run writes a cell,
every later frame resolves to the most recent one. A frame that drops its cell
mid-run reads back carrying the previous cell.

## Cost tracks change

Because every section carries its own index, the cost of a section follows how
often it **changes**, not how long the run is:

| Section | Entries in its `step_index` |
|---------|-----------------------------|
| Constant topology (`bonds` that never changes) | 1 |
| Reactive / grand-canonical topology | one per change |
| Coordinates (`atoms`, changing every step) | `nstep` |
| Fixed cell (`box/` under NVT) | 1 |

A section earns a new update only when its content differs from its previous
update. The reference writer compares bitwise, so a repeated `NaN` counts as
unchanged and does not force an entry.

This is what makes hand-splitting an unchanging topology into `system/` optional,
and it is what lets a topology that changes *sometimes* be expressed at all.

## Scope

Evolving frame-like state belongs in `trajectory`. Reduced scientific statistics
(spectra, free-energy surfaces) belong in [observables](observables.md); run-local
monitoring belongs in [metrics](metrics.md).
