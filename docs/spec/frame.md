# Frame

## Purpose

`frame` is the canonical snapshot. It is a fully general container: a map of names
to blocks, plus free-form metadata and an optional box. No block name is
privileged.

## Structure

```text
frame
+-- <block>
|   \-- <column>: <dtype>[count][...]
+-- <block>
|   \-- ...
+-- meta                         # free-form key -> value
\-- (box)
    +-- vectors: Float[ndim][ndim]     # columns are lattice vectors
    +-- (origin: Float[ndim])
    \-- (boundary: Bool[ndim])
```

## Column

A column is a typed N-dimensional array. Its dtype is one of `float`, `int`,
`uint`, `u8`, `bool`, `string` (see [Types](types.md)). Its leading axis length is
the owning block's count; trailing axes describe per-entity structure.

## Block

A block is a set of named columns sharing a common count:

- every column has the same axis-0 length (the count);
- a block may carry an optional structural shape whose product equals the count,
  letting it describe an N-D object with the same container as a flat table;
- a block imposes no meaning on its column names — that is a convention.

Examples (conventional, not required — see [Conventions](conventions.md)):

- an `atoms` block: `count` = number of atoms; columns `x`/`y`/`z`, `element`, ...
- a `bonds` block: `count` = number of bonds; columns `atomi`/`atomj`, `order`;
- a `density` block: structural shape `[nx, ny, nz]`; one float column per field.

## Frame

A frame maps names to blocks. It enforces no relationship between blocks: block
counts are independent, and any block name is legal. Free-form metadata lives in
`frame/meta` as key -> value pairs.

Which blocks exist and what their columns mean is supplied by
[Conventions](conventions.md), not by the frame.

## Box

The contract name for the simulation cell is **`Box` / `box` only**. Names such
as `simbox` / `SimBox` are **not** part of the MolRec contract. Writers MUST emit
`box`. The reference implementation (molrs) must expose **`Box`** as the public
type name for this cell.

`box` is an optional triclinic simulation cell carried by the frame:

```text
frame/box
+-- vectors: Float[ndim][ndim]     # cell vectors; columns are lattice vectors
+-- (origin: Float[ndim])          # cell origin
\-- (boundary: Bool[ndim])         # per-axis periodic boundary flags
```

The cell applies to the whole frame. For a trajectory, each frame carries its own
box, so fixed-cell and variable-cell runs are both natural.

## Volumetric data

MolRec has no dedicated grid type. Volumetric data is an ordinary block whose
structural shape is `[nx, ny, nz]` and whose columns are the scalar fields (each
of shape `[nx][ny][nz]`). The spatial cell is the frame's box — a volumetric
block carries no cell of its own.

## Interpretation

Read `frame` as: a general set of named blocks describing the canonical snapshot,
with a shared optional cell and free-form metadata. Meaning comes from
conventions, not from privileged fields.
