<div align="center">

<h1>
  <img src=".github/assets/moko.svg" alt="" height="48" align="absmiddle">
  &nbsp;MolRec
</h1>

<p><strong>A backend-neutral record specification for atomistic data.</strong></p>

<p>
  <a href="https://img.shields.io/badge/license-BSD--3--Clause-18432B?style=flat-square"><img src="https://img.shields.io/badge/license-BSD--3--Clause-18432B?style=flat-square" alt="License"></a>
</p>

<p>
  <a href="docs/index.md"><b>Documentation</b></a> &nbsp;&middot;&nbsp;
  <a href="#record-structure"><b>Record structure</b></a> &nbsp;&middot;&nbsp;
  <a href="#molcrafts-ecosystem"><b>Ecosystem</b></a>
</p>

</div>

MolRec defines **what** a molecular record means — not how to implement it. Any
project that stores atoms, trajectories, force fields, or computed observables
can adopt MolRec as its semantic layer.

> **Under active development.** The specification may change between releases.

## Why MolRec

Atomistic simulations produce diverse data: atom coordinates, cell vectors, charge densities, energy time-series, force-field parameters, and more. Different codes store these in different formats with different conventions. MolRec provides a single, language-agnostic semantic model so that:

- A record written by one tool can be interpreted by another without guessing what the arrays mean.
- Metadata is always explicit — the spec never infers meaning from array shape or dataset name alone.
- The model is extensible to classical MD, ML potentials, electronic structure, and multi-stage workflows.

## Record structure

```text
/
+-- meta                  # record-level metadata (required)
+-- frame                 # canonical snapshot (required)
|   +-- atoms/            #   named collection: atoms
|   +-- bonds/            #   named collection: bonds
|   +-- <grids>/          #   named volumetric grids
|   +-- box               #   simulation cell (SimBox)
+-- trajectory            # time-series frames (optional)
+-- observables           # derived quantities (optional)
|   +-- <scalar>          #   e.g. total energy per step
|   +-- <vector>          #   e.g. dipole moment
|   +-- <grid>            #   e.g. charge density field
+-- status                # execution state and progress (optional)
+-- metrics               # runtime metric stream (optional)
+-- method                # scientific context (optional)
+-- parameters            # workflow parameters (optional)
```

`meta` and `frame` are mandatory. Everything else is optional.

## Key design principles

- **Collections, not just atoms.** A frame can hold atoms, bonds, angles, beads, fragments, or any named entity set.
- **Grid as a first-class type.** Volumetric data (charge density, electrostatic potential, etc.) is stored as `Grid` — both inside `frame` and as `ObservableKind::Grid` in observables.
- **Metadata is mandatory for observables.** Every observable carries explicit `kind`, `description`, and `time_dependent` fields.
- **Status is explicit.** Execution state, stage, progress counters, task status, and errors live under `status`.
- **Metrics are append-oriented.** Training curves, validation scores, and performance counters live under `metrics`, separate from scientific observables.
- **Box lives on frame.** The simulation cell (`SimBox`) is a property of each frame, not a separate root-level concept.
- **Backend-neutral.** The spec does not mandate a storage format. The reference implementation uses Zarr v3, but HDF5, SQL, or any other backend can implement the same semantics.

## Documentation

Full specification: [docs/index.md](docs/index.md)

## Reference implementation

[molrs](https://github.com/MolCrafts/molrs) provides a Rust + Python implementation of MolRec with Zarr v3 as the storage backend.

## MolCrafts ecosystem

| Project | Role |
|---------|------|
| [molpy](https://github.com/MolCrafts/molpy)     | Python toolkit — the shared molecular data model & workflow layer |
| [molrs](https://github.com/MolCrafts/molrs)     | Rust core — molecular data structures & compute kernels (native + WASM) |
| [molpack](https://github.com/MolCrafts/molpack) | Packmol-grade molecular packing (Rust + Python) |
| [molvis](https://github.com/MolCrafts/molvis)   | WebGL molecular visualization & editing |
| [molexp](https://github.com/MolCrafts/molexp)   | Workflow & experiment-management platform |
| [molnex](https://github.com/MolCrafts/molnex)   | Molecular machine-learning framework |
| [molq](https://github.com/MolCrafts/molq)       | Unified job queue — local / SLURM / PBS / LSF |
| [molcfg](https://github.com/MolCrafts/molcfg)   | Layered configuration library |
| [mollog](https://github.com/MolCrafts/mollog)   | Structured logging, stdlib-compatible |
| [molhub](https://github.com/MolCrafts/molhub)   | Molecular dataset hub |
| [molmcp](https://github.com/MolCrafts/molmcp)   | MCP server for the ecosystem |
| **molrec** | Atomistic record specification — this repo |

## License

BSD-3-Clause — see [LICENSE](LICENSE).

<hr>

<div align="center">
<sub>Crafted with 💚 by <a href="https://github.com/MolCrafts">MolCrafts</a></sub>
</div>
