# Units

## Purpose

A number in a record is in some unit. This chapter names the unit systems a
record may declare. It does not add a dtype: a column's width stays the
closed set in [Types](types.md), and the unit is metadata.

## Where a unit is stated

| Data | Unit |
|------|------|
| `x`/`y`/`z`, `xyz`, velocities, `box.vectors`, `box.origin`, a block mesh | `meta.units` length |
| `trajectory.time` | `meta.units` time |
| `atoms.charge`, `atoms.mass` | `meta.units` charge and mass |
| Force-field parameters | `forcefield.units` — see below |
| One observable array | that array's `unit`, when set |

`meta.units` may be absent. Absent means those geometry arrays state no
unit. A reader does not borrow `forcefield.units` to fill the gap.

When both `meta.units.preset` and `forcefield.units.preset` are present,
they are the same preset. A simulation written in one unit system sets both.

An observable's `unit` is the unit of that array. When it is absent, the
array states no unit of its own.

## The object

`meta.units` and `forcefield.units` are the same object:

```text
units
+-- (preset: string)     # real | metal | si | cgs | electron | micro | nano | lj | openmm
+-- (length: string)
+-- (energy: string)
+-- (time: string)
+-- (mass: string)
+-- (charge: string)
\-- (angle: string)      # degree, in every built-in preset
```

A preset names the whole row below. A stated quantity must be that preset's
unit. Stating a different unit under a preset is invalid. With no preset,
each stated quantity is the unit of that dimension, and at least one
quantity is present.

`lj` is reduced units. Length is σ, energy is ε, time is τ, mass is the
reference mass, charge is the reduced charge. The document is
`{"preset": "lj"}`: those scales are the preset, so the quantity strings
are omitted, not unknown. Angle values are still degrees. A mesh whose
`unit` is set uses that length instead of the preset.

## Presets

| preset | length | energy | time | mass | charge |
|--------|--------|--------|------|------|--------|
| `real` | angstrom | kcal/mol | fs | dalton | e |
| `metal` | angstrom | eV | ps | dalton | e |
| `si` | m | J | s | kg | C |
| `cgs` | cm | erg | s | g | statcoulomb |
| `electron` | bohr | hartree | fs | dalton | e |
| `micro` | micrometer | picogram·micrometer²/microsecond² | microsecond | picogram | picocoulomb |
| `nano` | nm | attogram·nm²/ns² | ns | attogram | e |
| `openmm` | nm | kJ/mol | ps | dalton | e |
| `lj` | — | — | — | — | — |

`micro` and `nano` energy strings, as stored, are
`picogram * micrometer**2 / microsecond**2` and `attogram * nm**2 / ns**2`.

Angle values — a parameter whose dimension is exactly `A`, and any other
stored angle — are degrees in every preset. A force constant per radian has
a negative angle dimension (`E/A^2`, `E/A^3`, …) and is not converted when
the length and energy units change. See [Force field](forcefield.md).

## See also

- [Meta](meta.md)
- [Force field](forcefield.md)
- [Observables](observables.md)
