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
    +-- vectors: f64[ndim][ndim]       # columns are lattice vectors
    +-- origin: f64[ndim]              # absent in input means the zero vector
    \-- boundary: bool[ndim]           # absent in input means periodic on every axis
```

## Column

A column is a typed N-dimensional array. Its dtype is one of the closed set in
[Types](types.md). Its leading axis length is
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
- a `density` block: structural shape `[nx, ny, nz]`; one column per field.

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
+-- vectors: f64[ndim][ndim]       # cell vectors; columns are lattice vectors
+-- origin: f64[ndim]              # cell origin
\-- boundary: bool[ndim]           # per-axis periodic boundary flags
```

`vectors` is required and square. An omitted `origin` is the zero vector of
length `ndim`. An omitted `boundary` is periodic on every axis (`true` for
each). Writers materialize both, so a round trip does not have to guess.

The cell applies to the whole frame. For a trajectory, each frame carries its own
box, so fixed-cell and variable-cell runs are both natural. The reference
binding stores a 3×3 cell. The model itself is `ndim`. LAMMPS data uses one
orientation of this matrix ([Engines](engines.md#lammps-data)).

## Volumetric data

MolRec has no dedicated grid type. Volumetric data is an ordinary block with
a structural shape, a flat column of length `count`, and a `sample` of
`corner` or `center`. See [Conventions](conventions.md#volumetric-data).

## Interpretation

Read `frame` as: a general set of named blocks describing the canonical snapshot,
with a shared optional cell and free-form metadata. Meaning comes from
conventions, not from privileged fields.
