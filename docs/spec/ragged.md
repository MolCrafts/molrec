# Ragged trajectory

This chapter is the on-disk encoding of a
[trajectory](trajectory.md) section on the [Zarr V3](zarr.md) binding.
The logical model stays a sequence of frames; the layout below is how
that sequence is stored so a writer appends and a reader resolves a
frame without rewriting history. Groups sit on the
[root](storage.md); chunk and shard extents are
[Chunking and packing](chunking.md).

The layout is **append-first** (a new frame extends arrays) and **sparse**
(a block records an update only when it changes). A ragged run — a block
whose row count differs per frame — is the same layout: non-uniform
`diff(offset)`.

## One group per section

Dense per-step data (`step`, `time`, `meta/<key>`) has one row per frame;
the cell and each block carry their own sparse index of the ordinals at
which they changed. File count and open cost follow the number of sections,
and `nstep` stays off that axis.

There is one encoder and one decoder. `molrec_version` stays **1**.

## Layout

```text
trajectory
 \-- step: i64[nstep]
 \-- (time: f64[nstep])
 \-- (meta)
 |    \-- <key>: <dtype>[nstep]
 |         +-- molrs_meta_dtype
 \-- (box)
 |    +-- (cell_defined: bool[])
 |    \-- (step_index: u64[n_updates])
 |    \-- vectors: f64[n_updates][3][3]
 |    \-- (origin: f64[n_updates][3])
 |    \-- (boundary: bool[n_updates][3])
 \-- <block>
      +-- (structural_shape)
      \-- step_index: u64[n_updates]
      \-- offset: u64[n_updates+1]
      \-- <column>: <dtype>[total_rows][...]
```

Chunking, sharding, compression, and the `*.mrec/` / `*.mrec.zip` forms:
[Chunking and packing](chunking.md).

### `step` and `time`

`step` is always written, and it is written **last**: a writer lands every
other array of a commit before extending `step`, so `nstep` is the number of
frames that are fully on disk. A reader therefore takes `nstep` from `step`,
and a crash between two writes of one commit costs the uncommitted frames
and nothing else.

`time` exists only when the run supplied times. It is all-or-nothing: a
sequence that starts without times cannot gain them later, and vice versa.

`step` holds the producer's iteration counter (strictly increasing). Every
`step_index` below holds **frame ordinals** `0 .. nstep-1`, not those
counters. See [Trajectory](trajectory.md).

### Per-step metadata

Frame metadata that varies per step lands as one typed array per key under
`trajectory/meta/`, of shape `[nstep]` for a scalar or `[nstep][3|6|9]` for a
fixed vector. Each array carries the attribute `molrs_meta_dtype`, whose
value is the exact dtype tag of the values it holds (`f64`, `i32`, `u64x3`,
`f64x6`, `bool3`, `string`, `json`, …).

A meta key is declared once, when the sequence is created. A frame that
**omits a declared key** is an error unless that key was declared with an
explicit fill value. **There is no implicit `NaN`**. The fill is a
writer-side declaration: its value is materialized into the array at the
omitting step, and **no attribute records that choice**. A reader cannot
distinguish a filled value from one the producer supplied, and does not
need to.

### The cell

`box/` is one section, updated whenever the cell changes. Update `j` holds
the cell matrix (`vectors[j]`, lattice vectors as columns), its origin
(`origin[j]`) and its per-axis periodic flags (`boundary[j]`), at frame
ordinal `step_index[j]`. A fixed-cell run therefore writes exactly one
update. As on a [frame](frame.md#simulation-box), `origin` and `boundary`
are optional with the normative defaults (zero origin, all-periodic); the
reference writer omits each array when every update holds the default. A
trivial `box/step_index` — exactly one update at frame ordinal `0`, the
fixed-cell case — may also be omitted; absence reads back as `[0]`.

The group **MAY** carry the boolean attribute `cell_defined`. Absent means
`true`. A writer emits it only to record `false` (see
[Simulation box](frame.md#simulation-box)).

`box/` has no `offset` and therefore no absence marker: once a run writes a
cell, every later frame resolves to the most recent one. A frame that drops
its cell mid-run reads back carrying the previous cell.

### Per-block sparse updates (CSR)

Each block of the frames is one group under `trajectory/`, holding the rows
that block contributed across the whole run, in Compressed Sparse Row form:

| Element | Type | Meaning |
|---------|------|---------|
| `B/step_index` | `u64[n_updates]` | ascending frame ordinals at which `B` changed |
| `B/offset` | `u64[n_updates + 1]` | CSR prefix sum of row counts: `offset[0] == 0`; update `j` owns rows `offset[j] … offset[j+1]` of every column |
| `B/<column>` | `dtype[total_rows][…trailing]` | columns appended update after update; `total_rows == offset[n_updates]` |

Row **counts** are never stored; they are `diff(offset)`, so the two cannot
disagree. A conforming reader **MUST** compute the row count as
`offset[j+1] − offset[j]` with checked subtraction and **MUST** reject a
non-monotonic `offset`.

Because updates are recorded only when a block changes:

- a block with fixed topology across a run costs **one** `step_index` entry;
- a ragged run (row count differs per frame) is expressed directly by
  non-uniform `diff(offset)`.

A block that declares a [structural shape](frame.md#column-block-and-frame) mirrors it onto
its group as the attribute `structural_shape`.

## Raggedness

“Ragged” means the number of rows in a block is not constant across frames.
Growth, grand-canonical insertion, reactive topology, and variable-size
selection sets are all the same encoding: each update owns a (possibly
different) slice of the concatenated columns.

An update of **zero rows** (`offset[j+1] == offset[j]`) records that the
block is **present and empty** from that frame onward, while earlier updates
stay on disk. That is a different claim from absence: a block with no
`step_index` entry `≤ i` does not exist at frame `i` at all (see
[Resolving a frame](#resolving-a-frame)), and the conformance suite
distinguishes the two.

A frame may omit a whole block. Every column of a block it presents is
present: all columns of a block share one CSR row range.

## The pinned declaration

The set of blocks, columns, dtypes, and trailing shapes a trajectory may
carry is **declared when the trajectory is created and fixed for its
lifetime**. A later frame **MAY** present a subset of the declaration, but
**MUST NOT** present a block, column, or `meta` key outside it. A run that
must record a new section that was not declared needs a new trajectory.

To record a section that appears only partway through a run (per-frame bonds
in a growth run), a writer declares it up front — for instance by including
a representative frame carrying an even-empty block when deriving the
declaration.

The reference writer pins that declaration as the `trajectory/` group
attribute `molrs_sequence_schema`, published as
[`schema/binding/sequence-schema.schema.json`](../../schema/binding/sequence-schema.schema.json):
a `blocks` map (each block a `columns` map of `{dtype, trailing}`) and a
`meta` map of per-step dtype tags. Column `dtype`s are the closed record
dtype enum. The attribute carries **no version of its own**;
`meta["molrec_version"]` versions it.

The literal key `molrs_sequence_schema` is the reference writer's and is
not renamed here.

## Resolving a frame

To read block `B` at frame ordinal `i`:

1. binary-search `B/step_index` for the largest entry `≤ i`; call it update
   `j`;
2. **no entry `≤ i` means `B` does not exist at frame `i`** — absence, not
   an empty block;
3. otherwise the frame's rows are `offset[j] … offset[j+1]` of each column
   of `B`.

The box resolves the same way over `box/step_index`, minus the row range:
the frame's cell is update `j` itself.

Resolution therefore costs a binary search over a section's **changes**, not
over the run length.

## Reserved names

Two small namespaces are owned by the layout:

| Namespace | Reserved names | Owner |
|-----------|----------------|-------|
| Children of `trajectory/` | `step`, `time`, `meta`, `box` | the sequence itself |
| Children of a block group | `offset`, `step_index` | that block's index |

A block named `step` / `time` / `meta` / `box`, or a column named `offset` /
`step_index`, is rejected when the sequence is declared — not at the first
write.

## Cost tracks change

Because every section carries its own index, the cost of a section follows
how often it **changes**, not how long the run is:

| Section | Entries in its `step_index` |
|---------|-----------------------------|
| Constant topology (`bonds` that never changes) | 1 |
| Reactive / grand-canonical topology | one per change |
| Coordinates (`atoms`, changing every step) | `nstep` |
| Fixed cell (`box/` under NVT) | 1 |

A section earns a new update only when its content differs from its previous
update. The reference writer compares bitwise, so a repeated `NaN` counts as
unchanged and does not force an entry.

This is what makes hand-splitting an unchanging topology into `system/`
optional, and it is what lets a topology that changes *sometimes* be
expressed at all.

## Worked example: a growth trajectory

A growth trajectory (`growth.mrec/`) whose `atoms` block gains rows over 19
frames, with only positions, an element string, and a molecule id. The cell
is constant.

```text
growth.mrec
 \-- meta
 |    +-- molrec_version: 1
 \-- trajectory
      +-- molrs_sequence_schema
      \-- step: i64[19]
      \-- atoms
      |    \-- step_index: u64[19]
      |    \-- offset: u64[20]
      |    \-- element: string[N]
      |    \-- mol_id: u64[N]
      |    \-- x: f64[N]
      |    \-- y: f64[N]
      |    \-- z: f64[N]
      \-- box
           \-- step_index: u64[1]
           \-- vectors: f64[1][3][3]
```

Suppose the first three frames have 2, 2, and 5 atoms. Then:

```text
offset      = [0, 2, 4, 9, ...]
step_index  = [0, 1, 2, ...]
```

Frame `0` owns rows `0:2`, frame `1` owns `2:4` (still 2 atoms — the count
did not grow, but positions changed, so there is still an update), frame `2`
owns `4:9`. If bonds were constant they would have `step_index = [0]` and a
single row range covering the whole run; they are simply omitted here
because this writer did not declare them.

The pinned `trajectory` attribute:

```json
{
  "molrs_sequence_schema": {
    "blocks": {
      "atoms": {
        "columns": {
          "element": { "dtype": "string", "trailing": [] },
          "mol_id":  { "dtype": "u64",    "trailing": [] },
          "x":       { "dtype": "f64",    "trailing": [] },
          "y":       { "dtype": "f64",    "trailing": [] },
          "z":       { "dtype": "f64",    "trailing": [] }
        }
      }
    },
    "meta": {}
  }
}
```

Frame `i` is read by resolving each block through the algorithm above:
`atoms` at frame `i` owns rows `offset[i] … offset[i+1]` (here
`step_index[i] == i` because atoms change every frame); the box is its
single update.
