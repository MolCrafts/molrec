# Standardized identifiers

The containers have no special fields. The identifiers below restore
interoperability. They follow the Frame/Block naming that molpy documents as
the interchange representation — the same names molrs serializes.

The identifiers are recommended: a producer need not use them, and a reader
preserves blocks and columns outside this list. A producer that **does** use
one uses it with its canonical dtype and shape (below). Names reserved by
the layout itself — `box` and `_validity` among a frame's children, the
trajectory's own children — are listed in
[Root layout](storage.md#frame-shaped-group) and
[Ragged trajectory](ragged.md#reserved-names).

MolRec specifies the Frame/Block interchange representation. MolPy's Entity
graph (`itom` / `jtom` object references) is a construction API.

Block names are lowercase and plural. Field names are lowercase with
underscores for multi-word names.

## Canonical dtypes

A canonical column key has **one dtype and one shape wherever it appears** —
in any block, under `frame`, `system` or `trajectory`, on the frame path
and the trajectory path alike. Every key in this chapter is one value per
row (`<dtype>[N]`, no trailing axes), at the dtype the trees below give it.

| Keys | dtype |
|------|-------|
| `x` `y` `z` `vx` `vy` `vz` `fx` `fy` `fz` `charge` `mass` | `f64` |
| `quatw` `quati` `quatj` `quatk` `mux` `muy` `muz` `axis_x` `axis_y` `axis_z` `occupancy` `b_factor` | `f64` |
| `id` `atomic_number` `type_id` `mol_id` `res_id` `atom_map` | `u64` |
| `atomi` `atomj` `atomk` `atoml` `atomm` `ibead` `bond_type` `bond_number` | `u64` |
| `formal_charge` | `i64` |
| `ix` `iy` `iz` | `i32` |
| `free` `is_14` `exclude_14` | `bool` |
| `element` `type` `name` `res_name` `bead_type` `chain` `icode` `altloc` `style` | `string` |

The table is published as
[`schema/core/vocabulary.json`](../../schema/core/vocabulary.json)
(`{key: dtype}`), generated from the models.

- A writer **MUST NOT** store a canonical key at any other dtype or shape.
  A writer whose producer hands it a narrower unsigned array under one of
  these keys may widen it exactly (a `u32` `atomi` becomes `u64`) and
  write the canonical dtype.
- The unsigned identifiers and relation endpoints — `id`, `atomic_number`,
  `type_id`, `mol_id`, `res_id`, `atomi`, `atomj`, `atomk`, `atoml`,
  `atomm`, `ibead`, `bond_type`, `bond_number` — are **exactly `u64`**. A reader **MUST**
  refuse one stored at any other width or signedness rather than widen it on
  read: a record that holds one narrower came from a writer that broke the
  contract, and reading it back as `u64` would hide that.
- A reader **SHOULD** refuse any other canonical key at another dtype too.
- The [per-step scalars](#per-step-scalars) are canonical the same way: a
  declared `pe`, `ke`, `etotal`, `temp`, `press` or `volume` key is `f64`.

## `atoms`

An `atoms` block holds per-particle properties. All arrays have length `N`,
the number of particles. Positions are stored as three separate 1-D columns
`x`, `y`, `z` — the standardized form; there is no packed `xyz` column.

```text
atoms
 \-- (x, y, z: f64[N])
 \-- (vx, vy, vz: f64[N])
 \-- (fx, fy, fz: f64[N])
 \-- (ix, iy, iz: i32[N])
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
 \-- (chain: string[N])
 \-- (icode: string[N])
 \-- (altloc: string[N])
 \-- (occupancy: f64[N])
 \-- (b_factor: f64[N])
 \-- (bead_type: string[N])
 \-- (free: bool[N])
 \-- (quatw, quati, quatj, quatk: f64[N])
 \-- (mux, muy, muz: f64[N])
 \-- (axis_x, axis_y, axis_z: f64[N])
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

Partial charge and atomic mass. Their units are **defaults**, not fixed:
`mass` is in amu and `charge` in elementary charges `e` unless a declared
unit says otherwise — a [collection's](collection.md#model) `units`, or a
module under `meta/modules`. Coordinates, velocities, forces and energies
carry no default unit: without a declaration they are whatever the producer
used, and a reader that needs one must find it declared.

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

`ix`, `iy`, `iz`

Periodic image flags along the first, second and third lattice vector: how
many cells the atom has crossed. The continuous position is
`(x, y, z) + H · (ix, iy, iz)` with `H` the box `vectors`; the stored
coordinate stays wrapped. Signed. They travel with the coordinates: a writer
that drops one drops all three.

`res_id`, `res_name`, `chain`, `icode`, `altloc`

The residue an atom belongs to and where it came from. `res_id` is the source
file's residue number (never a row index; unsigned — a reader renumbers a
negative one at its boundary), `res_name` its name, `chain` the chain label
(PDB chain identifier, mmCIF `label_asym_id`), `icode` the insertion code and
`altloc` the alternate-location indicator, `""` for none. A residue is
identified by `(chain, res_id, icode)`. There is no `residues` or `chains`
block: the per-atom columns are the one carrier.

`occupancy`, `b_factor`

Crystallographic occupancy (a fraction) and isotropic displacement parameter
`B` (length²).

`free`

Whether an atom may move when coordinates are optimized. `false` pins it. A
block without the column has every atom free.

`quatw`, `quati`, `quatj`, `quatk`

A per-particle orientation quaternion `(w, i, j, k)`.

`mux`, `muy`, `muz`

A per-particle electric dipole moment (charge × length).

`axis_x`, `axis_y`, `axis_z`

A coarse-grained site's axis: from the first member of its group to the site
(length).

Positions are Cartesian. Fractional coordinates are not a convention: a
reader of a fractional format converts at its boundary.

## Relations

Relation blocks reference atoms by 0-based `u64` row indices into the
`atoms` block (`atomi` … `atomm`) — integers, never object references; a
relation that references another block says so with
[`targets`](frame.md#row-references).

```text
bonds
 \-- atomi: u64[E]
 \-- atomj: u64[E]
 \-- (type: string[E])
 \-- (type_id: u64[E])
 \-- (style: string[E])
 \-- (bond_type: u64[E])
 \-- (bond_number: u64[E])
```

`bond_type` is the chemical bond class: `0` unknown, `1` single, `2` double,
`3` triple, `4` aromatic. `bond_number` is the integer bond number of the
localized Lewis/Kekulé structure (`0` unknown, `1`–`4`) — never fractional;
aromaticity is a bond type, not a number. The two are orthogonal: an
aromatic bond is `bond_type = 4` carrying a `bond_number` of 1 or 2. There
is no float `order` column.

| Block | Endpoints | Optional |
|-------|-----------|----------|
| `bonds` | `atomi`, `atomj` | `type`, `type_id`, `style`, `bond_type`, `bond_number` |
| `angles` | `atomi`, `atomj` (vertex), `atomk` | `type`, `type_id`, `style` |
| `dihedrals` | `atomi` … `atoml` | `type`, `type_id`, `style`, `exclude_14` |
| `impropers` | `atomi` … `atoml` | `type`, `type_id`, `style`, `exclude_14` |
| `pairs` | `atomi`, `atomj` | `type_id`, `is_14`, `epsilon`, `sigma`, `charge_product`, `lj_scale`, `coul_scale` |
| `exclusions` | `atomi`, `atomj` | — |
| `constraints` | `atomi`, `atomj` | `type`, `type_id`, `style` |
| `virtual_sites` | `atomi` (the site), `atomj`, `atomk`, `atoml` (constructing atoms) | `type`, `type_id`, `style` |
| `drudes` | `atomi` (core), `atomj` (Drude particle) | `type`, `type_id`, `style` |
| `cmaps` | `atomi` … `atomm` | `type`, `type_id`, `style` |
| `members` | `ibead` → `atoms`, `atom` (declared) | — |

`type` names a row of the record's [force field](forcefield.md#linking-a-system)
and `style` picks the style when several hold that name. `type_id` is a
format-local ordinal (LAMMPS) and plays no part in linking. A relation may
carry per-instance parameters as further columns named as its style names
them (`r0` on `constraints`, `kb` on an MMFF `bonds`).

`is_14` marks a `pairs` row as a 1-4 pair; `exclude_14` marks a torsion whose
1-4 non-bonded term is suppressed (AMBER's negative third index). A `pairs`
row links no force-field row: its pair is priced by the pair styles through
its atoms' types, and its nullable `f64` columns `epsilon`, `sigma`,
`charge_product`, `lj_scale` and `coul_scale` override them for that one pair
([pair overrides](forcefield.md#pair-overrides)).
`exclusions` lists pairs excluded from non-bonded interaction.

A `virtual_sites` row constructs the particle `atomi` (an `atoms` row,
usually massless) from up to three others; a site built from fewer leaves
the trailing endpoints null. A `drudes` row pairs a core atom with its Drude
particle; both are `atoms` rows. A `cmaps` row is a CMAP cross term over two
consecutive dihedrals, `atomi`–`atomj`–`atomk`–`atoml` (φ) and
`atomj`–`atomk`–`atoml`–`atomm` (ψ); its `type` names a row of a
[`cmap` table](forcefield.md#categories).

A coarse-grained frame stores its beads as `atoms` rows (with `bead_type`)
and its bonds in `bonds`. `members` maps beads to the atoms they group, one
row per (bead, atom): `ibead` references `atoms` of the same frame; `atom`
references the all-atom block named by `targets` (`/frame/atoms`, …), and
without a declared target it is an opaque handle.

There is no `residues`, `chains` or `molecules` block: per-atom `res_id`,
`res_name`, `chain`, `icode` and `mol_id` are what every format carries, and
a block would be a second carrier of one fact. Residue-level data a producer
needs goes in a block of its own, referenced with `targets`.

Other entity sets (fragments, a producer's own groupings) follow the same
pattern with their own block name.

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

## Units on a frame

The meta key `units` (`json`) on a `frame` or `system` says what unit system
the frame's numbers are in. Its value has the shape of the
[force-field `units`](forcefield.md#the-document) object
(`{"preset": "real"}`, `{"length": "nm", "energy": "kJ/mol"}`). A string
value is read as `{"preset": <string>}`. Absent means the frame states none
(a collection states them once, in its `meta.units`).

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
value in a live observables WAL row, a value of a frame's or system's `meta`
(typed by `_meta_types`, [Root layout](storage.md#frame-shaped-group)) — it
is written in exactly one form:

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

An untyped document — the record's `meta`, `status`, `method`, the
`forcefield` document — has no declared dtype; its numbers are plain JSON,
and a producer that needs NaN in one stores it as data, not as a document
key. A frame's `meta` is typed: every key has a tag.
