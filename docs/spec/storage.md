# Root layout

This chapter is the layout of a record on the [Zarr V3](zarr.md) reference
binding. How arrays are chunked, sharded, compressed, and packed is
[Chunking and packing](chunking.md). Live metrics are
[Metrics WAL](metrics-wal.md). The trajectory encoding is
[Ragged trajectory](ragged.md).

Implemented first in [molrs](https://github.com/MolCrafts/molrs). Run hosts
(molexp / molnex) own the metrics WAL.

## Design in one sentence

One Zarr V3 root holds the whole record (array groups + document sections as
group attributes). Metrics curves densify to Zarr arrays; live metrics
append as a JSONL WAL.

## Two physical forms

| Form | Holds | Role |
|------|--------|------|
| **Zarr V3 root** | Every record section, including dense metrics series | Canonical, openable package |
| **JSONL text WAL** | Live `metrics` events only | Append-only log while a run is writing |

Document objects live as Zarr group attributes.

Rules:

1. Document sections (`meta`, `status`, `method`) → Zarr group attributes
   (one JSON object per section group).
2. Array sections (`frame`, `system`, `trajectory`, observable arrays) →
   Zarr groups + arrays.
3. Closed metrics → dense Zarr series arrays + catalog attributes
   ([Metrics](metrics.md)).
4. Live metrics → append-only UTF-8 JSONL WAL (`metrics/metrics.jsonl`);
   densify into Zarr on flush / close.
5. Readers must preserve unknown sibling sections and unknown keys.

## Canonical root

One openable Zarr hierarchy. The live scientific record is a directory
`*.mrec/` — that directory *is* the Zarr V3 root (`zarr.json` lives at
that root):

```text
<record-root>                       # *.mrec/ — this directory IS the Zarr V3 root
 \-- meta                           # group attributes = meta document
 \-- (status)                       # group attributes = status document
 \-- (method)                       # group attributes = method document
 \-- (metrics)
 |    +-- (catalog attributes)
 |    \-- (series)
 |    |    \-- <safe_name>          # dense float64 values (when densified)
 |    \-- (metrics.jsonl)           # live WAL (when a stream exists)
 \-- (system)
 \-- (frame)
 \-- (trajectory)                   # step, time, meta, box, <block> (CSR)
 \-- (observables)
```

A **host** (e.g. a molexp run directory) keeps identity / lifecycle in its
own files (`run.json`, a run-root `alive` heartbeat) and filename-gates
metrics so UIs (molplot) activate from those names:

```text
<run-dir>
 \-- executions/<id>/artifacts/
 |    \-- <stem>.mlp.jsonl     # live JSONL WAL — the metrics persist surface
 |    \-- (<name>.mlp.vl.json) # optional Vega-Lite plot artifact
 \-- (<stem>.mlp.zarr/)        # leftover dense store; ignored, never a surface
 \-- (<stem>.mlp.index.json)   # leftover host cache; never a UI trigger
```

Default writer stem is `metrics` → `artifacts/metrics.mlp.jsonl`. Discovery
and plugin activation match `*.mlp.jsonl` only; leftover `*.mlp.zarr/` and
`*.mlp.index.json` are recognised solely so they can be ignored.

A scientific record that lands *under* the host (typically `artifacts/`) is
still one Zarr root, named `*.mrec/` and discovered by that suffix plus the
presence of a Zarr root (`zarr.json` at the top). Scientific paths use
`*.mrec/` / `*.mrec.zip`. Host metrics stay on the filename-gated `*.mlp.*`
surface.

### Run-shaped root (no frame)

Still one Zarr root — only fewer groups:

```text
<record-root>
 \-- meta
 \-- status
 |    +-- state
 \-- (method)
 \-- (metrics)
      +-- (catalog attributes)
      \-- (series)
      \-- (metrics.jsonl)
```

No pure-JSON filesystem package is part of the reference binding.

## Section → form map

| Section | Logical content | On disk (reference) |
|---------|-----------------|---------------------|
| `meta` | Identity document (may be empty) | Zarr group attributes on `meta/` |
| `status` | Lifecycle snapshot | Zarr group attributes on `status/` |
| `method` | Scientific / training context | Zarr group attributes on `method/` |
| `metrics` (live) | Append-only events | JSONL WAL — Record: `metrics/metrics.jsonl`; host: `artifacts/<stem>.mlp.jsonl` |
| `metrics` (closed) | Dense series catalog | Zarr arrays — Record: `metrics/`. A host keeps only the WAL; leftover `*.mlp.zarr/` is ignored |
| `system` | Definition (topology, types, params) | Zarr array groups |
| `frame` | Instantaneous snapshot | Zarr array groups |
| `trajectory` | Ordered frames | Zarr array groups; [CSR + `step_index`, elided while regular](ragged.md) |
| `observables` | Named scientific results | Zarr arrays + per-name attribute metadata |

## Document sections

Logical field types in [Metadata](overview.md#metadata), [Status](status.md),
and [Method](method.md) are plain JSON (`string`, `number`, `object`,
`array`).

On disk, each section is one JSON object stored as the attribute map of the
corresponding empty (or array-free) Zarr group. The attribute object must be
exactly the document that section chapters describe.

| Section | Group path | Required keys when group exists |
|---------|------------|----------------------------------|
| `meta` | `meta/` | none — `molrec_version` is optional (see [Metadata](overview.md#metadata)) |
| `status` | `status/` | `state` |
| `method` | `method/` | `type`, `description`, `engine.name` |

Identity of a scientific record is the path suffix `*.mrec/` plus the Zarr
root itself. Writers always create the root group `zarr.json` and the
`meta/` group first — with the caller's document or an empty attribute map
— and only then the sections; a reader treats a missing `meta/` as an empty
document.

## Array groups

Reference implementation: molrs — `molrs.io.mrec.write_frame` /
`write_system` / `write_trajectory` and the streaming
`molrs.io.mrec.TrajectoryWriter`, with `read_frame` / `read_system` /
`read_trajectory` / `read_meta` on the way back.

- A frame-shaped section (`frame/`, `system/`) is a group of named blocks;
  each block is a group of named columns (arrays). Optional `box` is part of
  the frame group ([Containers](frame.md)).
- Column dtypes map per [Data types](frame.md#data-types).
- A trajectory is one group per section. Full rules:
  [Ragged trajectory](ragged.md); commit protocol and reopen rule:
  [Chunking and packing](chunking.md#normative).
- `observables/<name>` holds data arrays; `observables/meta/<name>` holds
  semantic attributes ([Observables](observables.md)).
- Dense metrics series use float64 arrays under `metrics/series/` on a
  record; see [Metrics](metrics.md) and [Metrics WAL](metrics-wal.md).
  Hosts keep only the WAL.

## Invariants

1. The openable package is a Zarr V3 root. The live scientific record
   directory `*.mrec/` *is* that root; the packed at-rest form is
   `*.mrec.zip` ([Chunking and packing](chunking.md)). Host metrics stay on
   the filename-gated `*.mlp.jsonl` WAL surface.
2. Document sections are group attributes.
3. Closed metrics use dense Zarr series arrays; live metrics may use an
   append-only JSONL WAL under `metrics/metrics.jsonl`.
4. Array sections use Zarr array groups. Trajectory uses the
   [ragged CSR layout](ragged.md).
5. Preserve unknown sections and keys.
6. `meta/` always exists (possibly empty). `meta["molrec_version"]` is
   optional during development: absent means no version check; present
   means an integer `>= 1`, no greater than the newest the reader supports.
   Scientific paths use `*.mrec/` / `*.mrec.zip`.
7. Data precede metadata. A writer lands chunk bytes before it replaces an
   array's `zarr.json` (atomically), `step` last of all, and a reader is
   bound by the trajectory group's `nstep` attribute.
