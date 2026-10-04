# System group

The `system` group answers what chemical or physical system the record is
about: the identity of the particle set, its connectivity and its typing.
Instantaneous coordinates of a time step live on `frame` or `trajectory`.

`system` is **strictly frame-shaped**: it is a
[frame-shaped group](storage.md#frame-shaped-group) — a `meta` document as
its attributes, named blocks as flat children, an optional `box` — with the
same blocks, columns and [standardized identifiers](conventions.md) a frame
uses.

```text
system                    attributes = the system's meta document
 \-- (atoms)
 \-- (bonds)
 \-- (angles)
 \-- ...
 \-- (box)
```

- Blocks are **flat** children of `system/` (`system/atoms`,
  `system/bonds`). There is no `system/topology/` level: a nested group is a
  block like any other, and a reader would take a `topology` group for a
  block named `topology`.
- The composition and identity keys of
  [Conventions](conventions.md#composition-and-identity-keys)
  (`total_charge`, `spin`, `smiles`, …) live in the meta document.
- There is no `box_policy` and no `parameters` child.

A conforming `system` may omit coordinate columns entirely; instantaneous
Cartesian coordinates belong on `frame` or `trajectory`.

Records with only `frame` (no `system`) remain valid. Records with only
`system` (no `frame`) are valid. A trajectory may omit `system`; when
`system` is present, `trajectory` should carry state updates only, aligned
1:1 by row order with the `system` block of the same name
([Trajectory](trajectory.md#with-and-without-system)).

Types are linked, not embedded: `atoms.type` and each relation block's
`type` name rows of the record's [`forcefield`](forcefield.md) section (or
its collection's), and a relation block's `style` column picks among styles
of one category. Per-instance parameters (MMFF, UFF) stay columns of the
relation blocks.
