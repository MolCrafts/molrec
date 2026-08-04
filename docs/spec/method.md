# Method

## Purpose

`method` stores the scientific context needed to interpret a MolRec record. It is
part of the **run surface** (with [Status](status.md) and [Metrics](metrics.md))
— see [Run surface](run.md).

It is a recommended record section — a convention layered on the general model
(see [Overview](overview.md)).

It answers questions such as:

- what class of method produced this record
- which engine wrote it
- which force field, model, or solver was used
- which important settings define the calculation

`method` is descriptive metadata. It is not the place for result arrays.

## Structure

```text
method
+-- type: String[]
+-- description: String[]
+-- engine
|   +-- name: String[]
|   \-- (version: String[])
+-- (order: String[nstage])
\-- (stages)
    +-- <stage_id>
    |   +-- type: String[]
    |   +-- description: String[]
    |   \-- ...
    \-- ...
```

`method/type` selects the parse rules for the subtree.

MolRec 0.1 ships with standard types such as `classical`, `ml`, `electronic_structure`, and
`workflow`, but `method` is not restricted to a fixed closed vocabulary.

Any custom method type is valid if its parse rules are documented in a module declared under
`meta/modules`.

## Typed method schemas

The interpretation of `method` is driven by `type`, not by hard-coded subtree names alone.

Rules:

- `method/type` is required
- `method/description` is required
- `method/engine/name` is required
- custom method types must define their parse rules in a module declared under `meta/modules`
- result arrays stay in `frame`, `trajectory`, or `observables`

## Standard types

### `classical`

Typical content includes:

- force field identity
- bonded and nonbonded model choices
- integrator
- thermostat
- barostat
- cutoff and long-range settings

### `ml`

Typical content includes:

- model family
- checkpoint or model identifier
- representation or descriptor family
- inference precision
- training provenance if needed for interpretation

### `electronic_structure`

Typical content includes:

- method family such as HF, DFT, MP2
- functional
- basis set
- pseudopotential or effective core potential
- SCF settings
- spin treatment
- convergence thresholds

### `workflow`

`workflow` is used for multi-stage or composite workflows.

Required structure:

- `method/type = "workflow"`
- `method/order`
- `method/stages/<stage_id>/type`

Typical content includes:

- stage names
- stage order
- stage-specific engines
- stage-specific methods
- stage-specific inputs and outputs
- stage-specific targets such as `/frame/atoms` or `/observables/free_energy`

Each stage is itself a typed method block and may use any standard or custom type.

### Custom method types

MolRec allows custom method types such as:

- QM/MM
- enhanced sampling variants
- active-learning loops
- multiscale workflows

The only requirement is that the `type` be declared and its parse rules be documented in a module
declared under `meta/modules`.

## Example

```text
method
+-- type: "workflow"
+-- description: "Geometry relaxation followed by single-point DFT"
+-- engine
|   \-- name: "MolFlow"
+-- order: ["relax", "single_point"]
\-- stages
    +-- relax
    |   +-- type: "classical"
    |   +-- description: "Pre-relaxation with a classical force field"
    |   \-- force_field: "GAFF"
    \-- single_point
        +-- type: "electronic_structure"
        +-- description: "Single-point DFT evaluation"
        +-- family: "DFT"
        +-- functional: "PBE"
        +-- basis: "def2-SVP"
        \-- spin: "restricted"
```
