# LMDB binding

A [collection](collection.md) — many records, read at random by a training
loader — in one [LMDB](http://www.lmdb.tech/doc/) file. The Zarr root is the
right shape for one record read front to back; a dataset of eighty thousand
small records read in shuffled order wants one memory-mapped file, one key per
record part, and a value whose numeric buffers a reader *can* view in place.
That is this binding.

It stores the same logical content the model defines, and the trajectory with
the same **sparse update** semantics as the [ragged layout](ragged.md): a
block is written at the frames where it changes and carries forward
everywhere else.

## The file

* One LMDB environment in **one file** (`subdir=False`), suffix
  `.mrec.lmdb`, one unnamed database. One writer at a time; readers take
  LMDB's reader lock (the `-lock` file beside it), so a file on read-only
  media is copied first.
* Keys are bytes. Values are UTF-8 JSON or [frame bytes](#frame-bytes).
* Record `r` and global frame ordinal `j` are unsigned 64-bit integers,
  encoded **big-endian** in keys so that byte order is numeric order and a
  record's frames are one contiguous cursor range.

| Key | Value | Holds |
|-----|-------|-------|
| `meta` | JSON | layout tag, collection `meta`, `sequence_schema`, counts |
| `index` | frame bytes | one block `records`, `R` rows |
| `ff` | frame bytes | the collection's [force field](forcefield.md): `meta` = the document, `blocks` = the style tables; absent key = none |
| `r` ‖ u64be(`r`) | JSON | record `r`'s `meta` document |
| `s` ‖ u64be(`r`) | frame bytes | record `r`'s `system`; absent key = no system |
| `f` ‖ u64be(`j`) | frame bytes | the trajectory update at global frame ordinal `j` |

### `meta`

```json
{
  "layout": "mrec-lmdb",
  "collection": {
    "units": { "length": "angstrom", "energy": "kcal/mol" }
  },
  "sequence_schema": { "blocks": { ... }, "meta": { ... } },
  "n_records": 83951,
  "n_frames": 2014824
}
```

`meta` is written **last**, in the transaction that commits the collection.
A file without it is not a collection, and a reader refuses it.

`layout` names this binding; a reader refuses any other value. `collection`
is the [collection](collection.md)'s document.

### `index`

One block named `records` with `R` rows:

| Column | Type | Meaning |
|--------|------|---------|
| `first_frame` | u64 | global ordinal of record `r`'s first frame |
| `n_frames` | u64 | frames in record `r` |
| `n_atoms` | u64 | rows of record `r`'s `atoms`: the system's block (even when it has zero rows), else the trajectory's first update of `atoms`; 0 when neither has one |
| `has_trajectory` | bool | whether record `r` has a trajectory at all — one of zero frames included |
| *…* | any | the collection's own [index columns](collection.md#model) |

`first_frame` is the exclusive prefix sum of `n_frames`, and the last
`first_frame + n_frames` equals `n_frames` in `meta`. A reader refuses an
index that breaks either. The four columns are the binding's: a
collection's own index columns may not take their names.

### Frames

The frames of record `r` are ordinals `first_frame[r] … first_frame[r] +
n_frames[r] - 1`. Frame `j` holds the record's trajectory update at that
ordinal:

* **blocks**: exactly the blocks that changed at this ordinal. The first frame
  of a record holds every block present at that ordinal; a later frame holds a
  block only when its content differs from the block it would carry forward.
  A zero-row block is an update that empties it. Carry-forward never crosses a
  record boundary. An [aligned](ragged.md#aligned-blocks) block is held to its
  target's row count at every resolved ordinal of the record.
* **meta**: every declared per-step key, with any declared fill materialized.
* **step**: the frame's step number; **time** when the trajectory has one.
* **box**: the cell, only at the ordinals where it changes.

A reader resolves a record's frames exactly as a
[trajectory](ragged.md#the-three-states-of-a-block) resolves them. Two
conforming files of one collection may differ byte for byte in which frames
restate an unchanged block; the logical content may not.

## Frame bytes

One frame — a system, a trajectory update, the index — as one value that
decodes in place:

```text
value   := magic | header_length | header | padding | payload
magic   := "MRF1"                          4 bytes
header_length := u32, little-endian        4 bytes
header  := UTF-8 JSON, header_length bytes
padding := zero bytes up to the next multiple of 8 (from the start of value)
payload := the column buffers
```

```json
{
  "blocks": {
    "atoms": {
      "count": 33,
      "structural_shape": null,
      "columns": {
        "x": { "dtype": "f64", "shape": [33], "offset": 0 },
        "element": { "dtype": "string", "shape": [33], "values": ["C", "H"] }
      }
    }
  },
  "meta": { "pe": -503415.87 },
  "step": 0
}
```

* Every numeric column is one buffer: C-order, **little-endian**, its bytes
  `prod(shape) × itemsize`, starting at `offset` bytes into the payload.
  Every `offset` is a multiple of 8, so a reader on a little-endian machine
  **may** view the buffer in place — for as long as the read transaction
  that returned the value is open (LMDB's memory map is only stable that
  long). A reader that keeps the data past the transaction copies it; the
  format promises alignment, not zero-copy.
* A column of a `system` or `index` frame that declares a
  [precision](frame.md#declared-precision) carries `"precision": p` in its
  header entry, and its buffer holds the rounded values. A trajectory frame's
  columns carry none: the collection's `sequence_schema` declares them. No
  codec is applied: frame bytes are raw buffers.
* A [nullable column](frame.md#nullable-columns) that carries a mask adds
  `"validity": <offset>` to its entry: a buffer of `shape[0]` one-byte
  `bool`s (`0` / `1`) at that 8-aligned offset. No `validity` key means
  every row is valid; a string column's mask is a buffer too.
* `bool` is one byte per element (`0` / `1`). `c64` / `c128` are interleaved
  real/imaginary pairs.
* A `string` column has no buffer: its values are the header's `values` list,
  row-major.
* `meta` is the frame's meta document, each value in its typed JSON form. A
  trajectory update's keys are typed by the `sequence_schema`; a `system`
  frame carries `"meta_types": {key: tag}` beside `meta` with the rules of
  the [Zarr frame group](storage.md#frame-shaped-group). The `ff` frame's
  `meta` is the force-field document and carries no `meta_types`. `step` (an
  `i64`) and `time` (an `f64`) are typed values too.
* A block's `targets`, when set, is its header entry's `targets`
  (`{column: target}`, [Row references](frame.md#row-references)).
* A block's own attributes (beyond `count`, `structural_shape` and
  `targets`) ride in the optional `attributes` object of its entry, on a
  system frame only — a trajectory block's attributes are its section's, not
  one update's.
* `step`, `time` and `box` appear only on trajectory updates; `box` follows
  the [cell](frame.md#simulation-box) fields.

The dtype set is the closed [column set](frame.md). A reader refuses an
unknown magic, a dtype outside the set, an offset that is not a multiple of 8,
and a buffer that runs past the value.

## What it is not

* Not a record root: a collection carries `meta`, `system` and `trajectory`
  per record, not `status`, `method`, metrics or observables.
* Not a replacement for the [Zarr root](storage.md). A single record is
  still a `*.mrec` package; this binding exists for many records read at
  random.
* Not an ASE database. A reader of ASE / FairChem LMDB files maps their rows
  onto these conventions; this layout is not theirs.
