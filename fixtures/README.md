# MolRec fixtures

Golden records for cross-repo alignment. Only what is listed here exists;
paths are conventional so new goldens can be added without renaming.

| Path | Shape | Expected sections |
|------|--------|-------------------|
| `fixtures/run-minimal/` | Run | `meta`, `status`, `metrics` buffer (no `frame`) |

Binary `*.mrec/` goldens (structure, system + frame, trajectory) are
**produced by molrs**, the reference writer, and land here from its
regression output — they are not hand-built in this repository, so that a
golden is always something a real writer emitted.

Fixture rules: no root `parameters/`, cell key `box` only,
`meta.molrec_version` stamped (the integer `1`). Physical forms
follow [docs/spec/storage.md](../docs/spec/storage.md):

- Documents → Zarr **group attributes** (payloads under `attrs/` for text goldens)
- Closed metrics → **dense Zarr series** under `metrics/`
- Live metrics → **JSONL WAL** only (`metrics/metrics.jsonl`)

### `run-minimal`

Text golden for a Run-shaped record without shipping a full Zarr hierarchy:

```text
fixtures/run-minimal/
├── attrs/
│   ├── meta.json              # → Zarr group attributes on meta/
│   ├── status.json            # → Zarr group attributes on status/
│   └── metrics.summary.json   # closed catalog (watermark + series) → metrics/ attrs
└── metrics/
    └── metrics.jsonl          # live WAL golden (compact t/k/s/w/v)
```

On disk under the reference binding these become:

```text
<record-root>/                 # Zarr V3
├── meta/                      # attributes = attrs/meta.json
├── status/                    # attributes = attrs/status.json
└── metrics/
    ├── (attributes)           # catalog / summary = attrs/metrics.summary.json
    ├── series/…               # dense arrays after densify
    └── metrics.jsonl          # = metrics/metrics.jsonl (WAL)
```

`attrs/*.json` files are **not** a parallel filesystem binding — they are
checked-in stand-ins for attribute maps so parsers and UIs can test without a
binary store. Consumers (molnex, molexp, molrs) SHOULD densify the WAL into
Zarr series for closed curves; the attr JSON is the document object stamped
onto Zarr groups.
