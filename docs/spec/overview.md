# Overview

## Purpose

MolRec is a **backend-neutral record contract** for the MolCrafts ecosystem.

It defines:

1. A minimal, fully general **data model** (containers with no privileged field names).
2. A **Record** root — the unit of interchange across tools.
3. Recommended **conventions** (domain section names and column names).
4. A **reference storage binding** (one Zarr root + metrics JSONL buffer).

It does **not** define a product class named `MolStore`, `SimStore`, or similar.
Implementations may provide record I/O APIs; the specification names **layout and
semantics**, not a store brand.

The design rule for L1 containers is: **the model has no special fields.**
Atoms, bonds, coordinates, charge density, and energy are conventional names
for ordinary blocks and columns. This keeps the model tiny and lets it carry
data its authors never anticipated.

## Layers (L0–L4)

| Layer | Name | Contents | Normativity |
|-------|------|----------|-------------|
| L0 | Vocabulary | dtypes, units, hard naming rules | Normative |
| L1 | Containers | Column · Block · Frame · Box | Normative |
| L2 | Record | Root sections, versioning, minimum shapes | Normative |
| L3 | Conventions | `system`, `trajectory`, `status`, `metrics`, … | Recommended |
| L4 | Backend binding | Zarr V3 root (arrays + document attrs) · metrics JSONL buffer | Reference only |

Details of L4: [Storage](storage.md).

## The model (L1)

### Column

A `Column` is a typed N-dimensional array. Its element type (`dtype`) is one of:

```text
float      64-bit floating point
int        signed integer
uint       unsigned integer
u8         8-bit unsigned integer
bool       boolean
string     UTF-8 string
```

The dtype set is closed; see [Types](types.md).

### Block

A `Block` is a set of named columns that share a common leading length, the
block's **count**:

```text
block
+-- <name>: Column
+-- <name>: Column
\-- ...
```

Every column in a block has the same axis-0 length. A block may also carry an
optional structural **shape** whose product equals the count — this lets one
block describe an N-D object (e.g. a volumetric grid `[nx, ny, nz]`) with the same
container as a flat table. When no shape is set, the block is a plain table of
`count` rows.

### Frame

A `Frame` is a snapshot: a set of named blocks, free-form metadata, and an
optional box.

```text
frame
+-- <block>: Block
+-- <block>: Block
+-- meta: key -> value
\-- (box)
```

A frame enforces no relationship between its blocks — it is a general container.
The count of one block is independent of another's, and any block name is legal.

### Box

`box` is an optional property of a frame: a triclinic simulation cell. It carries
cell vectors (columns are lattice vectors), an origin, and per-axis periodic
boundary flags. See [Frame](frame.md#box).

### Trajectory

A `trajectory` is an ordered sequence of frames, carrying a `step` (integer)
index array and an optional `time` (float) one, both aligned to the sequence. It
is a plain carrier; the canonical entity remains the frame. See
[Trajectory](trajectory.md).

## Model vs conventions

- **L0–L2** — this chapter, [Types](types.md), [Frame](frame.md), [Record](record.md)
  — are normative.
- **L3** — [Conventions](conventions.md), [System](system.md), [Run surface](run.md),
  and the section chapters — are recommended so tools interoperate.
- **L4** — [Storage](storage.md) — is the reference binding only.

A conforming reader must traverse the model. Interpreting an unknown convention
is optional, but unknown blocks and columns MUST be preserved.

## Records (L2)

A **Record** bundles optional companion sections under one root. See
[Record](record.md) for the full section map and versioning.

```text
/
+-- meta            required
+-- (system)        system definition
+-- (frame)         snapshot
+-- (trajectory)    frame sequence
+-- (observables)   scientific results
+-- (method)        scientific / training context
+-- (status)        execution lifecycle
\-- (metrics)       append-only run measurements
```

No record-root `parameters/`. Parameters: `system/parameters` or `method`.

### Minimum shapes

| Shape | Required | Notes |
|-------|----------|-------|
| Structure | `meta` + `frame` | Single snapshot |
| System def | `meta` + `system` | Definition without coordinates |
| Trajectory | `meta` + `trajectory` | `system` optional; with system prefer coords/state-only updates |
| **Run** | `meta` + `status` (+ `metrics` and/or `method`) | **No `frame` required** |
| Full | combinations | Experiment package |

A record MUST include `meta` and **at least one of** `frame`, `system`,
`trajectory`, or `status`.

`system` vs `frame`: definition vs instantaneous state — see [System](system.md).
Training / job logs: see [Run surface](run.md).

## Backend binding (L4)

The specification does not mandate a storage engine. The **reference** binding
is documented in [Storage](storage.md):

| Content | Reference form |
|---------|----------------|
| Openable package | **One Zarr V3 root** |
| Dense L1 tables (`frame`, `system`, `trajectory`, large observables) | Zarr array groups (molrs) |
| Documents (`meta`, `status`, `method`) | **Zarr group attributes** (not sibling `.json` files) |
| Closed metrics | **Dense Zarr series** under `metrics/` (catalog attrs + arrays) |
| Live metrics WAL | **Append-only JSONL** `metrics/metrics.jsonl` (densify on flush) |

Contract rules that travel with L4:

- No product API name `MolStore` / `SimStore`.
- Cell name is **`Box` / `box` only**.
- Sole schema version key: **`record_schema_version`** (starts at 1).
- Reference I/O lands in **molrs first**; consumers re-export — never a second
  layout brand.
- **No backward-compatible dual reads** of retired keys; migrate offline.

## Normative invariants

The following invariants define the current MolRec contract
(`record_schema_version = 1`):

1. L1 has exactly three containers — Column, Block, Frame — with no privileged
   field names.
2. A Column's dtype is one of `float`, `int`, `uint`, `u8`, `bool`, `string`.
3. All columns in a Block share the same count (axis-0 length).
4. A Block's optional structural shape has product equal to its count.
5. A Frame is a general map of names to Blocks; it enforces no cross-block
   relationship.
6. `box`, when present, is a triclinic cell whose `vectors` columns are lattice
   vectors.
7. A trajectory is an ordered list of frames with an aligned `step` array and an
   optional aligned `time` array.
8. A reader must preserve blocks, columns, and record sections it does not
   recognize.
9. A Record requires `meta` and at least one of `frame`, `system`, `trajectory`,
   or `status`.
10. Instantaneous Cartesian coordinates are not required content of `system/`.
11. Live metrics use the JSONL text buffer when present; Zarr metrics attributes
    are summary-only.
