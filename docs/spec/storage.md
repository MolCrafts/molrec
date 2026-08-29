# Storage

## Purpose

This chapter is the **L4 backend binding** of MolRec: how a logical Record is
laid out on disk. Semantics live in [Record](record.md) and the section
chapters; L4 only binds the **reference** physical form.

The contract remains **backend-neutral** at L0–L2. The reference binding below
is implemented first in [molrs](https://github.com/MolCrafts/molrs) (Zarr) with
run hosts (molexp / molnex) owning the metrics WAL + densify path.

MolRec does **not** name a product class `MolStore` / `SimStore`.

## Design in one sentence

> **One Zarr V3 root holds the whole record** (array groups + document sections
> as group attributes). **Metrics curves densify to Zarr arrays**; a JSONL file
> is only a **live WAL**, not a parallel document store for `meta` / `status` /
> `method`.

## Two physical forms

| Form | Holds | Role |
|------|--------|------|
| **Zarr V3 root** | Every record section, including **dense metrics series** | Canonical, openable package |
| **JSONL text WAL** | Live `metrics` events only | Append-only log while a run is writing |

There is **no** third form of sibling `meta/meta.json` / `status/status.json`
as a first-class binding. Document objects live as **Zarr group attributes**.

Rules:

1. Document sections (`meta`, `status`, `method`) → Zarr group attributes
   (one JSON object per section group).
2. Dense L1 tables (`frame`, `system`, `trajectory`, observable arrays) →
   Zarr groups + arrays.
3. **Closed metrics** → dense Zarr series arrays + catalog attributes
   ([Metrics](metrics.md)).
4. **Live metrics** → append-only UTF-8 JSONL WAL (`metrics/metrics.jsonl`);
   densify into Zarr on flush / close. Do **not** use per-step Zarr chunk
   append for the live stream.
5. Do **not** invent a second root layout or product name for the same sections.
6. Readers MUST preserve unknown sibling sections and unknown keys.

## Canonical record root

One openable Zarr hierarchy. Optional JSONL WAL sits under the `metrics/` path
as a plain text sibling (not a Zarr array):

```text
<record-root>/                      # Zarr V3 store root
├── meta/                           # group attributes = meta document
├── status/                         # group attributes = status document
├── method/                         # group attributes = method document
├── metrics/
│   ├── (group attributes)          # catalog / closed summary
│   ├── series/<safe_name>/         # dense float64 values (when densified)
│   └── metrics.jsonl               # live WAL (when a stream exists)
├── system/                         # frame-shaped array groups
├── frame/                          # frame-shaped array groups
├── trajectory/                     # step, time, meta/, box/, <block>/ (CSR)
└── observables/                    # meta/<name> attrs + <name> arrays
```

**Host layout** (e.g. a molexp Run directory) is **not a Record**. The host
keeps identity / lifecycle in its own files (`run.json`, `ops/run.json`) and
filename-gates metrics so UIs (molplot) activate without opening Zarr or
walking a `metrics/` directory:

```text
<run-dir>/
  <stem>.mlp.jsonl         # live JSONL WAL (default stem: metrics)
  <stem>.mlp.zarr/         # dense Zarr V3 SoT (series arrays + catalog attrs)
  <stem>.mlp.index.json    # host listing cache only (optional; never a UI trigger)
  <name>.mlp.vl.json       # optional Vega-Lite plot artifact (molplot)
```

Inside `*.mlp.zarr/` the series layout is the same catalog as a record
`metrics/` group (`series/<safe_name>/`, attrs `format_name=molmetrics`).
Discovery: match `*.mlp.jsonl`, `*.mlp.zarr`, `*.mlp.zarr/zarr.json`. Do
**not** match `*.mlp.index.json`.

A scientific Record that lands *under* the host (typically `artifacts/`) is
still one Zarr root, discovered by `meta/` attributes
(`record_schema_version`, optional `format_name=molrec`) — not by `*.mlp.*`.

### Run-shaped root (no frame)

Still one Zarr root — only fewer groups:

```text
<record-root>/
├── meta/              attributes: record_schema_version, format_name, …
├── status/            attributes: state, stage, …
├── method/            attributes: type, engine, …   (optional)
└── metrics/
    ├── (attributes)   catalog / summary
    ├── series/…       dense arrays when densified
    └── metrics.jsonl  live WAL when the run emits metrics
```

No pure-JSON filesystem package is part of the reference binding.

## Section → form map

| Section | Logical content | On disk (reference) |
|---------|-----------------|---------------------|
| `meta` | Identity + schema version | Zarr group **attributes** on `meta/` |
| `status` | Lifecycle snapshot | Zarr group **attributes** on `status/` |
| `method` | Scientific / training context | Zarr group **attributes** on `method/` |
| `metrics` (live) | Append-only events | **JSONL WAL** — Record: `metrics/metrics.jsonl`; host: `<stem>.mlp.jsonl` |
| `metrics` (closed) | Dense series catalog | **Zarr arrays** — Record: `metrics/`; host: `<stem>.mlp.zarr/` |
| `system` | Definition (topology, types, params) | Zarr array groups |
| `frame` | Instantaneous snapshot | Zarr array groups |
| `trajectory` | Ordered frames | Zarr array groups; one section per block, [CSR + `step_index`](trajectory.md#reference-layout-zarr) |
| `observables` | Named scientific results | Zarr arrays + per-name attribute metadata |

## Document sections (inside Zarr)

Logical field types in [Meta](meta.md), [Status](status.md), and
[Method](method.md) are plain JSON (`string`, `number`, `object`, `array`) —
not L1 Column shapes.

On disk, each section is **one JSON object** stored as the attribute map of
the corresponding empty (or array-free) Zarr group. The attribute object MUST
be exactly the document that section chapters describe.

| Section | Group path | Required keys when group exists |
|---------|------------|----------------------------------|
| `meta` | `meta/` | `record_schema_version` (see [Meta](meta.md)) |
| `status` | `status/` | `state` |
| `method` | `method/` | `type`, `description`, `engine.name` |

`format_name` on `meta` for this binding is **`molrec`** (never a product id
such as `molpy-zarr`).

## Array groups (Zarr V3)

Reference implementation: molrs (`write_record_*` / `read_record_*`).

- A **frame-shaped** section (`frame/`, `system/`) is a group of named
  **blocks**; each block is a group of named **columns** (arrays). Optional
  `box` is part of the frame group ([Frame](frame.md)).
- Column dtypes map per [Types](types.md).
- A **trajectory** is not a tree of per-frame groups. It is one group per
  section: dense `trajectory/step` (and optional `trajectory/time`,
  `trajectory/meta/<key>`) with one row per frame, plus `trajectory/box/` and
  one group per block, each carrying its own `step_index` of frame ordinals and
  — for a block — an `offset` row pointer over its columns. Full rules:
  [Trajectory](trajectory.md#reference-layout-zarr).
- `observables/<name>` holds data arrays; `observables/meta/<name>` holds
  semantic attributes ([Observables](observables.md)).
- Dense **metrics** series use float64 arrays under `metrics/series/` on a
  Record, or `*.mlp.zarr/series/` on a host; see [Metrics](metrics.md).

## Chunking, sharding, compression

How an array is cut up is a **backend choice, not a contract**: a conforming
reader opens any chunking, and two stores of the same data are expected to differ
byte for byte. The reference binding makes that choice as follows.

- **Inner chunk: a byte target, on the leading axis only.** One chunk aims for
  **512 KiB**, so a chunk spans `max(1, 512 KiB / row_bytes)` rows — never more
  than a fixed-size array's own length — where `row_bytes` is one row's width
  (the product of the trailing axes times the element size). Trailing axes are
  per-entity structure and are never split: a single entity would otherwise span
  several chunks. The target is bytes, not frames, so **a frame may straddle a
  chunk boundary**; that is what lets a million-atom frame work at all.
- **Shard: many chunks in one file.** A shard spans
  `chunks_per_shard × chunk` rows, with `chunks_per_shard` derived from a byte
  target of **256 MiB**: `max(1, 256 MiB / chunk_bytes)`. Fixed-size arrays
  (`frame/`, `system/`, observables) use the same chunk target and collapse into
  a single shard once they exceed four chunks; a trajectory's growing arrays have
  their chunk and shard extents **frozen at creation**, because a chunk grid
  cannot be re-planned under live data.
- **Shard index at the end** (`ShardingIndexLocation::End`, the Zarr default for
  `sharding_indexed`), so appending a chunk is a write at the tail of the shard
  file rather than a rewrite of it.
- **Compression is lossless `gzip`** on the inner chunks, unconditionally. No
  lossy codec is admitted, and `gzip` is the one codec every reader of these
  stores — wasm32 included — can decode.

The consequence that matters to a producer: a store costs
`total_bytes / shard_bytes + O(number of arrays)` files. **File count does not
scale with `nstep`.**

## At-rest form: `.zarr.zip`

A **closed** store MAY be packed into a single file: a zip of the directory store
in which every entry is **stored** (compression method 0). The chunks arrived
already gzipped, so packing is concatenation plus a central directory, and an
entry read out of the archive is bit-identical to the file it replaced.

Packing happens **after** the writer is closed. A live store is never packed: an
append needs in-place partial writes, which a zip cannot serve — so the running
form is a directory and the at-rest form is one file.

- Name: `<store>.zarr` packs to `<store>.zarr.zip`.
- Read path: any zip-backed Zarr store adapter — zarrs' `ZipStorageAdapter`, or
  zarr-python's `zarr.storage.ZipStore`. No bespoke archive format is involved.
- Random access survives packing (central directory plus per-entry byte ranges),
  and the at-rest file count is 1.

## Metrics WAL (live only)

The live metrics path is an **append-only text WAL**, not the closed SoT:

```text
metrics/metrics.jsonl     # Record root
<stem>.mlp.jsonl          # host Run (default stem: metrics)
```

Role of the WAL:

- High-frequency writers (training steps, MD monitors) **append** one UTF-8
  JSON object per line, terminated by `\n`.
- Writers MUST NOT rewrite or delete historical lines.
- Crash recovery = keep the file; readers skip blank / malformed lines.
- On flush / close, densify into Zarr series arrays (SoT).

### Compact keys

| Logical field | Compact key |
|---------------|-------------|
| `type` | `t` |
| `key` | `k` |
| `step` | `s` |
| `wall_time` | `w` |
| `value` | `v` |
| `tags` | `tags` |

Example line:

```json
{"t":"scalar","k":"train/loss","s":120,"w":"2026-08-04T12:00:00","v":0.42}
```

Full field tables and types: [Metrics](metrics.md).

### Authority

| Artifact | Authoritative for curves? | When |
|----------|---------------------------|------|
| Dense Zarr series | **Yes** when present | After densify / close |
| JSONL WAL | Live / fallback only | During a run; if no dense store |
| Catalog attrs / host `*.mlp.index.json` | No — listing | Optional; never a UI trigger |

There is **no** separate first-class `metrics/index.json` on a Record;
hosts MAY rebuild `*.mlp.index.json` beside the WAL.

## Versioning and hard cut

- Sole schema key: `meta.record_schema_version` (integer, starts at **1**).
- No `frame_schema_version` in the contract.
- No dual layout of document sections as loose `.json` files next to Zarr.
- New readers do **not** dual-decode retired keys or private layouts; migrate
  offline.

### The trajectory layout cut, and what it costs an old reader

The trajectory section described in [Trajectory](trajectory.md) replaced a tree
of per-frame groups (`trajectory/frames/<i>/`, written by molrs 0.13 and older).
The cut is hard: there is one encoder and one decoder, and no dual-decoding
reader exists. A reader of the current contract meeting such a store refuses it
by name — `legacy layout (written by molrs <= 0.13); re-write with 0.13` —
rather than returning an empty trajectory.

The reverse direction cannot be fixed, so it is stated rather than softened: a
molrs <= 0.13.2 reader meeting a store in this layout fails with
`trajectory.step length mismatch: expected 0, got N` — silently empty only when
`nstep == 0` — and the message names the wrong cause: it reports a step-length
mismatch where the real cause is the changed layout. `record_schema_version`
deliberately stays **1**, so the precise `unsupported record_schema_version` path
is not taken.

## Normative invariants (L4 reference)

1. The openable package is a **Zarr V3 root**.
2. Document sections are **group attributes**, not sibling document stores.
3. Closed metrics use **dense Zarr series arrays**; live metrics may use an
   **append-only JSONL WAL** under `metrics/metrics.jsonl`.
4. Dense L1 tables use Zarr array groups.
5. Preserve unknown sections and keys.
6. No product API name `MolStore` / `SimStore`.
