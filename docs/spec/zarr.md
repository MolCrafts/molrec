# Why Zarr V3

The [specification](specification.md) names groups, arrays, and attributes.
The *reference* physical form tools interoperate on is **Zarr version 3**.

This chapter says what Zarr V3 is, what it gives a molecular record, and
how a scientific record is named. The layout of a record on that binding is
[Root layout](storage.md). How arrays are cut up is
[Chunking and packing](chunking.md).

## What Zarr is

[Zarr](https://zarr.dev/) is a specification for chunked N-dimensional arrays
in a key-value store. A store may be a directory, a zip file, or an object
bucket (S3, GCS, …). Each array is a grid of compressed chunks; each group
and array carries its own JSON metadata (`zarr.json`). Readers fetch only
the chunks they need.

The current specification is **Zarr V3** ([ZEP 0001](https://zarr.dev/zeps/accepted/ZEP0001.html),
accepted 2023). V3 is what molrs writes.

A MolRec directory `*.mrec/` *is* a Zarr V3 hierarchy: `zarr.json` sits at
the top of that directory.

## What V3 gives a record

- **A store of keys.** Each chunk or shard is one object. Cloud object stores
  speak GET/PUT; a trajectory append is a write at the tail of a shard.
- **JSON metadata.** Group and array metadata are UTF-8 JSON. Document
  sections (`meta`, `status`, `method`) live as group attributes on the same
  root.
- **Sharding in the spec.** The V3 sharding codec ([ZEP 0002](https://zarr.dev/zeps/accepted/ZEP0002.html))
  packs many inner chunks into one object. A trajectory keeps a small inner
  chunk for random access and a large shard so file count tracks bytes, and
  `nstep` stays off that axis. The reference writer freezes chunk and shard
  extents at trajectory creation — see [Chunking](chunking.md).
- **One codec pipeline.** A single `codecs` list (endian, transpose, gzip,
  sharding, …). The contract names a small must-decode set — `bytes`,
  `gzip`, `crc32c`, `vlen-utf8`, `sharding_indexed`, `transpose` — that
  every reader of these stores, wasm32 included, decodes; `zstd` should be
  decodable. Nothing lossy. See [Chunking](chunking.md#normative).
- **Rust and wasm.** molrs is a Rust implementation. zarrs, zarr-python, and
  JavaScript/wasm readers exist for V3. New codecs extend the pipeline
  in-place.

## Path brand

The scientific path brand is `*.mrec/` (packed: `*.mrec.zip`). Discovery of
a record is that suffix plus a Zarr root at the top of the directory. The
path *is* the brand; `meta["molrec_version"]` (stamped by every writer,
validated by a reader when present) says which version of the contract
wrote it.

Host metrics use the filename-gated `*.mlp.*` surface (live WAL
`*.mlp.jsonl`). They are a separate concern from the record.

## Semantics sit on Zarr

MolRec's groups, dtypes, and [conventions](conventions.md) sit on the Zarr
root. Live metrics append as a [JSONL WAL](metrics-wal.md) and densify into
Zarr series on flush, so a high-frequency stream stays one text file until
close.

This binding is the one molrs implements first, and the one other MolCrafts
tools are expected to open.
