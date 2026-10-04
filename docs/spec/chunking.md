# Chunking and packing

How an array is cut up is a backend choice. A conforming reader opens any
chunking, and two stores of the same data are expected to differ byte for
byte. This chapter separates the few rules that are **normative** — what a
reader must be able to decode, and how a writer commits — from the
**reference writer's choices** for extents and codecs, and ends with the
packed at-rest form `*.mrec.zip`.

The layout of groups is [Root layout](storage.md). The *logical* encoding
of a trajectory is [Ragged trajectory](ragged.md).

## Normative

**Must-decode codec set.** A conforming reader decodes every array whose
codec pipeline is drawn from

```text
bytes   gzip   crc32c   vlen-utf8   sharding_indexed   transpose
```

and a conforming writer uses no codec outside this set unless the store is
for a reader known to have it. `zstd` **SHOULD** be decodable (it is on
native platforms; in a wasm build it depends on how the reader was
compiled). **No lossy codec is admitted.**

**Commit protocol.** Each flush of a trajectory writer lands in this order:

1. for every touched array: the chunk bytes first (positional writes into
   the shard), then its `zarr.json` replaced **atomically** (write a
   temporary file, rename over the old one);
2. if the flush is durable: `fsync` the touched data files and their
   directories;
3. the trajectory group's metadata last — one atomic replace carrying the
   new `nstep` and the `step_progression` / `time_progression` attributes.

Data therefore always precedes metadata, and the `nstep` attribute is the
commit marker. Explicit `flush()` and `close()` are durable; an automatic
flush (see below) does not `fsync`.

**Reopen rule.** A writer reopening a store to append, and a reader opening
one, are bound by `nstep`:

- `nstep` is the trajectory group attribute (`len(step)` for a store that
  kept no marker attribute);
- for every block with an index, `n_updates` is the length of the prefix of
  `step_index` whose entries are `< nstep`; `offset` has logical length
  `n_updates + 1` and `total_rows = offset[n_updates]`; for a regular block
  (no index), `n_updates = min(len(column) / uniform_rows, nstep)`;
- `time` and `meta/*` have logical length `nstep`; `box/` follows the block
  rule.

A reader reads only the logical lengths and tolerates a longer array — a
tail the writer had not yet committed. A reopening writer shrinks each array
back to its logical shape (`set_shape`) before appending.

**No compaction.** There is no seal, compact or compact-tail step:
`close()` is the last durable flush. Dead bytes arise only when an explicit
flush re-encodes a partial tail chunk; they are bounded and not reclaimed.

## Reference writer: extents

Every array under `trajectory/` is written with the `sharding_indexed`
codec, `index_location: start`. The shard index is rewritten in place;
appending a whole chunk lands at the tail of the shard file and creates no
dead bytes.

**Block columns are frame-aligned.** `frame_rows` is the block's row count
in a representative frame (when the declaration is derived from several
frames, the largest). With `row_bytes` the width of one row (trailing axes
times the element size; a string row is estimated at 16 bytes):

```text
rows_per_chunk = the smallest integer multiple of frame_rows
                 that is >= max(frame_rows, ceil(16 KiB / row_bytes))
```

so one frame never straddles a chunk and a small frame does not produce a
tiny chunk. A block with `frame_rows == 0` takes `max(1, 16 KiB / row_bytes)`
rows per chunk.

**Shards target 256 MiB.**

```text
chunks_per_shard = clamp(floor(256 MiB / chunk_bytes), 1, 4096)
```

The upper clamp keeps a shard index at or under 64 KiB.

**Dense arrays** — `step`, `time`, `meta/*`, `offset`, `step_index`,
`box/*` — are sharded the same way with **1024-row inner chunks and 256
chunks per shard** (a 4 KiB shard index: every landing rewrites the index
of each touched array in place, and a producer that flushes per frame
touches every dense array per frame).

Trailing axes are per-entity structure and are never split: a single entity
would otherwise span several chunks.

A trajectory's chunk and shard extents are **frozen at creation**, because a
chunk grid cannot be re-planned under live data. File count is
`total_bytes / shard_bytes + O(number of arrays)` and does not scale with
`nstep`.

**Fixed-size arrays** (`frame/`, `system/`, observables) are not sharded by
the reference writer: one chunk holds the whole array up to 4 MiB, and 4 MiB
leading-axis slabs beyond that.

## Reference writer: codecs

Each inner chunk's pipeline is

```text
bytes  (+ gzip level 1)  + crc32c
```

- `gzip` level 1 is applied to every **non-float column** and to **every
  dense array**;
- **float columns** (`f64` `c64` `c128`) are left uncompressed by
  default. The writer knob `Compression::{None, Gzip(level), Zstd(level)}`
  acts on float columns only;
- `crc32c` closes every inner pipeline;
- string columns serialize with `vlen-utf8` in place of `bytes`.

## Reference writer: automatic flush

The writer buffers frames and flushes every `K` frames, where

```text
K = max(1, ceil(4 MiB / frame_bytes_total))
```

rounded up to a multiple of the largest block's frames-per-chunk and capped
at 4096 frames. `with_flush_every(n)` overrides `K`; an explicit `flush()`
is available at any time and is durable.

## At-rest form: `*.mrec.zip`

A closed store may be packed into a single file: a zip of the directory
store in which every entry is *stored* (compression method 0). The chunks
arrived already encoded, so packing is concatenation plus a central
directory, and an entry read out of the archive is bit-identical to the
file it replaced.

Packing happens after the writer is closed. The running form is a directory
`*.mrec/` (append needs in-place partial writes); the at-rest form is one
file `*.mrec.zip`.

- Name: `<stem>.mrec/` packs to `<stem>.mrec.zip`.
- Scientific paths use `*.mrec/` / `*.mrec.zip`. Host metrics remain on
  the `*.mlp.*` surface.
- Read path: any zip-backed Zarr store adapter — zarrs'
  `ZipStorageAdapter`, or zarr-python's `zarr.storage.ZipStore`.
- Random access survives packing (central directory plus per-entry byte
  ranges), and the at-rest file count is 1.
