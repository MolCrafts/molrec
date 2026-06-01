# Types

## Purpose

This chapter defines the basic typed semantics used in MolRec.

The purpose of a type definition here is semantic, not language-specific. It tells a developer how a
dataset or metadata block should be interpreted and which fields are required to make that
interpretation stable.

These type definitions are used in two places:

- observable metadata under `observables/meta/<name>`
- typed schema blocks such as `method`

## Core rule

A shape or subtree name alone is not enough to define meaning.

MolRec therefore treats an observable as:

- raw data in `observables/<name>`
- semantic metadata in `observables/meta/<name>`

and a typed metadata block such as `method` as:

- a subtree rooted at `method`
- a required `type` field selecting its parse rules

At minimum, observable metadata must state:

- what kind of object the data are
- what the axes mean
- whether the data are time-dependent
- what sampling or domain model is used when relevant

At minimum, a typed metadata block must state:

- what `type` it uses
- which fields are required by that type
- how custom extensions should be parsed

## Observable metadata contract

The following fields define the minimum contract for `observables/meta/<name>`:

- `kind`: high-level data kind
- `description`: required human-readable meaning
- `time_dependent`: whether a leading time axis is present semantically
- `axes`: required when the data rank is greater than zero
- `unit`: required when the values carry a physical unit
- `sampling`: required when the values are samples over time, entities, grids, or point sets
- `domain`: required when the values live on a named domain
- `target`: required when interpretation depends on alignment to another subtree or collection

Each `kind` may require additional fields beyond this common contract.

## Relationship to metrics

The observable kinds in this chapter describe scientific data under `observables`.

Runtime metric records under `metrics` use the metric record contract in [Metrics](metrics.md), not
the observable metadata contract. A value may appear in both places only when it is both useful for
live monitoring and part of the interpreted scientific record.

## Scalar

A scalar represents one value per sample.

Typical shapes:

- `[]`
- `[ntimestep]`

Typical metadata:

```text
meta/<name>
+-- kind: "scalar"
+-- description: "..."
+-- time_dependent: false
```

Time-dependent scalar:

```text
meta/<name>
+-- kind: "scalar"
+-- description: "..."
+-- axes: ["timestep"]
+-- time_dependent: true
+-- sampling: "trajectory_sample"
+-- domain: "trajectory"
```

Required fields:

- `kind`
- `description`
- `time_dependent`
- `axes` if the stored shape has rank greater than zero
- `sampling` and `domain` when sampled over trajectory steps

Examples:

- total energy
- temperature
- RMS force
- SCF residual

## Vector

A vector represents an ordered tuple of components.

Typical shapes:

- `[ndim]`
- `[ntimestep][ndim]`

Typical metadata:

```text
meta/<name>
+-- kind: "vector"
+-- description: "..."
+-- axes: ["component"]
+-- time_dependent: false
```

Time-dependent vector:

```text
meta/<name>
+-- kind: "vector"
+-- description: "..."
+-- axes: ["timestep", "component"]
+-- time_dependent: true
+-- sampling: "trajectory_sample"
+-- domain: "trajectory"
```

Required fields:

- `kind`
- `description`
- `axes`
- `time_dependent`

Examples:

- dipole moment
- total momentum
- polarization vector

## Tensor

A tensor represents a rank-2 or higher component array.

Typical shapes:

- `[3][3]`
- `[ntimestep][3][3]`
- `[ntimestep][nstate][3][3]`

Typical metadata:

```text
meta/<name>
+-- kind: "tensor"
+-- description: "..."
+-- axes: ["row", "col"]
+-- time_dependent: false
```

Time-dependent tensor:

```text
meta/<name>
+-- kind: "tensor"
+-- description: "..."
+-- axes: ["timestep", "row", "col"]
+-- time_dependent: true
+-- sampling: "trajectory_sample"
+-- domain: "trajectory"
```

Required fields:

- `kind`
- `description`
- `axes`
- `time_dependent`

Examples:

- stress tensor
- polarizability tensor
- Hessian blocks

## Field

A field represents values defined over a sampled spatial domain.

Typical shapes:

- `[nx][ny][nz]`
- `[ntimestep][nx][ny][nz]`

Field metadata must say how the domain is sampled.

Minimum metadata:

```text
meta/<name>
+-- kind: "field"
+-- description: "..."
+-- axes: ["x", "y", "z"]
+-- sampling: "uniform_sample"
+-- domain: "real_space_grid"
+-- time_dependent: false
+-- grid_shape: Integer[3]
+-- origin: Float[3]
+-- spacing: Float[3]
```

Time-dependent field:

```text
meta/<name>
+-- kind: "field"
+-- description: "..."
+-- axes: ["timestep", "x", "y", "z"]
+-- sampling: "uniform_sample"
+-- domain: "real_space_grid"
+-- time_dependent: true
+-- grid_shape: Integer[3]
+-- origin: Float[3]
+-- basis_vectors: Float[3][3]
```

Required fields:

- `kind`
- `description`
- `axes`
- `time_dependent`
- `sampling`
- `domain`

Additional required fields by sampling mode:

- `uniform_sample`: `grid_shape`, `origin`, and one of `spacing` or `basis_vectors`
- `nonuniform_sample`: `points` or `points_target`

Examples:

- electron density
- electrostatic potential
- spin density
- volumetric occupancy

## Table

A table represents structured rows over one or more named axes.

Typical shapes:

- `[nrow][ncol]`
- `[ntimestep][nrow][ncol]`

Typical metadata:

```text
meta/<name>
+-- kind: "table"
+-- description: "..."
+-- axes: ["row", "column"]
+-- time_dependent: false
+-- columns: String[ncol]
```

Required fields:

- `kind`
- `description`
- `axes`
- `time_dependent`
- `columns` or an equivalent documented column schema

If a table samples a known domain or entity collection, it must also define `sampling`, `domain`,
and `target` as needed.

Examples:

- RDF bins and values
- band energies
- histogram outputs

## Sampling kinds

The `sampling` metadata field explains how the stored values sample an underlying object.

MolRec 0.1 recommends the following vocabulary.

### `uniform_sample`

The data are sampled on a uniform grid or regular lattice.

Typical use:

- volumetric fields on Cartesian grids
- regularly sampled 1D profiles

Required companion metadata:

- `axes`
- `domain`
- `grid_shape`
- `origin`
- `spacing` or `basis_vectors`

Example:

```text
meta/density
+-- kind: "field"
+-- sampling: "uniform_sample"
+-- domain: "real_space_grid"
+-- axes: ["x", "y", "z"]
```

### `nonuniform_sample`

The data are sampled on an irregular set of points.

Typical use:

- scattered probe values
- adaptive grids

Required companion metadata:

- `axes`
- `domain`
- `points` or `points_target`

### `entity_sample`

The data are sampled over a discrete entity collection already defined elsewhere in the record.

Typical use:

- per-atom scalar arrays
- per-bond values
- per-angle parameters

Required companion metadata:

- `domain`
- `target`

Examples:

- Mulliken charge per atom
- bond order per bond

### `trajectory_sample`

The data are sampled over the trajectory axis.

Typical use:

- total energy over steps
- convergence values over SCF iterations

Required companion metadata:

- `axes`
- `time_dependent = true`
- `domain`

### `custom`

Use `custom` when none of the standard sampling kinds fit.

If `custom` is used, `description` should explain the sampling model precisely.

If `custom` introduces additional parse rules, those rules must be documented in this chapter or in
a declared module specification.

## Domain kinds

The `domain` field explains what space the values live on.

Recommended values include:

- `record`
- `trajectory`
- `atom`
- `bond`
- `angle`
- `dihedral`
- `real_space_grid`
- `reciprocal_space_grid`
- `point_cloud`
- `custom`

## Typed schema blocks

Some MolRec subtrees are structured metadata objects rather than raw array datasets. `method` is the
main example.

A typed schema block must include:

- `type`
- any fields required by that type
- any nested typed blocks required by that type

Custom typed schemas are allowed, but their parse rules must be defined in this chapter or in a
module declared under `meta/modules`.

## Method schema types

The following method schema types are part of the MolRec 0.1 draft vocabulary.

### `classical`

Required interpretation:

- the block describes a classical simulation method
- the parse must expose force-field identity
- the parse must expose integrator details when dynamics are present

Common fields:

- `force_field`
- `integrator`
- `thermostat`
- `barostat`
- `cutoff`
- `long_range`

### `ml`

Required interpretation:

- the block describes an ML-based model or potential
- the parse must expose model identity and inference context

Common fields:

- `model_family`
- `model_id`
- `representation`
- `precision`
- `training_provenance`

### `electronic_structure`

Required interpretation:

- the block describes an electronic-structure method
- the parse must expose method family and basis or equivalent representation choices

Common fields:

- `family`
- `functional`
- `basis`
- `pseudopotential`
- `scf`
- `spin`
- `convergence`

### `workflow`

Required interpretation:

- the block describes a multi-stage workflow
- each stage is itself a typed method block

Required fields:

- `order: String[nstage]`
- `stages/<stage_id>/type`

Recommended fields:

- `stages/<stage_id>/engine`
- `stages/<stage_id>/inputs`
- `stages/<stage_id>/outputs`
- `stages/<stage_id>/target`

### Custom method types

Any custom method type is valid if:

- it declares `type`
- its parse rules are documented in this chapter or in a declared module specification
- readers that do not implement it can still identify the unknown type and preserve the raw subtree

## Examples

### Time-dependent scalar

```text
observables
\-- total_energy: Float[ntimestep]
\-- meta
    \-- total_energy
        +-- kind: "scalar"
        +-- description: "Total potential energy per trajectory step"
        +-- axes: ["timestep"]
        +-- time_dependent: true
        +-- sampling: "trajectory_sample"
        +-- domain: "trajectory"
        +-- unit: "eV"
```

### Per-atom scalar

```text
observables
\-- mulliken_charge: Float[N]
\-- meta
    \-- mulliken_charge
        +-- kind: "scalar"
        +-- description: "Mulliken charge aligned to the canonical atom collection"
        +-- axes: ["atom"]
        +-- time_dependent: false
        +-- sampling: "entity_sample"
        +-- domain: "atom"
        +-- target: "/frame/atoms"
        +-- unit: "e"
```

### Uniformly sampled field

```text
observables
\-- density: Float[nx][ny][nz]
\-- meta
    \-- density
        +-- kind: "field"
        +-- description: "Electron density on a uniform real-space grid"
        +-- axes: ["x", "y", "z"]
        +-- time_dependent: false
        +-- sampling: "uniform_sample"
        +-- domain: "real_space_grid"
        +-- grid_shape: [nx, ny, nz]
        +-- origin: [0.0, 0.0, 0.0]
        +-- basis_vectors: Float[3][3]
        +-- unit: "e bohr-3"
```
