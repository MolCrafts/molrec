# Force field

The `forcefield` section holds the parameters that *define* the energy model
of the record's particles: atom types, bonded and non-bonded styles, their
per-type tables, the unit system those numbers are in, and the 1-2 / 1-3 /
1-4 scaling. It is a peer of `meta`, `system` and `trajectory` at the
[root](overview.md). How a job *used* the model (engine, cutoff schedule,
thermostat) is [`method`](method.md); which particle carries which type is
[`system`](system.md).

`forcefield` is **frame-shaped**: a JSON document stored as the group's
attributes, plus one [block](frame.md#column-block-and-frame) per style. A
reader that knows nothing of force fields reads it with the frame codec and
loses nothing.

```text
forcefield
 +-- name: string[]
 +-- units
 |    +-- (preset: string[])
 |    +-- (length | energy | angle | charge | mass | time: string[])
 +-- (source)
 |    +-- format: string[]
 |    +-- (uri: string[])
 |    +-- (sha256: string[])
 +-- (special_bonds)
 |    +-- lj: f64[3]
 |    +-- coul: f64[3]
 +-- styles: [{category, style, (params), (expression), (endpoint_key)}, ...]
 \-- <category>.<style>             one block per entry of styles
      \-- name: string[T]
      \-- (itom | jtom | ktom | ltom | mtom: string[T])
      \-- (<annotation>: string[T])
      \-- (<param>: f64[T] | string[T])
      \-- (grid: f64[T, N, N])          a cmap table only
      \-- (_validity)
```

A record whose only substantive section is `forcefield` is valid: it is a
force-field package.

## The document

The group's attribute map is exactly the force-field document. Keys other
than those below are preserved by every reader.

`name`

Required. The force field's name (`"OPLS-AA"`, `"GAFF2"`, `"openff-2.1.0"`).

`units`

Required. The unit of every number in the section, by quantity. Every
parameter in a style table and every style-level parameter is a number in
these units, and a reader **MUST NOT** convert it on read. A writer that
translates a file states the file's own units here rather than converting
them, except for angle values, which are degrees ([Format
mappings](#format-mappings)).

| Key | Quantity | Example |
|-----|----------|---------|
| `length` | lengths, and the length part of every derived unit | `angstrom`, `nm` |
| `energy` | energies, and the energy part of every derived unit | `kcal/mol`, `kJ/mol`, `eV` |
| `angle` | angle **values**: equilibrium angles (`theta0`, `chi0`) and phases (`phase`, `phase<m>`, `phi1`…) | `degree` |
| `charge` | charges | `e` |
| `mass` | masses | `dalton` |
| `time` | times (rarely present) | `fs` |

A unit string is parseable by [pint](https://pint.readthedocs.io). A derived
dimension (a bond force constant, `energy/length²`) is composed from these;
it has no key of its own. `angle` is the unit of angle values only, never of
a force constant: a force constant is per **radian**ⁿ whatever `angle` says
(`angle.harmonic`'s `k` is energy/rad²), as in LAMMPS.

`preset` names a unit system instead of listing it. The presets are:

| Preset | length | energy | angle | charge | mass | time |
|--------|--------|--------|-------|--------|------|------|
| `real` | `angstrom` | `kcal/mol` | `degree` | `e` | `dalton` | `fs` |
| `metal` | `angstrom` | `eV` | `degree` | `e` | `dalton` | `ps` |
| `si` | `m` | `J` | `degree` | `C` | `kg` | `s` |
| `cgs` | `cm` | `erg` | `degree` | `statcoulomb` | `g` | `s` |
| `electron` | `bohr` | `hartree` | `degree` | `e` | `dalton` | `fs` |
| `micro` | `micrometer` | `picogram * micrometer**2 / microsecond**2` | `degree` | `picocoulomb` | `picogram` | `microsecond` |
| `nano` | `nm` | `attogram * nm**2 / ns**2` | `degree` | `e` | `attogram` | `ns` |
| `lj` | — | — | `degree` | — | — | — |

The presets are those of the LAMMPS `units` command, and so is their angle:
LAMMPS writes every angle value in degrees, so every preset's angle is the
`degree`. `lj` is reduced units: no quantity but `angle` has a unit, and the
numbers are in the reduced scale of the producer's choosing.

`units` **MUST** carry `preset` or at least one quantity. When both a preset
and a quantity are present they **MUST** agree (pint-equivalent strings); a
reader refuses a document where they do not. So `"angle": "radian"` beside a
preset is refused: a section that states it holds radian angles (a writer of
the earlier radian convention stated it so), and reading them as the preset's
degrees would be wrong. A style whose parameters need a
quantity that `units` does not resolve is not refused on read; a validator
**SHOULD** report it.

`source`

Optional provenance of the parameters: `format` (`"openmm-xml"`, `"offxml"`,
`"gromacs-top"`, `"lammps"`, `"amber-frcmod"`, …), `uri`, and `sha256` (64
lowercase hex digits) of the source file's bytes.

`special_bonds`

Optional. The scale applied to non-bonded interactions between atoms that are
1-2, 1-3 and 1-4 neighbours through bonds: `lj` for the van-der-Waals styles,
`coul` for the electrostatic ones, each `[w12, w13, w14]`. `0` excludes the
class, `1` leaves it at full strength. Pairs further apart are at full
strength. Absent means the force field declares no weights; a consumer
supplies its own default and **SHOULD** say so. Which weight set a pair style
takes is its registry entry's *special class* ([Style registry](#style-registry)).

`styles`

Required (it may be empty). An ordered list; each entry is one style:

| Field | Required | Meaning |
|-------|----------|---------|
| `category` | yes | what the style's rows parameterize ([Categories](#categories)); matches `^[a-z][a-z0-9_]*$` |
| `style` | yes | the functional form's name within its category (`harmonic`, `lj/cut`); non-empty UTF-8 |
| `params` | no | style-level parameters: a map of name to a finite number or a string (`cutoff`, `mixing`) |
| `expression` | no | the energy expression ([Expressions](#expressions)) |
| `endpoint_key` | no | `"type"` (default), `"class"` or `"smirks"`: what a row's endpoints name ([Endpoints](#endpoints)) |

A `(category, style)` pair appears at most once. Order is preserved; it
carries no physical meaning. Every entry has exactly one table, at the block
name below, even when the table has no rows.

Two style-level parameter names are reserved on pair styles. `params.special`
(`"lj"` or `"coul"`) gives an unregistered pair style its special class.
`params.mixing` on a van-der-Waals pair style is its combining rule:
`arithmetic` (Lorentz–Berthelot: σ = ½(σᵢ+σⱼ), ε = √(εᵢεⱼ)), `geometric`
(σ = √(σᵢσⱼ), ε = √(εᵢεⱼ)) or `sixthpower` (σ⁶ = ½(σᵢ⁶+σⱼ⁶),
ε = 2√(εᵢεⱼ)σᵢ³σⱼ³/(σᵢ⁶+σⱼ⁶)). Absent means the style declares none.

## Style tables

### Block name

A style's table is the block named

```text
<category> "." <encoded style>
```

where the encoded style is the style's UTF-8 bytes with every byte outside
`A–Z a–z 0–9 - _` written as `%` and two uppercase hex digits. So
`bond/harmonic` lives at `bond.harmonic` and `pair/lj/cut/coul/long` at
`pair.lj%2Fcut%2Fcoul%2Flong`. Decoding splits at the first `.` and
percent-decodes the rest. A reader resolves a style's table by this name; a
block whose name no style entry produces is preserved as unknown content.

### Rows and columns

A table has one row per type. Its count is the number of types. It carries
no structural shape.

`name`

Required, `string`, never null, unique within the table. The label a system
row names ([Linking a system](#linking-a-system)). Any UTF-8 string; it is
never parsed into endpoints.

`itom`, `jtom`, `ktom`, `ltom`, `mtom`

The endpoints, `string`, never null: the first *arity* of them, in this
order, and no others ([Categories](#categories)). A pair row always carries
both `itom` and `jtom`; a self pair has `itom == jtom`, and a row with
`itom ≠ jtom` is a *cross row* (CHARMM NBFIX, AMBER off-diagonal ACOEF/BCOEF,
GROMACS `[ nonbond_params ]`). [Linking a system](#linking-a-system), rule 3,
says what a cross row does and which pairs a table may restate.

Annotation columns, `string`, nullable:

| Column | Meaning |
|--------|---------|
| `class` | the atom class (OpenMM `class`, GROMACS `bond_type`); atom tables only |
| `element` | IUPAC symbol; atom tables only |
| `smarts` | a SMARTS pattern that assigns this type (foyer `def`) |
| `smirks` | a SMIRKS pattern that assigns this row (OpenFF) |
| `overrides` | comma-separated names of types this one takes precedence over |
| `desc` | free text |
| `doi` | a reference |

Parameter columns: every other column is one parameter, named as the style
names it (`k`, `r0`, `epsilon`, `periodicity2`), and is `f64` or `string`.
**No other dtype is admitted**, with one exception: a column whose name is a
[canonical key](conventions.md#canonical-dtypes) has that key's dtype, as it
does in every block (`atomic_number` is `u64`). An integer-valued parameter
that is not a canonical key (a periodicity) is an `f64`. A parameter a row
does not have is null in that row ([nullable columns](frame.md#nullable-columns)),
never a sentinel such as `0` or `NaN`. A column declares no
[precision](frame.md#declared-precision): parameters are stored exactly.
Every column of a table is one value per row (`[T]`, no trailing axes), with
one exception, `grid` on a `cmap` table (below); a style-level parameter is
always a scalar.

An atom table additionally recognises `mass` (`f64`, `units.mass`), `charge`
(`f64`, `units.charge`) and `atomic_number` (`u64`).

`grid`

On a `cmap` table only: the row's correction map, `f64[T, N, N]` — one
`N × N` grid of energies (`units.energy`) per row, `N ≥ 2`, one `N` for every
row of the table, laid out as LAMMPS `fix cmap` reads it
([CMAP](#cmap)): **φ-major**, the first trailing axis φ (the dihedral
`itom`–`jtom`–`ktom`–`ltom`), the second ψ (the dihedral
`jtom`–`ktom`–`ltom`–`mtom`), so `grid[a][b]` (flat index `a·N + b`) is the
correction at φ = −180° + a·360°/N, ψ = −180° + b·360°/N. It declares no
precision, and every value of a row that is not null is finite. A reader
**MUST** refuse a `cmap` grid of
another dtype or shape (one trailing axis, a non-square `N × M`, `N < 2`), a
non-finite value in a non-null row, and a column with trailing axes anywhere
else: another column of a `cmap` table, a `grid` of another category, any
column of an unknown category.

### Endpoints

`endpoint_key` says what the endpoint strings name:

- `"type"`: the `name` of a row of an atom table;
- `"class"`: the `class` of a row of an atom table (OpenMM bonded forces key
  on classes). Every atom table **MUST** then carry `class`;
- `"smirks"`: nothing. The table carries no endpoint columns; each row's
  `smirks` (required, never null) assigns it, and the arity is the number of
  mapped atoms in the pattern.

The empty string `""` is the **wildcard**: it matches any type or class.
GROMACS `X`, LAMMPS `*` and an absent OpenMM attribute become `""`.

When a consumer assigns rows to a topology by endpoints (typing, not
linking), a row matches a tuple of atom types when its endpoints equal the
tuple in order or reversed (an improper: in order only); among matching rows
the one with the fewest wildcards wins, and among those the first in table
order. A record that names its rows ([Linking a system](#linking-a-system))
needs none of this.

## Categories

| Category | Arity | Rows parameterize | System block |
|----------|-------|-------------------|--------------|
| `atom` | 0 | an atom type | `atoms` (`type`) |
| `bond` | 2 | a bond type | `bonds` |
| `angle` | 3 | an angle type; `jtom` the vertex | `angles` |
| `dihedral` | 4 | a proper torsion type | `dihedrals` |
| `improper` | 4 | an improper type | `impropers` |
| `pair` | 2 | a non-bonded pair of atom types | resolved through `atoms.type` |
| `constraint` | 2 | a constrained distance type | `constraints` |
| `virtual_site` | 0 | a virtual-site construction | `virtual_sites` |
| `drude` | 2 | a core–Drude pair type (`itom` core, `jtom` Drude) | `drudes` |
| `cmap` | 5 | a CMAP cross-term type over the two consecutive dihedrals `itom`…`ltom` and `jtom`…`mtom` (CHARMM φ/ψ); its `grid` is the correction | `cmaps` |

The system blocks are [standardized identifiers](conventions.md). A category
outside this table is legal and preserved; its arity is the number of
endpoint columns its table carries, which **MUST** be a prefix of `itom`,
`jtom`, `ktom`, `ltom`, `mtom`.

There is no `pair14` category. Per-type 1-4 parameters are the
`epsilon14` and `sigma14` of a `pair.lj/charmm` row, as in LAMMPS
([Style registry](#style-registry)); a pair's own 1-4 parameters or weights
are [pair overrides](#pair-overrides) on the system's `pairs` rows. A
`pair14` table an earlier writer laid down is a category outside this table,
preserved like any other.

## Linking a system

Types are linked **by name**. Each rule below is how a reader finds the
parameters of a system row:

1. `atoms.type` names a row of an atom table. A force field whose styles are
   all `smirks`-keyed has no atom table; `atoms.type` then names a row of its
   `pair` table.
2. A row of a relation block of category *c* (table above) names, in its
   `type` column, a row of a *c* table. If the block carries a `style` column
   (`string`), the row's table is `<c>.<style>`; otherwise every *c* table
   holding that name applies, and their energies add.
3. `pair` tables are resolved through atom types, not row names: for atoms
   of types *a* and *b*, the row whose endpoints are `{a, b}`, in either
   order. A cross row (`itom ≠ jtom`) therefore gives its pair its own
   parameters and overrides the style's `mixing` for that pair; a parameter
   a cross row leaves null is the `mixing` of that parameter, and `mixing`
   prices every parameter of the pairs no row names. A pair table **MUST
   NOT** hold two rows with the same unordered `{itom, jtom}` and different
   parameters: rows restating a pair, in either order, with equal values in
   every parameter column (null equal only to null; `name` and the
   annotation columns are not parameters) are one row, and a reader
   **MUST** refuse a table whose restatements differ. A cross row's `name`
   means nothing beyond its uniqueness in the table: it is not parsed, not
   derived from the endpoints, and no system row names it. A writer
   translating into a format that has no form for a cross row **MUST**
   refuse the row rather than write it as a self row of either endpoint.
   Failing a row, a `pair` style uses its `mixing` of the two self rows
   `{a, a}` and `{b, b}`. Every pair style of the force field applies to
   every non-excluded pair, weighted by `special_bonds` (`lj` or `coul` per
   the style's special class), except where the pair's `pairs` row
   overrides it (rule 4).
4. A relation block may carry a parameter column named as its style names
   it. Its value, where not null, is that row's parameter and overrides the
   table; a style whose table has no rows takes every parameter from the
   relation (a *per-instance* style, as MMFF and UFF are). The `pairs`
   block carries the [pair overrides](#pair-overrides), which override the
   pair styles for one pair of atoms.
5. `type_id`, where present, is a format-local ordinal and plays no part in
   linking.

A name that resolves to nothing is not a format error. A reader **MUST NOT**
refuse a record for it; a validator **SHOULD** report it. Two pair rows that
price one pair differently (rule 3) are a format error: the table cannot say
which applies.

### Pair overrides

A `pairs` row (`atomi`, `atomj`, and `is_14` for a 1-4 pair) may carry these
columns, each `f64` and nullable. A non-null cell overrides, for that one
pair of atoms, what the pair styles would give it; a null cell, or an absent
column, leaves the style's value:

| Column | Overrides |
|--------|-----------|
| `epsilon`, `sigma` | the Lennard-Jones parameters of the pair in every van-der-Waals pair style that has them (`lj/cut`, `lj/class2`, `lj/charmm`), in place of the style's row or its `mixing` |
| `charge_product` | qᵢqⱼ (`units.charge`²) of the pair in every electrostatic pair style, in place of the product of the atoms' charges |
| `lj_scale` | the weight of the pair's van-der-Waals energy, in place of the `special_bonds.lj` weight of its class |
| `coul_scale` | the weight of the pair's electrostatic energy, in place of the `special_bonds.coul` weight of its class |

An explicit parameter is final: it is used as given, never mixed or looked
up again. The weight still applies to it, and the weight is
`lj_scale` / `coul_scale` where the row states one and the `special_bonds`
weight of the pair's class otherwise; a stated scale replaces that weight,
it does not multiply it. So an OpenMM exception `(chargeProd, sigma,
epsilon)` is `charge_product`, `sigma`, `epsilon` with both scales `1`; a
GROMACS `[ pairs ]` funct-1 row with its own parameters is `sigma`,
`epsilon`, `lj_scale` `1`; an AMBER torsion whose `SCEE` / `SCNB` differ from
the force field's gives its 1-4 pair `coul_scale = 1/SCEE`,
`lj_scale = 1/SCNB`. An `exclusions` row excludes its pair whatever `pairs`
says. A `pairs` block names an unordered pair at most once; two rows that
name one pair with different overrides cannot say which applies, and a
validator **SHOULD** report them.

LAMMPS has no per-pair parameters or weights, so a writer to it (a data
file, a coefficient include) **MUST** refuse a frame whose `pairs` carry a
non-null override, rather than drop it; so does a writer to any other format
without a form for one.

## Style registry

A style named here **MUST** mean exactly this energy and these parameters.
A style not named here **SHOULD** carry an `expression`; a reader preserves it
either way.

The registry's conventions are LAMMPS's. For every style LAMMPS has, the
energy expression, its factors (no hidden ½), the parameters, their meanings
and their units are those of the LAMMPS style of the same name or the one the
row names, so a LAMMPS coefficient line is stored as written. Every other
source converts at its translator ([Format mappings](#format-mappings)),
never here. The names are LAMMPS's symbols lower-cased, except where LAMMPS
spells two things alike: a phase is `phase` (LAMMPS `d` of `dihedral charmm`,
`fourier`), a sign `sign` (`d` of `dihedral harmonic`, `improper cvff`), a
multiplicity `periodicity` (`n`).

Dimensions: *E* energy, *L* length, *deg* an angle value (`units.angle`,
the degree in every preset), *rad* the radian of a force constant (always
the radian, whatever `units.angle` is), *1* a pure number. θ is the angle at
`jtom`, φ the signed dihedral of the row's four atoms in the order listed
(`itom`…`ltom`; for a system row, `atomi`…`atoml`), χ = |φ|, *r* the
distance; the energy takes θ, φ and χ in radians, and an angle-valued
parameter enters it converted from degrees.

| Style | Energy | Per-type parameters | Style parameters |
|-------|--------|---------------------|------------------|
| `atom.full` | — | `mass`, `charge` | — |
| `bond.harmonic` | k·(r − r0)² | `k` E/L², `r0` L | — |
| `bond.morse` | d0·[1 − e^{−alpha·(r − r0)}]² | `d0` E, `alpha` 1/L, `r0` L | — |
| `bond.class2` | k2·Δ² + k3·Δ³ + k4·Δ⁴, Δ = r − r0 | `r0` L, `k2` E/L², `k3` E/L³, `k4` E/L⁴ | — |
| `angle.harmonic` | k·(θ − theta0)² | `k` E/rad², `theta0` deg | — |
| `angle.charmm` | k·(θ − theta0)² + k_ub·(r₁₃ − r_ub)², r₁₃ the `itom`–`ktom` distance (Urey–Bradley) | `k` E/rad², `theta0` deg, `k_ub` E/L², `r_ub` L | — |
| `angle.class2` | k2·Δ² + k3·Δ³ + k4·Δ⁴, Δ = θ − theta0 | `theta0` deg, `k2` E/rad², `k3` E/rad³, `k4` E/rad⁴ | — |
| `dihedral.periodic` | Σₘ kₘ·[1 + cos(nₘ·φ − γₘ)] | `k` E, `periodicity` 1, `phase` deg — or, per term m = 1, 2, …, `k<m>`, `periodicity<m>`, `phase<m>` | — |
| `dihedral.opls` | ½·[k1(1 + cos φ) + k2(1 − cos 2φ) + k3(1 + cos 3φ) + k4(1 − cos 4φ)] | `k1`…`k4` E | — |
| `dihedral.rb` | Σₙ₌₀⁵ cₙ·cosⁿ(φ − 180°) | `c0`…`c5` E | — |
| `dihedral.charmm` | k·[1 + cos(n·φ − γ)], and the 1-4 pair of its end atoms weighted by `w` (below) | `k` E, `periodicity` 1, `phase` deg, `w` 1 | — |
| `dihedral.harmonic` | k·[1 + sign·cos(n·φ)] | `k` E, `sign` 1 (±1), `periodicity` 1 | — |
| `dihedral.multi/harmonic` | Σₙ₌₁⁵ aₙ·cosⁿ⁻¹ φ | `a1`…`a5` E | — |
| `dihedral.class2` | Σₙ₌₁³ kₙ·[1 − cos(n·φ − phiₙ)] | `k1`, `phi1`, `k2`, `phi2`, `k3`, `phi3` (E, deg) | — |
| `improper.harmonic` | k·(χ − chi0)² | `k` E/rad², `chi0` deg | — |
| `improper.cvff` | k·[1 + sign·cos(n·φ)] | `k` E, `sign` 1 (±1), `periodicity` 1 | — |
| `improper.periodic` | k·[1 + cos(n·φ − γ)] | `k` E, `periodicity` 1, `phase` deg | — |
| `improper.trefoil` | ⅓·Σ over the three orderings of the outer atoms, central atom `jtom`, of the `dihedral.periodic` energy | as `dihedral.periodic` | — |
| `pair.lj/cut` | C·ε·[(σ/r)ⁿ − (σ/r)ᵐ], C = n/(n−m)·(n/m)^{m/(n−m)}, r < cutoff; n = 12, m = 6 gives 4ε[(σ/r)¹² − (σ/r)⁶] | `epsilon` E, `sigma` L | `cutoff` L, `mixing`, `n` 1, `m` 1, `shift` 1 (non-zero: shifted to 0 at cutoff) |
| `pair.lj/charmm` | 4ε[(σ/r)¹² − (σ/r)⁶], r < cutoff; the 1-4 pair a `dihedral.charmm` prices takes `epsilon14`, `sigma14` | `epsilon` E, `sigma` L, `epsilon14` E, `sigma14` L | `cutoff` L, `mixing` (absent: `arithmetic`) |
| `pair.lj/class2` | ε·[2(σ/r)⁹ − 3(σ/r)⁶] | `epsilon` E, `sigma` L | `cutoff` L, `mixing` |
| `pair.buck` | a·e^{−r/rho} − c/r⁶ | `a` E, `rho` L, `c` E·L⁶ | `cutoff` L |
| `pair.morse` | d0·[(1 − e^{−alpha(r − r0)})² − 1] | `d0` E, `alpha` 1/L, `r0` L | `cutoff` L |
| `pair.coul/cut` | coulomb·qᵢqⱼ / (dielectric·(r + delta)), r < cutoff | — (charges from `atoms.charge`) | `coulomb` E·L/Q², `dielectric` 1, `delta` L, `cutoff` L |
| `pair.coul/long/pme` | Ewald-summed coulomb·qᵢqⱼ/r (particle-mesh) | — (charges from `atoms.charge`) | `coulomb` E·L/Q², `cutoff` L, `alpha` 1/L, `order` 1, `grid_x`, `grid_y`, `grid_z` 1 |
| `pair.thole` | T(r)·C·qᵢqⱼ/r, T = 1 − (1 + s·r/2)·e^{−s·r}, s = ½(dampᵢ + dampⱼ)/(alphaᵢ·alphaⱼ)^{1/6}, C the Coulomb constant of `units` | `charge` Q, `alpha` L³, `damp` 1 | — |
| `constraint.fixed` | \|rᵢ − rⱼ\| = r0 | `r0` L | — |
| `virtual_site.average2` | x = w1·x_j + w2·x_k | `w1`, `w2` 1 | — |
| `virtual_site.average3` | x = w1·x_j + w2·x_k + w3·x_l | `w1`, `w2`, `w3` 1 | — |
| `virtual_site.outofplane3` | x = x_j + w12·r_jk + w13·r_jl + wcross·(r_jk × r_jl) | `w12`, `w13` 1, `wcross` 1/L | — |
| `drude.harmonic` | k·\|r_core − r_drude\|² (LAMMPS's harmonic core–Drude bond: k is half the Drude spring constant); polarizability alpha; Thole screening thole | `k` E/L², `alpha` L³, `thole` 1 | — |
| `cmap.charmm` | the map `grid` at (φ, ψ), interpolated as LAMMPS `fix cmap` does ([CMAP](#cmap)) | `grid` E (N × N) | — |

Special classes: `pair.lj/cut`, `pair.lj/charmm`, `pair.lj/class2`,
`pair.buck`, `pair.morse` take `special_bonds.lj`; `pair.coul/cut`,
`pair.coul/long/pme` and `pair.thole` take `special_bonds.coul`. An
unregistered pair style takes `lj` unless its `params.special` is `"coul"`.

A `pair.lj/charmm` self row whose `epsilon14` or `sigma14` is null has the
row's `epsilon` or `sigma` there (LAMMPS's default), and `mixing` mixes
`epsilon14` and `sigma14` as it mixes `epsilon` and `sigma`. The style prices
every non-excluded pair with `epsilon` and `sigma`, weighted by
`special_bonds`, as LAMMPS `lj/charmm/coul/*` does; `epsilon14` and
`sigma14` are read only by `dihedral.charmm`.

`dihedral.charmm`'s `w` is LAMMPS's weighting factor: the dihedral prices,
besides its torsion, the 1-4 pair of its end atoms (those of `itom` and
`ltom`), w·[4ε₁₄((σ₁₄/r)¹² − (σ₁₄/r)⁶) + C·qᵢqⱼ/r], with ε₁₄ and σ₁₄ the
`pair.lj/charmm` 1-4 parameters of their types and C the Coulomb constant of
`units`. It is used with `special_bonds` 1-4 weights of `0`, so the pair
styles do not price that pair again, and it needs a `pair.lj/charmm` style
(as LAMMPS needs `pair_style lj/charmm/coul/*`). CHARMM sets w = 1, ½ for a
torsion in a six-membered ring and 0 in a four- or five-membered one, so each
1-4 pair is counted once; `w = 0` prices the torsion alone (AMBER's use of
the style).

**Improper atom order.** An `improper` row prices the dihedral of its atoms
in the order listed, and which listed atom is the centre is the style's:

| Style | Centre | Whose order |
|-------|--------|-------------|
| `improper.harmonic`, `improper.cvff` | `itom` | LAMMPS's (its "atom of symmetry"), CHARMM's |
| `improper.periodic` | `ktom` | AMBER's: the order whose dihedral is AMBER's improper angle (none with the centre first has it, since that angle's axis runs through the centre) |
| `improper.trefoil` | `jtom` | SMIRNOFF's |

A system's `impropers` row lists its atoms in the order of its type's
endpoints.

In `virtual_site` rows the constructed site is `atomi` of its
`virtual_sites` row and x_j, x_k, x_l are the positions of `atomj`, `atomk`,
`atoml`; r_jk = x_k − x_j.

### CMAP

A `cmap` row is LAMMPS `fix cmap` (CHARMM's correction map). Its five
endpoints name a crossterm's atoms: φ is the dihedral `itom`–`jtom`–`ktom`–
`ltom` and ψ the dihedral `jtom`–`ktom`–`ltom`–`mtom` (on a `cmaps` row,
`atomi`…`atoml` and `atomj`…`atomm`), both in (−180°, 180°]. Its `grid` is
an N × N map of energies (CHARMM: N = 24, a 15° step), **φ-major**: element
`[i][j]` (flat index `i·N + j`) is the energy at φ = −180° + i·360°/N,
ψ = −180° + j·360°/N — the order of a CHARMM / LAMMPS `.cmap` file, each of
whose `# phi` blocks is one φ row of N ψ values. Between the grid points the
energy is LAMMPS's bicubic interpolation, with the derivatives LAMMPS
precomputes from periodic cubic splines of the map.

## Expressions

`expression` is the style's energy as one formula in the syntax of OpenMM's
custom forces (Lepton): `+ - * / ^`, parentheses, `exp log sqrt sin cos tan
asin acos atan abs min max step delta select`, numeric literals. Its free
variables are the geometric variable of the category (`r` for bond, pair,
constraint; `theta` for angle; `phi` for dihedral; `chi` for improper), the
style's per-type and style-level parameter names, and, for pair styles, `q1`
and `q2`. Per-term sums are written out.

`theta`, `phi` and `chi` are radians, as Lepton's trigonometry is, while an
angle-valued parameter is in `units.angle` (degrees): the expression
converts it. `angle.harmonic` written out is
`k*(theta - theta0*0.017453292519943295)^2`, never `k*(theta - theta0)^2`.

A reader **MUST** preserve `expression` byte for byte. It **MAY** evaluate
it. An expression on a registered style **MUST** agree with the registry.

## Collections

A [collection](collection.md) carries at most one force field, shared by
every record: `atoms.type` and every relation `type` in every record link
into it. A record of a collection carries no `forcefield` of its own. The
[LMDB binding](lmdb.md) stores it under the key `ff`.

## Format mappings

Informative. How the common sources map onto this section. "→" names the
table and column a source item lands in. Every translator writes the
registry's conventions, which are LAMMPS's: an un-halved harmonic `k`, angle
values in degrees, force constants per radian. Lengths, energies and charges
stay in the source's own units unless the row says otherwise.

| Source | bond `k` | angle `k`, `theta0` | phases | impropers |
|--------|----------|---------------------|--------|-----------|
| LAMMPS | `K` | `K`, deg | deg | as written |
| GROMACS | `k_b/2` | `k_θ/2`, deg | deg | as written |
| OpenMM XML | `k/2` | `k/2`, rad → deg | rad → deg | (c1, c2, c3, c4) → (c2, c3, c1, c4) |
| OpenFF | `k/2` | `k/2`, deg | deg | `improper.trefoil` |
| AMBER prmtop | `RK` | `TK`, rad → deg | rad → deg | AMBER order |

### OpenMM / foyer XML

`units`: `length nm`, `energy kJ/mol`, `angle degree`, `charge e`,
`mass dalton`. OpenMM's harmonic forces are ½k(x − x0)², so `k` is halved;
its angles and phases are radians, converted to degrees.

| Source | Section |
|--------|---------|
| `<ForceField name combining_rule>` | `name`; `combining_rule` → `params.mixing` of `pair.lj/cut` |
| `<Info><Source>` | `source.uri` |
| `<AtomTypes><Type name class element mass def desc doi overrides>` | `atom.full`: `name`, `class`, `element`, `mass`, `smarts` (`def`), `desc`, `doi`, `overrides` |
| `<HarmonicBondForce><Bond class1 class2 length k>` | `bond.harmonic`: `itom`, `jtom`, `r0` = length, `k` = k/2; `endpoint_key` `class` (or `type` for `type1`/`type2`) |
| `<HarmonicAngleForce><Angle … angle k>` | `angle.harmonic`: `theta0` = angle in degrees, `k` = k/2 |
| `<PeriodicTorsionForce><Proper … periodicityN phaseN kN>` | `dihedral.periodic`: `periodicity<N>`, `phase<N>` in degrees, `k<N>` |
| `<PeriodicTorsionForce><Improper class1 class2 class3 class4 …>`, `ordering` absent or `"amber"` | `improper.periodic` in AMBER's order: `itom`, `jtom`, `ktom`, `ltom` = class2, class3, class1, class4 (OpenMM prices the dihedral (c2, c3, c1, c4) of its centre `class1`); a writer writes the inverse |
| the same, `ordering="charmm"` | `improper.periodic`, endpoints as written (OpenMM prices (c1, c2, c3, c4)) |
| the same, `ordering="smirnoff"` | refused: OpenMM averages three permutations, which no registered style is |
| `<RBTorsionForce><Proper … c0…c5>` | `dihedral.rb`: `c0`…`c5` |
| `<AmoebaUreyBradleyForce><UreyBradley class1 class2 class3 k d>` | `angle.charmm`, the row of the same classes as the `<HarmonicAngleForce>` one, which gives `k` and `theta0`: `k_ub` = k (OpenMM adds a `HarmonicBondForce` term of 2k, so k is already un-halved), `r_ub` = d. A reader into `real` (molrs) writes `k_ub` = k/418.4, `r_ub` = 10·d |
| `<CMAPTorsionForce><Map>` and its `<Torsion class1 … class5 map>` | `cmap.charmm` rows: OpenMM stores `energy[i + N·j]` at φ = i·360°/N, ψ = j·360°/N (origin 0, φ fastest); element `(i, j)` lands at `grid[(i + N/2) mod N][(j + N/2) mod N]` — each index shifted by N/2 and the axes swapped into φ-major. OpenMM interpolates with a natural periodic bicubic spline, so its energies off the grid points differ from LAMMPS's at the interpolation's accuracy |
| `<NonbondedForce coulomb14scale lj14scale>` | `special_bonds` `lj [0, 0, lj14scale]`, `coul [0, 0, coulomb14scale]` |
| `<NonbondedForce><Atom type charge sigma epsilon>` | `pair.lj/cut` self row (`itom = jtom = type`) with `sigma`, `epsilon`; `charge` → `atom.full.charge`; a `pair.coul/long/pme` style with no rows |
| a `NonbondedForce` exception (a built system) | a [pair override](#pair-overrides): `charge_product`, `sigma`, `epsilon`, `lj_scale` = `coul_scale` = 1 |
| `<LennardJonesForce><NBFixPair type1 type2 sigma epsilon>` | no mapping yet (see below) |
| `<Custom*Force energy>` with `<PerBondParameter>` / `<GlobalParameter>` | a style named by the force, `expression` = energy, per-type columns and `params` |
| `<Residues>` | not carried |

`<NonbondedForce>` holds one `<Atom>` row per type, so a `pair.lj/cut` cross
row has no form there; OpenMM keeps pair overrides as `<NBFixPair>` rows of a
`<LennardJonesForce>`, which this mapping does not cover yet. A writer refuses
a cross row ([Linking a system](#linking-a-system), rule 3): written as an
`<Atom>` it would replace `itom`'s own parameters. A reader that does not map
`<NBFixPair>` refuses the file with an error naming it, or skips the
`<LennardJonesForce>` with a diagnostic that says so; it never drops the
overrides silently, which would leave each such pair at its mixed value.

### OpenFF (SMIRNOFF `.offxml`)

Every value carries its unit in the file; a translator converts each into the
declared `units` (commonly `angstrom`, `kcal/mol`, `degree`, `e`, `dalton`).
SMIRNOFF's harmonic terms are ½k(x − x0)², so `k` is halved; its angles are
degrees and stay degrees.

| Source | Section |
|--------|---------|
| `<SMIRNOFF version aromaticity_model>` | `source.format` `offxml`; `aromaticity_model` kept as a document key |
| `<Bonds potential="harmonic"><Bond smirks id length k>` | `bond.harmonic`, `endpoint_key` `smirks`: `name` = id, `smirks`, `r0`, `k` = k/2 |
| `<Angles potential="harmonic"><Angle smirks id angle k>` | `angle.harmonic`, `smirks`-keyed: `theta0` (degrees), `k` = k/2 |
| `<ProperTorsions><Proper smirks id periodicityN phaseN kN idivfN>` | `dihedral.periodic`, `smirks`-keyed: `k<N>` = kN / idivfN, `phase<N>` (degrees) |
| `<ImproperTorsions><Improper …>` | `improper.trefoil`, `smirks`-keyed, `k<N>` = kN / idivfN |
| `<vdW potential="Lennard-Jones-12-6" combining_rules scale12 scale13 scale14 cutoff switch_width><Atom smirks id epsilon sigma\|rmin_half>` | `pair.lj/cut`, `smirks`-keyed: `sigma` (= rmin_half·2^{5/6} when given as rmin_half), `epsilon`; `params` `mixing arithmetic`, `cutoff`, `switch_width`; `special_bonds.lj` = `[scale12, scale13, scale14]` (a `scale15` other than 1 has no form here) |
| `<Electrostatics scale12 scale13 scale14 cutoff>` | `special_bonds.coul`; `pair.coul/long/pme` |
| `<Constraints><Constraint smirks id distance>` | `constraint.fixed`, `smirks`-keyed: `r0` = distance (null when absent) |
| `<LibraryCharges>`, `<ToolkitAM1BCC>`, `<ChargeIncrementModel>` | not tables: charges land in `atoms.charge` |

A system parameterized from it names rows by id: `bonds.type = "b1"`,
`atoms.type = "n16"`.

### GROMACS topology

`units`: `length nm`, `energy kJ/mol`, `angle degree`, `charge e`,
`mass dalton`. GROMACS's harmonic terms are ½k(x − x0)², so their `k` is
halved; its angles and phases are degrees and stay degrees.

| Source | Section |
|--------|---------|
| `[ defaults ] nbfunc comb-rule gen-pairs fudgeLJ fudgeQQ` | `special_bonds` `lj [0, 0, fudgeLJ]`, `coul [0, 0, fudgeQQ]`; comb-rule 2 → `mixing arithmetic`, 3 → `geometric` (comb-rule 1, C6/C12, is an unregistered pair style with `expression`) |
| `[ atomtypes ] name bond_type at.num mass charge ptype V W` | `atom.full`: `name`, `class` (= bond_type), `atomic_number`, `mass`, `charge`, `ptype`; a self row of the van-der-Waals pair style (`pair.lj/cut`, or `pair.lj/charmm` when the file has `[ pairtypes ]`) with `sigma` = V, `epsilon` = W |
| `[ bondtypes ]` funct 1 / 3 | `bond.harmonic` (`r0` = b0, `k` = k_b/2) / `bond.morse` (`r0`, `d0` = D, `alpha` = β) |
| `[ angletypes ]` funct 1 | `angle.harmonic` (`theta0` = θ₀, `k` = k_θ/2) |
| `[ angletypes ]` funct 5 `θ₀ k_θ r13 k_UB` | `angle.charmm` (`theta0` = θ₀, `k` = k_θ/2, `r_ub` = r13, `k_ub` = k_UB/2) |
| `[ dihedraltypes ]` funct 1 / 9 | `dihedral.periodic` (`phase` = φₛ); funct 9 rows with equal endpoints become terms `k<m>`, `periodicity<m>`, `phase<m>` of one row |
| `[ dihedraltypes ]` funct 2 | `improper.harmonic`, `k` = k_ξ/2, `chi0` = ξ₀ (agrees only at ξ₀ = 0) |
| `[ dihedraltypes ]` funct 3 / 4 | `dihedral.rb` (`c0`…`c5`) / `improper.periodic`, endpoints as written (GROMACS prices φ(i, j, k, l)) |
| `[ nonbond_params ] i j funct V W`, funct 1 | a cross row in the `pair` table that holds the `[ atomtypes ]` self rows: `itom`, `jtom` = the type names i, j; `sigma` = V, `epsilon` = W. `j i` restating `i j` with the same V, W is the same row; with different ones the file is refused. Other funct codes have no mapping |
| `[ pairtypes ] i j funct V W`, funct 1 | the `pair.lj/charmm` cross row of i, j (the one `[ nonbond_params ]` gives, or a new one whose `epsilon`, `sigma` are null): `sigma14` = V, `epsilon14` = W |
| `[ pairs ]` funct 1 with parameters (a molecule's) | a [pair override](#pair-overrides): `sigma`, `epsilon`, `lj_scale` = 1 |
| `[ constrainttypes ]` funct 1 | `constraint.fixed` (`r0`) |
| `[ cmaptypes ]` | `cmap.charmm` (CHARMM's grid; a reader is checked against a GROMACS energy before it is trusted) |
| endpoint `X` | `""` |
| molecule sections | the `system` ([conventions](conventions.md)) |

### LAMMPS coefficients

The identity: `units.preset` is the file's `units` style, and every
coefficient is stored as written, angles in degrees, under the registry's
name of its slot. No coefficient converts.

| Source | Section |
|--------|---------|
| `bond_style harmonic` `K r0` | `bond.harmonic`: `k` = K, `r0` |
| `bond_style morse` `D0 alpha r0` | `bond.morse`: `d0`, `alpha`, `r0` |
| `bond_style class2` `r0 K2 K3 K4` | `bond.class2` |
| `angle_style harmonic` `K θ0` | `angle.harmonic`: `k` = K, `theta0` |
| `angle_style charmm` `K θ0 K_ub r_ub` | `angle.charmm`: `k`, `theta0`, `k_ub`, `r_ub` |
| `angle_style class2` `θ0 K2 K3 K4` | `angle.class2` (its `bb` / `ba` cross terms have no mapping) |
| `dihedral_style opls` `K1 K2 K3 K4` | `dihedral.opls`: `k1`…`k4` |
| `dihedral_style fourier` `m K1 n1 d1 …` | `dihedral.periodic`: `k<i>`, `periodicity<i>`, `phase<i>` |
| `dihedral_style charmm` `K n d w` | `dihedral.charmm`: `k`, `periodicity`, `phase` = d, `w` |
| `dihedral_style harmonic` `K d n` | `dihedral.harmonic`: `k`, `sign` = d, `periodicity` |
| `dihedral_style multi/harmonic` `A1…A5` | `dihedral.multi/harmonic`: `a1`…`a5` |
| `dihedral_style class2` `K1 φ1 K2 φ2 K3 φ3` | `dihedral.class2` (its `mbt` / `ebt` / `at` / `aat` / `bb13` terms have no mapping) |
| `improper_style harmonic` `K χ0` | `improper.harmonic`: `k` = K, `chi0` |
| `improper_style cvff` `K d n` | `improper.cvff`: `k`, `sign` = d, `periodicity`; a writer writes an `improper.periodic` row of one term with γ ∈ {0°, 180°} as `cvff` (`K = k`, `d = cos γ`, `n`), atoms in the row's (AMBER) order |
| `pair_style lj/cut/coul/long rc` / `pair_coeff i j ε σ` | `pair.lj/cut` (`params.cutoff` = rc; row `itom` i, `jtom` j: a self row for i = j, a cross row otherwise) and `pair.coul/long/pme`. A later `pair_coeff` for the same pair, in either order, replaces the earlier one, as in LAMMPS, so the table holds one row per pair. A cross `pair_coeff` with a wildcard (`pair_coeff c3 * …`) has no mapping and is refused, not expanded |
| `pair_style lj/charmm/coul/charmm` or `lj/charmm/coul/long` / `pair_coeff i j ε σ ε14 σ14` | `pair.lj/charmm` (`epsilon`, `sigma`, `epsilon14`, `sigma14`; `mixing arithmetic` unless `pair_modify mix` says otherwise) and the electrostatic style |
| `pair_style morse` `D0 alpha r0` | `pair.morse`: `d0`, `alpha`, `r0` |
| data file `Pair Coeffs` `t ε σ` / `PairIJ Coeffs` `i j ε σ` | as `pair_coeff t t ε σ` / `pair_coeff i j ε σ`: `PairIJ Coeffs` rows with i ≠ j are cross rows |
| `pair_modify mix <rule>` | `params.mixing` |
| `special_bonds lj a b c coul d e f` | `special_bonds` |
| `fix cmap` with its `.cmap` file, and the data file's `CMAP` section | `cmap.charmm`: one row per map, `grid` as the file lists it (φ-major); the `CMAP` section's crossterms are `cmaps` rows |
| `pair_style hybrid` sub-styles | one style each; relation rows carry `style` |
| type labels (`Atom Type Labels`) | `name`; without labels the decimal type number |
| `*` (outside a cross `pair_coeff`) | `""` |

A LAMMPS writer refuses what LAMMPS cannot hold: a [pair
override](#pair-overrides), a cross row of a style LAMMPS gives none, a
style with no LAMMPS form.

### AMBER prmtop

`units`: `length angstrom`, `energy kcal/mol`, `angle degree`, `charge e`,
`mass dalton`. AMBER's force constants are already un-halved; its angles and
phases are radians, converted to degrees. A type name is the atom's
`AMBER_ATOM_TYPE`; its LJ class is its `ATOM_TYPE_INDEX`.

| Source | Section |
|--------|---------|
| `BOND_FORCE_CONSTANT` RK, `BOND_EQUIL_VALUE` | `bond.harmonic`: `k` = RK, `r0` |
| `ANGLE_FORCE_CONSTANT` TK, `ANGLE_EQUIL_VALUE` | `angle.harmonic`: `k` = TK, `theta0` in degrees |
| `DIHEDRAL_FORCE_CONSTANT` PK, `DIHEDRAL_PERIODICITY`, `DIHEDRAL_PHASE` | `dihedral.periodic` (`improper.periodic`, in AMBER's order, for a negative fourth atom index): `k` = PK, `periodicity`, `phase` in degrees |
| `SCEE_SCALE_FACTOR`, `SCNB_SCALE_FACTOR` (one value over the torsions; absent, 1.2 and 2.0) | `special_bonds` `coul [0, 0, 1/SCEE]`, `lj [0, 0, 1/SCNB]`; a torsion whose values differ gives its 1-4 pair `coul_scale`, `lj_scale` ([pair overrides](#pair-overrides)) |
| `LENNARD_JONES_ACOEF` A, `LENNARD_JONES_BCOEF` B on the diagonal of `NONBONDED_PARM_INDEX` | `pair.lj/cut` self row of every type name on that LJ class: `sigma` = (A/B)^{1/6}, `epsilon` = B²/(4A); `params.mixing arithmetic` |
| an off-diagonal A, B that is the Lorentz–Berthelot mix of its two classes' self terms | no row: `mixing` gives it |
| an off-diagonal A, B that is not (NBFIX, ParmEd `changeLJPair`) | a cross row, with σ and ε of that entry, for every pair of type names on the two LJ classes, endpoints in byte order |

## Conformance

The force-field suite (`module = "forcefield"`) pins down:

- `ff-minimal`: a name, `units` and one atom style round-trip;
- `ff-round-trip`: atom, bond, angle, multi-term dihedral, improper, two pair
  styles with `mixing`, `special_bonds` and `source` round-trip exactly, its
  numbers in the registry's conventions (LAMMPS's `K`, degrees);
- `ff-wildcard-endpoints`: `""` endpoints survive;
- `ff-absent-params`: a parameter some rows lack is null there, not filled;
- `ff-string-params`: `class`, `element`, `smarts` and a non-canonical string
  parameter survive;
- `ff-style-name-encoding`: `pair.lj%2Fcut%2Fcoul%2Flong` resolves to
  `lj/cut/coul/long`;
- `ff-pair-cross-rows`: a cross row whose `name` is no endpoint spelling,
  and a reversed restatement of it with equal parameters, survive beside the
  self rows (that the row overrides `mixing` is an energy, which a format
  suite does not compute);
- `ff-hybrid-styles`: two bond styles, and a record whose `bonds` carry
  `style`;
- `ff-per-instance-style`: a style with no rows beside relation columns that
  carry its parameters;
- `ff-unknown-style-with-expression` and `ff-unknown-category` (a
  `cross_term.example` table): preserved verbatim;
- `ff-cmap-grid`: a `cmap` table's five endpoints and its `f64[T, N, N]`
  `grid` come back bit for bit;
- `ff-angle-charmm`: an `angle.charmm` table (`k`, `theta0`, `k_ub`, `r_ub`)
  beside a `dihedral.charmm` one with `w`;
- `ff-pair-lj-charmm`: a `pair.lj/charmm` table whose self rows carry or
  leave null `epsilon14` / `sigma14`, and a cross row that carries only
  them (a GROMACS `[ pairtypes ]` row);
- `ff-units-preserved`: `nm` / `kJ/mol` numbers come back unconverted;
- `ff-lj-preset`: `preset lj` with no quantity strings;
- `ff-smirks-keyed`: a `smirks`-keyed table with no endpoint columns;
- `ff-without-special-bonds`: absence survives as absence;
- `ff-document-keys-preserved`: a document key and a table no style names
  survive as unknown content;
- refusals on read: `reject-ff-no-units`, `reject-ff-units-conflict`,
  `reject-ff-radian-angle-unit` (`"angle": "radian"` beside a preset),
  `reject-ff-duplicate-style`, `reject-ff-missing-table`,
  `reject-ff-duplicate-type-name`, `reject-ff-wrong-arity`,
  `reject-ff-param-dtype`, `reject-ff-null-name`,
  `reject-ff-class-key-without-class`, `reject-ff-pair-conflict` (`B`–`A`
  restating `A`–`B` with another `epsilon`), `reject-ff-cmap-grid-shape` (a
  non-square `f64[T, 3, 4]` grid), `reject-ff-cmap-grid-nonfinite` (a `NaN`
  in a non-null row), `reject-ff-grid-outside-cmap` (a `grid` with trailing
  axes on a bond table).

The record suite adds `record-with-forcefield` (a `system` whose `atoms.type`
and `bonds.type` link into it), `forcefield-only-record` and
`record-pair-overrides` (a `system` whose `pairs` rows carry every
[pair override](#pair-overrides), null in some rows, beside a
`pair.lj/charmm` force field); the collection
suite adds `collection-forcefield` and `collection-cmap` (a `cmap` grid under
the LMDB key `ff`, linked from `cmaps` rows).
