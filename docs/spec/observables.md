# Observables group

Named scientific result quantities — a total energy, a dipole moment, a
per-atom charge — are stored in the `observables` group. A record need not
carry one.

Observables are scientific results a reader would treat as part of the
chemistry or physics payload. Run-local monitoring (training loss, step
time, throughput) belongs under [metrics](metrics.md).

Each observable is a pair: data under `observables/<name>` and semantic
metadata under `observables/meta/<name>`. When the section is present the
pairing is mandatory.

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
 \-- <name>: <dtype>[...]
```

`kind`

Either `scalar` (one value per sample) or `vector` (an ordered tuple of
components per sample). Higher-rank data are expressed with the same two
kinds plus `axes` naming the trailing axes.

`time_dependent`

Time dependence is stated in metadata, not inferred from shape. When true,
the leading axis is the trajectory axis.

`sampling`, `domain`

Optional free-text provenance: how the quantity was sampled (e.g.
`per_frame`, `time_average`) and what domain it is defined over. The
reference implementation (molrs `ObservableRecord`) carries both as
first-class fields.

`target`

The block an entity-aligned observable indexes (e.g. `/frame/atoms`).

A producer that needs a distinct kind declares it in a module under
`meta/modules`.

A dims-based redesign of this section (named dimensions instead of `kind` /
`time_dependent`, xarray-style shared coordinates) exists as a **draft** in
the reference package (`schema/draft/observables/`). It is not part of
version 1; adopting it is a normative change and requires a
`molrec_version` bump.
