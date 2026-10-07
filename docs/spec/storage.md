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
2. Array sections (`frame`, `system`, `trajectory`, `forcefield`'s style
   tables, observable arrays) → Zarr groups + arrays.
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
 |    +-- (catalog attributes)      # series summaries + the WAL watermark
 |    \-- (series)
 |    |    \-- <safe_name>          # dense float64 values (when densified)
 |    \-- (steps), (wall_time)      # per-point step / time, aligned with series
 |    \-- (metrics.jsonl)           # live WAL, a plain file (when a stream exists)
 \-- (system)
 \-- (frame)
 \-- (trajectory)                   # step, time, meta, box, <block> (CSR)
 \-- (forcefield)                   # document attrs + one block per style
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
| `system` | Definition (topology, types) | a [frame-shaped group](#frame-shaped-group) |
| `frame` | Instantaneous snapshot | a [frame-shaped group](#frame-shaped-group) |
| `trajectory` | Ordered frames | Zarr array groups; [CSR + `step_index`, elided while regular](ragged.md) |
| `forcefield` | Force-field document + style tables | Zarr group attributes + one block group per style ([Force field](forcefield.md)) |
| `observables` | Named scientific results | Zarr arrays + per-name attribute metadata |

## Document sections

Logical field types in [Metadata](overview.md#metadata), [Status](status.md),
and [Method](method.md) are plain JSON (`string`, `number`, `object`,
`array`).

On disk, each section is one JSON object stored as the attribute map of the
corresponding empty (or array-free) Zarr group. The attribute map **is** the
section's document: the keys its chapter names (a named key left unset is
absent, never `null`) plus every key a producer added, which a reader
preserves verbatim — a `null`-valued one included. Numbers are plain finite
JSON: a document cannot carry NaN or infinity.

| Section | Group path | Required keys when group exists |
|---------|------------|----------------------------------|
| `meta` | `meta/` | `molrec_version`, the current version stamped by every writer (absent only on a pre-1 store, read by version 1's rules; see [Metadata](overview.md#metadata)) |
| `status` | `status/` | `state` |
| `method` | `method/` | `type`, `description`, `engine.name` |

Identity of a scientific record is the path suffix `*.mrec/` plus the Zarr
root itself. Writers **MUST** create the root group `zarr.json` and the
`meta/` group first — the caller's document with the current
`molrec_version` stamped in — and only then the sections. A reader treats a
missing `meta/` as an empty document (a pre-1 store, read by version 1's
rules).

## Frame-shaped group

`frame/` and `system/` — and any producer section that declares itself
frame-shaped — share one normative layout:

```text
<frame-shaped group>
 +-- <meta key> ...               the group's attributes ARE the meta document
 +-- (_meta_types)                reserved: {key: tag} for every meta key
 \-- <block>
 |    +-- count: i64[]            required: the block's row count N (>= 0)
 |    +-- (structural_shape: i64[k])   optional: product equals count
 |    +-- (targets: {column: target})  optional: row references
 |    +-- (<other attribute>)     preserved
 |    \-- <column>: <dtype>[N][...]
 |         +-- (precision: f64[])      optional: the column's declared precision
 |    \-- (_validity)            reserved: the block's validity masks
 |         \-- (<column>: bool[N])
 \-- (box)                        reserved: the cell
```

- **The group's attributes are the frame's `meta` document**, exactly: every
  key a writer puts there is a meta key, and a reader hands every key back
  as one — except `_meta_types`. The frame group carries no other
  attributes (no version, no layout tag).
- **The meta document is typed.** The attribute `_meta_types` maps every key
  of the document to its [tag](ragged.md#per-step-metadata), and each value
  is in the [typed JSON form](conventions.md#typed-json-values) of that tag
  (so an `f64` NaN is `"NaN"` and a `u64` beyond 2⁵³ a decimal string). A
  writer emits an entry for every key and omits the attribute for an empty
  document; `_meta_types` is not a meta key, and a writer refuses a document
  that has one. A reader decodes a tagged key under its tag and refuses any
  other form; it infers the tag of an untagged key — `bool`; an integer in
  `[−2⁶³, 2⁶³)` as `i64`, in `[2⁶³, 2⁶⁴)` as `u64`; any other number `f64`;
  a string `string`; anything else `json` — and ignores a tag whose key is
  absent. The `forcefield` document is plain JSON and carries no
  `_meta_types`.
- **A column may declare a precision**: the array's attribute `precision`
  ([Declared precision](frame.md#declared-precision)). A reader preserves it
  and returns the stored values exactly.
- **A block is a child group**; its **columns are its child arrays**. Each
  block group carries the required integer attribute `count` — a block with
  no columns still has one, and a reader refuses a block whose columns
  disagree with it — and, for a volumetric block, `structural_shape`, whose
  product equals `count`, and, when set, `targets`
  ([Row references](frame.md#row-references)). Any other attribute of a
  block group is a producer's and is preserved.
- **Reserved child names.** Among a frame-shaped group's children, `box` is
  the [cell](frame.md#simulation-box) and is not a block; a block named
  `box` is refused at write. Among a block group's children, `_validity` is
  the subgroup of [validity masks](frame.md#nullable-columns); a column named
  `_validity` is refused at write. Nothing else is reserved: `meta`,
  `atoms`, `values` are ordinary block names, because the meta document is
  attributes.
- A reader preserves a block, a column, or a block attribute it does not
  recognise.

## Data types on Zarr V3

Each [column dtype](frame.md#data-types) is stored as exactly one Zarr V3
`data_type`; the mapping is total and exact in both directions.

| dtype | Zarr V3 `data_type` | Notes |
|-------|---------------------|-------|
| `f64` | `float64` | `float16` / `float32` arrays are refused, never widened |
| `i8` `i16` `i32` `i64` | `int8` `int16` `int32` `int64` | |
| `u8` `u16` `u32` `u64` | `uint8` `uint16` `uint32` `uint64` | |
| `bool` | `bool` | one byte per element, `0` / `1` |
| `string` | `string` | variable-length UTF-8, serialized by the `vlen-utf8` codec |
| `c64` `c128` | `complex64` `complex128` | interleaved (real, imaginary) |

- A string column is always the variable-length `string` type. A
  fixed-length string or raw-bytes type (`fixed_length_utf32`, `bytes`,
  `r*`) is not a column dtype, and a reader refuses it.
- Writers emit little-endian bytes (`bytes` codec with `endian: "little"`);
  a reader decodes either endianness, since `bytes` is in the must-decode
  codec set.
- A Zarr data type outside this table is not a column; a reader refuses it.

## Array groups

Reference implementation: molrs — `molrs.io.write_mrec` /
`write_mrec_system` / `write_mrec_trajectory` and the streaming
`molrs.io.mrec.MrecWriter`, with `read_mrec` / `read_mrec_system` /
`read_mrec_trajectory` / `read_mrec_meta` (and
`molrs.io.mrec.section_names`) on the way back.

- A frame-shaped section (`frame/`, `system/`) is a
  [frame-shaped group](#frame-shaped-group).
- `forcefield/` is laid out as a frame-shaped section whose attribute map is
  the force-field document and whose blocks are its style tables
  ([Force field](forcefield.md)).
- Column dtypes map per [Data types on Zarr V3](#data-types-on-zarr-v3).
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
6. Writers create `meta/` and stamp `meta["molrec_version"]` with the version
   they write (`2`), over any producer value. A reader validates the key when
   present: a JSON integer `>= 1`, no greater than the newest the reader
   supports, never `null`. It reads an older version's store by that
   version's rules — converting exactly or refusing, never reading it as
   its own ([Reading a version-1 record](forcefield.md#reading-a-version-1-record));
   absent means a pre-1 store, read by version 1's rules. `meta` is handed
   back as stored. A version-1 trajectory is not appended to. Scientific
   paths use `*.mrec/` / `*.mrec.zip`.
7. Data precede metadata. A writer lands chunk bytes before it replaces an
   array's `zarr.json` (atomically), and the trajectory group's `nstep`
   attribute — the commit marker — last of all; a reader is bound by it
   ([Chunking and packing](chunking.md#normative)).
