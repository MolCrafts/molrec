# Overview

The root of a MolRec package holds named **sections**. `meta` is always
present (an empty document is a valid one). Every other section — `system`
and `frame` included — is optional: take the ones that match the data,
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

A section is a named group at the root. Content falls into four kinds:

**Document.** A JSON object stored as group attributes. Small, structured
facts: identity, lifecycle, scientific context. `meta`, `status`, and
`method` are documents.

**Frame-shaped.** Named [blocks](frame.md) of columns, a `meta` document
(the group's attributes), optional `box`. Instantaneous or definitional
tables. `frame` and `system` are frame-shaped
([Frame-shaped group](storage.md#frame-shaped-group)).

**Array.** Named arrays, each beside a metadata document. `observables` is
an array section: one data array of any shape per name, with its `kind` and
the rest of its metadata under `observables/meta/<name>`; see
[Observables](observables.md).

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
section (or a frame's meta document). N-dimensional values belong in
columns. Force-field parameters: see [Force field](forcefield.md); how a
job was run lives under `method`.

**Modules name extra rules.** A shared interpretation beyond this
specification is declared under `meta/modules/<name>` with a major/minor
version. Custom `method` types and custom metric types point there.

## Adding your own content

Four places, in increasing size of the addition:

1. **Extra keys** on an existing document (`meta`, `status`, `method`).
   Readers preserve them.
2. **Extra columns or blocks** on `frame`, `system`, or `trajectory`. Same
   containers; your names. Readers preserve them.
3. **A new sibling section** at the root. Same four kinds: document,
   frame-shaped, array, or sequence. Older tools ignore the name and keep
   the group.
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
 +-- molrec_version: i64[]           (absent only on a pre-1 store)
 +-- (creator)
 |    +-- name: string[]
 |    +-- (version: string[])
 +-- (author)
 |    +-- name: string[]
 |    +-- (email: string[])
 +-- (created_at: string[])            RFC 3339 with an explicit offset
 +-- (source: string[])
 \-- (modules)
      \-- <module1>
           +-- version: i64[2]
```

`molrec_version`

The integer version of this contract the package was written against. It
covers the whole package — layout, containers, dtypes, and the trajectory
sequence declaration. The current version is `1`.

- **Writers always emit it.** A writer stamps `molrec_version: 1` on every
  record it writes (a producer that supplied its own valid value keeps it).
- **Readers validate it only when present.** An absent key marks a store
  written before version 1; a reader opens it best-effort and performs no
  version check. A present key must be a JSON integer in
  `1 ..= <newest the reader supports>`. `null`, `0`, a string, a float, a
  boolean, or a newer version is refused — present means validated.

Identity of a record is the path brand `*.mrec/` / `*.mrec.zip` plus a Zarr
root, not this key. A bump indicates a change to a normative rule. Additive
content that older readers can carry through unrecognised needs no bump.

`record_id`, `content_hash`

Optional provenance: a producer-chosen identifier and a content digest.

`creator`, `author`, `created_at`, `source`

Optional provenance. Producers may add any other keys; a reader preserves
keys it does not recognise.

`modules`

Each module is a subgroup keyed by name, holding a major/minor `version`
pair and any module-specific information.
