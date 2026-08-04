<div align="center">

<h1>
  <img src=".github/assets/moko.svg" alt="" height="48" align="absmiddle">
  &nbsp;MolRec
</h1>

<p><strong>Backend-neutral record contract for the MolCrafts ecosystem.</strong></p>

<p>
  <a href="https://img.shields.io/badge/license-BSD--3--Clause-18432B?style=flat-square"><img src="https://img.shields.io/badge/license-BSD--3--Clause-18432B?style=flat-square" alt="License"></a>
</p>

<p>
  <a href="docs/index.md"><b>Documentation</b></a> &nbsp;&middot;&nbsp;
  <a href="#record-structure"><b>Record structure</b></a> &nbsp;&middot;&nbsp;
  <a href="#molcrafts-ecosystem"><b>Ecosystem</b></a>
</p>

</div>

MolRec defines **what a scientific record means** — not a store product, not a
class named `MolStore` / `SimStore`, and not “Frame only.”

Any project that shares:

- molecular **systems** (topology, types, parameters),
- **snapshots** and **trajectories**,
- **scientific observables**, or
- **training / job execution logs** (status + metrics + method)

should adopt MolRec as the semantic layer so tools interoperate without guessing
private layouts.

> **Under active development.** The specification may change between releases.

## Why MolRec

Atomistic and ML workflows produce diverse data: coordinates, cells, densities,
energies, force-field tables, training curves, and workflow state. Different
codes invent different formats. MolRec provides one language-agnostic contract:

- A record written by one tool can be read by another without private guessing.
- Metadata is explicit — meaning is never inferred from array shape alone.
- The same root serves MD packages, electronic-structure results, and training runs.

## Record structure

```text
/
+-- meta                  # required — identity, schema version
+-- system                # recommended — system definition (no required xyz)
+-- frame                 # recommended — instantaneous snapshot
+-- trajectory            # optional — frame sequence
+-- observables           # optional — scientific results
+-- status                # optional — lifecycle / progress (run surface)
+-- metrics               # optional — append-only run measurements
+-- method                # optional — scientific / training context
```

There is **no** root `parameters/` (use `system/parameters` or `method`).

`meta` is mandatory. A record must also include **at least one of** `frame`,
`system`, or `status`. A **Run**-shaped record (`meta` + `status`) does not
require a frame. Trajectory may omit `system/`. The cell is **Box** only; the
sole version key is **`record_schema_version` (1)**. See
[docs/spec/record.md](docs/spec/record.md) and
[docs/spec/run.md](docs/spec/run.md).

## Layers

| Layer | Role |
|-------|------|
| L0 Vocabulary | dtypes, units, hard naming rules |
| L1 Containers | Column · Block · Frame · Box |
| L2 Record | Root sections and minimum shapes |
| L3 Conventions | Domain section and field names |
| L4 Backend binding | Arrays: Zarr V3 in molrs; metrics stream: JSONL (`metrics/metrics.jsonl`) |

## Key design principles

- **Record first.** Frame is an L1 container; the unit of ecosystem interchange is the Record.
- **Single root.** One Record is one openable root — no nested Record trees in L2.
- **System ≠ state.** `system/` defines the system; coordinates live on `frame` / `trajectory`.
- **Run surface.** Training and jobs use `status` + `metrics` + `method` as one surface.
- **Box only.** The cell contract name is `Box` / `box` — not `simbox`.
- **One schema version.** `meta.record_schema_version` (starts at 1); no parallel `frame_schema_version`.
- **molrs first.** Reference Zarr I/O for array sections lands in molrs; molpy re-exports — never a second layout named MolStore. Live **metrics** use JSONL append (`metrics/metrics.jsonl`), not Zarr.
- **Hard cut.** New writers do not dual-read retired keys or private layouts; migrate offline.
- **Collections, not only atoms.** Named blocks carry any entity set.
- **Preserve the unknown.** Readers keep sections, blocks, and columns they do not interpret.
- **Backend-neutral.** Semantics do not require Zarr; Zarr V3 is the reference binding only.

## Documentation

Full specification: [docs/index.md](docs/index.md)

## Reference implementation

[molrs](https://github.com/MolCrafts/molrs) implements L1 containers and the
reference Zarr binding. Other packages **consume** the contract; they must not
ship a parallel store product name for the same layout.

## MolCrafts ecosystem

| Project | Role |
|---------|------|
| [molpy](https://github.com/MolCrafts/molpy) | Python toolkit & workflows |
| [molrs](https://github.com/MolCrafts/molrs) | Rust core — containers & compute (reference MolRec binding) |
| [molpack](https://github.com/MolCrafts/molpack) | Molecular packing |
| [molvis](https://github.com/MolCrafts/molvis) | Visualization |
| [molexp](https://github.com/MolCrafts/molexp) | Experiment / run management |
| [molnex](https://github.com/MolCrafts/molnex) | ML framework (run surface consumer) |
| [molq](https://github.com/MolCrafts/molq) | Job queue |
| [molcfg](https://github.com/MolCrafts/molcfg) | Configuration |
| [mollog](https://github.com/MolCrafts/mollog) | Logging |
| [molhub](https://github.com/MolCrafts/molhub) | Dataset hub |
| [molmcp](https://github.com/MolCrafts/molmcp) | MCP server |
| **molrec** | **Record contract — this repo** |

## License

BSD-3-Clause — see [LICENSE](LICENSE).

<hr>

<div align="center">
<sub>Crafted with 💚 by <a href="https://github.com/MolCrafts">MolCrafts</a></sub>
</div>
