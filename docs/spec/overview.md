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
 \-- (forcefield)
 \-- (observables)
 \-- (method)
 \-- (status)
 \-- (metrics)
```

A package includes `meta` and at least one of `frame`, `system`,
`trajectory`, `forcefield`, or `status`. Inside a section, every group or array is again
optional unless that section's chapter says otherwise.

Typical compositions:

| Composition | Sections | Typical use |
|-------------|----------|-------------|
| Structure | `meta`, `frame` | one conformation |
| System def | `meta`, `system` | topology without coordinates |
| Force field | `meta`, `forcefield` | a parameter set, distributed on its own |
| Trajectory | `meta`, `trajectory` | MD time series (`system` optional) |
| Run | `meta`, `status` | training job / workflow (`metrics` and/or `method` recommended) |

## Section kinds

A section is a named group at the root. Content falls into four kinds:

**Document.** A JSON object stored as group attributes. Small, structured
facts: identity, lifecycle, scientific context. `meta`, `status`, and
`method` are documents.

**Frame-shaped.** Named [blocks](frame.md) of columns, a `meta` document
(the group's attributes), optional `box`. Instantaneous or definitional
tables. `frame`, `system` and [`forcefield`](forcefield.md) are
frame-shaped ([Frame-shaped group](storage.md#frame-shaped-group)).

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
columns. The parameters that *define* the energy model live in the
[`forcefield`](forcefield.md) section; how a job was run lives under
`method`.

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
covers the whole package — layout, containers, dtypes, the trajectory
sequence declaration, and what the numbers of the force-field IR mean. The
current version is `2`.

- **Writers always emit it.** A writer stamps the version it writes,
  `molrec_version: 2`, on every record, over any value the producer's
  document carries: what it writes is version-2 content whatever the
  document claims.
- **Readers validate it when present.** A present key must be a JSON integer
  in `1 ..= <newest the reader supports>`; `null`, `0`, a string, a float, a
  boolean, or a newer version is refused — present means validated.
- **A reader never reads an older version as its own.** It reads a
  version-*n* store by version *n*'s rules: what a later version changed, it
  converts exactly, or it refuses the store. A version-2 reader reads a
  version-1 store as [Reading a version-1 record](forcefield.md#reading-a-version-1-record)
  says. An absent key marks a store written before version 1; a reader opens
  it best-effort, by version 1's rules.
- **`meta` comes back as stored.** A reader that converted a store's sections
  hands its `meta` back unchanged — the version it was written in, or no key —
  and a writer of the record stamps the current version again.

Identity of a record is the path brand `*.mrec/` / `*.mrec.zip` plus a Zarr
root, not this key. A bump indicates a change to a normative rule. Additive
content that older readers can carry through unrecognised needs no bump.

| Version | Changed from the previous one |
|---------|-------------------------------|
| `1` | — |
| `2` | The [force-field registry](forcefield.md#style-registry) is the force-field IR, which adopts LAMMPS's definitions. Stored numbers whose meaning changed: `units.angle` is the `degree` in every preset (it was the radian), so `theta0`, `chi0`, `phase`, `phase<m>` and `phi1` … `phi3` are degrees and a force constant is per radianⁿ whatever `units.angle` says; `bond.harmonic`, `angle.harmonic` and `drude.harmonic` are k(x − x0)² (they were ½k(x − x0)²: `k` halves); `bond.morse` names its well depth `d0` (it was `D`); the `pair14` category is retired (per-type 1-4 parameters are `pair.lj/charmm`'s, per-pair ones [pair overrides](forcefield.md#pair-overrides)); `dihedral.charmm` `w` prices its end atoms' 1-4 pair. The same holds for a relation block's parameter columns. Version 1 producers' own styles: `dihedral.fourier` is `dihedral.periodic`, `pair.morse` `D0` is `d0`, `pair.thole` `a_thole` is `damp`, MMFF / UFF out-of-plane rows list the centre first. Added beside them (no conversion needed): `pair.lj/charmm`, `pair.coul/charmm`, `angle.charmm`, `cmap.charmm`, `dihedral.nharmonic`, pair overrides. |

`record_id`, `content_hash`

Optional provenance: a producer-chosen identifier and a content digest.

`creator`, `author`, `created_at`, `source`

Optional provenance. Producers may add any other keys; a reader preserves
keys it does not recognise.

`modules`

Each module is a subgroup keyed by name, holding a major/minor `version`
pair and any module-specific information.
