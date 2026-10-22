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
| `x`, `y`, `z` | `f64` | Cartesian coordinates |
| `xyz` | `f64` `[count][3]` | packed Cartesian coordinates |
| `vx`, `vy`, `vz` | `f64` | Cartesian velocity components |
| `id` | `u64` | stable per-atom identifier |
| `element` | string | element symbol (e.g. `"C"`) |
| `type` | string | force-field / atom type label |
| `type_id` | `u64` | optional engine integer for that label. Absent means the numbering in [Engines](engines.md#type-numbers) |
| `name` | string | atom name (e.g. `"CA"`) |
| `charge` | `f64` | partial charge |
| `mass` | `f64` | atomic mass |
| `mol_id` | `i64` | molecule grouping |
| `res_id`, `res_name` | `i64`, string | residue grouping |
| `bead_type` | string | coarse-grained bead type |

Coordinates may be stored as split `x`/`y`/`z` **or** packed `xyz`; a reader does
not synthesize one from the other. Continuous quantities (`x`/`y`/`z`,
`vx`/`vy`/`vz`, `charge`, `mass`, `order`) are `f64`: a value written as an
integer is stored as `f64` so a later fractional write is accepted.

## Relations

Tuple blocks (`bonds`, `angles`, `dihedrals`) reference atoms by 0-indexed
endpoints, one column per position:

| Column | Position |
|--------|----------|
| `atomi` | 1st endpoint |
| `atomj` | 2nd endpoint |
| `atomk` | 3rd endpoint |
| `atoml` | 4th endpoint |

The same blocks may carry `type` (string) and `type_id` (`u64`). Numbering
is [Engines](engines.md#type-numbers).

Endpoints are `u64`, indexing into **that section's** `atoms` block, 0-based.
An index past the block's count is invalid. A missing endpoint, where a row
may name fewer atoms, is a validity mask on that column
([Types](types.md#missing-values)), not a sentinel index. The block's count
is the number of relations. Per-relation properties (e.g. `order`) are
aligned columns.

The same positions on `impropers` and `cmaps` use `atomi`…`atoml`, and
`cmaps` adds `atomm` for the fifth endpoint.

## Particle identity

Row order is the identity of a particle **inside one section**. Across
`system`, `frame`, and `trajectory`, the join is:

1. If no `atoms` block in the record has an `id` column, row `i` is the same
   particle in every section, and every `atoms` block has the same count.
2. If any `atoms` block has `id`, every `atoms` block has `id`, the values
   are unique inside each block, and the join is `id`. A frame or trajectory
   frame may contain a subset of the system's ids. Its endpoint columns
   index **its own** `atoms` rows.
3. A trajectory whose frames do not all have the same atom count uses rule 2.
   A packed frame's mask marks rows inactive. It does not renumber `id`.

Topology blocks (`bonds`, `angles`, `dihedrals`, `impropers`, `cmaps`,
`constraints`) on a frame are the topology of that frame. `system` is the
topology used when the frame omits those blocks. A trajectory frame may
therefore carry a different bond set from the system — a reactive step —
by writing the blocks. Omitting them means "use the system". When `system`
is absent, each frame carries the topology it needs.

`frame` and `trajectory` may both be present. `frame` is one snapshot. It is
not defined to be the last trajectory frame. A producer that wants that
writes the same particles in both.

`atoms.charge` on `frame` overrides `atoms.charge` on `system`, which
overrides a charge on the force-field atom type. The same order applies to
`mass`.

## Box

The simulation cell is the frame's `box` (see [Frame](frame.md#box)): a triclinic
cell whose `vectors` columns are lattice vectors, with an origin and per-axis
periodic boundary flags. A LAMMPS data file uses a restricted orientation of
this same matrix; see [Engines](engines.md#lammps-data).

## Volumetric data

A volumetric field is a block whose `structural_shape` is the voxel count
along each axis, rank 1 or more, product equal to `count`. Each field is a
flat column of length `count`. `structural_shape` is how that column
unflattens, row-major: index `(i, j, k)` for shape `[n0, n1, n2]` is
`i·n1·n2 + j·n2 + k`. The column's own shape is `[count]`, not
`[n0, n1, n2]`.

The block states `sample`:

| `sample` | The value at index `i` sits at |
|----------|--------------------------------|
| `corner` | `origin + vectors @ i` — a Gaussian cube node |
| `center` | `origin + vectors @ (i + ½)` — a molrs density voxel centre |

`sample` is required when `structural_shape` is present. It is not inferred.

The voxel edges are the block's mesh, `<block>/_mesh/`:

| Array or attribute | Meaning |
|--------------------|---------|
| `origin`, `f64[ndim]` | Corner of voxel 0 |
| `vectors`, `f64[ndim][ndim]` | Columns are the edge of one voxel along each axis |
| `boundary`, optional `bool[ndim]` | Periodicity of each grid axis |
| `unit`, optional string | Length unit of `origin` and `vectors`, when it differs from `meta.units` length |

This is molrs `RegularGrid`: voxel `i` spans `origin + Σ (i_d + t_d) · edge_d`
for `t_d ∈ [0, 1)`. `_mesh` is not a column name.

With no mesh, the grid is the frame box divided into those voxels, as
`RegularGrid::over_box`: `origin` is the box origin, column `d` of `vectors`
is box column `d` divided by `n_d`, and `boundary` is the box boundary. The
box rank must equal `structural_shape`'s rank. With neither a mesh nor a
box, the block has index space only.

## Trajectory packing

A [trajectory](trajectory.md) may store its frames packed: per-block arrays
with a leading time axis (e.g. `atoms/x` of shape `[nstep][count]`), plus aligned
`step` (`i64`) and `time` (`f64`) index arrays. `time` uses the record's time
unit ([Units](units.md)). Packed storage is a convention; the
logical meaning is still an ordered list of frames.
