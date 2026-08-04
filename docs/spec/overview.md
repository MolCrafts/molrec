# Overview

## Purpose

MolRec is a **backend-neutral record contract** for the MolCrafts ecosystem.

It defines:

1. A minimal, fully general **data model** (containers with no privileged field names).
2. A **Record** root — the unit of interchange across tools.
3. Recommended **conventions** (domain section names and column names).

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
| L4 | Backend binding | Arrays: Zarr V3 in molrs; metrics stream: JSONL | Reference only |

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

A `trajectory` is an ordered sequence of frames, with optional `step` (integer)
and `time` (float) index arrays aligned to the sequence. It is a plain carrier;
the canonical entity remains the frame. See [Trajectory](trajectory.md).

## Model vs conventions

- **L0–L2** — this chapter, [Types](types.md), [Frame](frame.md), [Record](record.md)
  — are normative.
- **L3** — [Conventions](conventions.md), [System](system.md), [Run surface](run.md),
  and the section chapters — are recommended so tools interoperate.

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

A record MUST include `meta` and **at least one of** `frame`, `system`, or
`status`.

`system` vs `frame`: definition vs instantaneous state — see [System](system.md).
Training / job logs: see [Run surface](run.md).

## Backend binding (L4)

The specification does not mandate a storage engine. The **reference** binding
is Zarr V3 in [molrs](https://github.com/MolCrafts/molrs). Other backends may
implement the same section semantics.

MolRec never names a required product API `MolStore` or `SimStore`.
The cell is **`Box` / `box` only** in the contract. The sole schema version key
is **`record_schema_version`** (starts at 1). Reference I/O is implemented in
**molrs first**, then consumed by molpy via re-export — never a second layout
called MolStore. **No backward-compatible dual reads** of retired keys or
layouts; migrate offline.

## Normative invariants

The following invariants define MolRec 0.3:

1. L1 has exactly three containers — Column, Block, Frame — with no privileged
   field names.
2. A Column's dtype is one of `float`, `int`, `uint`, `u8`, `bool`, `string`.
3. All columns in a Block share the same count (axis-0 length).
4. A Block's optional structural shape has product equal to its count.
5. A Frame is a general map of names to Blocks; it enforces no cross-block
   relationship.
6. `box`, when present, is a triclinic cell whose `vectors` columns are lattice
   vectors.
7. A trajectory is an ordered list of frames with optional aligned `step`/`time`
   arrays.
8. A reader must preserve blocks, columns, and record sections it does not
   recognize.
9. A Record requires `meta` and at least one of `frame`, `system`, or `status`.
10. Instantaneous Cartesian coordinates are not required content of `system/`.
