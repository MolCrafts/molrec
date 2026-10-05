# Observables group

Named scientific result quantities — a total energy, a dipole moment, a
per-atom charge — are stored in the `observables` group. A record need not
carry one.

Observables are scientific results a reader would treat as part of the
chemistry or physics payload. Run-local monitoring (training loss, step
time, throughput) belongs under [metrics](metrics.md).

## Layout

`observables` is an **array section**: one data array per name, beside one
metadata document per name. It is not frame-shaped — there are no blocks,
and an observable's array has whatever shape its `kind` and `axes` say.

```text
observables
 \-- meta
 |    \-- <name>
 |         +-- kind: string[]
 |         +-- description: string[]
 |         +-- time_dependent: bool[]
 |         +-- (unit: string[])
 |         +-- (axes: string[...])
 |         +-- (sampling: string[])
 |         +-- (domain: string[])
 |         +-- (target: string[])
 |         +-- (<any other key>)
 \-- <name>: <dtype>[...]
```

- The data of observable `<name>` is the array `observables/<name>`: any
  shape (a 0-d array is a single value), any [column dtype](frame.md#data-types).
- Its metadata is the attribute map of the group `observables/meta/<name>`.
- **The pairing is mandatory.** A data array without its metadata group, or
  a metadata group without its data array, is malformed and a reader refuses
  it.
- `<name>` is one node name: non-empty, no `/`, not `.` or `..`, no leading
  `__`, and not `meta`, which names the metadata group.

## Metadata

`kind`

How the array is read: `scalar` (one value per sample) or `vector` (an
ordered tuple of components per sample). Higher-rank data are expressed with
the same two kinds plus `axes` naming the trailing axes. Required.

A producer that needs a distinct kind uses its own name for it (and
declares a module under `meta/modules` when other tools must agree on what
it means). **A reader carries a kind it does not know through unchanged**:
it neither refuses the observable nor rewrites the kind, and a writer that
read one writes it back as it found it.

`description`

Free text. Required.

`time_dependent`

Time dependence is stated in metadata, not inferred from shape. When true,
the leading axis is the trajectory axis, so the array has at least one
axis. Required.

`unit`, `axes`

Optional. `unit` is a unit string; `axes` names the trailing axes, in
order.

`sampling`, `domain`

Optional free-text provenance: how the quantity was sampled (e.g.
`per_frame`, `time_average`) and what domain it is defined over.

`target`

The block an entity-aligned observable indexes (e.g. `/frame/atoms`).

Every other key is a producer's: a reader preserves it verbatim, a
`null`-valued one included.

## Draft

A dims-based redesign of this section (named dimensions instead of `kind` /
`time_dependent`, xarray-style shared coordinates) exists as a **draft**
(`schema/draft/observables/`, the `draft/observables` conformance module).
It is not part of version 1, and a conformance run that names no modules
does not judge an implementation by it. Adopting it is a normative change
and requires a `molrec_version` bump.
