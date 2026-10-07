# Metrics WAL

The live metrics path is an append-only text WAL. On a record, dense Zarr
series under `metrics/` are the source of truth up to the catalog's
watermark ([Metrics](metrics.md#the-catalog)). On a host, the WAL is the only
persist surface. Logical fields live in [Metrics](metrics.md).

```text
metrics/metrics.jsonl                        # record root (a plain file, not a Zarr node)
artifacts/<stem>.mlp.jsonl                   # host run (default stem: metrics)
```

## Role

High-frequency writers (training steps, MD monitors) append one UTF-8 JSON
object per line, terminated by `\n`. Historical lines stay. On flush / close
a record writer densifies into Zarr series and records the watermark.

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
{"t":"scalar","k":"train/loss","s":120,"w":"2026-08-04T12:00:00Z","v":0.42}
```

`w` is RFC 3339 with an explicit offset; `v` is a finite JSON number for a
`scalar` (a non-finite measurement is the string `"NaN"` / `"Infinity"` /
`"-Infinity"`, as for every [typed JSON value](conventions.md#typed-json-values)).

## Writers and crashes

- **One writer.** A WAL has exactly one appending process at a time.
- **Torn tail.** A crash can leave an unterminated last line. A writer that
  reopens a WAL **truncates it to just after its last `\n`** before it
  appends, so a new line is never glued onto a torn one.
- A writer appends whole lines, each with its terminating `\n`, and does not
  rewrite or reorder history.

## Readers

- A reader reads complete lines only: the unterminated tail (if any) is
  torn and is ignored.
- A blank line is skipped. A complete line that is not valid UTF-8, or not
  one JSON object, is corruption — not a crash artefact — and a reader
  refuses it rather than skip it silently.
- Events are merged per key under the duplicate-step rule of
  [Metrics](metrics.md#events).

## Authority

| Artifact | Authoritative for curves? | When |
|----------|---------------------------|------|
| Dense Zarr series (record `metrics/`) | Yes, up to the watermark | After densify / close |
| JSONL WAL | Record: past the watermark, or when no dense series exist. Host: **always** | During a run; the host's only surface |

There is no separate first-class `metrics/index.json` on a record, and hosts
do not maintain a dense store or an index beside the WAL.
