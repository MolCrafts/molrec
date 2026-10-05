# Layout by example

This chapter is a guided tour of how MolRec data sits on disk. It walks
through small, concrete records — one water molecule, two short
trajectories, a force field, a run, a collection — and shows each one as the
tree of groups, arrays and attributes the reference codecs actually write.

The tour explains; it does not legislate. Every rule it mentions is stated in
the chapter it links to, and where the two seem to differ, the linked chapter
wins.

**Every tree here is generated.** `scripts/layout_examples.py` builds each
example from molrec's own models, writes it with molrec's own codecs (the
Zarr V3 binding, the LMDB binding) into a temporary directory, and reads what
landed on disk back out: each node's `zarr.json`, the leading values of each
array, the keys and value bytes of the LMDB file. `python
scripts/layout_examples.py --write` regenerates the blocks of this page, and
a test fails when they drift from what the codecs write.

## How to read the trees

The trees use the notation of [Objective](spec/specification.md#notation-and-naming):

```text
<name>/                          a group (a directory with a zarr.json)
 +-- key: value                  an attribute of the group above, as JSON
 \-- child/                      a child group
 \-- name: f64[3] = [1.0, …]     an array: dtype, shape, its leading values
 |    zarr: chunk [3] · bytes → crc32c
 |                               how the array is chunked and encoded
```

The `zarr:` line abbreviates the array's metadata. `chunk [n]` is the inner
chunk shape; `shard [m], chunk [n]` means the array uses the
`sharding_indexed` codec, `m` rows per shard file and `n` rows per inner
chunk, with the shard index at the start of the file. The codec pipeline
reads left to right as the writer applies it:

| Abbreviation | Codec |
|--------------|-------|
| `bytes` | raw little-endian bytes |
| `vlen-utf8` | variable-length UTF-8 strings |
| `shuffle(8)` | `numcodecs.shuffle`, element size 8 — a byte shuffle |
| `gzip(1)`, `zstd(3)` | lossless compressors, with their level |
| `crc32c` | a checksum that closes every chunk |

An ellipsis `…` marks values or long attributes cut short for the page.

## The 30-second picture

One record is one directory, `x.mrec/`, and that directory **is** a Zarr V3
root: a `zarr.json` at its top, and below it one group per section. Every
group and every array is a directory holding its own `zarr.json`; an array's
data sits beside it as chunk files (`x/c/0`, `x/c/1`, …). Packed for storage,
the same files become the entries of one `x.mrec.zip`
([below](#the-packed-form-xmreczip)).

The sections come in a few kinds, and the kind decides the shape on disk:

```text
                                 x.mrec/
                       (zarr.json: the Zarr V3 root)
                                    |
      +-------------------+---------+----------+-----------------------+
      |                   |                    |                       |
  documents          frame-shaped          sequence            arrays and runs
  attributes only    attributes + blocks   blocks over time
      |                   |                    |                       |
  meta/              frame/                trajectory/         observables/
  status/            system/                                   metrics/
  method/            forcefield/
```

- A **document** is a JSON object stored as the attributes of an otherwise
  empty group: `meta` (identity, always present), `status` (lifecycle) and
  `method` (how a job ran).
- A **frame-shaped** section is a group whose attributes are a document and
  whose child groups are *blocks* — tables of columns sharing one row count.
  `frame` is one snapshot, `system` the topology, `forcefield` the parameter
  tables.
- The **sequence** `trajectory` holds blocks over time, written only when
  they change.
- `observables` pairs named result arrays with their metadata; `metrics`
  holds training curves as dense arrays plus a live text log.

Here is a record carrying every section at once, more than a real record
would (a frame of water beside a hydrogen peroxide system): each root group
with its kind, its attribute keys and its children.

<!-- BEGIN generated:overview -->
```text
tour.mrec/          the root group; its attributes: {}
 \-- meta/          document         attributes: molrec_version, creator, created_at
 \-- system/        frame-shaped     attributes: smiles, total_charge, _meta_types
 |                                   children:   atoms/, bonds/, angles/, dihedrals/
 \-- frame/         frame-shaped     attributes: smiles, total_charge, units,
 |                                               _meta_types
 |                                   children:   atoms/, bonds/, density/, box/
 \-- trajectory/    sequence         attributes: sequence_schema, step_progression,
 |                                               time_progression, nstep
 |                                   children:   meta/, atoms/, box/
 \-- forcefield/    frame-shaped     attributes: name, units, special_bonds, styles
 |                                   children:   angle.harmonic/, atom.full/,
 |                                               bond.harmonic/, dihedral.periodic/,
 |                                               pair.lj%2Fcut/
 \-- observables/   array section    children:   meta/, dipole, msd
 \-- method/        document         attributes: type, description, engine
 \-- status/        document         attributes: state, stage, global_step, started_at,
 |                                               finished_at
 \-- metrics/       catalog + series attributes: wal, series
                                     children:   series/, steps/, wall_time/,
                                                 metrics.jsonl
```
<!-- END generated:overview -->

The rules: [Overview](spec/overview.md#section-kinds) for the section kinds,
[Root layout](spec/storage.md) for how each lands on Zarr.

## A single frame: one water molecule

A `frame` is one snapshot. This record holds one water molecule: its atoms,
its two bonds, a small density grid and a cubic box.

<!-- BEGIN generated:frame -->
```text
water.mrec/
 \-- meta/
 |    +-- molrec_version: 1
 \-- frame/
      +-- smiles: "O"
      +-- total_charge: 0
      +-- units: {"length": "angstrom", "mass": "dalton"}
      +-- _meta_types: {"smiles": "string", "total_charge": "i64", "units": "json"}
      \-- atoms/
      |    +-- count: 3
      |    \-- b_factor: f64[3] = [11.8, 0.0, 0.0]
      |    |    zarr: chunk [3] · bytes → crc32c
      |    \-- element: string[3] = ["O", "H", "H"]
      |    |    zarr: chunk [3] · vlen-utf8 → gzip(1) → crc32c
      |    \-- mass: f64[3] = [15.999, 1.008, 1.008]
      |    |    zarr: chunk [3] · bytes → crc32c
      |    \-- x: f64[3] = [0.0, 0.0, 0.0]
      |    |    zarr: chunk [3] · bytes → shuffle(8) → zstd(3) → crc32c
      |    |    +-- precision: 0.001
      |    \-- y: f64[3] = [0.0, 0.7568359375, -0.7568359375]
      |    |    zarr: chunk [3] · bytes → shuffle(8) → zstd(3) → crc32c
      |    |    +-- precision: 0.001
      |    \-- z: f64[3] = [0.1171875, -0.46875, -0.46875]
      |    |    zarr: chunk [3] · bytes → shuffle(8) → zstd(3) → crc32c
      |    |    +-- precision: 0.001
      |    \-- _validity/
      |         \-- b_factor: bool[3] = [true, false, false]
      |              zarr: chunk [3] · bytes → gzip(1) → crc32c
      \-- bonds/
      |    +-- count: 2
      |    \-- atomi: u64[2] = [0, 0]
      |    |    zarr: chunk [2] · bytes → gzip(1) → crc32c
      |    \-- atomj: u64[2] = [1, 2]
      |    |    zarr: chunk [2] · bytes → gzip(1) → crc32c
      |    \-- bond_type: u64[2] = [1, 1]
      |         zarr: chunk [2] · bytes → gzip(1) → crc32c
      \-- density/
      |    +-- count: 8
      |    +-- structural_shape: [2, 2, 2]
      |    \-- rho: f64[8] = [0.0313, 0.0449, 0.0388, 0.0113, 0.015, 0.0437, …]
      |         zarr: chunk [8] · bytes → crc32c
      \-- box/
           \-- vectors: f64[3][3] =
                [[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]]
                zarr: chunk [3, 3] · bytes → crc32c
```
<!-- END generated:frame -->

Reading it top to bottom:

- **`meta/` comes first and carries `molrec_version: 1`.** Every writer
  creates it and stamps the version, even when the producer gave no
  identity at all.
- **The attributes of `frame/` are the frame's meta document.** `smiles`,
  `total_charge` and `units` are the producer's keys; there is no `meta`
  child group. `_meta_types` is the one reserved attribute: it tags each key
  with its type, so `total_charge` reads back as an `i64` and `units` as a
  JSON document rather than whatever a JSON parser guesses.
- **A block is a group; its columns are its arrays.** `atoms/` carries
  `count: 3`, and every column under it has 3 rows on its leading axis.
  Coordinates are three separate columns `x`, `y`, `z`, never one packed
  array.
- **Relations point at rows.** `bonds/atomi` and `bonds/atomj` are 0-based
  `u64` row indices into `atoms`: the bonds are O–H1 and O–H2. `bond_type`
  `1` is a single bond.
- **A volumetric block declares its shape.** `density/` has `count: 8` and
  `structural_shape: [2, 2, 2]`; its column `rho` is stored flat, and the
  attribute is what lets a reader reshape it into the grid.
- **A nullable column carries a mask.** The structure resolves the oxygen
  only, so `b_factor` has a value for row 0 alone. Its mask
  `atoms/_validity/b_factor` is `[true, false, false]`; the `0.0` stored
  under the hydrogen rows means nothing. Columns with no null rows (all the
  others) have no mask array at all.
- **A declared precision rounds before it encodes.** `x`, `y`, `z` carry the
  attribute `precision: 0.001`. The writer stored each value on the grid of
  the largest power of two not above it, `q = 2⁻¹⁰`: the input `0.7572`
  became `0.7568359375` (= 775/1024), within `q/2 ≈ 0.0005` of what was
  given. Those arrays alone get `shuffle(8) → zstd(3)`, because on that grid
  their low mantissa bits are zeros a compressor removes. `mass` declares no
  precision: its bytes go to disk as they are.
- **The box is a reserved group, not a block.** Only `vectors` is written
  (the lattice vectors are its columns); `origin` and `boundary` are omitted
  because they hold their defaults (zero, periodic on every axis).

Every array here is one chunk: a frame-path array is cut into 512 KiB pieces
along its leading axis, and is sharded only beyond four of them. One detail
that surprises people: the molecule lies in the `yz` plane, so `x` is all
zeros, and Zarr writes no chunk file for a chunk that holds only the fill
value. A reader gets the zeros back all the same
([the packed listing](#the-packed-form-xmreczip) shows the missing file).

The rules: [Frame-shaped group](spec/storage.md#frame-shaped-group),
[Containers](spec/frame.md#column-block-and-frame),
[Nullable columns](spec/frame.md#nullable-columns),
[Declared precision](spec/frame.md#declared-precision),
[Simulation box](spec/frame.md#simulation-box),
[Standardized identifiers](spec/conventions.md), and the extents and codecs
in [Chunking and packing](spec/chunking.md#reference-writer-extents).

## A trajectory with fixed topology

Four frames of a vibrating hydrogen peroxide molecule, H–O–O–H. Nothing about
the molecule changes but its coordinates, so the topology goes in `system`,
written once, and the trajectory carries positions only. Frames are dumped
every 100 steps, 0.5 time units apart, in a fixed cubic cell, with the
potential energy and temperature of each frame.

<!-- BEGIN generated:trajectory-fixed -->
```text
vibration.mrec/
 \-- meta/
 |    +-- molrec_version: 1
 \-- system/
 |    +-- smiles: "OO"
 |    +-- total_charge: 0
 |    +-- _meta_types: {"smiles": "string", "total_charge": "i64"}
 |    \-- atoms/
 |    |    +-- count: 4
 |    |    \-- element: string[4] = ["H", "O", "O", "H"]
 |    |    |    zarr: chunk [4] · vlen-utf8 → gzip(1) → crc32c
 |    |    \-- type: string[4] = ["H1", "O1", "O1", "H1"]
 |    |         zarr: chunk [4] · vlen-utf8 → gzip(1) → crc32c
 |    \-- bonds/
 |         +-- count: 3
 |         \-- atomi: u64[3] = [0, 1, 2]
 |         |    zarr: chunk [3] · bytes → gzip(1) → crc32c
 |         \-- atomj: u64[3] = [1, 2, 3]
 |         |    zarr: chunk [3] · bytes → gzip(1) → crc32c
 |         \-- type: string[3] = ["O1-H1", "O1-O1", "O1-H1"]
 |              zarr: chunk [3] · vlen-utf8 → gzip(1) → crc32c
 \-- trajectory/
      +-- sequence_schema: {
      |      "blocks": {
      |        "atoms": {
      |          "columns": {
      |            "x": {"dtype": "f64", "trailing": []},
      |            "y": {"dtype": "f64", "trailing": []},
      |            "z": {"dtype": "f64", "trailing": []}
      |          }
      |        }
      |      },
      |      "meta": {"pe": {"dtype": "f64"}, "temp": {"dtype": "f64"}}
      |    }
      +-- step_progression: {"start": 0, "stride": 100}
      +-- time_progression: {"start": 0.0, "stride": 0.5}
      +-- nstep: 4
      \-- meta/
      |    \-- pe: f64[4] = [-12.4, -12.1476, -12.1272, -12.3577]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    |    +-- meta_dtype: "f64"
      |    \-- temp: f64[4] = [300.0, 302.5, 297.1, 300.0]
      |         zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |         +-- meta_dtype: "f64"
      \-- atoms/
      |    +-- uniform_rows: 4
      |    +-- dense_updates: true
      |    \-- x: f64[16] = [0.8397, -0.0102, 0.0114, -0.8759, 0.8526, 0.0093, …]
      |    |    zarr: shard [8388608], chunk [2048] · bytes → crc32c
      |    \-- y: f64[16] = [0.9072, 0.728, -0.7351, -0.8487, 0.8773, 0.7505, …]
      |    |    zarr: shard [8388608], chunk [2048] · bytes → crc32c
      |    \-- z: f64[16] = [0.4465, -0.0105, 0.0149, 0.4201, 0.4144, -0.0041, …]
      |         zarr: shard [8388608], chunk [2048] · bytes → crc32c
      \-- box/
           +-- vectors: [[20.0, 0.0, 0.0], [0.0, 20.0, 0.0], [0.0, 0.0, 20.0]]
```
<!-- END generated:trajectory-fixed -->

What to notice:

- **`system/` is frame-shaped**, exactly like `frame/` above: element,
  force-field type and bonds, written once. The trajectory's `atoms` rows
  line up 1:1 by position with `system/atoms` — every frame has 4 rows.
- **`trajectory/atoms` is a *regular* block, so it has no index.** Each
  column holds the 4 frames' rows one after the other, 16 rows in all. The
  group's attributes `uniform_rows: 4` and `dense_updates: true` say that
  update `j` sits at frame `j` and owns rows `4j … 4j+4`, so neither
  `step_index` nor `offset` is written.
- **The step and time numbers are formulas, not arrays.**
  `step_progression: {"start": 0, "stride": 100}` means `step[i] = 100·i`;
  `time_progression` likewise gives `time[i] = 0.5·i`. There is no `step`
  or `time` array.
- **A fixed cell costs no array.** `box/` holds the cell as its attribute
  `vectors`.
- **Per-step scalars are one array per key.** `meta/pe` and `meta/temp` have
  one value per frame, and each states its type in `meta_dtype`.
- **`sequence_schema` is the pinned declaration.** It lists every block,
  column, dtype and trailing shape the trajectory may ever carry, and every
  per-step key with its tag. It is fixed when the trajectory is created.
- **`nstep: 4` is the commit marker.** A writer lands every array first and
  replaces the group's metadata — `nstep` with the progressions — last, so
  a crash costs the uncommitted frames and nothing else.

Every array under `trajectory/` is sharded. A block column's inner chunk is
a whole number of frames of at least 16 KiB — here 2048 rows, 512 frames of
4 atoms — and a shard holds up to 4096 such chunks. Per-step and index
arrays use 1024-row chunks, 256 per shard. These are capacities: a shard file
holds its index and the chunks written so far, nothing for the chunks still
to come.

The rules: [Trajectory](spec/trajectory.md),
[Ragged trajectory](spec/ragged.md#layout) (the
[regular-block elision](spec/ragged.md#per-block-sparse-updates-csr),
[step and time](spec/ragged.md#step-and-time),
[the cell](spec/ragged.md#the-cell),
[per-step metadata](spec/ragged.md#per-step-metadata),
[the pinned declaration](spec/ragged.md#the-pinned-declaration),
[the commit marker](spec/ragged.md#the-commit-marker-nstep)), and
[Chunking and packing](spec/chunking.md#reference-writer-extents).

## A trajectory whose topology changes

Five frames in which the chemistry moves. Two OH radicals drift; at frame 2
they recombine into H–O–O–H, which adds a bond and retypes the atoms; at
frame 3 a grand-canonical move inserts an argon atom; at frame 4 the
barostat resizes the cell. The producer handed the writer these frames:

| frame | step | blocks the producer presented |
|-------|------|-------------------------------|
| 0 | 0 | `atoms` (4), `bonds` (2: O–H, O–H), `atom_types` (4: `HO`, `OH`, `OH`, `HO`) |
| 1 | 10 | `atoms` (4) |
| 2 | 20 | `atoms` (4), `bonds` (3: the O–O bond forms), `atom_types` (4: `H1`, `O1`, `O1`, `H1`) |
| 3 | 25 | `atoms` (5: argon inserted), `atom_types` (5), `insertions` (1: row 4) |
| 4 | 30 | `atoms` (5), `insertions` (0 rows); cell 12 → 12.25 |

A block a frame does not present is not "missing": it carries forward from
the previous frame.

<!-- BEGIN generated:trajectory-variable -->
```text
reaction.mrec/
 \-- meta/
 |    +-- molrec_version: 1
 \-- trajectory/
      +-- sequence_schema: {
      |      "blocks": {
      |        "atoms": {
      |          "columns": {
      |            "element": {"dtype": "string", "trailing": []},
      |            "x": {"dtype": "f64", "trailing": []},
      |            "y": {"dtype": "f64", "trailing": []},
      |            "z": {"dtype": "f64", "trailing": []}
      |          }
      |        },
      |        "bonds": {
      |          "columns": {
      |            "atomi": {"dtype": "u64", "trailing": []},
      |            "atomj": {"dtype": "u64", "trailing": []}
      |          }
      |        },
      |        "atom_types": {
      |          "columns": {"type": {"dtype": "string", "trailing": []}},
      |          "aligned_with": "atoms"
      |        },
      |        "insertions": {"columns": {"atomi": {"dtype": "u64", "trailing": []}}}
      |      },
      |      "meta": {"pe": {"dtype": "f64"}}
      |    }
      +-- nstep: 5
      \-- meta/
      |    \-- pe: f64[5] = [-4.1, -4.3, -12.2, -12.4, -12.3]
      |         zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |         +-- meta_dtype: "f64"
      \-- step: i64[5] = [0, 10, 20, 25, 30]
      |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      \-- atoms/
      |    \-- step_index: u64[5] = [0, 1, 2, 3, 4]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    \-- offset: u64[6] = [0, 4, 8, 12, 17, 22]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    \-- element: string[22] = ["H", "O", "O", "H", "H", "O", …]
      |    |    zarr: shard [8396800], chunk [2050] · vlen-utf8 → gzip(1) → crc32c
      |    \-- x: f64[22] = [0.8501, -0.0464, 0.0182, -0.8224, 0.8329, -0.0046, …]
      |    |    zarr: shard [8396800], chunk [2050] · bytes → crc32c
      |    \-- y: f64[22] = [0.8844, 0.7426, -0.7219, -0.874, 0.9102, 0.7195, …]
      |    |    zarr: shard [8396800], chunk [2050] · bytes → crc32c
      |    \-- z: f64[22] = [0.4208, -0.0425, 0.0166, 0.4113, 0.4104, -0.0103, …]
      |         zarr: shard [8396800], chunk [2050] · bytes → crc32c
      \-- bonds/
      |    \-- step_index: u64[2] = [0, 2]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    \-- offset: u64[3] = [0, 2, 5]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    \-- atomi: u64[5] = [0, 2, 0, 1, 2]
      |    |    zarr: shard [8392704], chunk [2049] · bytes → gzip(1) → crc32c
      |    \-- atomj: u64[5] = [1, 3, 1, 2, 3]
      |         zarr: shard [8392704], chunk [2049] · bytes → gzip(1) → crc32c
      \-- atom_types/
      |    \-- step_index: u64[3] = [0, 2, 3]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    \-- offset: u64[4] = [0, 4, 8, 13]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    \-- type: string[13] = ["HO", "OH", "OH", "HO", "H1", "O1", …]
      |         zarr: shard [4198400], chunk [1025] · vlen-utf8 → gzip(1) → crc32c
      \-- insertions/
      |    \-- step_index: u64[2] = [3, 4]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    \-- offset: u64[3] = [0, 1, 1]
      |    |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
      |    \-- atomi: u64[1] = [4]
      |         zarr: shard [8388608], chunk [2048] · bytes → gzip(1) → crc32c
      \-- box/
           \-- step_index: u64[2] = [0, 4]
           |    zarr: shard [262144], chunk [1024] · bytes → gzip(1) → crc32c
           \-- vectors: f64[2][3][3] =
                [[[12.0, 0.0, 0.0], [0.0, 12.0, 0.0], [0.0, 0.0, 12.0]], …]
                zarr: shard [262144, 3, 3], chunk [1024, 3, 3] · bytes → gzip(1) → crc32c
```
<!-- END generated:trajectory-variable -->

Each block is its own **sparse update series** in compressed-sparse-row
(CSR) form: `step_index` lists the frame ordinals at which the block was
written, and update `j` owns rows `offset[j] … offset[j+1]` of every column.

- **`atoms` changes every frame and changes size at frame 3**, so it is not
  regular: it carries the index, `step_index = [0, 1, 2, 3, 4]` and
  `offset = [0, 4, 8, 12, 17, 22]`. Row counts are never stored; they are
  the differences of `offset`.
- **`bonds` was written twice**, at frames 0 and 2. Frames 1, 3 and 4 did
  not present it, so they cost nothing and read back the previous bonds.
- **`atom_types` is aligned with `atoms`** (`aligned_with` in
  `sequence_schema`): its rows *are* the atoms' rows. It is written at frame
  0, at frame 2 (retyped) and at frame 3 — restated because `atoms` grew —
  and carries forward at frames 1 and 4, where the atom count did not
  change. Coordinates that move every frame do not drag the types along.
- **`insertions` shows *absent* versus *empty*.** Before frame 3 it has no
  update, so frames 0–2 have no `insertions` block at all. At frame 3 it has
  one row. Frame 4 presented it with zero rows, which is an update too:
  `offset = [0, 1, 1]`, and from frame 4 on the block is present and empty.
  Once a block has appeared it is never absent again.
- **The step numbers are not a progression** (an extra dump at step 25), so
  they are the `step` array.
- **The cell changed**, so `box/` holds arrays: `step_index = [0, 4]` and
  one `vectors` matrix per change.

### How a reader resolves frame `i`

To read block `B` at frame `i`, a reader binary-searches `B/step_index` for
the largest entry `≤ i` — call its position `j`. No such entry means the
block is absent at frame `i`. Otherwise the frame's rows are
`offset[j] … offset[j+1]`; a zero-length range is an empty block, present
with its columns and no rows. A regular block has no index to search: its
update is `j = min(i, n_updates − 1)` and its rows are `j·N … (j+1)·N`. The
cell resolves the same way over `box/step_index`, without a row range.

This table is that algorithm run over the arrays printed above:

<!-- BEGIN generated:resolve -->
| frame `i` | `step[i]` | `atoms` | `bonds` | `atom_types` | `insertions` | `box` |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 | j=0 → `0:4` (4 rows) | j=0 → `0:2` (2 rows) | j=0 → `0:4` (4 rows) | absent | j=0 (edge "12.0") |
| 1 | 10 | j=1 → `4:8` (4 rows) | j=0 → `0:2` (2 rows) | j=0 → `0:4` (4 rows) | absent | j=0 (edge "12.0") |
| 2 | 20 | j=2 → `8:12` (4 rows) | j=1 → `2:5` (3 rows) | j=1 → `4:8` (4 rows) | absent | j=0 (edge "12.0") |
| 3 | 25 | j=3 → `12:17` (5 rows) | j=1 → `2:5` (3 rows) | j=2 → `8:13` (5 rows) | j=0 → `0:1` (1 row) | j=0 (edge "12.0") |
| 4 | 30 | j=4 → `17:22` (5 rows) | j=1 → `2:5` (3 rows) | j=2 → `8:13` (5 rows) | j=1 → `1:1` (empty) | j=1 (edge "12.25") |
<!-- END generated:resolve -->

Take frame 3: in `atoms/step_index = [0, 1, 2, 3, 4]` the largest entry
`≤ 3` is at position 3, so the frame's atoms are rows `12:17` of `x`, `y`,
`z` and `element`. In `bonds/step_index = [0, 2]` it is position 1: the
three bonds of rows `2:5`, written at frame 2 and carried forward. The cost
of a lookup is a search over a block's *changes*, not over the run.

The rules: [Per-block sparse updates](spec/ragged.md#per-block-sparse-updates-csr),
[The three states of a block](spec/ragged.md#the-three-states-of-a-block),
[Aligned blocks](spec/ragged.md#aligned-blocks),
[Resolving a frame](spec/ragged.md#resolving-a-frame).

## The force field

The parameters of the energy model live in their own frame-shaped section:
the group's attributes are the force-field document, and each style is one
table, stored as an ordinary block. This record carries the H–O–O–H system
and a small force field for it.

<!-- BEGIN generated:forcefield -->
```text
peroxide.mrec/
 \-- forcefield/
      +-- name: "h2o2-demo"
      +-- units: {"preset": "real"}
      +-- special_bonds: {"lj": [0.0, 0.0, 0.5], "coul": [0.0, 0.0, 0.8333]}
      +-- styles: [
      |      {"category": "atom", "style": "full"},
      |      {"category": "bond", "style": "harmonic"},
      |      {"category": "angle", "style": "harmonic"},
      |      {"category": "dihedral", "style": "periodic"},
      |      {
      |        "category": "pair",
      |        "style": "lj/cut",
      |        "params": {"cutoff": 10.0, "mixing": "geometric"}
      |      }
      |    ]
      \-- angle.harmonic/
      |    +-- count: 1
      |    \-- name: string[1] = ["H1-O1-O1"]
      |    |    zarr: chunk [1] · vlen-utf8 → gzip(1) → crc32c
      |    \-- itom: string[1] = ["H1"]
      |    |    zarr: chunk [1] · vlen-utf8 → gzip(1) → crc32c
      |    \-- jtom: string[1] = ["O1"]
      |    |    zarr: chunk [1] · vlen-utf8 → gzip(1) → crc32c
      |    \-- ktom: string[1] = ["O1"]
      |    |    zarr: chunk [1] · vlen-utf8 → gzip(1) → crc32c
      |    \-- k: f64[1] = [100.0]
      |    |    zarr: chunk [1] · bytes → crc32c
      |    \-- theta0: f64[1] = [1.7488]
      |         zarr: chunk [1] · bytes → crc32c
      \-- atom.full/
      |    +-- count: 2
      |    \-- name: string[2] = ["H1", "O1"]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- charge: f64[2] = [0.41, -0.41]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- element: string[2] = ["H", "O"]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- mass: f64[2] = [1.008, 15.999]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- ptype: string[2] = ["A", "A"]
      |         zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      \-- bond.harmonic/
      |    +-- count: 2
      |    \-- name: string[2] = ["O1-O1", "O1-H1"]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- itom: string[2] = ["O1", "O1"]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- jtom: string[2] = ["O1", "H1"]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- k: f64[2] = [600.0, 1106.0]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- r0: f64[2] = [1.475, 0.967]
      |         zarr: chunk [2] · bytes → crc32c
      \-- dihedral.periodic/
      |    +-- count: 2
      |    \-- name: string[2] = ["H1-O1-O1-H1", "X-O1-O1-X"]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- itom: string[2] = ["H1", ""]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- jtom: string[2] = ["O1", "O1"]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- ktom: string[2] = ["O1", "O1"]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- ltom: string[2] = ["H1", ""]
      |    |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      |    \-- k1: f64[2] = [1.2, 0.5]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- k2: f64[2] = [0.8, 0.0]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- periodicity1: f64[2] = [1.0, 3.0]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- periodicity2: f64[2] = [2.0, 0.0]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- phase1: f64[2] = [0.0, 0.0]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- phase2: f64[2] = [3.141592654, 0.0]
      |    |    zarr: chunk [2] · bytes → crc32c
      |    \-- _validity/
      |         \-- k2: bool[2] = [true, false]
      |         |    zarr: chunk [2] · bytes → gzip(1) → crc32c
      |         \-- periodicity2: bool[2] = [true, false]
      |         |    zarr: chunk [2] · bytes → gzip(1) → crc32c
      |         \-- phase2: bool[2] = [true, false]
      |              zarr: chunk [2] · bytes → gzip(1) → crc32c
      \-- pair.lj%2Fcut/
           +-- count: 2
           \-- name: string[2] = ["O1-O1", "H1-H1"]
           |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
           \-- itom: string[2] = ["O1", "H1"]
           |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
           \-- jtom: string[2] = ["O1", "H1"]
           |    zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
           \-- epsilon: f64[2] = [0.17, 0.0]
           |    zarr: chunk [2] · bytes → crc32c
           \-- sigma: f64[2] = [3.0, 1.0]
                zarr: chunk [2] · bytes → crc32c
```
<!-- END generated:forcefield -->

- **The document** is plain JSON in the group's attributes: the `name`; the
  `units` every number in the section is in (here the `real` preset:
  ångström, kcal/mol, radian, e, dalton); the 1-2 / 1-3 / 1-4
  `special_bonds` weights; and the ordered `styles` list. A style may carry
  style-level parameters, as `lj/cut` does with its `cutoff` and `mixing`
  rule.
- **One block per style, named `<category>.<style>`.** Bytes of the style
  name outside `A–Z a–z 0–9 - _` are percent-encoded, so `pair` / `lj/cut`
  lives at `pair.lj%2Fcut`.
- **A table has one row per type.** `name` labels the row; `itom` … `ltom`
  name the atom types at its endpoints, as many as the category has (none
  for `atom`, two for `bond`, four for `dihedral`). Every other column is a
  parameter, `f64` or `string`.
- **The empty string is a wildcard.** The second torsion row,
  `X-O1-O1-X`, has `""` at both ends: it matches any type there.
- **Parameters may be strings.** `atom.full/ptype` is one.
- **A parameter a row lacks is null, not zero.** The generic torsion has one
  cosine term, the specific one two, so `k2`, `periodicity2` and `phase2`
  carry masks `[true, false]` under `dihedral.periodic/_validity/`.

The system names its types; it never repeats the numbers:

<!-- BEGIN generated:forcefield-system -->
```text
peroxide.mrec/
 \-- system/
      +-- smiles: "OO"
      +-- total_charge: 0
      +-- _meta_types: {"smiles": "string", "total_charge": "i64"}
      \-- atoms/
      |    +-- count: 4
      |    \-- element: string[4] = ["H", "O", "O", "H"]
      |    \-- type: string[4] = ["H1", "O1", "O1", "H1"]
      \-- bonds/
      |    +-- count: 3
      |    \-- atomi: u64[3] = [0, 1, 2]
      |    \-- atomj: u64[3] = [1, 2, 3]
      |    \-- type: string[3] = ["O1-H1", "O1-O1", "O1-H1"]
      \-- angles/
      |    +-- count: 2
      |    \-- atomi: u64[2] = [0, 3]
      |    \-- atomj: u64[2] = [1, 2]
      |    \-- atomk: u64[2] = [2, 1]
      |    \-- type: string[2] = ["H1-O1-O1", "H1-O1-O1"]
      \-- dihedrals/
           +-- count: 1
           \-- atomi: u64[1] = [0]
           \-- atomj: u64[1] = [1]
           \-- atomk: u64[1] = [2]
           \-- atoml: u64[1] = [3]
           \-- type: string[1] = ["H1-O1-O1-H1"]
```
<!-- END generated:forcefield-system -->

(Its arrays are stored exactly like the frame's above; their `zarr:` lines
are left out here.) Linking is by name: `atoms.type` names a row of the atom
table, and each relation block's `type` names a row of a table of its
category. Resolved against the tables read back from disk:

<!-- BEGIN generated:linking -->
| system row | `type` | table → row | parameters |
| --- | --- | --- | --- |
| `atoms[0]` | `H1` | `atom.full` row 0 | charge 0.41, mass 1.008 |
| `atoms[1]` | `O1` | `atom.full` row 1 | charge -0.41, mass 15.999 |
| `bonds[0]` | `O1-H1` | `bond.harmonic` row 1 | k 1106.0, r0 0.967 |
| `bonds[1]` | `O1-O1` | `bond.harmonic` row 0 | k 600.0, r0 1.475 |
| `angles[0]` | `H1-O1-O1` | `angle.harmonic` row 0 | k 100.0, theta0 1.7488 |
| `dihedrals[0]` | `H1-O1-O1-H1` | `dihedral.periodic` row 0 | k1 1.2, k2 0.8, periodicity1 1.0, periodicity2 2.0, phase1 0.0, phase2 3.141592654 |
<!-- END generated:linking -->

Pair styles are resolved through the atom types instead: two `O1` atoms take
the `O1-O1` row of `pair.lj%2Fcut`, and a pair with no row of its own is
mixed from the two self rows by the style's `mixing` rule.

The rules: [Force field](spec/forcefield.md) — [the document](spec/forcefield.md#the-document),
[style tables](spec/forcefield.md#style-tables),
[endpoints](spec/forcefield.md#endpoints),
[linking a system](spec/forcefield.md#linking-a-system).

## Observables and metrics

**Observables** are named scientific results. Each is a pair: a data array
`observables/<name>` of any shape, and its metadata document as the
attributes of `observables/meta/<name>`. One without the other is malformed.

<!-- BEGIN generated:observables -->
```text
results.mrec/
 \-- observables/
      \-- meta/
      |    \-- dipole/
      |    |    +-- kind: "vector"
      |    |    +-- description: "molecular dipole moment"
      |    |    +-- time_dependent: false
      |    |    +-- unit: "e*angstrom"
      |    \-- msd/
      |         +-- kind: "scalar"
      |         +-- description: "mean squared displacement"
      |         +-- time_dependent: true
      |         +-- unit: "angstrom**2"
      |         +-- sampling: "per_frame"
      \-- dipole: f64[3] = [0.0, 0.0, 0.3929]
      |    zarr: chunk [3] · bytes → crc32c
      \-- msd: f64[4] = [0.0, 0.0011, 0.0024, 0.0031]
           zarr: chunk [4] · bytes → crc32c
```
<!-- END generated:observables -->

`kind` says how to read the array (`vector`: one 3-vector; `scalar`: one
value per sample), and `time_dependent: true` says the leading axis of `msd`
is the trajectory's frames.

**Metrics** are run-local curves (training loss, validation error), kept
apart from scientific results. This run record is the
`fixtures/run-minimal` golden: `meta`, `status` and `method` documents, and
a `metrics/` group holding both forms of the same three events.

<!-- BEGIN generated:metrics -->
```text
fit.mrec/
 \-- meta/
 |    +-- molrec_version: 1
 |    +-- creator: {"name": "molrec-fixtures", "version": "0.0.0"}
 |    +-- created_at: "2026-08-04T00:00:00+00:00"
 \-- method/
 |    +-- type: "training"
 |    +-- description: "fit a potential to the H2O2 conformers"
 |    +-- engine: {"name": "molnex", "version": "0.0.0"}
 \-- status/
 |    +-- state: "succeeded"
 |    +-- stage: "train"
 |    +-- global_step: 2
 |    +-- started_at: "2026-08-04T00:00:00+00:00"
 |    +-- finished_at: "2026-08-04T00:00:02+00:00"
 \-- metrics/
      +-- wal: {"lines": 3, "bytes": 233}
      +-- series: {
      |      "train/loss": {
      |        "type": "scalar",
      |        "count": 2,
      |        "latest_step": 2,
      |        "latest_timestamp": "2026-08-04T00:00:02+00:00"
      |      },
      |      "eval/MAE": {
      |        "type": "scalar",
      |        "count": 1,
      |        "latest_step": 2,
      |        "latest_timestamp": "2026-08-04T00:00:02+00:00"
      |      }
      |    }
      \-- series/
      |    \-- eval%2FMAE: f64[1] = [0.1]
      |    |    zarr: chunk [1] · bytes → crc32c
      |    \-- train%2Floss: f64[2] = [0.5, 0.25]
      |         zarr: chunk [2] · bytes → crc32c
      \-- steps/
      |    \-- eval%2FMAE: i64[1] = [2]
      |    |    zarr: chunk [1] · bytes → gzip(1) → crc32c
      |    \-- train%2Floss: i64[2] = [1, 2]
      |         zarr: chunk [2] · bytes → gzip(1) → crc32c
      \-- wall_time/
      |    \-- eval%2FMAE: string[1] = ["2026-08-04T00:00:02+00:00"]
      |    |    zarr: chunk [1] · vlen-utf8 → gzip(1) → crc32c
      |    \-- train%2Floss: string[2] = ["2026-08-04T00:00:01+00:00", …]
      |         zarr: chunk [2] · vlen-utf8 → gzip(1) → crc32c
      \-- metrics.jsonl    (a plain file, not a Zarr node)

metrics/metrics.jsonl:
{"t":"scalar","k":"train/loss","s":1,"w":"2026-08-04T00:00:01+00:00","v":0.5}
{"t":"scalar","k":"train/loss","s":2,"w":"2026-08-04T00:00:02+00:00","v":0.25}
{"t":"scalar","k":"eval/MAE","s":2,"w":"2026-08-04T00:00:02+00:00","v":0.1}
```
<!-- END generated:metrics -->

- **The live form** is `metrics/metrics.jsonl`, a plain UTF-8 file (not a
  Zarr node) with one JSON object per line, in compact keys: `t` type,
  `k` series key, `s` step, `w` wall time, `v` value. A running job only
  ever appends to it.
- **The closed form** is dense arrays, one per series key and per field:
  `series/` holds the values, `steps/` the steps, `wall_time/` the times,
  aligned index for index. A key becomes an array name by percent-encoding:
  `train/loss` → `train%2Floss`.
- **The catalog** is the attributes of `metrics/`: a summary per series and
  the watermark `wal: {"lines": 3, "bytes": 233}` — the dense arrays hold
  exactly the first 3 lines (233 bytes) of the log. Here that is the whole
  log; lines appended past the watermark would be newer, and a reader would
  add them.

The rules: [Observables](spec/observables.md),
[Metrics](spec/metrics.md), [Metrics WAL](spec/metrics-wal.md),
[Status](spec/status.md), [Method](spec/method.md).

## A collection in LMDB

A training set is thousands of small records read in shuffled order. A
*collection* stores them in one LMDB file, one key per record part, sharing
one trajectory declaration and one force field. This one holds two H2O2
conformer records: record 0 with three frames (the third repeats the
second's coordinates), record 1 with two.

<!-- BEGIN generated:lmdb-keys -->
```text
conformers.mrec.lmdb    (one file; keys in LMDB's byte order)

f ‖ u64be(0)    key bytes 66 00 00 00 00 00 00 00 00
    MRF1 · header 228 B · pad 4 B · payload 96 B
    step 0 · meta {"pe": -12.4}
    atoms[4]: buffers x f64 @0, y f64 @32, z f64 @64
f ‖ u64be(1)    key bytes 66 00 00 00 00 00 00 00 01
    MRF1 · header 228 B · pad 4 B · payload 96 B
    step 1 · meta {"pe": -12.3}
    atoms[4]: buffers x f64 @0, y f64 @32, z f64 @64
f ‖ u64be(2)    key bytes 66 00 00 00 00 00 00 00 02
    MRF1 · header 42 B · pad 6 B · payload 0 B
    step 2 · meta {"pe": -12.2}
    no blocks: nothing changed since the previous frame
f ‖ u64be(3)    key bytes 66 00 00 00 00 00 00 00 03
    MRF1 · header 228 B · pad 4 B · payload 96 B
    step 0 · meta {"pe": -12.4}
    atoms[4]: buffers x f64 @0, y f64 @32, z f64 @64
f ‖ u64be(4)    key bytes 66 00 00 00 00 00 00 00 04
    MRF1 · header 228 B · pad 4 B · payload 96 B
    step 1 · meta {"pe": -12.3}
    atoms[4]: buffers x f64 @0, y f64 @32, z f64 @64
ff              key bytes 66 66
    MRF1 · header 2495 B · pad 1 B · payload 232 B
    meta keys name, units, special_bonds, styles
    atom.full[2]: strings name, element, ptype; buffers mass f64 @0, charge f64 @16
    bond.harmonic[2]: strings name, itom, jtom; buffers k f64 @32, r0 f64 @48
    angle.harmonic[1]: strings name, itom, jtom, ktom; buffers k f64 @64, theta0 f64 @72
    dihedral.periodic[2]: strings name, itom, jtom, ktom, ltom; buffers k1 f64 @80,
        periodicity1 f64 @96, phase1 f64 @112, k2 f64 @128 (validity @144), periodicity2
        f64 @152 (validity @168), phase2 f64 @176 (validity @192)
    pair.lj%2Fcut[2]: strings name, itom, jtom; buffers epsilon f64 @200, sigma f64 @216
index           key bytes 69 6e 64 65 78
    MRF1 · header 353 B · pad 7 B · payload 56 B
    records[2]: strings smiles; buffers first_frame u64 @0, n_frames u64 @16, n_atoms
        u64 @32, has_trajectory bool @48
meta            key bytes 6d 65 74 61
    {
      "layout": "mrec-lmdb",
      "layout_version": 1,
      "collection": {
        "molrec_version": 1,
        "units": {"length": "angstrom", "energy": "kcal/mol"}
      },
      "sequence_schema": {
        "blocks": {
          "atoms": {
            "columns": {
              "x": {"dtype": "f64", "trailing": [], "precision": 0.001},
              "y": {"dtype": "f64", "trailing": [], "precision": 0.001},
              "z": {"dtype": "f64", "trailing": [], "precision": 0.001}
            }
          }
        },
        "meta": {"pe": {"dtype": "f64"}}
      },
      "n_records": 2,
      "n_frames": 5
    }
r ‖ u64be(0)    key bytes 72 00 00 00 00 00 00 00 00
    {"record_id": "h2o2-0"}
r ‖ u64be(1)    key bytes 72 00 00 00 00 00 00 00 01
    {"record_id": "h2o2-1"}
s ‖ u64be(0)    key bytes 73 00 00 00 00 00 00 00 00
    MRF1 · header 523 B · pad 5 B · payload 48 B
    meta {"smiles": "OO", "total_charge": 0} · meta_types {"smiles": "string",
        "total_charge": "i64"}
    atoms[4]: strings element, type
    bonds[3]: strings type; buffers atomi u64 @0, atomj u64 @24
s ‖ u64be(1)    key bytes 73 00 00 00 00 00 00 00 01
    MRF1 · header 523 B · pad 5 B · payload 48 B
    meta {"smiles": "OO", "total_charge": 0} · meta_types {"smiles": "string",
        "total_charge": "i64"}
    atoms[4]: strings element, type
    bonds[3]: strings type; buffers atomi u64 @0, atomj u64 @24
```
<!-- END generated:lmdb-keys -->

- **Keys are bytes, numbers are big-endian.** `r`, `s` and `f` keys are one
  prefix letter followed by a big-endian `u64`, so LMDB's byte order is
  numeric order and one record's frames are one contiguous cursor range.
- **`meta` is JSON and is written last**, in the transaction that commits
  the collection. It carries the layout tag and version, the collection
  document (with `molrec_version` and the `units` every record's numbers
  are in), the one `sequence_schema` every record uses, and the counts.
- **`index`** is one block `records` with a row per record: the binding's
  own `first_frame`, `n_frames`, `n_atoms`, `has_trajectory`, plus the
  collection's columns (`smiles`). Record 1's frames start at global
  ordinal 3.
- **`r‖u64be(r)`** is record `r`'s meta document; **`s‖u64be(r)`** its
  system, which types its own meta (`meta_types`).
- **`f‖u64be(j)`** is the trajectory update at *global* frame ordinal `j`,
  holding only the blocks that changed there. Frame 2 changed nothing but
  its energy, so its value has no blocks at all; record 1's first frame
  (`f‖u64be(3)`) restates `atoms`, because carry-forward never crosses a
  record boundary.
- **`ff`** is the collection's force field: the document as the frame's
  meta, one block per style table.

Every value except `meta` and `r` is *frame bytes*: a small fixed header,
a JSON description, then the numeric columns as raw buffers that a reader
can view in place. Here is `f‖u64be(1)`, byte range by byte range:

<!-- BEGIN generated:lmdb-frame -->
```text
key f ‖ u64be(1) = 66 00 00 00 00 00 00 00 01; value 336 B

[0, 4)      magic           'MRF1'
[4, 8)      header_length   228 (u32, little-endian)
[8, 236)    header          UTF-8 JSON:
                {
                  "blocks": {
                    "atoms": {
                      "count": 4,
                      "structural_shape": null,
                      "columns": {
                        "x": {"dtype": "f64", "shape": [4], "offset": 0},
                        "y": {"dtype": "f64", "shape": [4], "offset": 32},
                        "z": {"dtype": "f64", "shape": [4], "offset": 64}
                      }
                    }
                  },
                  "meta": {"pe": -12.3},
                  "step": 1
                }
[236, 240)  padding         4 zero bytes
[240, 272)  atoms/x         f64 = [0.8212890625, -0.0517578125, -0.0078125, -0.8369140625]
[272, 304)  atoms/y         f64 = [0.900390625, 0.751953125, -0.751953125, -0.876953125]
[304, 336)  atoms/z         f64 = [0.4345703125, -0.017578125, -0.0126953125, 0.375]
```
<!-- END generated:lmdb-frame -->

The buffers are little-endian and start at multiples of 8, so a reader on a
little-endian machine can map them straight into arrays. String columns have
no buffer: their values ride in the header (`element` in the `s` values
above). A nullable column adds a mask buffer, as the `ff` value's torsion
parameters show (`validity @…`). Trajectory columns carry no `precision` of
their own — the collection's `sequence_schema` declares `0.001` for `x`,
`y`, `z` — but their values are already on the grid: `0.8212890625` is
841/1024.

The rules: [Collection](spec/collection.md), [LMDB binding](spec/lmdb.md)
([the file](spec/lmdb.md#the-file), [frames](spec/lmdb.md#frames),
[frame bytes](spec/lmdb.md#frame-bytes)).

## The packed form `x.mrec.zip`

A record that is finished — no longer being appended to — can be packed into
one file. Packing is a zip of the directory with every chunk copied as it
is: the water record of the second section, packed:

<!-- BEGIN generated:packed -->
```text
water.mrec.zip    30 entries, all stored (method 0): true, directory entries: 0
                  reads back equal to water.mrec/: true

  frame/atoms/_validity/b_factor/c/0          chunk 0
  frame/atoms/_validity/b_factor/zarr.json    array metadata
  frame/atoms/_validity/zarr.json             group metadata
  frame/atoms/b_factor/c/0                    chunk 0
  frame/atoms/b_factor/zarr.json              array metadata
  frame/atoms/element/c/0                     chunk 0
  frame/atoms/element/zarr.json               array metadata
  frame/atoms/mass/c/0                        chunk 0
  frame/atoms/mass/zarr.json                  array metadata
  frame/atoms/x/zarr.json                     array metadata
  frame/atoms/y/c/0                           chunk 0
  frame/atoms/y/zarr.json                     array metadata
  frame/atoms/z/c/0                           chunk 0
  frame/atoms/z/zarr.json                     array metadata
  frame/atoms/zarr.json                       group metadata
  frame/bonds/atomi/zarr.json                 array metadata
  frame/bonds/atomj/c/0                       chunk 0
  frame/bonds/atomj/zarr.json                 array metadata
  frame/bonds/bond_type/c/0                   chunk 0
  frame/bonds/bond_type/zarr.json             array metadata
  frame/bonds/zarr.json                       group metadata
  frame/box/vectors/c/0/0                     chunk 0/0
  frame/box/vectors/zarr.json                 array metadata
  frame/box/zarr.json                         group metadata
  frame/density/rho/c/0                       chunk 0
  frame/density/rho/zarr.json                 array metadata
  frame/density/zarr.json                     group metadata
  frame/zarr.json                             group metadata
  meta/zarr.json                              group metadata
  zarr.json                                   group metadata
```
<!-- END generated:packed -->

- **Entry names are relative to the record root**: `zarr.json`,
  `meta/zarr.json`, `frame/atoms/x/zarr.json`; the directory `water.mrec/`
  is not part of any name.
- **Every entry is *stored*** (compression method 0). Chunks are already
  compressed by their codec pipeline, and a second layer would cost random
  access.
- **There are no directory entries**: a Zarr store has keys, not folders.
- `frame/atoms/x/c/0` and `frame/bonds/atomi/c/0` are not there: those
  chunks hold only the fill value (zeros), and Zarr does not write such a
  chunk. A reader returns the zeros.

Any zip-backed Zarr store opens it (zarr-python's `ZipStore`, zarrs'
`ZipStorageAdapter`), and reading it gives back the record exactly.

The rules: [At-rest form](spec/chunking.md#at-rest-form-mreczip).

## Cost cheat-sheet

What a trajectory costs on disk follows how often its sections *change*,
not how long the run is. For coordinates, the bytes per atom per frame of
the three columns `x`, `y`, `z` through the reference pipeline (3000 atoms
scattered in a box — no molecular order, the worst case for a compressor —
over 40 frames; shard indexes not counted):

<!-- BEGIN generated:cost-density -->
| coordinates `x`, `y`, `z` | pipeline | bytes per atom per frame |
| --- | --- | ---: |
| lossless `f64` | bytes → crc32c | 24.0 |
| precision `p = 1e-3` | bytes → shuffle(8) → zstd(3) → crc32c | 7.6 |
| precision `p = 1e-2` | bytes → shuffle(8) → zstd(3) → crc32c | 5.8 |
<!-- END generated:cost-density -->

A lossless `f64` column is stored uncompressed: random low mantissa bits do
not compress, and skipping the compressor keeps reads fast. A declared
precision is what buys density: `p = 1e-3` Å keeps every coordinate within
half a milliångström and stores a third of the bytes.

What the two trajectories above pay beyond their column values:

<!-- BEGIN generated:cost-sections -->
| record | section | updates | on disk beyond the column values |
| --- | --- | --- | --- |
| vibration.mrec | `step` | — | attribute `step_progression` |
| vibration.mrec | `time` | — | attribute `time_progression` |
| vibration.mrec | `atoms` | 4 | nothing: `uniform_rows` + `dense_updates` attributes |
| vibration.mrec | `box` | 1 | nothing: attribute `vectors` on `box/` |
| reaction.mrec | `step` | — | `step` array, 5 entries |
| reaction.mrec | `atoms` | 5 | `step_index` (5) + `offset` (6): 88 B raw |
| reaction.mrec | `bonds` | 2 | `step_index` (2) + `offset` (3): 40 B raw |
| reaction.mrec | `atom_types` | 3 | `step_index` (3) + `offset` (4): 56 B raw |
| reaction.mrec | `insertions` | 2 | `step_index` (2) + `offset` (3): 40 B raw |
| reaction.mrec | `box` | 2 | `step_index` (2) + `vectors` (2×3×3) |
<!-- END generated:cost-sections -->

**Costs nothing beyond the values:**

- a block whose row count is constant and which is written every frame (or
  once and never again): two attributes, no index;
- a fixed cell: one attribute;
- step and time numbers that are arithmetic progressions: one attribute
  each;
- a frame that omits a block, or presents it unchanged bit for bit: no
  update at all;
- topology kept in `system/`: written once, whatever the run length.

**Costs per change:**

- every update of a block that is not regular: one `step_index` entry and
  one `offset` entry (16 bytes before compression) plus the update's rows;
  the first irregular update also writes the index for the updates before
  it;
- every change of the cell: one `step_index` entry and one 3×3 `vectors`
  matrix (plus `origin` / `boundary` when off their defaults);
- step numbers that break the progression: the whole `step` array, 8 bytes
  per frame;
- each per-step meta key: one value per frame.

The number of files grows with the number of arrays and with the bytes
written, never with the number of frames: a shard holds thousands of chunks.
In LMDB nothing is compressed — a collection is built for random reads — so
coordinates cost their 24 raw bytes per atom, plus a header of a couple of
hundred bytes per frame value.

The rules: [Cost tracks change](spec/ragged.md#cost-tracks-change),
[Chunking and packing](spec/chunking.md).
