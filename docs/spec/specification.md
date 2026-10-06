# Objective

MolRec is a specification for a scientific record: one self-describing package
of molecular and operational data that independent tools may exchange without
guessing private layouts. It covers molecular systems, snapshots and
trajectories, scientific observables, and run logs (status, metrics, method).

MolRec names layout and semantics. Implementations expose their own APIs
(the reference implementation's are `molrs.io.write_mrec`,
`write_mrec_trajectory` and the streaming `molrs.io.mrec.TrajectoryWriter`);
the contract is the structure in the chapters that follow.

The unit of interchange is the *record*. A `frame` section *is* a frame; a
`trajectory` section *is* an ordered series of frames. Time-dependent data is
a record section.

Every writer stamps `meta["molrec_version"]` (currently `2`); a reader
validates it when present and reads a version-1 store by version 1's rules,
converting it exactly or refusing it, never as version 2; an absent key marks
a store written before version 1 (see [Metadata](overview.md#metadata)). A record is
identified by its `*.mrec` path suffix and its Zarr root.

## Storage format

The specification is backend-neutral. The *reference* physical form is one
[Zarr](https://zarr.dev/) V3 hierarchy. The live scientific record is a
directory `*.mrec/` — that directory *is* the Zarr root (`zarr.json` at its
top). The packed at-rest form is `*.mrec.zip`. Scientific paths use that
brand.

Document sections (`meta`, `status`, `method`) are stored as group attributes.
Array sections (`frame`, `system`, `trajectory`, observables) are stored as
groups and arrays; `forcefield` is a document (its group's attributes) beside
one table of arrays per style. Live metrics may use an append-only JSONL
buffer; closed metrics densify to Zarr series.

Implementation details start at [Why Zarr V3](zarr.md): the layout of a
record on that binding, chunking, the metrics WAL, and the ragged
trajectory encoding follow from there.

## Notation and naming

A record is organized into groups and arrays, summarized as *objects*, which
form a tree with arrays as leaves. Attributes can be attached to each object.
The specification adopts this naming and uses the following notation to
depict the tree or its subtrees:

`\-- item`

An object within a group, that is either an array or a group. If it is a
group itself, the objects within the group are indented by five spaces with
respect to the group name.

`+-- attribute`

An attribute, that relates either to a group or an array.

`\-- data: <dtype>[dim1][dim2]`

An array with dimensions `dim1` by `dim2` and of type `<dtype>`. The type is
taken from the closed set in [Containers](frame.md#data-types). A scalar is
indicated by `[]`.

`(identifier)`

An optional item.

`<identifier>`

An optional item with unspecified name.

## General organization

MolRec defines an organization of a record into groups, arrays, and
attributes. The root of a record may coincide with the Zarr root of a
`*.mrec/` directory. A number of groups are defined at the
[root](overview.md). Several levels of subgroups may exist inside,
allowing the storage and description of subsystems.

The record is allowed to possess non-specified groups, arrays, or attributes
that contain additional information such as application-specific parameters
or data structures, leaving scope for future extensions. Only the `meta`
group is mandatory at the root, and it may be an empty document. All other
root groups — `system` and `frame` included — are optional, allowing the
user to store only relevant data. A record must nevertheless contain at
least one of `frame`, `system`, `trajectory`, `forcefield`, or `status`
besides `meta`.
Inside each group, every group or array is again optional, unless specified
differently.

A reader preserves sibling sections and keys it does not recognise.

Force-field parameters live in the [`forcefield`](forcefield.md) section. How
a job is run lives under `method`.

Array data live in [columns, blocks, and frames](frame.md). Time-dependent
data live in the [trajectory](trajectory.md) section. Recommended names are
[standardized identifiers](conventions.md).

## Published schemas

The prose is normative; the JSON Schemas under `schema/` are generated from
the reference models and describe the same documents for other languages:

| Directory | Describes |
|-----------|-----------|
| `schema/core/` | the record, its documents (`meta`, `status`, `method`), frames, blocks, columns, cells, trajectories, collections |
| `schema/observables/` | the v1 [observables](observables.md) section |
| `schema/binding/` | the trajectory group's pinned `sequence_schema` attribute |
| `schema/ref/` | a pointer from one record into another (`uri`, optional content `hash`), used by the draft observables' provenance |
| `schema/report/` | one conformance violation — the closed vocabulary a conformance report names failures with, so implementations in other languages report the same names |
| `schema/draft/observables/` | the dims-based observables **draft**; not part of version 1 |
