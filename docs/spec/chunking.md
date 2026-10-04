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

**Must-decode codec set.** A conforming reader — a wasm32 build included —
decodes every array whose codec pipeline is drawn from

```text
bytes   gzip   zstd   numcodecs.shuffle   crc32c   vlen-utf8   sharding_indexed   transpose
```

and a conforming writer uses no codec outside this set unless the store is
for a reader known to have it. `numcodecs.shuffle` is the byte shuffle of the
Zarr extension registry (configuration `{"elementsize": n}`). **No lossy codec
is admitted**: a [declared precision](frame.md#declared-precision) is a
rounding the writer applies to values before they reach the pipeline, and
every pipeline returns the stored bytes exactly.

**Commit protocol.** Each flush of a trajectory writer lands in this order:

1. for every touched array: the chunk bytes first (positional writes into
   the shard), then its `zarr.json` replaced **atomically** (write a
   temporary file, rename over the old one);
2. if the flush is durable: `fsync` the touched data files, their
   `zarr.json` files, and their directories;
3. the trajectory group's metadata last — one atomic replace carrying the
   new `nstep` and the `step_progression` / `time_progression` attributes;
4. if the flush is durable: `fsync` that `zarr.json` and the `trajectory/`
   directory, so the rename that published the commit is itself on disk.

Data therefore always precedes metadata, and the `nstep` attribute is the
commit marker. Explicit `flush()` and `close()` are durable; an automatic
flush (see below) does not `fsync`.

**What the protocol guarantees, and where.** The guarantee is scoped to the
kind of failure and the kind of store:

- *Process crash* (the writer dies, the machine keeps running): after any
  flush, automatic or explicit, the store opens at the last `nstep` the
  operating system received; uncommitted tails are read past.
- *Power loss or kernel crash*: only an **explicit** `flush()` / `close()`
  is durable. Frames landed by automatic flushes since the last explicit one
  may be lost, and an `nstep` the disk never received reads as the previous
  one — never as a store that claims frames it lacks.
- *One writer, no concurrent readers.* A store has exactly one writer at a
  time. A reader that opens a store while it is being written may observe a
  half-replaced metadata file on a store without atomic rename; reading a
  live store is a convenience of POSIX filesystems, not a guarantee of the
  format.
- *Live append needs a POSIX-like store*: positional writes into a shard,
  atomic rename, `fsync`. An object store (S3, GCS) has none of these, so it
  holds **closed** records — written elsewhere, then uploaded, or packed into
  `*.mrec.zip` — and is read, never appended to.

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

Every column of one block shares one `rows_per_chunk`, computed from the
block's **narrowest** column (the smallest `row_bytes`), so a frame's rows
sit at the same chunk boundaries in every column; `chunks_per_shard` is then
each column's own.

**Dense arrays** — `step`, `time`, `meta/*`, `offset`, `step_index`,
`box/*`, and a nullable column's mask — are sharded the same way with
**1024-row inner chunks and 256 chunks per shard** (a 4 KiB shard index:
every landing rewrites the index of each touched array in place, and a
producer that flushes per frame touches every dense array per frame). A
mask shares its block's `rows_per_chunk` instead, so its chunks line up with
the values it qualifies.

Trailing axes are per-entity structure and are never split: a single entity
would otherwise span several chunks.

A trajectory's chunk and shard extents are **frozen at creation**, because a
chunk grid cannot be re-planned under live data. File count is
`total_bytes / shard_bytes + O(number of arrays)` and does not scale with
`nstep`.

**Fixed-size arrays** (`frame/`, `system/`, `observables/`, `metrics/`) are
cut along the leading axis only:

```text
rows   = min(N, max(1, floor(512 KiB / row_bytes)))
chunks = ceil(N / rows)
```

An array of `chunks <= 4` is stored as those chunks; one of more is packed
into **one shard spanning the whole array** (`rows × chunks` rows, the shard
index at the end). A string array, an empty leading axis, or a 0-d array is
one chunk holding the whole array.

## Reference writer: codecs

Each inner chunk's pipeline is `bytes` (or `vlen-utf8` for strings), then the
column's bytes-to-bytes codecs, then `crc32c`:

| Array | Bytes-to-bytes codecs |
|-------|----------------------|
| non-float column, every dense array | `gzip` level 1 |
| `f64` column with a declared precision | `numcodecs.shuffle` (`elementsize` 8), then `zstd` level 3 |
| any other float column (`f64`, `c64`, `c128`) | none |

- A writer that cannot encode `zstd` (the reference wasm32 build) writes a
  precision column with `numcodecs.shuffle` then `gzip` level 1.
- The writer knob `Compression::{None, Gzip(level), Zstd(level)}` selects the
  compressor of float columns: for a column without a precision it replaces
  "none"; for a precision column it replaces `zstd` level 3, and the shuffle
  stays.
- `crc32c` closes every inner pipeline.

Expected size of coordinates (3 `f64` columns; worst-case atom order):
24 B/atom/frame raw; 7.6 at `p = 10⁻³` and 5.8 at `p = 10⁻²` with the
reference pipeline.

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
store. The chunks arrived already encoded, so packing is concatenation plus
a central directory, and an entry read out of the archive is bit-identical
to the file it replaced. The archive follows fixed rules, so any zip-backed
Zarr store can open any packed record:

- One entry per file of the directory store, named by its path **relative
  to the record root** (the directory `<stem>.mrec/` itself is not a path
  component): `zarr.json`, `meta/zarr.json`, `trajectory/atoms/x/c/0`, …
- Path separators are `/`, never `\`; no entry name is absolute or contains
  `..`.
- Every entry is *stored*: compression method `0`. A chunk is already
  compressed by its codec pipeline; a second layer would cost random access.
- ZIP64 extensions are used whenever a size, an offset or the entry count
  needs them (a shard is routinely larger than 4 GiB).
- No directory entries: a Zarr store has keys, not directories.

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
