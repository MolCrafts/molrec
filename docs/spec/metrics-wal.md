# Metrics WAL

The live metrics path is an append-only text WAL. On a record, dense Zarr
series under `metrics/` are the source of truth once densified. On a host,
the WAL is the only persist surface. Logical fields live in
[Metrics](metrics.md).

```text
metrics/metrics.jsonl                        # package root
artifacts/<stem>.mlp.jsonl                   # host run (default stem: metrics)
```

## Role

High-frequency writers (training steps, MD monitors) append one UTF-8 JSON
object per line, terminated by `\n`. Historical lines stay. Crash recovery
is keep the file; readers skip blank or malformed lines. On flush / close,
densify into Zarr series arrays.

A live stream stays one text file until close. Sharding then packs the
dense series; see [Why Zarr V3](zarr.md).

## Compact keys

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

## Authority

| Artifact | Authoritative for curves? | When |
|----------|---------------------------|------|
| Dense Zarr series (record `metrics/`) | Yes when present | After densify / close |
| JSONL WAL | Record: live / fallback. Host: **always** | During a run; the host's only surface |
| Leftover host `*.mlp.zarr/` / `*.mlp.index.json` | No — ignored | Recognised only to be skipped; never a UI trigger |

There is no separate first-class `metrics/index.json` on a record, and hosts
do not maintain a dense store or an index beside the WAL.
