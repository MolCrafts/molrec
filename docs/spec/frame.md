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
counts are independent, and any block name is legal.

```text
frame
 \-- <block>
 |    \-- <column>: <dtype>[N][...]
 \-- <block>
 |    \-- ...
 \-- (meta)
 \-- (box)
```

A `frame` section of a record is this container. A `trajectory` section
sequences the same container over time.

MolRec has no dedicated grid type. Volumetric data is an ordinary block whose
structural shape is `[nx][ny][nz]` and whose columns are the scalar fields.
The spatial cell is the frame's box; a volumetric block carries no cell of
its own.

All arrays are stored in C-order (row-major). A column's leading axis is the
block count; trailing axes are per-entity structure and are never split
across chunks in the reference binding.

## Simulation box

The specification of the simulation cell is stored in the group `box`.
Writers emit `box`. The reference implementation (molrs) exposes this cell
as `Box` in its Python binding; the Rust core type is `SimBox`.

`box` is an optional triclinic cell carried by the frame. A box may be
absent (an open, non-periodic system).

```text
box
 \-- vectors: f64[3][3]
 \-- (origin: f64[3])
 \-- (boundary: bool[3])
 +-- (cell_defined: bool[])
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

The cell applies to the whole frame. For a trajectory, each frame carries
its own box, so fixed-cell and variable-cell runs are both natural.

Absence of optional parts has a fixed meaning: two readers that default them
differently turn one store into two different physical systems, so the
defaults above are normative.
