# Record

## Purpose

A **Record** is the top-level unit of interchange in MolRec: one self-describing
package of scientific or operational data that any MolCrafts tool may read
without guessing private layouts.

A Record is **not** a store product, a file format brand, or a class named
`MolStore` / `SimStore`. Those names are forbidden in this specification.
Implementations may expose APIs such as `open_record` or
`RecordReader` / `RecordWriter`; the **contract** is the layout and semantics
below.

## Root layout

```text
<record-root>/
├── meta/                 # required — identity, schema version, modules
├── system/               # recommended — system definition (see system.md)
├── frame/                # recommended — instantaneous snapshot (see frame.md)
├── trajectory/           # optional — ordered frames (see trajectory.md)
├── observables/          # optional — scientific results (see observables.md)
├── method/               # optional — how it was produced (see method.md)
├── status/               # optional — lifecycle / progress (see status.md)
└── metrics/              # optional — append-only run measurements (see metrics.md)
```

There is **no** record-root `parameters/` section. Scientific / force-field /
model parameters live under `system/parameters`. How a job is run lives under
`method/`.

Section names above are **conventional record keys**. Unknown sibling sections
MUST be preserved by readers that do not understand them.

Physical forms (JSON vs Zarr vs JSONL) for each section: [Storage](storage.md).

## Versioning

`meta` **MUST** carry (for writers of new records):

| Key | Meaning |
|-----|---------|
| `record_schema_version` | **Sole** schema version integer for the whole record (layout + L1 encoding). Starts at **1**. |
| `format_name` | Record format brand — not a binding id or storage discriminator. Optional at L2 (a backend-neutral record may omit it). The reference binding **MUST** emit `mrec` and **MUST** reject a missing value and any other string, including the retired `molrec`. Never a product name like `molpy-zarr`. |

There is **no** parallel `frame_schema_version` and **no** layout version key
named `meta.version`. New writers MUST NOT emit retired keys. Readers of the
current contract do **not** implement backward-compatible dual-key decoding;
migrate old files offline.

Full meta field table: [Meta](meta.md).

## Minimum record shapes

| Shape | Required sections | Typical use |
|-------|-------------------|-------------|
| Structure | `meta` + `frame` | Single conformation / snapshot |
| System def | `meta` + `system` | Topology / types without coordinates |
| Trajectory | `meta` + `trajectory` (+ optional `system`) | MD time series |
| Run | `meta` + `status` (+ `metrics` and/or `method`) | Training job / workflow run |
| Full | any combination | Reproducible experiment package |

Rules:

1. **`meta` is always required.**
2. A record MUST include **at least one of** `frame`, `system`, `trajectory`, or
   `status`. Each of the four is a valid **sole** section beside `meta`, matching
   the shapes table above: a trajectory-only record (`meta` + `trajectory`) is
   conforming, and a reader MUST NOT require a `frame` beside it.
3. A **Run**-shaped record does **not** require `frame`.
4. Instantaneous Cartesian coordinates belong on `frame` / `trajectory`, not as
   required content of `system` (see [System](system.md)).
5. When both `system/` and `trajectory/` are present, trajectory **SHOULD**
   carry state updates only (coordinates, instantaneous properties, instantaneous
   Box) and not restate topology.
6. Trajectory **MAY** omit `system/`; frames may then embed full blocks
   (compatible with frame-sequence writers).
7. The cell type/key in the contract is **`Box` / `box` only** — not `simbox`.

## Relationship to L1 containers

Record sections are built from the same containers as the rest of MolRec:

- **Column / Block / Frame** — [Types](types.md), [Frame](frame.md)
- Domain meaning of block names — [Conventions](conventions.md)

A `frame/` section is an L1 Frame. A `system/` section is a conventional tree
that may embed Blocks without time-dependent coordinates. Document sections
(`meta`, `status`, `method`) are JSON objects stored as **Zarr group
attributes**. Live metrics use an append-only **JSONL text buffer** under the
same root — see [Storage](storage.md).

## Backend binding (non-normative)

Summary — full chapter: [Storage](storage.md).

| Kind | Sections | Reference form |
|------|----------|----------------|
| Zarr root | whole package | One openable Zarr V3 hierarchy |
| Arrays | `frame`, `system`, `trajectory`, large `observables` | Zarr groups + arrays |
| Documents | `meta`, `status`, `method`, closed metrics summary | Zarr **group attributes** |
| Dense series | closed `metrics` | Zarr arrays under `metrics/` (+ catalog attrs) |
| Live WAL | live `metrics` | `metrics/metrics.jsonl` (UTF-8 text; densify on flush) |

There is **no** reference layout of loose `meta.json` / `status.json` beside
the store. molrs writes document sections as attributes; run hosts append the
metrics buffer.

## See also

- [Overview](overview.md) — L0–L4 layering
- [Storage](storage.md) — Zarr root + JSONL buffer
- [System](system.md) — system definition section
- [Run surface](run.md) — training / job logs as records
