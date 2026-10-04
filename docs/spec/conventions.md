# Standardized identifiers

The containers have no special fields. The identifiers below restore
interoperability. They follow the Frame/Block naming that molpy documents as
the interchange representation — the same names molrs serializes.

The identifiers are recommended. A reader preserves blocks and columns
outside this list. Reserved names (`box`, `meta`, `atoms`, `atomi`, …) keep
their conventional meaning.

MolRec specifies the Frame/Block interchange representation. MolPy's Entity
graph (`itom` / `jtom` object references) is a construction API.

Block names are lowercase and plural. Field names are lowercase with
underscores for multi-word names.

## `atoms`

An `atoms` block holds per-particle properties. All arrays have length `N`,
the number of particles. Positions are stored as three separate 1-D columns
`x`, `y`, `z` — the standardized form; there is no packed `xyz` column.

```text
atoms
 \-- (x: f64[N])
 \-- (y: f64[N])
 \-- (z: f64[N])
 \-- (vx: f64[N])
 \-- (vy: f64[N])
 \-- (vz: f64[N])
 \-- (fx: f64[N])
 \-- (fy: f64[N])
 \-- (fz: f64[N])
 \-- (id: u64[N])
 \-- (atomic_number: u64[N])
 \-- (element: string[N])
 \-- (type: string[N])
 \-- (type_id: u64[N])
 \-- (name: string[N])
 \-- (charge: f64[N])
 \-- (formal_charge: i64[N])
 \-- (atom_map: u64[N])
 \-- (mass: f64[N])
 \-- (mol_id: u64[N])
 \-- (res_id: u64[N])
 \-- (res_name: string[N])
 \-- (bead_type: string[N])
```

`x`, `y`, `z`

Cartesian coordinates.

`vx`, `vy`, `vz`

Cartesian velocity components.

`fx`, `fy`, `fz`

Cartesian force components on each particle: the negative gradient of the
state's potential energy (`pe`), as a producer computed or labelled it.

`id`

A stable per-atom identifier carried by the source file. Never an index —
relation endpoints are 0-based row indices.

`atomic_number`

Atomic number Z.

`element`

IUPAC element symbol (e.g. `"C"`).

`type`

Force-field type label. Always a string — a label is what survives a round
trip through a force field. Numeric type ordinals live in `type_id`.

`charge`, `mass`

Partial charge and atomic mass. `mass` is in amu and `charge` in
elementary-charge units. Coordinates and velocities carry no intrinsic
unit.

Continuous quantities (`x`/`y`/`z`, `vx`/`vy`/`vz`, `charge`, `mass`) are
float-canonical: a value written as an integer is stored as a float so a
later fractional write is accepted.

Format-specific aliases (LAMMPS `q`, `mol`) exist only at the I/O boundary.
Readers canonicalize them to `charge` and `mol_id`.

The same `atoms` block may appear under `system` without coordinate columns.
When it does and `trajectory/atoms` exists too, the two are aligned 1:1 by
row order — every trajectory update has exactly the `system` row count — and
an `id` column present on both sides is equal row for row. A ragged
trajectory block never shares a name with a `system` block
([Trajectory](trajectory.md#with-and-without-system)).

`formal_charge`

Integer formal charge of each atom in the bonding pattern, in `e`. Distinct
from `charge`, the (partial) charge an energy model assigns.

`atom_map`

The atom-map number of each atom in a mapped SMILES string
(`mapped_smiles`), `0` for an unmapped atom. Row `i` of `atoms` is the atom
mapped `atom_map[i]`.

## Relations

Tuple blocks reference atoms by 0-based integer indices into the `atoms`
block's row order. Endpoints are `u64` and must store integers — never
object references.

```text
bonds
 \-- atomi: u64[E]
 \-- atomj: u64[E]
 \-- (type: string[E])
 \-- (bond_type: u64[E])
 \-- (bond_number: u64[E])
```

`bond_type` is the chemical bond class: `0` unknown, `1` single, `2` double,
`3` triple, `4` aromatic. `bond_number` is the integer bond number of the
localized Lewis/Kekulé structure (`0` unknown, `1`–`4`) — never fractional;
aromaticity is a bond type, not a number. The two are orthogonal: an
aromatic bond is `bond_type = 4` carrying a `bond_number` of 1 or 2. There
is no float `order` column.

| Block | Endpoint columns | Optional |
|-------|------------------|----------|
| `bonds` | `atomi`, `atomj` | `type`, `bond_type`, `bond_number` |
| `angles` | `atomi`, `atomj`, `atomk` | `type` |
| `dihedrals` | `atomi`, `atomj`, `atomk`, `atoml` | `type` |
| `impropers` | `atomi`, `atomj`, `atomk`, `atoml` | `type` |

`atomj` is the center atom of an angle. Other entity sets (beads, fragments,
residues, virtual sites) follow the same pattern with their own block name.

The naming conventions do not change with the record section. An `atoms`
block under `trajectory` carries the same columns it carries under `frame`.
The [box](frame.md#simulation-box) identifiers (`vectors`, `origin`,
`boundary`, `cell_defined`) are part of the cell, not of these blocks.

## Per-step scalars

Per-step scalars of a trajectory land under `trajectory/meta/<key>`
([Ragged trajectory](ragged.md#per-step-metadata)). The standard keys are
all `f64`:

| Key | Meaning |
|-----|---------|
| `pe` | potential energy |
| `ke` | kinetic energy |
| `etotal` | total energy |
| `temp` | temperature |
| `press` | pressure |
| `volume` | cell volume |

As with columns, the tag carries no unit; producers add other keys freely
and readers preserve them.

## Composition and identity keys

Keys of a `system` (or `frame`) meta document that say what the particles
*are*, as opposed to what state they are in. Recommended; a reader
preserves others.

| Key | Type | Meaning |
|-----|------|---------|
| `total_charge` | integer | net charge of the system, in `e` |
| `spin` | integer | spin multiplicity `2S + 1` |
| `smiles` | string | SMILES of the system |
| `mapped_smiles` | string | atom-mapped SMILES; `atoms.atom_map` indexes it |
| `molecule_id` | string | identity of the molecule, shared by every record of it |
| `source_record_id` | string | the record's identifier in the upstream source |

`molecule_id` is what keeps two records of one molecule on the same side of
a train/test split. Two records carry equal `molecule_id` exactly when they
describe the same molecule.

## Typed JSON values

JSON has no NaN, no infinity, no complex number, and a reader whose numbers
are binary64 (JavaScript, a wasm viewer) silently rounds an integer beyond
2⁵³. Wherever a JSON value has a declared dtype — a per-step `fill` in
`sequence_schema`, a per-step value in an [LMDB](lmdb.md) frame header, a
value in a live observables WAL row — it is written in exactly one form:

| Element dtype | JSON form |
|---------------|-----------|
| `f64` | a JSON number when finite; the strings `"NaN"`, `"Infinity"`, `"-Infinity"` otherwise |
| `c64`, `c128` | a two-element array `[re, im]`, each part an `f64` as above |
| an integer dtype | a JSON number when `|v| ≤ 2⁵³`; its decimal string (`"18446744073709551615"`) beyond |
| `bool`, `string` | itself |
| `json` (meta tag) | the document itself, which must be finite JSON |

A vector tag (`f64x3`, `u64x3`, …) is a JSON array of its elements, each in
the form above.

- A writer serializes every document with NaN and infinity forbidden
  (`allow_nan=False` or its equivalent) and hands numbers over as plain
  JSON numbers, never as a language's native scalar type.
- A reader accepts exactly these forms, plus an exact JSON integer beyond
  2⁵³ (what a writer with 64-bit integers may emit), and refuses everything
  else: `null` where a number is declared is a broken value, not a NaN, and
  a real where an integer is declared is not rounded.
- A value is held to its dtype's range: an `i32` fill of `2³¹` is refused.

An untyped document — `meta`, `status`, `method`, a frame's `meta` — has no
declared dtype; its numbers are plain JSON and a producer that needs NaN in
one stores it as data, not as a document key.
