# Force field

## Purpose

`forcefield/` is a record section: the Hamiltonian library this record uses.
It is a document plus one table per style. A record may be only `meta` and
`forcefield`. A system uses the library through type labels
([Conventions](conventions.md#particle-identity)); it does not embed a second
copy of the tables.

`method` does not select this section and does not hold the numbers.

Classical styles and, later, a model contribution are both children of this
section. A reader prices what is present.

## Layout

```text
forcefield/                         group attributes = the document
├── <category>.<style>/             one block per style
│   ├── name, itom, …               columns
│   └── _validity/<column>          absent parameters
└── models/
    └── <name>/                     one model contribution
        ├── (attributes)
        └── <tensor>                named arrays
```

The block name is `<category>.<style>`. `category` matches
`^[a-z][a-z0-9_]*$`. In `style`, every UTF-8 byte outside
`A–Z a–z 0–9 _ -` is `%XX` with uppercase hex. `lj/cut` is stored as
`pair.lj%2Fcut`. The logical name remains `(pair, lj/cut)`.

Column order is not significant. Missing parameters are validity masks
([Types](types.md#missing-values)). A default is not written into the cell.

## Document

```text
name: string                         # required
units: object                        # required — Units
special_bonds:                       # absent means not declared
  lj: [f64, f64, f64]                # 1-2, 1-3, 1-4
  coul: [f64, f64, f64]
styles:                              # ordered
  - category, style                  # required
    params: object                   # style-level numbers and strings
    endpoint_key: type | class | smirks    # absent means type
    expression, center, dims, source, defaults, arity, coordinate, order
```

`styles` lists each `(category, style)` once. An entry has a table. A table
with no entry is preserved and is not priced as a style.

`special_bonds` absent is not the evaluator default. That default, for an
implementation that needs one, is lj and coul both `[0, 0, 1]`. Writers do
not write the default back. Weights may be fractions, and lj may differ from
coul. Both are legal data.

`units` is [Units](units.md). Angle values (dimension exactly `A`) are
degrees. A negative angle dimension is per radian and is not converted with
the preset.

## Type tables

One row is one type.

| Columns | Role |
|---------|------|
| `name` | string, unique in the table. The label a system row's `type` carries |
| `itom` … `mtom` | string endpoints. Count is the category arity. Pair rows always have two; a self pair has `itom == jtom`. Empty string is the wildcard |
| `class`, `element`, `smarts`, `smirks`, `overrides`, `desc`, `doi` | string annotations. They do not price the row. OpenMM `def` is stored as `smarts` |
| `priority`, `layer` | optional integers from a Foyer `<Type>`. They do not price the row |
| `estimated` | bool |
| `estimate_penalty` | float |
| `estimate_method`, `estimate_analog` | string |
| other columns | parameters, or preserved extras |

For a built-in style, a column prices the row only when its name is in that
style's parameter list. Any other column is kept and is not compared as a
parameter.

`endpoint_key` is `type` (the default), `class`, or `smirks`. `class`
requires a `class` column on the atom table. `smirks` has no endpoint
columns and a non-empty `smirks` column. The compiled key on the system is
still the `type` string. The endpoints are how a typifier chooses that
string.

Within one category, type names of styles whose source is `type_rows` do
not repeat. A per-instance style does not take part in that set. Its type
table may be empty; the named parameters sit on the system's interaction
rows.

A pair table holds at most one row per unordered `{itom, jtom}`. Two rows
for the same pair with different parameter columns are invalid. The
comparison ignores `name`, annotations, and provenance.

An indexed family is stored as the author wrote it: `k1`, `periodicity1`,
`phase1`, contiguous from 1. `dihedral periodic` may also use the bare
names `k`, `periodicity`, `phase` for a single term. A round trip keeps the
spelling.

## Categories

| category | endpoints | system block | coordinate |
|----------|-----------|--------------|------------|
| `atom` | 0 | `atoms` | none |
| `bond` | 2 | `bonds` | distance `r` |
| `constraint` | 2 | `constraints` | none |
| `angle` | 3 | `angles` | angle `theta` |
| `dihedral` | 4 | `dihedrals` | dihedral `phi` |
| `improper` | 4 | `impropers` | improper; `chi = abs(phi)` where the style uses it |
| `pair` | 2 | neighbour pairs of `atoms.type` | distance `r` |
| `cmap` | 5 | `cmaps` | two dihedrals |
| `drude` | 2, ordered core then Drude | `drudes` | distance `r` |
| `virtual_site` | 0 | `virtual_sites` | none |

Bond, angle, and dihedral endpoints are reversible. Pair endpoints are
unordered. Improper endpoints are ordered, and the center atom is style
data:

| improper style | `center` (0-based) |
|----------------|--------------------|
| `harmonic`, `cvff`, `mmff_oop`, `uff_inversion` | 0 |
| `periodic` | 2 |

A built-in improper omits `center`; the table above is the value. Any other
improper states `center`. Topology rows are stored in that order.

A category outside this table states `arity`, `coordinate`
(`distance`, `angle`, `dihedral`, `improper`, `compound`, `none`), and
`order` (`reversible`, `ordered`, `unordered`) on the style entry.

## Built-in styles

Dimension letters: `E` energy, `L` length, `A` angle, `Q` charge, `M` mass,
`1` dimensionless. The formulas below use radians for `theta` and `phi`.
The style converts a parameter of dimension `A` from degrees. `k` in
`angle harmonic` is `E/A^2` and is already per radian squared.

Per-instance styles (`source: per_instance`) read these parameters from the
system rows. Coulomb styles read the atom charges. Their type tables may
be empty.

### atom, constraint, virtual site, drude

| style | parameters |
|-------|------------|
| `atom full` | `mass` `M`, `charge` `Q` |
| `constraint fixed` | `r0` `L` |
| `virtual_site average2` | `w1`, `w2` dimensionless. Position `w1 r_j + w2 r_k` |
| `virtual_site average3` | `w1`, `w2`, `w3`. Position `w1 r_j + w2 r_k + w3 r_l`. TIP4P uses `w1 = 1 − 2a`, `w2 = w3 = a` |
| `virtual_site outofplane3` | `w12`, `w13` dimensionless, `wcross` `1/L`. Position `r_j + w12 (r_k − r_j) + w13 (r_l − r_j) + wcross (r_k − r_j) × (r_l − r_j)` |
| `drude harmonic` | Spring `k r²` with `k` `E/L^2`. `alpha` `L^3` and `thole` are the polarizability and Thole parameter of the core, not extra terms in the spring |

### bond

| style | parameters | energy |
|-------|------------|--------|
| `harmonic` | `k` `E/L^2`, `r0` `L` | `k (r − r0)²` |
| `morse` | `d0` `E`, `alpha` `1/L`, `r0` `L` | `d0 (1 − exp(−alpha (r − r0)))²` |
| `class2` | `r0` `L`, `k2` `E/L^2`, `k3` `E/L^3`, `k4` `E/L^4` | `k2 d² + k3 d³ + k4 d⁴`, `d = r − r0` |
| `mmff_bond` | `kb`, `r0` `L`, per instance | `½ · 143.9325 · kb · Δr² · (1 − 2 Δr + 7/3 Δr²)`. `kb` is the MMFF table number. The constant yields kcal/mol |
| `uff_bond` | `kb` `E/L^2`, `r0` `L` | `½ kb (r − r0)²`, RDKit UFF, in the record's energy unit |

### angle

| style | parameters | energy |
|-------|------------|--------|
| `harmonic` | `k` `E/A^2`, `theta0` `A` | `k (θ − θ0)²` |
| `charmm` | those, plus `k_ub` `E/L^2`, `r_ub` `L` | harmonic plus `k_ub (r13 − r_ub)²` |
| `class2` | `theta0` `A`, `k2` `E/A^2`, `k3` `E/A^3`, `k4` `E/A^4` | `k2 d² + k3 d³ + k4 d⁴`, `d = θ − θ0` |
| `mmff_angle` | `ka`, `theta0` `A`, `linear` | cubic: `½ · 143.9325 · ka · Δθ² · (1 − 0.4 Δθ)`. linear centre (`linear ≠ 0`): `143.9325 · ka · (1 + cos θ)`. Result is kcal/mol |
| `mmff_stbn` | `kba_ijk`, `kba_kji`, `r0_ij`, `r0_kj` `L`, `theta0` `A`, `linear` | `143.9325 (kba_ijk Δr_ij + kba_kji Δr_kj) Δθ`, kcal/mol |
| `uff_angle` | `ka` `E`, `order`, `c0`, `c1`, `c2` | UFF Fourier bend, RDKit form, in the record's energy unit. A stored `theta0` is metadata |

### dihedral

`phi` is the dihedral in radians.

| style | parameters | energy |
|-------|------------|--------|
| `periodic` | indexed `k` `E`, `periodicity` dimensionless, `phase` `A` (default 0) | sum of `k (1 + cos(n φ − phase))` |
| `charmm` | `k` `E`, `periodicity`, `phase` `A` (default 0), `w` dimensionless (default 0) | `k (1 + cos(n φ − phase))`. `w` is the 1–4 weight |
| `opls` | `k1`…`k4` `E`, default 0 | `½ (k1(1+cos φ) + k2(1−cos 2φ) + k3(1+cos 3φ) + k4(1−cos 4φ))` |
| `multi/harmonic` | `a1`…`a5` `E`, default 0 | `a1 + a2 c + a3 c² + a4 c³ + a5 c⁴`, `c = cos φ` |
| `nharmonic` | indexed `a` `E` (`a1`…) | the same polynomial, as many terms as stored |
| `harmonic` | `k` `E`, `sign` dimensionless, `periodicity` | `k (1 + sign · cos(n φ))` |
| `class2` | `k1` `E`, `phi1` `A`, and the same for 2 and 3; all default 0 | `Σ ki (1 − cos(i φ − phii))` |
| `rb` | `c0`…`c5` `E` | `c0 + c1 c + … + c5 c⁵`, `c = −cos φ` |
| `mmff_torsion` | `v1`, `v2`, `v3` `E` | `½ [v1(1 + cos φ) + v2(1 − cos 2φ) + v3(1 + cos 3φ)]`, per instance |
| `uff_torsion` | `V` `E`, `order`, `cosTerm` dimensionless | `V/2 [1 − cosTerm · cos(n φ)]`, RDKit form, per instance |

### improper

| style | parameters | energy |
|-------|------------|--------|
| `harmonic` | `k` `E/A^2`, `chi0` `A` (default 0) | `k (χ − χ0)²` |
| `cvff` | `k` `E`, `sign`, `periodicity` | `k (1 + sign · cos(n φ))` |
| `periodic` | `k` `E`, `periodicity`, `phase` `A` (default 0) | `k (1 + cos(n φ − phase))` |
| `mmff_oop` | `koop` | `½ · 143.9325 · koop · χ²`, χ the Wilson angle of bond I→L out of the plane (I, J, K). `koop` is the MMFF table number. The constant yields kcal/mol |
| `uff_inversion` | `K` `E`, `c0`, `c1`, `c2` dimensionless | `K [c0 + c1 cos ω + c2 cos 2ω]`, ω the angle of bond I→L to the plane (I, J, K) |

### cmap

`cmap charmm` has one parameter, `grid`, dimension `E`, shape `f64[T, N, N]`
with `N ≥ 2` the same for every row. φ is the leading axis. The origin of
the grid is −180° and the values are energies in `units`. The grid stores
values, not derivatives. Interpolation belongs to the style.

### pair

Style parameters sit on the style entry's `params`, not on each row.
`cutoff` defaults to infinity (no truncation) for `lj/cut`, `lj/class2`,
`buck`, and `morse`.

`lj/cut` also has `n` (default 12), `m` (default 6), and `shift`
(default 0). The unshifted energy is
`C ε ((σ/r)^n − (σ/r)^m)`, `C = n/(n−m) · (n/m)^(m/(n−m))`. `n = 12`,
`m = 6` is `4 ε ((σ/r)^12 − (σ/r)^6)`. `shift ≠ 0` subtracts the same
expression evaluated at `r = cutoff`, so the energy is zero at the cutoff.
Every pair style with a finite cutoff prices only `r < cutoff`.

`epsilon` combines by geometric mean. `sigma` combines by `mixing`:

| `mixing` | σ | ε |
|----------|---|---|
| `arithmetic` | `(σᵢ + σⱼ) / 2` | `√(εᵢ εⱼ)` |
| `geometric` | `√(σᵢ σⱼ)` | `√(εᵢ εⱼ)` |
| `sixthpower` | `(½ (σᵢ⁶ + σⱼ⁶))^(1/6)` | `2 √(εᵢ εⱼ) · σᵢ³ σⱼ³ / (σᵢ⁶ + σⱼ⁶)` |

The default is `arithmetic`, except `lj/class2`, whose default is
`sixthpower`. A cross row (`itom ≠ jtom`) replaces the combined pair.

| style | row parameters | energy |
|-------|----------------|--------|
| `lj/cut` | `epsilon` `E`, `sigma` `L` | above |
| `lj/class2` | `epsilon` `E`, `sigma` `L` | `ε (2 (σ/r)⁹ − 3 (σ/r)⁶)` |
| `buck` | `a` `E`, `rho` `L`, `c` `E·L⁶` | `a exp(−r/ρ) − c/r⁶` |
| `morse` | `d0` `E`, `alpha` `1/L`, `r0` `L` | `d0 ((1 − exp(−alpha (r − r0)))² − 1)` |
| `lj/charmm` | `epsilon`, `sigma`, `epsilon14` `E`, `sigma14` `L` | `4 ε ((σ/r)¹² − (σ/r)⁶) · S(r)`. `one_four` is `regular` (default) or `epsilon14` |
| `coul/cut` | per instance | `coulomb · q1 q2 / (dielectric (r + delta))`. `dielectric` defaults to 1, `delta` to 0 |
| `coul/charmm` | per instance | `coulomb · qᵢ qⱼ / (dielectric · r) · S(r)`. The force molrs evaluates is `(coulomb · qᵢ qⱼ / r²) · S(r)`, LAMMPS's switched force, not the gradient of that energy |
| `coul/long/pme` | per instance. Style params `coulomb`, `cutoff` `L`, `alpha` `1/L`, `order`, `grid_x`, `grid_y`, `grid_z` | Ewald sum of `coulomb · qᵢ qⱼ / r` on the frame's periodic box: real-space `erfc(α r)`, reciprocal mesh of B-spline order `order` on `grid_*`, plus the self term. The kernel tallies energy and forces and does not tally a virial |
| `thole` | `charge` `Q`, `alpha` `L^3`, `damp` (`a`) dimensionless | `T(r) · qᵢ qⱼ / r`, `T = 1 − (1 + s r / 2) exp(−s r)`, `s = ½ (aᵢ + aⱼ) / (αᵢ αⱼ)^(1/6)`. This screen multiplies `qᵢ qⱼ / r`; it does not include `coulomb` |
| `coul/tt` | `charge` `Q`. Style params `b` `1/L` (default 4.5), `c` (default 1), `order` `n` (default 4) | `fₙ(r) · qᵢ qⱼ / r`, `fₙ = 1 − c exp(−b r) Σ_{k=0}^{n} (b r)^k / k!` |
| `uff_lj` | `x1` `L`, `D1` `E` | UFF Lennard-Jones in the record's energy unit, per instance |
| `mmff_vdw` | `alpha` `L³`, `n_eff`, `a_i`, `g_i`, `da` (default 0, neither donor nor acceptor) | MMFF buffered 14–7. Style params `B` 0.2, `Beta` 12, `DARAD` 0.8, `DAEPS` 0.5. The energy is the MMFF vdW term and, like the other MMFF kernels, is in kcal/mol |

The CHARMM switch `S(r)` is 1 for `r ≤ inner`, 0 for `r ≥ cutoff`, and
between them

```text
S(r) = (cutoff² − r²)² (cutoff² + 2 r² − 3 inner²) / (cutoff² − inner²)³
```

MMFF bonded styles (`mmff_bond`, `mmff_angle`, `mmff_stbn`, `mmff_oop`)
and `mmff_vdw` store the published MMFF numbers. The bonded kernels
multiply by 143.9325, and that product is kcal/mol. A force field that
uses them declares `units.preset = real`. The registered dimension `E` on
those parameters is not a licence to rescale `kb` into eV and still run
the kernel.

MMFF electrostatics is not a separate style. It is `pair coul/cut` with
`coulomb = 332.0716`, `dielectric = 1`, `delta = 0.05` Å. The 1–4 Coulomb
weight is 0.75 and the 1–4 van der Waals weight is 1. Both belong in
`special_bonds`, not in the vdW kernel.

A stated `coulomb` overrides the preset's Coulomb constant. The record
keeps the stated value.

`params.special` on a pair style is `lj` or `coul` when the style is
scaled by only one of the two `special_bonds` rows. The built-in Lennard-Jones
styles use `lj`. The built-in Coulomb styles use `coul`.

## Linking

| system column | points at |
|---------------|-----------|
| `atoms.type` | `atom` table `name`, and the atom-type labels in pair endpoints |
| `bonds.type`, and the same on angles, dihedrals, impropers, cmaps, constraints | that category's table `name` |
| `pairs` columns `epsilon`, `sigma`, `lj_scale`, `coul_scale`, `charge_product` | one pair exception. An empty cell (validity false) uses the force field |

Pair exceptions are not a `pair14` category. A reader preserves a `pair14`
table it finds and does not write a new one.

Charge and mass: `frame` atoms, then `system` atoms, then the `atom full`
row.

## Models

A model contribution is not a style table. It lives at `forcefield/models/<name>/`.

Attributes:

| key | meaning |
|-----|---------|
| `architecture` | model family (`mace`, `nequip`, `deepmd`, …) |
| `cutoff` | neighbor cutoff. Length unit is `length_unit`, or else `forcefield.units` length |
| `length_unit` | optional, when positions the model expects are not the force field's length |
| `species` | atomic numbers (`u64`) or element symbols the model accepts, in the order of `energy_shifts` |
| `energy_shifts` | optional `f64` array, one isolated-atom energy per species, in `energy_unit` |
| `energy_unit` | unit of the model output, when it is not `forcefield.units` energy |
| `output` | `atomic_energy` or `total_energy` |
| `forces` | `gradient` when the forces are the gradient of that energy |

The weights are named arrays under the group, each with its own shape and
dtype. The record does not store a neighbor list or a message-passing
graph. Species match `atoms.atomic_number` (`u64`) or `atoms.element`.
The classical styles, when present, and the model are separate
contributions. Add them only after both energies are in one unit.

## A style outside the tables

A style this chapter does not list carries:

- `dims` — parameter name to a dimension spelling (`E/L^2`, `A`, `1`, …)
- `source` — `type_rows` or `per_instance`
- `expression`, when a reader without this style's kernel should price it.
  The expression's coordinates are `r`, `theta`, `phi`, and `chi`, in
  radians. Angle-valued parameters are still degrees in the table
- `defaults`, for parameters the table may omit
- `arity`, `coordinate`, and `order`, when the category is not in the
  category table
- `center`, when it is an improper and not in the center table

A built-in style does not repeat `expression` or `dims`. The tables above
are those values.

## Not stored

Compiled pair lists, CMAP derivatives, and a kernel binary are not part of
the section. `materialize_one_four` output is not written back onto the
type tables. Engine command lines are not the record.

## See also

- [Units](units.md)
- [Engines](engines.md) — LAMMPS data and OpenMM XML
- [System](system.md)
- [Storage](storage.md)
