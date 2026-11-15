"""How big a chunk and a shard are -- the reference writer's choices.

None of this is contractual. A conforming reader must open any chunking, and
two records of the same data are expected to differ byte for byte. The rules
below are the ones ``docs/spec/chunking.md`` records for the reference writer,
so the codec here lays arrays out the way molrs does.

Trajectory arrays:

* **Block columns are frame-aligned.** ``frame_rows`` is the block's row count
  in a representative frame (the largest, when derived from several).
  ``rows_per_chunk`` is the smallest integer multiple of ``frame_rows`` that is
  at least ``max(frame_rows, ceil(16 KiB / row_bytes))``, so one frame never
  straddles a chunk and a tiny frame does not make a tiny chunk. A block that
  has no rows in its representative frame falls back to ``16 KiB / row_bytes``
  rows. A string row is estimated at 16 bytes.
* **Shards hold 256 MiB.** ``chunks_per_shard = clamp(256 MiB / chunk_bytes,
  1, 4096)``; the cap keeps a shard index under 64 KiB.
* **Dense arrays** (``step``, ``time``, ``meta/*``, ``offset``, ``step_index``,
  ``box/*``) take 1024-row chunks, 256 chunks per shard (a 4 KiB shard index).

Fixed-size arrays (``frame/``, ``system/``, ``observables/``) aim for 512 KiB
leading-axis chunks; an array of more than four chunks packs them into one
shard spanning the whole array. A string, an empty leading axis or a 0-d
array is one chunk. Trailing axes are per-entity structure and are never
split.
"""

from __future__ import annotations

import math

KIB = 1024
MIB = 1024 * KIB

#: The smallest inner chunk a frame-aligned column is allowed to have.
CHUNK_FLOOR_BYTES = 16 * KIB
#: What one shard of a trajectory column aims to hold.
SHARD_TARGET_BYTES = 256 * MIB
#: The most inner chunks one shard may index (a 64 KiB index at 16 B/entry).
MAX_CHUNKS_PER_SHARD = 4096
#: Per-step and index arrays: rows per inner chunk, chunks per shard.
DENSE_ROWS_PER_CHUNK = 1024
DENSE_CHUNKS_PER_SHARD = 256
#: A variable-width string row, for the byte arithmetic above.
STRING_ROW_BYTES = 16
#: Fixed-size (frame / system / observables) arrays: the chunk byte target.
FIXED_CHUNK_BYTES = 512 * KIB
#: A fixed-size array of more than this many chunks is packed into one shard.
SHARD_ABOVE = 4


def row_bytes(trailing: tuple[int, ...], itemsize: int | None) -> int:
    """Bytes in one row: the trailing axes times the element size."""
    width = STRING_ROW_BYTES if itemsize is None else itemsize
    return max(1, math.prod(trailing) * width) if trailing else max(1, width)


def rows_per_chunk(frame_rows: int, bytes_per_row: int) -> int:
    """The frame-aligned inner chunk of a trajectory column, in rows."""
    floor_rows = max(1, math.ceil(CHUNK_FLOOR_BYTES / bytes_per_row))
    if frame_rows <= 0:
        return max(1, CHUNK_FLOOR_BYTES // bytes_per_row)
    return frame_rows * math.ceil(max(frame_rows, floor_rows) / frame_rows)


def chunks_per_shard(chunk_bytes: int) -> int:
    """How many inner chunks one shard of a trajectory column holds."""
    return max(1, min(MAX_CHUNKS_PER_SHARD, SHARD_TARGET_BYTES // max(1, chunk_bytes)))


def plan(
    shape: tuple[int, ...], itemsize: int | None
) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None]:
    """``(chunks, shards)`` for a fixed-size array; either may be ``None``.

    Leading-axis chunks of about :data:`FIXED_CHUNK_BYTES`; above
    :data:`SHARD_ABOVE` of them, one shard spanning the whole array (rounded
    up to a whole number of chunks). ``chunks`` is ``None`` -- one chunk for
    the whole array -- for a variable-width dtype, an empty leading axis or a
    0-d array; ``shards`` is ``None`` when there are few enough chunks.
    The reference implementation's ``chunking.rs`` is this function.
    """
    if not shape or shape[0] == 0 or itemsize is None:
        return None, None
    rows_total = shape[0]
    per_row = max(1, math.prod(shape[1:]) * itemsize)
    rows = min(rows_total, max(1, FIXED_CHUNK_BYTES // per_row))
    chunks = (rows, *shape[1:])
    count = math.ceil(rows_total / rows)
    if count <= SHARD_ABOVE:
        return chunks, None
    return chunks, (rows * count, *shape[1:])
