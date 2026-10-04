# Collection

A **collection** is many records that share one declaration: a dataset of
molecules, each with its own topology and its own trajectory. It is what a
training set is — tens of thousands of relaxations, torsion scans or MD
snippets — and what one record cannot be.

A collection is a list of [records](overview.md) plus the few things every
record in it has in common. It adds no new container: each record is an
ordinary record, its `system` an ordinary frame, its `trajectory` an ordinary
[trajectory](trajectory.md), with the same carry-forward semantics.

## Model

```text
collection
 \-- meta            the collection's document: units, provenance
 \-- sequence_schema the one trajectory declaration every record uses
 \-- index           per-record columns the writer derives from each record
 \-- (forcefield)    the one force field every record links into
 \-- records[r]      record r: meta, system, trajectory
```

`meta`

A document. It **must** carry `units`: a map from quantity to unit string,
declared once for every record and every column in the collection.

| Quantity | Applies to |
|----------|------------|
| `length` | `x/y/z`, the cell |
| `energy` | `pe`, `ke`, `etotal` |
| `force` | `fx/fy/fz` |
| `charge` | `charge`, `total_charge` |
| `mass` | `mass` |
| `time` | the trajectory's `time` |

A unit string is parseable by [pint](https://pint.readthedocs.io)
(`angstrom`, `kcal/mol`, `kcal/mol/angstrom`, `eV`, `e`). A quantity the
records do not carry may be omitted; an omitted `mass` or `charge` keeps
its [default](conventions.md#atoms) (amu, `e`). Columns and per-step tags
still carry no unit of their own: a collection's numbers mean what `units`
says, for every record in it. Other keys are preserved.

`sequence_schema`

The [sequence declaration](ragged.md) — blocks, columns, dtypes, trailing
shapes, nullability, precisions, row references, alignments, per-step meta
tags and fills — that **every** record's
trajectory uses. One declaration for the collection is what makes its records
interchangeable: a reader can size a batch of them without opening any.

A record's frames may present a **subset** of the declared blocks (a record
that never carries `bonds` belongs to a collection that declares them), but
nothing outside the declaration, and its per-step `meta` declaration is the
collection's exactly. A record that presents anything else is refused. When
a writer derives the declaration rather than being handed one, it is the
union of the records' blocks — which must agree on every column they share —
and the per-step `meta` all records declare.

`index`

A block of `R` rows, one per record, in record order. Its columns are
**derived** from the records by the writer — a molecule code, a per-record
element mask, a size — so that a reader can answer a question about every
record without decoding one. A reader hands them back as written; it does not
recompute them. Four column names are reserved for the binding
(`first_frame`, `n_frames`, `n_atoms`, `has_trajectory`) and are not part of
the model.

`forcefield`

Optional. The [force field](forcefield.md#collections) every record's
`atoms.type` and relation `type` columns link into. A record of a collection
carries no `forcefield` of its own.

`records[r]`

An ordinary record restricted to `meta`, `system` and `trajectory`. Either of
`system` and `trajectory` may be absent, not both. Record order is the order
the writer appended them in and is stable.

## Topology once, state per frame

A record whose topology does not change carries it in `system` and nowhere
else; its trajectory carries state — coordinates, forces, per-step scalars.
When a `system` block and a `trajectory` block share a name they are aligned
**1:1 by row order** ([trajectory](trajectory.md#with-and-without-system)):
every trajectory update of that block has exactly the system block's row
count, and a reader presents the two as one block whose columns are the union.
A column may not appear in both.

A record whose topology *does* change — a reaction, a growing polymer —
declares the changing block in the trajectory instead, where it is written as
a [sparse update series](ragged.md): only at the frames where it changes.

## Conformance

The collection suite (`module = "collection"`) pins down:

* the round trip of meta, schema, index and every record;
* a record with no system, and one with no trajectory;
* a topology block that changes mid-record, and one that never does;
* records that present different subsets of one declaration, and a record
  whose trajectory has zero frames;
* refusal of a record whose trajectory declaration differs from
  `sequence_schema`;
* refusal of a trajectory block whose row count differs from the system block
  it shares a name with;
* refusal of a collection without `units`;
* a collection-wide force field round-trips;
* an aligned block that carries forward while its target moves, and one
  restated on growth;
* refusal of an aligned block that shares a name with a `system` block, and
  of one whose row count differs from its target's.

The one binding is [LMDB](lmdb.md).
