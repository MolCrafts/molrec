# Containers

Three containers, plus an optional box, carry every record's array data. The
model has no special fields: coordinates, bonds, charge density, and energy
are ordinary blocks and columns under conventional names. Domain meaning is
supplied by [Conventions](conventions.md).

## Data types

A column's element type is exactly one member of this closed set:

| dtype | Meaning |
|-------|---------|
| `f64` | IEEE 754 binary64 — the one real-valued dtype |
| `i8`, `i16`, `i32`, `i64` | signed integer, 8–64 bit |
| `u8`, `u16`, `u32`, `u64` | unsigned integer, 8–64 bit |
| `bool` | boolean |
| `string` | UTF-8 string |
| `c64`, `c128` | complex: an interleaved (real, imaginary) pair of binary32 / binary64 |

Thirteen dtypes, and every integer width is explicit: there is no
width-abstract `float` / `int` / `uint`. A tool that cannot represent a dtype
natively must preserve it rather than silently change it: a `u64` identifier
column must not be read back as `i64`, nor an `i32` as `i64`.

**Floats are `f64` only.** `f16` and `f32` are not column dtypes: a writer
does not emit them, and a reader **MUST** refuse an array stored as binary16
or binary32 rather than widen it — widening would hide that a producer
stored less precision than the record claims.

Type does not carry unit, description, or axis meaning.

`json` is **not** a column dtype. It exists only as a per-step `meta` tag on
a [trajectory](ragged.md#per-step-metadata), where one UTF-8 JSON document
per step is stored as a `string` array. Structured facts on a frame go in
the frame's `meta` document, not in a column.

## Column, block and frame

A *column* is a typed N-dimensional array. Its leading axis length equals the
owning block's count; trailing axes describe per-entity structure. For
instance, `f64[N]` is one scalar per entity, `f64[N][3]` is one 3-vector per
entity.

A *block* is a set of named columns that share one leading length, the
block's *count*. Every column in a block must have the same axis-0 length. A
block may declare a *structural shape* whose product equals its count. This
lets one container describe both a flat table (implicit shape `[N]`) and an
N-D object (a volumetric grid `[nx][ny][nz]` with `nx·ny·nz == N`). When no
shape is set, the block is a plain table of `N` rows.

A *frame* is a snapshot: a set of named blocks, a free-form `meta` mapping,
and an optional box. A frame enforces no relationship between its blocks —
counts are independent, and any block name is legal except `box`, which
names the cell. On the reference binding the frame is a
[frame-shaped group](storage.md#frame-shaped-group): the `meta` mapping is
the group's attributes, not a child, so `meta` is an ordinary block name.

```text
frame
 +-- <meta key>                          the meta document: the group's attributes
 \-- <block>
 |    +-- count: i64[]
 |    +-- (structural_shape: i64[k])
 |    \-- <column>: <dtype>[N][...]
 |    \-- (_validity)
 \-- <block>
 |    \-- ...
 \-- (box)
```

A `frame` section of a record is this container. A `trajectory` section
sequences the same container over time.

## Nullable columns

A column may be **nullable**: beside its values it carries a *validity
mask*, one `bool` per row, `true` where the row holds a value and `false`
where it holds none. The value stored under a null row is carried as written
and means nothing; a reader must not interpret it.

```text
<block>
 \-- <column>: <dtype>[N][...]
 \-- (_validity)
      \-- (<column>: bool[N])
```

- The mask of column `c` of block `B` is the array `B/_validity/c`: exactly
  one flag per row of the block (shape `[N]`, no trailing axes — a mask
  marks a *row* null, whatever shape the row has), stored as `bool`.
- An absent `_validity` subgroup, or an absent mask array in it, means every
  row of that column is valid. An all-`true` mask means the same thing, and
  the two spellings are one value: a writer **MAY** omit an all-`true` mask,
  and a reader hands back "no mask" for either.
- `_validity` is a **reserved** block-child name: a column named
  `_validity` is refused at write. A reader skips the subgroup when it lists
  a block's columns (it is a group, and columns are arrays).
- A reader **MUST** refuse a mask that is not `bool`, that does not carry
  exactly one flag per row, or that names no column of its block.
- A block no column of which is masked writes no subgroup, so its bytes are
  those of a writer that predates masks.

On a [trajectory](ragged.md#nullable-columns) the mask rides the block's CSR
rows the way its values do.

MolRec has no dedicated grid type. Volumetric data is an ordinary block whose
structural shape is `[nx][ny][nz]` and whose columns are the scalar fields.
The spatial cell is the frame's box; a volumetric block carries no cell of
its own.

All arrays are stored in C-order (row-major). A column's leading axis is the
block count; trailing axes are per-entity structure and are never split
across chunks in the reference binding.

## Declared precision

An `f64` column may declare a **precision** `p`: an absolute tolerance in the
column's own units (`1e-3` on coordinates in Å keeps them to a thousandth of
an ångström). It is the writer's statement about the values it stored, not a
codec and not a dtype: the column is `f64`, a reader decodes it knowing
nothing of `p`, and the values it returns are exactly the stored ones.

From `p` a writer derives the **quantum** `q`, the largest power of two not
above `p`: with `p = m · 2^e` and `0.5 ≤ m < 1`,

```text
q = 2^(e − 1)
```

and stores, for each value `x`,

```text
stored(x) = x                              when x is NaN or ±∞, or |x| ≥ 2^52 · q
stored(x) = roundTiesToEven(x / q) · q     otherwise
```

in binary64. Both operations are exact (`q` is a power of two), so two
writers store the same bits; a writer **MUST** store exactly `stored(x)`.
Every finite stored value is an integer multiple of `q`, and
`|x − stored(x)| ≤ q/2 ≤ p/2`. A null row (its validity flag false) is
unconstrained.

The grid is binary on purpose: a multiple of `2^−10` has zero low-order
mantissa bits, which a byte shuffle gathers into runs a lossless compressor
removes ([Chunking](chunking.md)); a multiple of `10^−3` has a full mantissa
and compresses no better than raw data.

- `p` is a finite binary64 with `2^−1000 ≤ p ≤ 2^1000`. Only an `f64`
  column declares one; a writer refuses any other.
- On a frame-shaped section `p` is the column array's attribute
  `precision`. On a trajectory it is the column's entry in the pinned
  [`sequence_schema`](ragged.md#the-pinned-declaration) and nowhere else.
- Absent means the values are stored as given.
- A reader preserves the declaration: a record read and written back
  declares the same `p`.
- A reader does not re-round, re-check or refuse. A stored value off the grid
  is the writer's defect; a validator **SHOULD** report it.

## Simulation box

The specification of the simulation cell is stored in the group `box`.
Writers emit `box`. The reference implementation (molrs) exposes this cell
as `Box` in its Python binding; the Rust core type is `SimBox`.

`box` is an optional triclinic cell carried by the frame. A box may be
absent (an open, non-periodic system).

```text
box
 +-- (cell_defined: bool[])
 \-- vectors: f64[3][3]
 \-- (origin: f64[3])
 \-- (boundary: bool[3])
```

`vectors`

A `3` × `3` matrix of `f64` type. Columns are lattice vectors.

`origin`

An optional `f64[3]` array. Absent means `[0, 0, 0]` — the cell is anchored
at the coordinate origin.

`boundary`

An optional `bool[3]` **array** — on the frame path and, one update per row,
on the [trajectory path](ragged.md#the-cell) alike; it is never an
attribute. Absent means `[true, true, true]` — periodic on every axis.

`cell_defined`

An optional boolean **attribute** of the `box` group. `boundary` says which
axes wrap; `cell_defined` says whether there is a cell at all. Absent means
`true`. A writer emits it only when it is `false`.

**An undefined cell.** A box with `cell_defined: false` records that the
system has an origin but no cell — a molecule in vacuum that still carries a
reference point. Its parts follow from that:

- `vectors` mean nothing. A writer **MUST** write the identity matrix; a
  reader **MUST** ignore whatever `vectors` it finds (zeros included — it
  never inverts them) and hands back the identity.
- `origin` keeps its ordinary meaning and default.
- It is periodic on **no** axis. A writer **MUST** write `boundary` as the
  all-`false` array — explicitly, because the omitted default is
  all-periodic — and a reader treats an undefined cell as non-periodic: an
  omitted `boundary` on an undefined cell reads as all-`false`, and a
  `boundary` with a `true` flag on one is malformed and **SHOULD** be
  refused.

On a trajectory, `cell_defined` is the `box/` section's one attribute and
covers every update; an update carries no flag of its own
([Ragged trajectory](ragged.md#the-cell)).

The cell applies to the whole frame. For a trajectory, each frame carries
its own box, so fixed-cell and variable-cell runs are both natural.

Absence of optional parts has a fixed meaning: two readers that default them
differently turn one store into two different physical systems, so the
defaults above are normative.
