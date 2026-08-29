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

Only `vectors` is required. The other parts are optional, and **absence has a
fixed meaning**: two readers that default them differently turn one store into
two different physical systems, so the defaults are normative.

| Part | Absent means |
|------|--------------|
| `boundary` | `[true, true, true]` — periodic on every axis |
| `origin` | `[0, 0, 0]` — cell anchored at the coordinate origin |
| `cell_defined` | `true` — the cell is geometrically defined |

`cell_defined` is an optional boolean on the box. It is **not** periodicity:
`boundary` says which axes wrap, `cell_defined` says whether there is a cell at
all. A free-boundary system with a real bounding cell stays *defined*; only a box
with no meaningful cell — the identity matrix carried so that geometry operations
degrade to no-ops — sets the flag `false`. A writer emits it **only when it is
`false`**, because every store written before the flag existed carries a defined
cell and absent must keep meaning `true`.

In the reference Zarr binding, `vectors` and `origin` are arrays under the `box`
group while `boundary` and `cell_defined` are attributes of that group. A
[trajectory](trajectory.md#the-cell)'s `box/` section is the same cell, indexed:
`vectors`, `origin` and `boundary` become per-update arrays with a leading update
axis, and `cell_defined` stays an attribute of the section.

## Volumetric data

A volumetric field is a block with structural shape `[nx, ny, nz]` (see
[Types](types.md#block-structural-shape)); each scalar field is a float column of
shape `[nx][ny][nz]`. The cell is the frame's box — a volumetric block carries no
cell of its own.

## Trajectory sections

A [trajectory](trajectory.md) does not repeat a frame's structure per step. The
same block and column names above are used, one group per block, holding the rows
that block contributed across the run: a `step_index` of the frame ordinals at
which the block changed, an `offset` row pointer marking each update's row range,
and the columns themselves with a leading `total_rows` axis. `step` (int) and the
optional `time` (float) are aligned to the frame order.

The naming conventions do not change with the section — an `atoms` block under
`trajectory/` carries the same `x`/`y`/`z`, `element`, `charge` columns it
carries under `frame/`. What changes is only how often a section is written:
once per **change**, not once per step. Rules and resolution:
[Trajectory](trajectory.md#reference-layout-zarr).
