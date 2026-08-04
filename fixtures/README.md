# MolRec fixtures

Golden records for cross-repo alignment live here (later phases). Paths are
conventional; binary payloads may be added without changing names.

| Path | Shape | Expected sections |
|------|--------|-------------------|
| `fixtures/structure-minimal/` | Structure | `meta`, `frame` (with `box` if present — never `simbox`) |
| `fixtures/system-frame-minimal/` | System + snapshot | `meta`, `system`, `frame` |
| `fixtures/trajectory-coords-only/` | Trajectory without system | `meta`, `trajectory` (frames carry coords; optional full blocks) |
| `fixtures/run-minimal/` | Run | `meta`, `status`, `metrics` (JSONL binding; no `frame`) |

All new fixtures: `meta.record_schema_version = 1`. No root `parameters/`.

### `run-minimal` (filesystem / hybrid)

Populated reference for the **JSONL metrics** binding and a minimal Run package:

```text
fixtures/run-minimal/
├── meta/meta.json
├── status/status.json
└── metrics/
    ├── metrics.jsonl    # authoritative stream (compact t/k/s/w/v)
    └── index.json       # derived summary
```

Consumers (molnex, molexp, later molpy/molrs) SHOULD treat this tree as the
shared golden for run-surface discovery and metrics parsing.
