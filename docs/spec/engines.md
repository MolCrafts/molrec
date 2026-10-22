# Engines

## Purpose

A molrec record is the form a LAMMPS data file and an OpenMM
`<ForceField>` XML both convert to. Writers read that record back out.
The conversions below are the whole mapping: factors, indices, and the
fields each file cannot hold.

The record keeps the force-field IR units ([Units](units.md), preset
`real` unless the file was already in another preset). It does not keep
the source file's factor convention (OpenMM's hidden ½, radians, nm).

## Type numbers

LAMMPS data numbers types. The record stores the label in `type` (string).
`type_id` (`u64`), when present on a block, is that file's integer, and
the label for id `n` is the `type` on the rows with that `type_id`.

When `type_id` is absent, the integers are assigned:

1. Every label in the block is an integer string (`"2"`, `"10"`): the id
   is that integer. `"2"` comes before `"10"`. Id `0` is invalid.
2. Otherwise ids are `1…` in byte order of the labels.

Labels no row uses are still numbered when the block's metadata carries
an inventory `{"1": "C", "2": "H"}` under the key `<block>_type_labels`
(`atoms_type_labels`, and the same for `bonds`, `angles`, `dihedrals`,
`impropers`, `cmaps`). A data-file writer emits a `* Type Labels` section
from this numbering. Two writers that follow this rule emit the same ids.

A `drudes` row is a LAMMPS bond: the writer numbers it in the bond id
space, after the `bonds` rows, and writes `bond harmonic` with `K = k`
and `r0 = 0`. The record keeps the `drude harmonic` row; it does not
rewrite it into `bonds` on the way in.

## LAMMPS data

A data file is one snapshot plus the coefficient sections its types use.

| Data file | Record |
|-----------|--------|
| `Atoms` coordinates, charge | `frame` or `system` `atoms` `x` `y` `z` `charge` |
| molecule id (`atom_style full`) | `mol_id`. Absent on write means `0` |
| atom type | `type` / `type_id` as above |
| `Masses` | `atom full` row `mass`, else `atoms.mass` |
| `Velocities` | `vx` `vy` `vz` |
| `Bonds`, `Angles`, `Dihedrals`, `Impropers` | the block of that name. File indices are 1-based; the record is 0-based |
| `Bond Coeffs`, `Angle Coeffs`, `Dihedral Coeffs`, `Improper Coeffs`, `Pair Coeffs` | the style table whose LAMMPS style has that header. Several styles in one category are one `hybrid` section, the sub-style named on the row |
| `PairIJ Coeffs` | explicit pair cross rows (`itom ≠ jtom`) |
| `special_bonds` | `forcefield` document `special_bonds` |

`pair lj/cut` together with `pair coul/cut` is written as one
`pair_style lj/cut/coul/cut`, so geometric mixing still applies. Written
as `hybrid` with a `pair_coeff * * coul/cut` wildcard, every cross pair
becomes explicit and mixing stops. `lj/charmm` together with
`coul/charmm` is `pair_style lj/charmm/coul/charmm`.

`dihedral periodic` is LAMMPS `fourier`. One-term `improper periodic` at
phase 0° or 180° is LAMMPS `cvff` with `d = cos(phase)`. The stored
endpoint order is unchanged.

`cmap charmm` is a `fix cmap` file, not a `* Coeffs` section. The grid in
the record is already φ-major from −180°.

The box in a data file is restricted triclinic. With columns of `vectors`
as the lattice vectors:

```text
a = (lx,  0,  0)
b = (xy, ly,  0)
c = (xz, yz, lz)
```

`lx`, `ly`, `lz` are the orthogonal edge components, not the Euclidean
lengths of `a`, `b`, `c`. `xlo xhi` is `origin_x` and `origin_x + lx`,
and the same for y and z. A reader stores this matrix and this origin.
A writer emits it when the box already has that shape (`a` along +x, `b`
in the xy plane, `lx`, `ly`, `lz` positive). A box in any other
orientation is rotated into this shape, and the coordinates are rotated
with it, before the file is written.

These have no data-file form. The record keeps them; a LAMMPS writer
refuses the file instead of dropping them:

- `virtual_sites`. TIP4P in LAMMPS is a `*/tip4p/*` pair style on a
  three-site water, the M charge put back on O.
- per-pair override columns on `pairs` (`epsilon`, `sigma`, `lj_scale`,
  `coul_scale`, `charge_product`).
- a non-zero class2 cross term (`bb`, `ba`, `mbt`, `ebt`, `at`, `aat`,
  `bb13`). The diagonal class2 term is the style the record stores.
- `one_four = epsilon14`. LAMMPS prices a 1–4 pair at the ordinary
  `epsilon` / `sigma`.

## OpenMM XML

An OpenMM `<ForceField>` is nm, kJ/mol, radians, and a harmonic energy
carries a factor ½. The record is Å, kcal/mol, degrees, and the IR
energies in [Force field](forcefield.md) (no hidden ½). `4.184` kJ = 1
kcal. `1 nm = 10 Å`.

| OpenMM | Record | Factor |
|--------|--------|--------|
| `<Bond length k>` | `bond harmonic` `r0`, `k` | `r0 = 10 length`. `k_record = k / (2 × 4.184 × 100)` |
| `<Angle angle k>` | `angle harmonic` `theta0`, `k` | `theta0` in degrees. `k_record = k / (2 × 4.184)` |
| `<UreyBradley k d>` | `angle charmm` `k_ub`, `r_ub`, joined to the angle row of the same three labels | `k_ub = k / 4.184`, `r_ub = 10 d`. No angle row: the angle `k` is 0 |
| `<Proper>` periodic `k periodicity phase` | `dihedral periodic` | `k / 4.184`, phase in degrees |
| `<Proper c0..c3>` | `dihedral opls` | `k_n = c_{n−1} / 4.184` |
| `<RBTorsionForce><Proper c0..c5>` | `dihedral nharmonic` (`c5` present) or `multi/harmonic` (`c5` absent) | `a_{n+1} = (−1)^n C_n / 4.184` |
| `<Improper>` of `<PeriodicTorsionForce>` | `improper periodic`, one term, XML order | `k / 4.184`. Center is endpoint 2 |
| `<CustomTorsionForce energy="k*(abs(theta)-theta0)^2">` `<Improper>` | `improper harmonic` | `k / 4.184`, `chi0` in degrees |
| `<Map>` of size `N×N`, `N` even | `cmap charmm` `grid` | OpenMM `energy[i + N j]` at `(φ, ψ) = (2πi/N, 2πj/N)` is `grid[(i + N/2) mod N][(j + N/2) mod N] / 4.184` |
| `<NonbondedForce coulomb14scale lj14scale>` | `pair lj/cut` + `pair coul/cut`, charge on `atom full` | `sigma × 10`, `epsilon / 4.184`. `special_bonds` is `[0, 0, scale]` for lj and coul separately |
| `<LennardJonesForce>` with `sigma14` / `epsilon14` or `<NBFixPair>` | `pair lj/charmm` + `pair coul/charmm` | same length and energy factors. `one_four = epsilon14` when a 1–4 σ or ε differs from the regular pair |

`combining_rule` on the `<ForceField>` root, or the writer's
geometric-mixing `<Script>`, is the pair style's `mixing`. Absent means
`arithmetic`, which is OpenMM's default.

Every Coulomb style read from OpenMM states `coulomb = 332.06371329919216`
kcal·Å/(mol·e²), OpenMM's `ONE_4PI_EPS0` (138.93545764438198 kJ·nm) after
the unit change. That is not LAMMPS `real`'s 332.06371. The record keeps
the OpenMM value so the electrostatics match OpenMM. A writer puts OpenMM's
constant back and does not write `coulomb` into the XML.

`<AtomTypes><Type name class element mass def overrides>` is an `atom full`
row: `name` is the type name, `class`, `element`, `smarts` (`def`),
`overrides`, plus `mass`. `priority` and `layer` are the optional integer
columns of that name. Bonded rows key on `class1…` or `type1…`; an empty
attribute is the wildcard `""`, and `endpoint_key` records which vocabulary
the table uses.

`<Residues>` and `<Patches>` are topology templates, not parameters. The
molrec `system` (`element`, `name`, `res_name`, `res_id`, bonds) is the
topology those templates would have built. A reader does not require the
templates when `system` is present. A writer that must emit them groups
atoms by `res_name` and uses `name` as the template atom name.

OpenMM cutoffs and switching are `createSystem` arguments, not file
values. A field read from XML has no `cutoff` and no `inner`. The caller
sets them on the style params before a run.

These XML forms are refused, because they do not map onto one IR style:

- `<Script>` other than the geometric-mixing script
- `Custom*Force` other than the harmonic improper above
- `<RBTorsionForce><Improper>`, a multi-term periodic improper
- `ordering="smirnoff"`
- an odd CMAP period
- a Urey–Bradley row with a wildcard
- an `<NBFixPair>` of a type with itself
- a `<NonbondedForce>` with non-zero `epsilon` beside a `<LennardJonesForce>`
- AMOEBA multipoles, GBSA, and Drude forces

A record that holds those as IR styles (`drude harmonic`, a SMIRKS table
with `endpoint_key = smirks`) is still valid. The OpenMM writer refuses
them by name rather than emitting a force OpenMM will not build.

## See also

- [Force field](forcefield.md)
- [Units](units.md)
- [Conventions](conventions.md)
