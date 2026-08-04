# MolRec

MolRec is the **backend-neutral record contract** for the MolCrafts ecosystem.

It is not a store product, not a class named `MolStore`, and not “only a Frame
format.” A **Record** is anything tools must share for reproducibility: molecular
systems, snapshots and trajectories, scientific observables, **and** training or
job execution logs.

MolRec defines:

1. A small general **data model** (Column / Block / Frame).
2. A **Record** root layout (sections under one package).
3. **Conventions** so independent tools agree on names.

A reader that knows only the model can traverse any record. A reader that also
knows the conventions can interpret it.

## The model (L1)

Three general containers:

```text
Column     a typed N-dimensional array
Block      named columns sharing one length (+ optional structural shape)
Frame      named blocks + free-form metadata + an optional box
```

No key is privileged; no field is required by the model itself. Domain meaning
is convention — see [Conventions](spec/conventions.md).

## The Record (L2)

```text
<record-root>/
├── meta/              # required
├── system/            # definition of the chemical/physical system
├── frame/             # instantaneous snapshot
├── trajectory/        # time series of frames
├── observables/       # scientific results
├── method/            # how it was produced
├── status/            # lifecycle / progress (run surface)
└── metrics/           # append-only run measurements
```

No root `parameters/`. Minimum shapes: Structure, System-def, Trajectory
(system optional), **Run** (`meta`+`status`, frame optional). Contract cell name
is **Box**; sole version is **`record_schema_version`**. Details:
[Record](spec/record.md), [Run surface](spec/run.md).

## Reading guide

| Chapter | What it covers |
|---------|----------------|
| [Overview](spec/overview.md) | L0–L4, model, minimum records, invariants |
| [Record](spec/record.md) | Root layout, versioning, section map |
| [Types](spec/types.md) | Column dtypes and structural shape |
| [Frame](spec/frame.md) | Frame, Block, Column, Box |
| [System](spec/system.md) | System definition vs frame state |
| [Conventions](spec/conventions.md) | Recommended block/field names |
| [Trajectory](spec/trajectory.md) | Frame sequences |
| [Run surface](spec/run.md) | Training / job logs as records |
| [Observables](spec/observables.md) | Scientific result quantities |
| [Status](spec/status.md) | Execution lifecycle |
| [Metrics](spec/metrics.md) | Append-oriented measurements |
| [Meta](spec/meta.md) | Record-level metadata |
| [Method](spec/method.md) | Scientific context |

## Reference implementation

[molrs](https://github.com/MolCrafts/molrs) provides the reference L1 containers
and the Zarr V3 binding for frames (and, over time, full record roots). Consumers
(molpy, molnex, molexp, …) adopt this contract; they must not invent a parallel
store product name for the same layout.
