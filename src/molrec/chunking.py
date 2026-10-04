"""How big a chunk and a shard are -- the reference writer's choices.

None of this is contractual. A conforming reader must open any chunking, and
two stores of the same data are expected to differ byte for byte. The rules
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
  ``box/*``) take 1024-row chunks, 4096 chunks per shard.

Fixed-size arrays (``frame/``, ``system/``) are not sharded: one chunk holds
the whole array up to 4 MiB, and 4 MiB leading-axis slabs beyond that.
Trailing axes are per-entity structure and are never split.
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
DENSE_CHUNKS_PER_SHARD = 4096
#: A variable-width string row, for the byte arithmetic above.
STRING_ROW_BYTES = 16
#: Fixed-size (frame / system) arrays: one chunk up to this many bytes.
FIXED_CHUNK_BYTES = 4 * MIB


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


def fixed_chunk_rows(rows: int, bytes_per_row: int) -> int:
    """The inner chunk of a fixed-size (frame / system) array, in rows."""
    if rows <= 0:
        return 1
    return min(rows, max(1, FIXED_CHUNK_BYTES // bytes_per_row))


def plan(
    shape: tuple[int, ...], itemsize: int | None
) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None]:
    """``(chunks, shards)`` for a fixed-size array; either may be ``None``.

    The fixed-size rule above, in the shape the observables binding consumes:
    leading-axis chunks only, no shard.
    """
    if not shape or shape[0] == 0:
        return None, None
    rows = fixed_chunk_rows(shape[0], row_bytes(tuple(shape[1:]), itemsize))
    return (rows, *shape[1:]), None
