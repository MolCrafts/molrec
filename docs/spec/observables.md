# Observables

## Purpose

`observables` is a recommended record section for named quantities that are
part of the interpreted scientific record: a total energy, a dipole, an RDF,
a free-energy surface. It is a convention layered on the general model (see
[Overview](overview.md)). A record need not carry one.

Run-local monitoring (training loss, step time, throughput) belongs under
[Metrics](metrics.md). An observable is a quantity a reader treats as part of
the chemistry or physics payload.

An observable is a value array over named dimensions. Coordinates that
several quantities share are stored once on the section.

Physical form: **Zarr arrays** with `dims` (and optional `unit`) on each
array's attributes. See [Storage](storage.md).

## Structure

```text
observables/
├── coordinates/
│   └── <safe_name>          # array; attrs: dims, (unit)
└── observables/
    └── <safe_name>          # array; attrs: dims, (unit), (description),
                              #              (payload), (source)
```

`<safe_name>` is the percent-encoding in [Storage](storage.md). The logical
name may contain `/`.

A coordinate and a quantity may share a logical name. They live in different
groups, so the stored names do not collide.

## Values

Each quantity has:

| Field | Required | Meaning |
|-------|----------|---------|
| `values` | yes | One array: `dims`, `dtype`, `shape`, data |
| `description` | no | Prose |
| `unit` | no | Unit of the values, on the array |
| `payload` | no | What the number is when the name is not enough |
| `source` | no | Provenance: `refs`, optional `method_ref` |

`dims` has one name per axis, and `shape` has the same length. A scalar has
`dims = ()` and `shape = ()`.

The section checks one rule: a dimension name has one length everywhere it
appears. A grid and a scatter are different dimension names, not a flag:

```text
grid        phi.dims=(phi,)      psi.dims=(psi,)    values.dims=(phi, psi)
scatter     phi.dims=(sample,)   psi.dims=(sample,) values.dims=(sample,)
curve       step.dims=(point,)   values.dims=(point,)
```

There is no `kind` of scalar versus vector, and no `time_dependent` flag.
The dimensions already say both. A second copy of that fact can disagree
with the array.

`dtype` is the closed set in [Types](types.md). A `f32` observable stays
`f32`.

## Coordinates

`coordinates` holds the axes. A hundred curves over one `step` store that
`step` array once. The dimension list is derived from the arrays; it is not
a second table.

## See also

- [Metrics](metrics.md) — run-local series
- [Types](types.md) — dtypes and validity
