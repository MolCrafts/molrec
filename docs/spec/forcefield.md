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
translates a file states the file's own units here rather than converting,
except where one quantity is mixed inside the source (a degree angle beside a
per-radian force constant): it then converts that quantity to one unit and
states that unit.

| Key | Quantity | Example |
|-----|----------|---------|
| `length` | lengths, and the length part of every derived unit | `angstrom`, `nm` |
| `energy` | energies, and the energy part of every derived unit | `kcal/mol`, `kJ/mol`, `eV` |
| `angle` | angles and phases, and the angle part of force constants | `radian`, `degree` |
| `charge` | charges | `e` |
| `mass` | masses | `dalton` |
| `time` | times (rarely present) | `fs` |

A unit string is parseable by [pint](https://pint.readthedocs.io). A derived
dimension (a bond force constant, `energy/length²`) is composed from these;
it has no key of its own.

`preset` names a unit system instead of listing it. The presets are:

| Preset | length | energy | angle | charge | mass | time |
|--------|--------|--------|-------|--------|------|------|
| `real` | `angstrom` | `kcal/mol` | `radian` | `e` | `dalton` | `fs` |
| `metal` | `angstrom` | `eV` | `radian` | `e` | `dalton` | `ps` |
| `si` | `m` | `J` | `radian` | `C` | `kg` | `s` |
| `cgs` | `cm` | `erg` | `radian` | `statcoulomb` | `g` | `s` |
| `electron` | `bohr` | `hartree` | `radian` | `e` | `dalton` | `fs` |
| `micro` | `micrometer` | `picogram * micrometer**2 / microsecond**2` | `radian` | `picocoulomb` | `picogram` | `microsecond` |
| `nano` | `nm` | `attogram * nm**2 / ns**2` | `radian` | `e` | `attogram` | `ns` |
| `lj` | — | — | `radian` | — | — | — |

The names are those of the LAMMPS `units` command, but the angle is a radian
in every preset: a LAMMPS input file's degrees are an input convention, not
the unit system. `lj` is reduced units: no quantity but `angle` has a unit,
and the numbers are in the reduced scale of the producer's choosing.

`units` **MUST** carry `preset` or at least one quantity. When both a preset
and a quantity are present they **MUST** agree (pint-equivalent strings); a
reader refuses a document where they do not. A style whose parameters need a
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

On a `cmap` table only: the row's correction table, `f64[T, N, N]` — one
`N × N` grid of energies (`units.energy`) per row, `N ≥ 2`, one `N` for every
row of the table. The first trailing axis is φ, the dihedral
`itom`–`jtom`–`ktom`–`ltom`; the second is ψ, the dihedral
`jtom`–`ktom`–`ltom`–`mtom`; `grid[a][b]` is the correction at
φ = −π + 2πa/N, ψ = −π + 2πb/N. It declares no precision, and every value of
a row that is not null is finite. A reader **MUST** refuse a `cmap` grid of
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
| `pair14` | 2 | an explicit 1-4 pair of atom types | `pairs` rows with `is_14` |
| `constraint` | 2 | a constrained distance type | `constraints` |
| `virtual_site` | 0 | a virtual-site construction | `virtual_sites` |
| `drude` | 2 | a core–Drude pair type (`itom` core, `jtom` Drude) | `drudes` |
| `cmap` | 5 | a CMAP cross-term type over the two consecutive dihedrals `itom`…`ltom` and `jtom`…`mtom` (CHARMM φ/ψ); its `grid` is the correction | `cmaps` |

The system blocks are [standardized identifiers](conventions.md). A category
outside this table is legal and preserved; its arity is the number of
endpoint columns its table carries, which **MUST** be a prefix of `itom`,
`jtom`, `ktom`, `ltom`, `mtom`.

A `pair14` row replaces, for a 1-4 pair of its two types, the parameters the
same-named `pair` style would give it, and that pair's `special_bonds` 1-4
weight is then not applied on top.

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
3. `pair` and `pair14` tables are resolved through atom types, not row
   names: for atoms of types *a* and *b*, the row whose endpoints are
   `{a, b}`, in either order. A cross row (`itom ≠ jtom`) therefore gives
   its pair its own parameters and overrides the style's `mixing` for that
   pair; `mixing` prices only the pairs no row names. A pair table **MUST
   NOT** hold two rows with the same unordered `{itom, jtom}` and different
   parameters: rows restating a pair, in either order, with equal values in
   every parameter column (null equal only to null; `name` and the
   annotation columns are not parameters) are one row, and a reader
   **MUST** refuse a table whose restatements differ. A cross row's `name`
   means nothing beyond its uniqueness in the table: it is not parsed, not
   derived from the endpoints, and no system row names it. A writer
   translating into a format that has no form for a cross row **MUST**
   refuse the row rather than write it as a self row of either endpoint.
   Failing a row, a `pair` style uses its `mixing` of the two self
   rows `{a, a}` and `{b, b}`; a `pair14` style gives nothing, and the pair
   keeps its scaled `pair` interaction. Every pair style of the force field
   applies to every non-excluded pair, scaled by `special_bonds` (`lj` or
   `coul` per the style's special class). The `pairs` block, where present,
   lists intramolecular pairs explicitly; its `is_14` rows are the 1-4 pairs
   `pair14` tables apply to.
4. A relation block may carry a parameter column named as its style names
   it. Its value, where not null, is that row's parameter and overrides the
   table; a style whose table has no rows takes every parameter from the
   relation (a *per-instance* style, as MMFF and UFF are).
5. `type_id`, where present, is a format-local ordinal and plays no part in
   linking.

A name that resolves to nothing is not a format error. A reader **MUST NOT**
refuse a record for it; a validator **SHOULD** report it. Two pair rows that
price one pair differently (rule 3) are a format error: the table cannot say
which applies.

## Style registry

A style named here **MUST** mean exactly this energy and these parameters.
A style not named here **SHOULD** carry an `expression`; a reader preserves it
either way. Dimensions: *E* energy, *L* length, *A* angle, *1* a pure number.
φ is the signed dihedral, χ = |φ|, θ the angle at `jtom`, *r* the distance.

| Style | Energy | Per-type parameters | Style parameters |
|-------|--------|---------------------|------------------|
| `atom.full` | — | `mass`, `charge` | — |
| `bond.harmonic` | ½·k·(r − r0)² | `k` E/L², `r0` L | — |
| `bond.morse` | D·(1 − e^{−alpha·(r − r0)})² | `D` E, `alpha` 1/L, `r0` L | — |
| `bond.class2` | k2·Δ² + k3·Δ³ + k4·Δ⁴, Δ = r − r0 | `r0` L, `k2` E/L², `k3` E/L³, `k4` E/L⁴ | — |
| `angle.harmonic` | ½·k·(θ − theta0)² | `k` E/A², `theta0` A | — |
| `angle.class2` | k2·Δ² + k3·Δ³ + k4·Δ⁴, Δ = θ − theta0 | `theta0` A, `k2` E/A², `k3` E/A³, `k4` E/A⁴ | — |
| `dihedral.periodic` | Σₘ kₘ·[1 + cos(nₘ·φ − γₘ)] | `k` E, `periodicity` 1, `phase` A — or, per term m = 1, 2, …, `k<m>`, `periodicity<m>`, `phase<m>` | — |
| `dihedral.opls` | ½·[k1(1 + cos φ) + k2(1 − cos 2φ) + k3(1 + cos 3φ) + k4(1 − cos 4φ)] | `k1`…`k4` E | — |
| `dihedral.rb` | Σₙ₌₀⁵ cₙ·cosⁿ(φ − π) | `c0`…`c5` E | — |
| `dihedral.charmm` | k·[1 + cos(n·φ − γ)] | `k` E, `periodicity` 1, `phase` A, `w` 1 (the 1-4 weight; not in this term) | — |
| `dihedral.harmonic` | k·[1 + sign·cos(n·φ)] | `k` E, `sign` 1 (±1), `periodicity` 1 | — |
| `dihedral.multi/harmonic` | Σₙ₌₁⁵ aₙ·cosⁿ⁻¹ φ | `a1`…`a5` E | — |
| `dihedral.class2` | Σₙ₌₁³ kₙ·[1 − cos(n·φ − phiₙ)] | `k1`, `phi1`, `k2`, `phi2`, `k3`, `phi3` (E, A) | — |
| `improper.harmonic` | k·(χ − chi0)² | `k` E/A², `chi0` A | — |
| `improper.periodic` | as `dihedral.periodic` | as `dihedral.periodic` | — |
| `improper.cvff` | k·[1 + sign·cos(n·χ)] | `k` E, `sign` 1, `periodicity` 1 | — |
| `improper.trefoil` | ⅓·Σ over the three orderings of the outer atoms, central atom `jtom`, of the `dihedral.periodic` energy | as `dihedral.periodic` | — |
| `pair.lj/cut` | C·ε·[(σ/r)ⁿ − (σ/r)ᵐ], C = n/(n−m)·(n/m)^{m/(n−m)}, r < cutoff; n = 12, m = 6 gives 4ε[(σ/r)¹² − (σ/r)⁶] | `epsilon` E, `sigma` L | `cutoff` L, `mixing`, `n` 1, `m` 1, `shift` 1 (non-zero: shifted to 0 at cutoff) |
| `pair.lj/class2` | ε·[2(σ/r)⁹ − 3(σ/r)⁶] | `epsilon` E, `sigma` L | `cutoff` L, `mixing` |
| `pair.buck` | a·e^{−r/rho} − c/r⁶ | `a` E, `rho` L, `c` E·L⁶ | `cutoff` L |
| `pair.morse` | d0·[(1 − e^{−alpha(r − r0)})² − 1] | `d0` E, `alpha` 1/L, `r0` L | `cutoff` L |
| `pair.coul/cut` | coulomb·qᵢqⱼ / (dielectric·(r + delta)), r < cutoff | — (charges from `atoms.charge`) | `coulomb` E·L/Q², `dielectric` 1, `delta` L, `cutoff` L |
| `pair.coul/long/pme` | Ewald-summed coulomb·qᵢqⱼ/r (particle-mesh) | — (charges from `atoms.charge`) | `coulomb` E·L/Q², `cutoff` L, `alpha` 1/L, `order` 1, `grid_x`, `grid_y`, `grid_z` 1 |
| `pair14.lj/cut` | as `pair.lj/cut` | `epsilon` E, `sigma` L | — |
| `constraint.fixed` | \|rᵢ − rⱼ\| = r0 | `r0` L | — |
| `virtual_site.average2` | x = w1·x_j + w2·x_k | `w1`, `w2` 1 | — |
| `virtual_site.average3` | x = w1·x_j + w2·x_k + w3·x_l | `w1`, `w2`, `w3` 1 | — |
| `virtual_site.outofplane3` | x = x_j + w12·r_jk + w13·r_jl + wcross·(r_jk × r_jl) | `w12`, `w13` 1, `wcross` 1/L | — |
| `drude.harmonic` | ½·k·\|r_core − r_drude\|²; polarizability alpha; Thole screening thole | `k` E/L², `alpha` L³, `thole` 1 | — |

Special classes: `pair.lj/cut`, `pair.lj/class2`, `pair.buck`, `pair.morse`
take `special_bonds.lj`; `pair.coul/cut` and `pair.coul/long/pme` take
`special_bonds.coul`. An unregistered pair style takes `lj` unless its
`params.special` is `"coul"`. `pair14` styles take no weight.

In `virtual_site` rows the constructed site is `atomi` of its
`virtual_sites` row and x_j, x_k, x_l are the positions of `atomj`, `atomk`,
`atoml`; r_jk = x_k − x_j.

The registry's conventions are the reference implementation's. Where a
source format differs — LAMMPS `bond_style harmonic` is K·(r − r0)², so
k = 2K — the translation is in [Format mappings](#format-mappings).

## Expressions

`expression` is the style's energy as one formula in the syntax of OpenMM's
custom forces (Lepton): `+ - * / ^`, parentheses, `exp log sqrt sin cos tan
asin acos atan abs min max step delta select`, numeric literals. Its free
variables are the geometric variable of the category (`r` for bond, pair,
pair14, constraint; `theta` for angle; `phi` for dihedral; `chi` for
improper), the style's per-type and style-level parameter names, and, for
pair styles, `q1` and `q2`. Per-term sums are written out.

A reader **MUST** preserve `expression` byte for byte. It **MAY** evaluate
it. An expression on a registered style **MUST** agree with the registry.

## Collections

A [collection](collection.md) carries at most one force field, shared by
every record: `atoms.type` and every relation `type` in every record link
into it. A record of a collection carries no `forcefield` of its own. The
[LMDB binding](lmdb.md) stores it under the key `ff`.

## Format mappings

Informative. How the common sources map onto this section. "→" names the
table and column a source item lands in; units are the source's own unless
the row says otherwise.

### OpenMM / foyer XML

`units`: `length nm`, `energy kJ/mol`, `angle radian`, `charge e`,
`mass dalton`.

| Source | Section |
|--------|---------|
| `<ForceField name combining_rule>` | `name`; `combining_rule` → `params.mixing` of `pair.lj/cut` |
| `<Info><Source>` | `source.uri` |
| `<AtomTypes><Type name class element mass def desc doi overrides>` | `atom.full`: `name`, `class`, `element`, `mass`, `smarts` (`def`), `desc`, `doi`, `overrides` |
| `<HarmonicBondForce><Bond class1 class2 length k>` | `bond.harmonic`: `itom`, `jtom`, `r0` = length, `k`; `endpoint_key` `class` (or `type` for `type1`/`type2`) |
| `<HarmonicAngleForce><Angle … angle k>` | `angle.harmonic`: `theta0` = angle, `k` |
| `<PeriodicTorsionForce><Proper … periodicityN phaseN kN>` | `dihedral.periodic`: `periodicity<N>`, `phase<N>`, `k<N>` |
| `<PeriodicTorsionForce><Improper …>` | `improper.periodic`, endpoints in file order (`class1` central) |
| `<RBTorsionForce><Proper … c0…c5>` | `dihedral.rb`: `c0`…`c5` |
| `<NonbondedForce coulomb14scale lj14scale>` | `special_bonds` `lj [0, 0, lj14scale]`, `coul [0, 0, coulomb14scale]` |
| `<NonbondedForce><Atom type charge sigma epsilon>` | `pair.lj/cut` self row (`itom = jtom = type`) with `sigma`, `epsilon`; `charge` → `atom.full.charge`; a `pair.coul/long/pme` style with no rows |
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
declared `units` (commonly `angstrom`, `kcal/mol`, `radian`, `e`, `dalton`;
angles convert from degrees because force constants are per radian²).

| Source | Section |
|--------|---------|
| `<SMIRNOFF version aromaticity_model>` | `source.format` `offxml`; `aromaticity_model` kept as a document key |
| `<Bonds potential="harmonic"><Bond smirks id length k>` | `bond.harmonic`, `endpoint_key` `smirks`: `name` = id, `smirks`, `r0`, `k` |
| `<Angles potential="harmonic"><Angle smirks id angle k>` | `angle.harmonic`, `smirks`-keyed: `theta0`, `k` |
| `<ProperTorsions><Proper smirks id periodicityN phaseN kN idivfN>` | `dihedral.periodic`, `smirks`-keyed: `k<N>` = kN / idivfN |
| `<ImproperTorsions><Improper …>` | `improper.trefoil`, `smirks`-keyed, `k<N>` = kN / idivfN |
| `<vdW potential="Lennard-Jones-12-6" combining_rules scale12 scale13 scale14 cutoff switch_width><Atom smirks id epsilon sigma\|rmin_half>` | `pair.lj/cut`, `smirks`-keyed: `sigma` (= rmin_half·2^{5/6} when given as rmin_half), `epsilon`; `params` `mixing arithmetic`, `cutoff`, `switch_width`; `special_bonds.lj` = `[scale12, scale13, scale14]` (a `scale15` other than 1 has no form here) |
| `<Electrostatics scale12 scale13 scale14 cutoff>` | `special_bonds.coul`; `pair.coul/long/pme` |
| `<Constraints><Constraint smirks id distance>` | `constraint.fixed`, `smirks`-keyed: `r0` = distance (null when absent) |
| `<LibraryCharges>`, `<ToolkitAM1BCC>`, `<ChargeIncrementModel>` | not tables: charges land in `atoms.charge` |

A system parameterized from it names rows by id: `bonds.type = "b1"`,
`atoms.type = "n16"`.

### GROMACS topology

`units`: `length nm`, `energy kJ/mol`, `angle radian`, `charge e`,
`mass dalton`. GROMACS degrees (θ₀, φₛ) convert to radians.

| Source | Section |
|--------|---------|
| `[ defaults ] nbfunc comb-rule gen-pairs fudgeLJ fudgeQQ` | `special_bonds` `lj [0, 0, fudgeLJ]`, `coul [0, 0, fudgeQQ]`; comb-rule 2 → `mixing arithmetic`, 3 → `geometric` (comb-rule 1, C6/C12, is an unregistered pair style with `expression`) |
| `[ atomtypes ] name bond_type at.num mass charge ptype V W` | `atom.full`: `name`, `class` (= bond_type), `atomic_number`, `mass`, `charge`, `ptype`; `pair.lj/cut` self row with `sigma` = V, `epsilon` = W |
| `[ bondtypes ]` funct 1 / 3 | `bond.harmonic` (`r0` = b0, `k` = kb) / `bond.morse` (`r0`, `D`, `alpha` = β) |
| `[ angletypes ]` funct 1 | `angle.harmonic` (`theta0`, `k`) |
| `[ dihedraltypes ]` funct 1 / 9 | `dihedral.periodic`; funct 9 rows with equal endpoints become terms `k<m>`, `periodicity<m>`, `phase<m>` of one row |
| `[ dihedraltypes ]` funct 2 | `improper.harmonic`, `k` = k_ξ/2, `chi0` = ξ₀ (agrees only at ξ₀ = 0) |
| `[ dihedraltypes ]` funct 3 / 4 | `dihedral.rb` (`c0`…`c5`) / `improper.periodic` |
| `[ nonbond_params ] i j funct V W`, funct 1 | a cross row in the `pair` table that holds the `[ atomtypes ]` self rows (`pair.lj/cut` under comb-rule 2 or 3): `itom`, `jtom` = the type names i, j; V and W read as `[ atomtypes ]` reads them (`sigma`, `epsilon`). `j i` restating `i j` with the same V, W is the same row; with different ones the file is refused. Other funct codes have no mapping |
| `[ pairtypes ]` funct 1 | `pair14.lj/cut` (`sigma`, `epsilon`) |
| `[ constrainttypes ]` funct 1 | `constraint.fixed` (`r0`) |
| endpoint `X` | `""` |
| molecule sections | the `system` ([conventions](conventions.md)) |

### LAMMPS coefficients

`units.preset` is the file's `units` style; angles convert from degrees to
radians.

| Source | Section |
|--------|---------|
| `bond_style harmonic` / `bond_coeff t K r0` | `bond.harmonic`: `k` = 2K, `r0` |
| `angle_style harmonic` / `angle_coeff t K θ0` | `angle.harmonic`: `k` = 2K, `theta0` |
| `dihedral_style opls` `K1 K2 K3 K4` | `dihedral.opls`: `k1`…`k4` |
| `dihedral_style fourier` `m K1 n1 d1 …` | `dihedral.periodic`: `k<i>`, `periodicity<i>`, `phase<i>` |
| `dihedral_style charmm` `K n d w` | `dihedral.charmm`: `k`, `periodicity`, `phase`, `w` |
| `dihedral_style harmonic` `K d n` | `dihedral.harmonic`: `k`, `sign` = d, `periodicity` |
| `dihedral_style multi/harmonic` `A1…A5` | `dihedral.multi/harmonic`: `a1`…`a5` |
| `improper_style harmonic` `K χ0` | `improper.harmonic`: `k` = K, `chi0` |
| `improper_style cvff` `K d n` | `improper.cvff`: `k`, `sign` = d, `periodicity` |
| `pair_style lj/cut/coul/long rc` / `pair_coeff i j ε σ` | `pair.lj/cut` (`params.cutoff` = rc; row `itom` i, `jtom` j: a self row for i = j, a cross row otherwise) and `pair.coul/long/pme`. A later `pair_coeff` for the same pair, in either order, replaces the earlier one, as in LAMMPS, so the table holds one row per pair. A cross `pair_coeff` with a wildcard (`pair_coeff c3 * …`) has no mapping and is refused, not expanded |
| data file `Pair Coeffs` `t ε σ` / `PairIJ Coeffs` `i j ε σ` | as `pair_coeff t t ε σ` / `pair_coeff i j ε σ`: `PairIJ Coeffs` rows with i ≠ j are cross rows |
| `pair_modify mix <rule>` | `params.mixing` |
| `special_bonds lj a b c coul d e f` | `special_bonds` |
| `pair_style hybrid` sub-styles | one style each; relation rows carry `style` |
| type labels (`Atom Type Labels`) | `name`; without labels the decimal type number |
| `*` (outside a cross `pair_coeff`) | `""` |

### AMBER prmtop

`units`: `length angstrom`, `energy kcal/mol`, `angle radian`, `charge e`,
`mass dalton`. A type name is the atom's `AMBER_ATOM_TYPE`; its LJ class is
its `ATOM_TYPE_INDEX`.

| Source | Section |
|--------|---------|
| `BOND_FORCE_CONSTANT` RK, `BOND_EQUIL_VALUE` | `bond.harmonic`: `k` = 2·RK, `r0` |
| `ANGLE_FORCE_CONSTANT` TK, `ANGLE_EQUIL_VALUE` | `angle.harmonic`: `k` = 2·TK, `theta0` |
| `DIHEDRAL_FORCE_CONSTANT` PK, `DIHEDRAL_PERIODICITY`, `DIHEDRAL_PHASE` | `dihedral.periodic` (`improper.periodic` for a negative fourth atom index): `k` = PK, `periodicity`, `phase` |
| `SCEE_SCALE_FACTOR`, `SCNB_SCALE_FACTOR` (one value over the torsions; absent, 1.2 and 2.0) | `special_bonds` `coul [0, 0, 1/SCEE]`, `lj [0, 0, 1/SCNB]` |
| `LENNARD_JONES_ACOEF` A, `LENNARD_JONES_BCOEF` B on the diagonal of `NONBONDED_PARM_INDEX` | `pair.lj/cut` self row of every type name on that LJ class: `sigma` = (A/B)^{1/6}, `epsilon` = B²/(4A); `params.mixing arithmetic` |
| an off-diagonal A, B that is the Lorentz–Berthelot mix of its two classes' self terms | no row: `mixing` gives it |
| an off-diagonal A, B that is not (NBFIX, ParmEd `changeLJPair`) | a cross row, with σ and ε of that entry, for every pair of type names on the two LJ classes, endpoints in byte order |

## Conformance

The force-field suite (`module = "forcefield"`) pins down:

- `ff-minimal`: a name, `units` and one atom style round-trip;
- `ff-round-trip`: atom, bond, angle, multi-term dihedral, improper, two pair
  styles with `mixing`, `special_bonds` and `source` round-trip exactly;
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
- `ff-units-preserved`: `nm` / `kJ/mol` numbers come back unconverted;
- `ff-lj-preset`: `preset lj` with no quantity strings;
- `ff-smirks-keyed`: a `smirks`-keyed table with no endpoint columns;
- `ff-without-special-bonds`: absence survives as absence;
- `ff-document-keys-preserved`: a document key and a table no style names
  survive as unknown content;
- refusals on read: `reject-ff-no-units`, `reject-ff-units-conflict`,
  `reject-ff-duplicate-style`, `reject-ff-missing-table`,
  `reject-ff-duplicate-type-name`, `reject-ff-wrong-arity`,
  `reject-ff-param-dtype`, `reject-ff-null-name`,
  `reject-ff-class-key-without-class`, `reject-ff-pair-conflict` (`B`–`A`
  restating `A`–`B` with another `epsilon`), `reject-ff-cmap-grid-shape` (a
  non-square `f64[T, 3, 4]` grid), `reject-ff-cmap-grid-nonfinite` (a `NaN`
  in a non-null row), `reject-ff-grid-outside-cmap` (a `grid` with trailing
  axes on a bond table).

The record suite adds `record-with-forcefield` (a `system` whose `atoms.type`
and `bonds.type` link into it) and `forcefield-only-record`; the collection
suite adds `collection-forcefield` and `collection-cmap` (a `cmap` grid under
the LMDB key `ff`, linked from `cmaps` rows).
