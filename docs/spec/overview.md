# Overview

The root of a MolRec package holds named **sections**. `meta` is always
present. Every other section is optional: take the ones that match the data,
leave the rest off.

```text
root
 \-- meta
 \-- (system)
 \-- (frame)
 \-- (trajectory)
 \-- (observables)
 \-- (method)
 \-- (status)
 \-- (metrics)
```

A package includes `meta` and at least one of `frame`, `system`,
`trajectory`, or `status`. Inside a section, every group or array is again
optional unless that section's chapter says otherwise.

Typical compositions:

| Composition | Sections | Typical use |
|-------------|----------|-------------|
| Structure | `meta`, `frame` | one conformation |
| System def | `meta`, `system` | topology without coordinates |
| Trajectory | `meta`, `trajectory` | MD time series (`system` optional) |
| Run | `meta`, `status` | training job / workflow (`metrics` and/or `method` recommended) |

## Section kinds

A section is a named group at the root. Content falls into three kinds:

**Document.** A JSON object stored as group attributes. Small, structured
facts: identity, lifecycle, scientific context. `meta`, `status`, and
`method` are documents.

**Frame-shaped.** Named [blocks](frame.md) of columns, optional `meta`,
optional `box`. Instantaneous or definitional tables. `frame` and `system`
are frame-shaped; so is each named observable's data.

**Sequence.** An ordered series of frames with `step` and optional `time`.
`trajectory` is the sequence section. Time-dependent data lives here; see
[Trajectory](trajectory.md).

Live `metrics` append as text and densify to arrays; that hybrid is
specified with the [metrics](metrics.md) section.

## Design principles

**Peer sections.** Sections sit side by side at the root. A trajectory is a
section, the same kind of thing as `frame` or `status`.

**Compose what you have.** A training run is `meta` + `status` + `metrics`.
A packed snapshot is `meta` + `frame`. An MD package is `meta` + `system` +
`trajectory`. The unused names stay absent.

**Unknown siblings stay.** A reader preserves sections and keys it does not
recognise. That is how new content enters the ecosystem: add a sibling, and
older tools carry it through.

**Conventional names, new names.** If the data *is* atoms, bonds, a box, use
the [standardized identifiers](conventions.md). If it is something else —
a mesh, a k-point grid, a docking pose — pick a new section or block name
and keep it. Reserved names keep their meaning.

**Facts vs arrays.** Structured facts that fit in JSON belong on a document
section (or `frame/meta`). N-dimensional values belong in columns. Force-field
and model tables that *define* the system live under `system/parameters`;
how a job was run lives under `method`.

**Modules name extra rules.** A shared interpretation beyond this
specification is declared under `meta/modules/<name>` with a major/minor
version. Custom `method` types and custom metric types point there.

## Adding your own content

Four places, in increasing size of the addition:

1. **Extra keys** on an existing document (`meta`, `status`, `method`).
   Readers preserve them.
2. **Extra columns or blocks** on `frame`, `system`, or `trajectory`. Same
   containers; your names. Readers preserve them.
3. **A new sibling section** at the root. Same three kinds: document,
   frame-shaped, or sequence. Older tools ignore the name and keep the
   group.
4. **A module** under `meta/modules` when independent tools must agree on
   what that extra content means.

Worked sketches:

- A volumetric density already fits: a block with structural shape
  `[nx][ny][nz]` on `frame`, cell on `box`.
- A docking score is an [observable](observables.md) (`kind` `scalar`,
  `target` `/frame/atoms`) or a column on a new `poses` block.
- A custom optimiser log is `metrics` (run-local curves) plus extra keys on
  `method`.
- A domain-specific tree (QM basis, crystal symmetry operations) is a new
  root section; declare a module if a second package must parse it.

## Metadata

Identity of the package lives in `meta`. In the reference binding the
contents are group attributes (one JSON object):

```text
meta
 +-- molrec_version: i64[]
 +-- (creator)
 |    +-- name: string[]
 |    +-- (version: string[])
 +-- (author)
 |    +-- name: string[]
 |    +-- (email: string[])
 +-- (created_at: string[])
 +-- (source: string[])
 \-- (modules)
      \-- <module1>
           +-- version: i64[2]
```

`molrec_version`

An attribute of integer type. It is the sole version key for the whole
package — layout, containers, dtypes, and the trajectory sequence
declaration. It starts at 1. The current value is 1. The scientific path
brand is `*.mrec/` / `*.mrec.zip`. Writers emit `molrec_version`; readers
decode that key.

A bump indicates a change to a normative rule. Additive content that older
readers can carry through unrecognised needs no bump.

`creator`, `author`, `created_at`, `source`

Optional provenance. Producers may add any other keys; a reader preserves
keys it does not recognise.

`modules`

Each module is a subgroup keyed by name, holding a major/minor `version`
pair and any module-specific information.
