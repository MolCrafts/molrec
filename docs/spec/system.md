# System group

The `system` group answers what chemical or physical system the record is
about. It holds identity of the particle set, connectivity, typing,
force-field or model binding, and box policy. Instantaneous coordinates of
a time step live on `frame` or `trajectory`.

```text
system
 \-- (meta)
 \-- (atoms)
 \-- (bonds)
 \-- ...
 \-- (parameters)
 \-- (box_policy)
```

Writers may group topology under `system/topology/` or flatten blocks
directly under `system/` (`system/atoms`, `system/bonds`) when a `topology`
group adds no value. Field names reuse [standardized
identifiers](conventions.md). Topology vocabulary is the same as on a frame.

`system/parameters` holds tables, types, and styles that *define* the
Hamiltonian or model binding for this system. `method` holds narrative
scientific context (engine name, stage order).

Instantaneous Cartesian coordinates belong on `frame` or `trajectory`. A
conforming `system` may omit coordinate columns entirely.

Records with only `frame` (no `system`) remain valid. Records with only
`system` (no `frame`) are valid. A trajectory may omit `system`; when
`system` is present, `trajectory` should carry state updates only.
