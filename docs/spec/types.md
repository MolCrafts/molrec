# Types

## Purpose

MolRec's type system is deliberately small. A column has a scalar **dtype** and a
**shape**; a block has an optional **structural shape**. That is the whole type
model. Domain semantics — what a column means, its unit, its axes — are
conventions and observable metadata, not part of the type.

## Column dtypes

A column's element type is one of the names below. Each numeric name is one
width. There is no dtype called `float`, `int`, or `uint`: those words name
families, and a family has no single width.

| dtype | Width | Zarr V3 type |
|-------|-------|----------------|
| `f16` | 16-bit float | `float16` |
| `f32` | 32-bit float | `float32` |
| `f64` | 64-bit float | `float64` |
| `i8` | signed 8-bit | `int8` |
| `i16` | signed 16-bit | `int16` |
| `i32` | signed 32-bit | `int32` |
| `i64` | signed 64-bit | `int64` |
| `u8` | unsigned 8-bit | `uint8` |
| `u16` | unsigned 16-bit | `uint16` |
| `u32` | unsigned 32-bit | `uint32` |
| `u64` | unsigned 64-bit | `uint64` |
| `bool` | 8-bit boolean | `bool` |
| `string` | UTF-8, variable width | `string` |
| `c64` | complex pair of `f32` | `complex64` |
| `c128` | complex pair of `f64` | `complex128` |

The set is closed. On disk the Zarr data type is the width. A reader that
sees `f32` and returns `f64`, or `i64` and returns `i32`, has lost the
column. Preserve a width the host cannot compute on; do not narrow it and do
not widen it.

An implementation may spell `f64` / `i32` / `u64` as `float` / `int` / `uint`
in its own API. Those three spellings are these three dtypes. They are not
extra dtypes, and they are not written as a second name beside the Zarr type.

## Column shape

A column is an N-dimensional array. Its leading axis length equals the owning
block's count; trailing axes describe per-entity structure:

- `Float[count]` — one scalar per entity (a charge);
- `Float[count][3]` — one 3-vector per entity (a packed position);
- `UInt[count][2]` — one pair per entity (a bond's endpoints).

## Block structural shape

A block may declare a structural shape whose product equals its count. This lets
one container describe both flat tables and N-D objects:

- a plain table has implicit shape `[count]`;
- a volumetric block has shape `[nx, ny, nz]`, with `nx * ny * nz == count`.

The shape only tells a consumer how to unflatten the leading axis; the storage is
the same row-major column.

## Missing values

A column is dense. A missing entry is a **validity mask**, not a sentinel in
the value array and not a dtype of its own.

When any row is missing, the column carries a `bool` mask of length `count`.
`true` means the value is present. `false` means the stored value is filler
and readers must not interpret it. No mask means every row is present.

In the Zarr binding the mask is `bool[count]` at
`<block>/_validity/<column>`. A block whose columns are all present writes
no `_validity` group. `_validity` is a reserved column name.

## Semantic metadata is not a type

MolRec does not encode unit, description, or axis meaning in the dtype. Those are
conventions (see [Conventions](conventions.md)) or, for derived quantities,
observable metadata (see [Observables](observables.md)).

## Normative invariants

1. A column dtype is one of `f16`, `f32`, `f64`, `i8`, `i16`, `i32`, `i64`, `u8`, `u16`, `u32`, `u64`, `bool`, `string`, `c64`, `c128`.
2. A column's leading axis length equals its block's count.
3. A block's structural shape, when present, has product equal to its count.
4. Type does not carry domain meaning; that is supplied by conventions.
5. A validity mask, when present, has one boolean per row. Absent mask means every row is present.
