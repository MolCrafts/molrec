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

MolRec defines **what a scientific record means**.

Any project that shares:

- molecular **systems** (topology, types),
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

## Root layout

```text
/
+-- meta                  # required — identity document (may be empty)
+-- system                # optional — system definition (no required xyz)
+-- frame                 # optional — instantaneous snapshot
+-- trajectory            # optional — frame sequence
+-- observables           # optional — scientific results
+-- status                # optional — lifecycle / progress (run surface)
+-- metrics               # optional — append-only run measurements
+-- method                # optional — scientific / training context
```

Force-field parameters: see the [force field](docs/spec/forcefield.md) chapter; how a job was run lives under `method`.

`meta` is mandatory (an empty document is valid); `system` and `frame` are
optional. A record also includes **at least one of** `frame`, `system`,
`trajectory`, or `status`. A **Run**-shaped record (`meta` + `status`) is
valid on its own; a trajectory-only record (`meta` + `trajectory`) is
equally valid, and trajectory may omit `system/`. The cell is **Box**.
Every writer stamps `meta["molrec_version"]` (currently `1`); readers
validate it only when present — an absent key marks a store written before
version 1. A record is identified by its `*.mrec` path suffix plus its Zarr
root. See the [format specification](docs/spec/specification.md).

## Key design principles

- **Record first.** Column / Block / Frame / Box are how a record holds array data. A trajectory is a record section.
- **Single root.** One Record is one openable root.
- **System and state.** `system/` defines the system; coordinates live on `frame` / `trajectory`.
- **Run surface.** Training and jobs use `status` + `metrics` + `method` as one surface.
- **Box.** The cell contract name is `Box` / `box`.
- **One schema version.** Writers stamp `meta["molrec_version"]` (integer, currently 1); readers validate it when present and refuse a newer one.
- **Zarr + metrics WAL.** One Zarr V3 root holds arrays and document sections (group attributes). Closed metrics densify to Zarr series; live metrics use an append-only JSONL WAL (`metrics/metrics.jsonl`). The trajectory encoding is the [ragged CSR layout](docs/spec/ragged.md).
- **Hard cut.** Writers emit the current keys (`sequence_schema`, `meta_dtype`, no vendor prefixes); migrate older files offline.
- **Collections.** Named blocks carry any entity set.
- **Preserve the unknown.** Readers keep sections, blocks, and columns they do not interpret.
- **Backend-neutral.** Semantics are independent of the store; the Zarr root + JSONL buffer is the reference binding.

## Documentation

Full specification: [docs/index.md](docs/index.md) ·
[format specification](docs/spec/specification.md)

## Reference implementation

[molrs](https://github.com/MolCrafts/molrs) implements the containers and the
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
