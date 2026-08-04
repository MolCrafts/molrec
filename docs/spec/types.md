# Types

## Purpose

MolRec's type system is deliberately small. A column has a scalar **dtype** and a
**shape**; a block has an optional **structural shape**. That is the whole type
model. Domain semantics — what a column means, its unit, its axes — are
conventions and observable metadata, not part of the type.

## Column dtypes

A column's element type is one of:

| dtype | Meaning |
|-------|---------|
| `float` | 64-bit floating point |
| `int` | signed integer |
| `uint` | unsigned integer |
| `u8` | 8-bit unsigned integer |
| `bool` | boolean |
| `string` | UTF-8 string |

The set is closed. A tool that cannot represent a dtype natively should preserve
it rather than silently narrow it (for example, `uint` endpoints must not be read
back as signed `int`).

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

## Semantic metadata is not a type

MolRec does not encode unit, description, or axis meaning in the dtype. Those are
conventions (see [Conventions](conventions.md)) or, for derived quantities,
observable metadata (see [Observables](observables.md)).

## Normative invariants

1. A column dtype is one of `float`, `int`, `uint`, `u8`, `bool`, `string`.
2. A column's leading axis length equals its block's count.
3. A block's structural shape, when present, has product equal to its count.
4. Type does not carry domain meaning; that is supplied by conventions.
