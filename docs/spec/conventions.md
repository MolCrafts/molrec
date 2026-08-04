# Conventions

## Purpose

The model has no special fields. Conventions restore interoperability: they assign
recommended names and dtypes to blocks and columns so independent tools read each
other's records.

Conventions are **recommended, not required**. A reader must preserve blocks and
columns that do not follow them. The names below are kept in sync with the
reference implementations (molrs, molpy).

## Entity blocks

Recommended block names for common entity sets. Each is a plain table whose count
is the number of entities:

| Block | Count is | Typical columns |
|-------|----------|-----------------|
| `atoms` | number of atoms | `x`/`y`/`z`, `element`, `type`, `charge`, ... |
| `bonds` | number of bonds | `atomi`/`atomj`, `order` |
| `angles` | number of angles | `atomi`/`atomj`/`atomk` |
| `dihedrals` | number of dihedrals | `atomi`/`atomj`/`atomk`/`atoml` |

Other entity sets (beads, fragments, residues, virtual sites) follow the same
pattern with their own block name.

### Topology without coordinates

The same `atoms` / `bonds` / … blocks MAY appear under the record section
`system/` **without** Cartesian coordinate columns (`x`/`y`/`z` or `xyz`). That
shape is valid for a system definition: identity and connectivity without a
snapshot. Coordinates belong on `frame` / `trajectory`. See [System](system.md).

## Atom columns

Recommended column names and canonical dtypes for an `atoms`-like block:

| Column | dtype | Meaning |
|--------|-------|---------|
| `x`, `y`, `z` | float | Cartesian coordinates |
| `xyz` | float `[count][3]` | packed Cartesian coordinates |
| `vx`, `vy`, `vz` | float | Cartesian velocity components |
| `id` | uint / int | stable per-atom identifier |
| `element` | string | element symbol (e.g. `"C"`) |
| `type` | string | force-field / atom type label |
| `name` | string | atom name (e.g. `"CA"`) |
| `charge` | float | partial charge |
| `mass` | float | atomic mass |
| `mol_id` | int | molecule grouping |
| `res_id`, `res_name` | int, string | residue grouping |
| `bead_type` | string | coarse-grained bead type |

Coordinates may be stored as split `x`/`y`/`z` **or** packed `xyz`; a reader does
not synthesize one from the other. Continuous quantities (`x`/`y`/`z`,
`vx`/`vy`/`vz`, `charge`, `mass`, `order`) are float-canonical: a value written as
an integer is stored as a float so a later fractional write is accepted.

## Relations

Tuple blocks (`bonds`, `angles`, `dihedrals`) reference atoms by 0-indexed
endpoints, one column per position:

| Column | Position |
|--------|----------|
| `atomi` | 1st endpoint |
| `atomj` | 2nd endpoint |
| `atomk` | 3rd endpoint |
| `atoml` | 4th endpoint |

Endpoints are `uint`, indexing into the `atoms` block's row order. The block's
count is the number of relations. Per-relation properties (e.g. `order`) are
aligned columns.

## Box

The simulation cell is the frame's `box` (see [Frame](frame.md#box)): a triclinic
cell whose `vectors` columns are lattice vectors, with an origin and per-axis
periodic boundary flags.

## Volumetric data

A volumetric field is a block with structural shape `[nx, ny, nz]` (see
[Types](types.md#block-structural-shape)); each scalar field is a float column of
shape `[nx][ny][nz]`. The cell is the frame's box — a volumetric block carries no
cell of its own.

## Trajectory packing

A [trajectory](trajectory.md) may store its frames packed: per-block arrays
with a leading time axis (e.g. `atoms/x` of shape `[nstep][count]`), plus aligned
`step` (int) and `time` (float) index arrays. Packed storage is a convention; the
logical meaning is still an ordered list of frames.
