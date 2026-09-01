# Chunking and packing

How an array is cut up is a backend choice. A conforming
reader opens any chunking, and two stores of the same data are expected to
differ byte for byte. This chapter is the choice the [Zarr V3](zarr.md)
reference binding makes, and the packed at-rest form `*.mrec.zip`.

The layout of groups is [Root layout](storage.md). Trajectory arrays follow
the same chunk/shard rules; their *logical* encoding is
[Ragged trajectory](ragged.md).

## Inner chunk

One chunk aims for **512 KiB**, on the leading axis only. A chunk spans
`max(1, 512 KiB / row_bytes)` rows — never more than a fixed-size array's
own length — where `row_bytes` is one row's width (the product of the
trailing axes times the element size).

Trailing axes are per-entity structure and are never split: a single entity
would otherwise span several chunks. The target is bytes, not frames, so a
frame may straddle a chunk boundary; that is what lets a million-atom frame
work at all.

## Shard

A shard spans `chunks_per_shard × chunk` rows, with `chunks_per_shard`
derived from a byte target of **256 MiB**:
`max(1, 256 MiB / chunk_bytes)`.

Fixed-size arrays (`frame/`, `system/`, observables) use the same chunk
target and collapse into a single shard once they exceed four chunks. A
trajectory's growing arrays have their chunk and shard extents **frozen at
creation**, because a chunk grid cannot be re-planned under live data.

The shard index sits at the end (`ShardingIndexLocation::End`, the Zarr
default for `sharding_indexed`), so appending a chunk is a write at the tail
of the shard file.

This is why V3 sharding is in the binding at all: file count is
`total_bytes / shard_bytes + O(number of arrays)`. **File count does not
scale with `nstep`.**

## Compression

Compression is lossless `gzip` on the inner chunks, unconditionally. No
lossy codec is admitted, and `gzip` is the one codec every reader of these
stores — wasm32 included — can decode.

## At-rest form: `*.mrec.zip`

A closed store may be packed into a single file: a zip of the directory
store in which every entry is *stored* (compression method 0). The chunks
arrived already gzipped, so packing is concatenation plus a central
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
