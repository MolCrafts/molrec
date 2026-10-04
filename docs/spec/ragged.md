# Ragged trajectory

This chapter is the on-disk encoding of a
[trajectory](trajectory.md) section on the [Zarr V3](zarr.md) binding.
The logical model stays a sequence of frames; the layout below is how
that sequence is stored so a writer appends and a reader resolves a
frame without rewriting history. Groups sit on the
[root](storage.md); chunk and shard extents, codecs and the commit
protocol are [Chunking and packing](chunking.md).

The layout is **append-first** (a new frame extends arrays) and **sparse**
(a block records an update only when it changes). A ragged run — a block
whose row count differs per frame — is the same layout: non-uniform
`diff(offset)`.

## One group per section

Dense per-step data (`step`, `time`, `meta/<key>`) has one row per frame;
the cell and each block carry their own sparse index of the ordinals at
which they changed. File count and open cost follow the number of sections,
and `nstep` stays off that axis.

There is one encoder and one decoder.

## Layout

```text
trajectory
 +-- sequence_schema
 +-- nstep                          the commit marker
 +-- (step_progression: {start, stride})
 +-- (time_progression: {start, stride})
 \-- (step: i64[nstep])             only when the numbering is not a progression
 \-- (time: f64[nstep])             only when supplied, and not a progression
 \-- (meta)
 |    \-- <key>: <dtype>[nstep][...]
 |         +-- meta_dtype
 \-- (box)
 |    +-- (cell_defined: bool[])
 |    +-- (vectors, origin, boundary)   a fixed cell from ordinal 0, as attributes
 |    \-- (step_index: u64[n_updates])   the arrays, once the cell changes
 |    \-- (vectors: f64[n_updates][3][3])
 |    \-- (origin: f64[n_updates][3])
 |    \-- (boundary: bool[n_updates][3])
 \-- <block>
      +-- (structural_shape)
      +-- (uniform_rows)
      +-- (dense_updates)
      \-- (step_index: u64[n_updates])   absent while the block is regular
      \-- (offset: u64[n_updates+1])     absent while the block is regular
      \-- <column>: <dtype>[total_rows][...]
```

Every array under `trajectory/` is sharded; extents and codecs are
[Chunking and packing](chunking.md). The layout is built so that the common
run — a fixed number of atoms moving every frame, a topology written once, a
fixed cell, frames dumped every `k` steps — costs **one array per column and
nothing else**: no index arrays, no `step` array, no `box/` arrays.

### The commit marker: `nstep`

The trajectory group's attribute `nstep` is the number of frames fully on
disk. It is written **last**: a writer lands every array of a commit before
replacing the group metadata (atomically), so a crash between two writes of
one commit costs the uncommitted frames and nothing else. A reader takes
`nstep` from that attribute; every array is read to its logical length and
**MAY** be longer (a tail the writer had not yet committed) but **MUST NOT**
be shorter. A store from a writer that kept no marker attribute is read to
`len(step)`. The full protocol is
[Chunking and packing](chunking.md#normative).

### `step` and `time`

While the step numbers are an arithmetic progression — the dump every `k`
steps that every MD run produces — they are recorded as the attribute
`step_progression: {"start": s, "stride": k}` (`stride` appears from the
second frame on) and **no `step` array exists**. The first frame whose step
number breaks the progression materializes the `step` array, backfilled with
the whole history, and the attribute is removed. `time` follows the same
rule with `time_progression`, compared exactly (a time that is
`start + i·stride` in floating point stays regular; an accumulated one
usually does not). A reader resolves step `i` as `start + i·stride` from the
attribute, else from the array.

`time` exists only when the run supplied times. It is all-or-nothing: a
sequence that starts without times cannot gain them later, and one that
starts with them cannot drop them. A writer **MUST** refuse either.

`step` holds the producer's iteration counter (strictly increasing; a
repeated or smaller step number is refused at append). Every `step_index`
below holds **frame ordinals** `0 .. nstep-1`, not those counters. See
[Trajectory](trajectory.md).

### Per-step metadata

Frame metadata that varies per step lands as one typed array per key under
`trajectory/meta/`, of shape `[nstep]` for a scalar or `[nstep][3|6|9]` for a
fixed vector. Each array carries the attribute `meta_dtype`, whose value is
the exact tag of the values it holds.

The tag set is closed:

| Tag | Value per step |
|-----|----------------|
| one of the 15 column [dtypes](frame.md#data-types) | a scalar |
| `<t>x3`, `<t>x6`, `<t>x9` for numeric `t` (`f64x3`, `i64x6`, `u32x9`, …) | a fixed vector of `t` |
| `bool3` | three booleans |
| `json` | one UTF-8 JSON document; physically a `string` array |

`json` is a **meta** tag only: a block column never carries it. The
standard per-step scalar keys (`pe`, `ke`, `etotal`, `temp`, `press`,
`volume`, all `f64`) are [Standardized identifiers](conventions.md#per-step-scalars).

A meta key is declared once, when the sequence is created, as
`{dtype, fill?}`. A frame that **omits a declared key** is an error unless
that key was declared with an explicit fill value. **There is no implicit
`NaN`**. The fill is materialized into the array at the omitting step and
the declaration — tag and fill — is recorded in the pinned
[`sequence_schema`](#the-pinned-declaration). The array itself does not
mark which steps were filled.

### The cell

`box/` is one section, updated whenever the cell changes. Update `j` holds
the cell matrix (`vectors[j]`, lattice vectors as columns), its origin
(`origin[j]`) and its per-axis periodic flags (`boundary[j]`), at frame
ordinal `step_index[j]`. As on a [frame](frame.md#simulation-box), `origin`
and `boundary` are arrays, optional with the normative defaults (zero
origin, all-periodic); the reference writer omits each when every update
holds the default. A trivial `box/step_index` — exactly one update at frame
ordinal `0` — may also be omitted; absence reads back as `[0]`.

**A fixed cell costs no array.** A cell present from ordinal `0` that never
changes is recorded as the `box/` group's own attributes — `vectors` (a 3×3
nested list, lattice vectors as columns), and `origin` / `boundary` when off
their defaults — with no arrays at all. The first change migrates the cell
into the arrays above (update 0 is the attribute cell, backfilled) and
removes the `vectors` / `origin` / `boundary` attributes. A reader that finds
no `box/vectors` array reads the attributes: one update at ordinal `0`.

The group **MAY** carry the boolean attribute `cell_defined`. Absent means
`true`. A writer emits it only to record `false` (see
[Simulation box](frame.md#simulation-box)).

The cell carries forward like a block: once a run writes a cell, every later
frame resolves to the most recent update. A frame that drops its cell
mid-run reads back carrying the previous cell; `box/` has no absence marker.

### Per-block sparse updates (CSR)

Each block of the frames is one group under `trajectory/`, holding the rows
that block contributed across the whole run, in Compressed Sparse Row form:

| Element | Type | Meaning |
|---------|------|---------|
| `B/step_index` | `u64[n_updates]` | ascending frame ordinals at which `B` was updated |
| `B/offset` | `u64[n_updates + 1]` | CSR prefix sum of row counts: `offset[0] == 0`; update `j` owns rows `offset[j] … offset[j+1]` of every column |
| `B/<column>` | `dtype[total_rows][…trailing]` | columns appended update after update; `total_rows == offset[n_updates]` |

Row **counts** are never stored; they are `diff(offset)`, so the two cannot
disagree. A conforming reader **MUST** compute the row count as
`offset[j+1] − offset[j]` with checked subtraction and **MUST** reject a
non-monotonic `offset`.

A block that declares a [structural shape](frame.md#column-block-and-frame)
mirrors it onto its group as the attribute `structural_shape`. Such a block
has a **fixed row count**: every update holds exactly the product of the
shape, and a writer refuses an update that does not.

**A regular block costs no index.** Two attributes are maintained by the
writer on the block group:

| Attribute | Meaning while it holds |
|-----------|------------------------|
| `uniform_rows: N` | every update so far has exactly `N > 0` rows |
| `dense_updates: true` | every update so far sits at its own ordinal (`step_index[j] == j`) |

While **both** hold, `step_index` and `offset` are **not written**: update
`j` is at ordinal `j` and owns rows `j·N … (j+1)·N`, and the number of
updates is `min(len(column) / N, nstep)` for any column of the block. The
first update that breaks either rule — a different row count (a ragged run,
a zero-row update), or an update at an ordinal other than its own (a
topology that changed at frame 5) — materializes both arrays, backfilled
with the regular history, and removes the attributes for good. Once the
arrays exist they are authoritative and the attributes never return. A
constant topology (one update at ordinal `0`) and coordinates that move
every frame are both regular; only a block that *sometimes* changes, or
changes size, pays for an index.

## The three states of a block

At any frame ordinal `i`, a declared block `B` is in exactly one of three
states, decided by its most recent update at or before `i`:

| State | On disk | What the frame carries |
|-------|---------|------------------------|
| **present** | the most recent update has rows | `B` with those rows |
| **empty** | the most recent update has zero rows (`offset[j+1] == offset[j]`) | `B` with its declared columns and no rows — it *does* appear in the frame |
| **absent** | no update at or before `i` | no `B` at all |

The rules that follow from this:

- A frame that **omits** a declared block writes **no update**. The block
  carries forward: at that ordinal it is whatever the previous ordinal made
  it. Omission is never written as a zero-row update.
- A frame that presents a **zero-row** block writes a zero-row update. From
  that ordinal on the block is present and empty, until its next update.
- A block is absent only before its first update. Once present it is
  **never absent again**: there are no tombstones. To clear a block, write a
  zero-row update.
- A writer compares a presented block with its previous update **bitwise**;
  an identical presentation writes no update. A repeated `NaN` therefore
  counts as unchanged.
- A reader resolving a zero-row update hands back a block with the declared
  columns and zero rows, and that block appears in the frame.

The conformance suite distinguishes the three states.

## Raggedness

"Ragged" means the number of rows in a block is not constant across frames.
Growth, grand-canonical insertion, reactive topology, and variable-size
selection sets are all the same encoding: each update owns a (possibly
different) slice of the concatenated columns.

A frame may omit a whole block. Every column of a block it presents is
present: all columns of a block share one CSR row range.

## System and trajectory side by side

When `system/<block>` and `trajectory/<block>` coexist, the trajectory
block is the per-step state of the rows `system` defines, aligned **1:1 by
row order**: every update of `trajectory/<block>` holds exactly as many rows
as `system/<block>`. When both sides carry an `id` column the values are
equal row for row, so a reader may also join on `id`. A ragged trajectory
block **MUST NOT** share a name with a `system` block. See
[Trajectory](trajectory.md).

## The pinned declaration

The set of blocks, columns, dtypes, trailing shapes and per-step meta keys
a trajectory may carry is **declared when the trajectory is created and
fixed for its lifetime**. A later frame **MAY** present a subset of the
declaration, but **MUST NOT** present a block, column, or `meta` key outside
it. A run that must record a new section that was not declared needs a new
trajectory.

To record a section that appears only partway through a run (per-frame bonds
in a growth run), a writer declares it up front — by declaring the block
explicitly, or by including a representative frame carrying an even-empty
block when deriving the declaration.

Reserved names are refused **at declaration**, not at the first write (see
[Reserved names](#reserved-names)).

The declaration is pinned as the `trajectory/` group attribute
`sequence_schema`, published as
[`schema/binding/sequence-schema.schema.json`](../../schema/binding/sequence-schema.schema.json):

- `blocks`: a map of block name to `{columns, structural_shape?}`, each
  column `{dtype, trailing}`. Column `dtype`s are the closed record dtype
  set; `trailing` is the per-entity shape after the leading count axis.
- `meta`: a map of key to `{dtype, fill?}`, `dtype` drawn from the per-step
  tag set above.

The attribute carries **no version of its own**; the record's optional
`meta["molrec_version"]` covers it.

## Resolving a frame

To read block `B` at frame ordinal `i`:

1. binary-search `B/step_index` for the largest entry `≤ i`; call it update
   `j`;
2. **no entry `≤ i` means `B` is absent at frame `i`** — no block, not an
   empty one;
3. otherwise the frame's rows are `offset[j] … offset[j+1]` of each column
   of `B`. **A zero-row range yields an empty block**: present, with its
   declared columns and no rows.

With `dense_updates` and `uniform_rows` both set there is no index to
search: `j = min(i, n_updates − 1)` with `n_updates = min(len(column) / N,
nstep)`, and the rows are `j·N … (j+1)·N`.

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

A section earns a new update only when its content differs bitwise from its
previous update.

This is what makes hand-splitting an unchanging topology into `system/`
optional, and it is what lets a topology that changes *sometimes* be
expressed at all.

## Worked example: a growth trajectory

A growth trajectory (`growth.mrec/`) whose `atoms` block gains rows over 19
frames, with only positions, an element string, and a molecule id. The cell
is constant, and the potential energy is recorded per step.

```text
growth.mrec
 \-- meta
 \-- trajectory
      +-- sequence_schema
      \-- step: i64[19]
      \-- meta
      |    \-- pe: f64[19]
      |         +-- meta_dtype: "f64"
      \-- atoms
      |    +-- dense_updates: true
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

`meta/` is present with an empty attribute map: writers always create it and
do not write `molrec_version`.

Suppose the first three frames have 2, 2, and 5 atoms. Then:

```text
offset      = [0, 2, 4, 9, ...]
step_index  = [0, 1, 2, ...]
```

Frame `0` owns rows `0:2`, frame `1` owns `2:4` (still 2 atoms — the count
did not grow, but positions changed, so there is still an update), frame `2`
owns `4:9`. Had this writer also declared `bonds` and presented the same
bonds on every frame, they would have `step_index = [0]` and a single row
range covering the whole run; a frame that omitted them would still read
them back.

The pinned `trajectory` attribute:

```json
{
  "sequence_schema": {
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
    "meta": {
      "pe": { "dtype": "f64" }
    }
  }
}
```

Frame `i` is read by resolving each block through the algorithm above:
`atoms` at frame `i` owns rows `offset[i] … offset[i+1]` (here
`step_index[i] == i` because atoms change every frame, which is what
`dense_updates` records); the box is its single update.
