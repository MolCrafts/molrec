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

A document. Its `units` is the collection's one
[unit system](conventions.md#units): a map from quantity to unit string,
stated once for every record and every column in the collection. The nine
quantities are `length`, `energy`, `force`, `charge`, `mass`, `time`,
`pressure`, `temperature` and `angle`; which column or meta key each is the
unit of, and which make it required, is the table in
[Units](conventions.md#units).

- A quantity is required exactly when some record carries it. A collection
  whose records carry none — topologies with no coordinates, say — may leave
  `units` out altogether; one whose records carry `x` and no `length` is
  refused.
- No quantity has a default: a collection whose records carry `mass` or
  `charge` states their units.
- **A record of a collection carries no `meta.units`.** The collection's is
  the one statement; a record that restates it is refused, an empty object
  included.
- A column's own `unit` overrides the collection's unit for that column
  alone, and does not stand in for it.

A unit string is a label (`angstrom`, `kcal/mol`, `kcal/mol/angstrom`, `eV`,
`e`): a reader hands it back as written. Other keys of `meta` are preserved.

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
A column may not appear in both, `id` excepted: restated, it is equal row for
row. This is the record's own rule, not a collection's.

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
* refusal of a collection whose records carry coordinates, forces and
  energies and whose `meta` states no `units`;
* a collection-wide force field round-trips;
* an aligned block that carries forward while its target moves, and one
  restated on growth;
* refusal of an aligned block that shares a name with a `system` block, and
  of one whose row count differs from its target's.

The layout is [LMDB](lmdb.md). molrec ships the plain reference codec.
molhub ships the collection store.
