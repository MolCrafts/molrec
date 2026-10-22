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
├── forcefield/                     # attributes = force-field document
│   └── <style block>/              # one block per style
├── metrics/
│   ├── (group attributes)          # catalog: which series exist
│   ├── series/<safe_name>/         # dense f64 values (when densified)
│   └── metrics.jsonl               # live WAL (when a stream exists)
├── system/                         # frame-shaped array groups
├── frame/                          # frame-shaped array groups
├── trajectory/                     # step, time, frames/0..n-1/  (or packed)
└── observables/                    # shared coordinates + value arrays
```

One root. Metrics series are arrays in this root, under `metrics/series/`.
There is no nested `metrics/zarr/` store and no second format name for the
catalog. A host that is not itself a record still writes this `metrics/`
group inside the record it emits.

Discovery: open the Zarr root. Read documents from group attributes. Read
curves from `metrics/series/`. Read the WAL only while the run is live, or
when the dense series are absent.

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
| `metrics` (live) | Append-only events | **JSONL WAL** `metrics/metrics.jsonl` |
| `metrics` (closed) | Dense series catalog | **Zarr arrays** under `metrics/` (+ catalog attrs) |
| `system` | Definition (topology, types, params) | Zarr array groups |
| `frame` | Instantaneous snapshot | Zarr array groups |
| `trajectory` | Ordered frames | Zarr array groups; list or [packed](trajectory.md#packed-storage-convention) |
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
| `method` | `method/` | none — the document is open |

`format_name` on `meta` for this binding is **`molrec`** (never a product id
such as `molpy-zarr`).

## Array groups (Zarr V3)

Reference implementation: molrs (`write_record_*` / `read_record_*`).

- A **frame-shaped** section (`frame/`, `system/`, each trajectory frame) is a
  group of named **blocks**; each block is a group of named **columns**
  (arrays). Optional `box` is part of the frame group ([Frame](frame.md)).
- Column dtypes map per [Types](types.md).
- Trajectory reference layout in molrs today: `trajectory/step`,
  `trajectory/time`, `trajectory/frames/<i>/`. The [packed](trajectory.md)
  convention is an allowed optimisation over the same logical model.
- A block column with missing rows stores `bool[count]` at
  `<block>/_validity/<column>` ([Types](types.md#missing-values)). No mask
  means every row is present. `_validity` is not a column name.
- A volumetric block stores `sample` (`corner` or `center`) on the block
  group's attributes, beside `count` and `structural_shape`. Its own voxel
  edges, when present, are `f64` arrays at `<block>/_mesh/origin` and
  `<block>/_mesh/vectors`, with optional `boundary` and `unit` attributes
  ([Conventions](conventions.md#volumetric-data)). `_mesh` is not a column
  name. The field itself is a flat column of length `count`.
- Array names that are not a single Zarr path segment use **percent-encoding**:
  every UTF-8 byte outside `A–Z a–z 0–9 . _ -` is `%XX` with uppercase hex.
  `train/loss` is `train%2Floss`. The encoding is reversible.
- `observables/` holds shared coordinate arrays and value arrays
  ([Observables](observables.md)).
- Dense **metrics** series use float64 arrays under `metrics/series/` (or the
  host nested store); see [Metrics](metrics.md).

## Metrics WAL (live only)

The live metrics path is an **append-only text WAL**, not the closed SoT:

```text
metrics/metrics.jsonl
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
| `metrics/metrics.jsonl` | Live / fallback only | During a run; if no dense store |
| Catalog attrs only | No — listing | Optional |

There is **no** separate first-class `metrics/index.json` in the reference
binding; listing metadata belongs in Zarr attributes or is rebuilt by hosts.

## Versioning and hard cut

- Sole schema key: `meta.record_schema_version` (integer, starts at **1**).
- No `frame_schema_version` in the contract.
- No dual layout of document sections as loose `.json` files next to Zarr.
- New readers do **not** dual-decode retired keys or private layouts; migrate
  offline.

## Normative invariants (L4 reference)

1. The openable package is a **Zarr V3 root**.
2. Document sections are **group attributes**, not sibling document stores.
3. Closed metrics use **dense Zarr series arrays**; live metrics may use an
   **append-only JSONL WAL** under `metrics/metrics.jsonl`.
4. Dense L1 tables use Zarr array groups.
5. Preserve unknown sections and keys.
6. No product API name `MolStore` / `SimStore`.
