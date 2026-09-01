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
 \-- (id: u64[N])
 \-- (atomic_number: u64[N])
 \-- (element: string[N])
 \-- (type: string[N])
 \-- (type_id: u64[N])
 \-- (name: string[N])
 \-- (charge: f64[N])
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
