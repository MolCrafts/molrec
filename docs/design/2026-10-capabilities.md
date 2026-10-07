# Design: five record capabilities (2026-10)

Status: **design, ready to implement**. Every decision below is made; the
open questions at the end are the only ones left, and none blocks an
implementer.

| # | Capability | New normative text |
|---|------------|--------------------|
| F1 | Declared precision + shuffle/zstd | `frame.md`, `ragged.md`, `chunking.md`, `zarr.md`, `lmdb.md` edits |
| F2 | `forcefield` root section | [`docs/spec/forcefield.md`](../spec/forcefield.md) (new) + edits |
| F3 | Typed frame meta (`_meta_types`) | `frame.md`, `storage.md`, `lmdb.md` edits |
| F4 | Topology conventions + `targets` | `conventions.md`, `frame.md`, `ragged.md`, `storage.md` edits |
| F5 | Aligned trajectory blocks | `ragged.md`, `trajectory.md`, `collection.md`, `lmdb.md` edits |

Two implementers work in parallel:

- **A — molrec**: `src/molrec/core/model.py` (the models *are* the
  contract), `src/molrec/core/bindings/{zarr,lmdb}.py`,
  `src/molrec/core/suite.py`, `src/molrec/schema_export.py`, the chapters.
- **B — molrs** (`molrs-align` tree): `molrs/src/core/store`,
  `molrs/src/io/zarr`, `molrs/src/ff/forcefield`, `molrs-python/src`,
  `molrs-wasm`.

A and B share only the chapters and the conformance case ids. B validates
against A's suite through `tests/molrs_adapter.py`.

## 0. Baseline and cross-cutting decisions

**Baseline.** This design is written against the chapters *after* the
alignment pass: `molrec_version` always stamped; one float dtype `f64`
(`f16`/`f32` gone; `c64`/`c128` remain); the per-step tag set is molrs's
sixteen (`bool i32 i64 u32 u64 f64 string bool3 i32x3 i64x3 u32x3 u64x3 f64x3
f64x6 f64x9 json`, `META_LAYOUT` in `model.py`); nullable columns with
`<block>/_validity/<column>` masks and `nullable` in `sequence_schema`; the
typed JSON value forms of `molrec.jsonvalue` (NaN as `"NaN"`, integers beyond
2⁵³ as decimal strings, complex as `[re, im]`) specified in
`conventions.md`; canonical key widths normative; `system` strictly
frame-shaped and flat; `system/parameters` removed.

Every chapter edit below is a block "**E<f>.<n> — <chapter> § <section>:
replace / insert …**" whose fenced body is the final text. Anchor on the
section heading; where the alignment pass has reworded the anchor paragraph,
anchor on its first sentence. Apply after the alignment pass lands.

**D0.1 — Version.** The five capabilities are part of `molrec_version` 1.
Rationale: the alignment pass is what introduces the stamp; no reader bound to
version 1 has been released, and four of the five are additive (an unaware
reader carries them through). The fifth — `numcodecs.shuffle` and `zstd` in
the must-decode set — is a reader obligation, which is exactly what version 1
is being fixed to now. *Contingency:* if version 1 has shipped by the time F1
lands, set `MOLREC_VERSION = 2`, make the must-decode change the version-2
rule, and stamp a package `2` only when one of its arrays uses `zstd` or
`numcodecs.shuffle` (stamp `1` otherwise); the other four stay additive in 1.

**D0.2 — Landing order.** F3, F4 and F5 are independent of each other. F1
needs nothing. F2 uses F4's `style` column and the relation blocks; land F4's
conventions edit first or together. Suggested order: F1 ∥ F3 ∥ F5, then F4,
then F2.

**D0.3 — One quantization function, one block-name function.** Both are
specified bit-exactly (F1, F2) so that two implementations store the same
bytes and resolve the same names; the suite compares exactly.

---

## F1. Declared precision, and a codec that pays for it

### F1.1 Rationale

Coordinates are stored as `f64` and nothing else (molrs 0.15 rule), so a
trajectory costs 24 B per atom per frame and gzip saves 5 %: 52 random
mantissa bits do not compress. A producer usually knows its data is good to
10⁻³ Å. Letting the writer *round* to a declared absolute tolerance — on a
binary grid, so the discarded bits become zeros — and pairing that with a
byte shuffle and a fast entropy coder cuts a trajectory to a third, with no
new dtype, no lossy codec, and nothing new for a reader to do. Absolute
rounding is chosen over bit-rounding because it is unit-aware and uniform
(the same 0.001 Å everywhere in the box, as XTC does); bit-rounding is
relative, so precision degrades with distance from the origin and is
needlessly fine near zero. The grid is a power of two because a decimal grid
(multiples of 10⁻³) leaves a full 52-bit mantissa that a shuffle cannot
compress (measured: 20.6 B/atom/frame, no better than raw).

### F1.2 Decisions

- **D1.1** Opt-in, per column, `f64` only. Absent = stored as given (today's
  behaviour; the reference writer's default stays lossless).
- **D1.2** Quantum `q = 2^(e−1)` where `p = m·2^e`, `0.5 ≤ m < 1` (C/Rust/Python
  `frexp`) — the largest power of two `≤ p`. `stored(x) = roundTiesToEven(x/q)·q`
  for finite `|x| < 2⁵²·q`, else `x`. Writers **MUST** store exactly this.
- **D1.3** Bounds: `p` finite, `2⁻¹⁰⁰⁰ ≤ p ≤ 2¹⁰⁰⁰` (keeps `q` normal and
  `x/q` exact).
- **D1.4** Codecs. zarrs 0.23.14 implements `numcodecs.shuffle` in pure Rust
  on every target with no feature flag; zarr-python 3.3 registers it
  (`zarr.registry.get_codec_class("numcodecs.shuffle")`, verified). `blosc` is
  rejected: zarrs' wasm32 path (`blusc`) depends unconditionally on the C
  `zstd` crate, and blosc widens the must-decode surface to five internal
  compressors for no density gain over shuffle + zstd as separate codecs.
  `zstd` is promoted from SHOULD to MUST: it is zarr-python's own default
  compressor, it is 8× faster to encode and 7× faster to decode than gzip-1
  at equal or better density, and a pure-Rust decoder (`ruzstd`) lets
  wasm32 decode it without C.
  Must-decode becomes `bytes gzip zstd numcodecs.shuffle crc32c vlen-utf8
  sharding_indexed transpose`.
- **D1.5** Reference pipeline for a precision column:
  `bytes → numcodecs.shuffle{elementsize: 8} → zstd{level: 3} → crc32c`.
  A writer that cannot *encode* zstd (the reference wasm32 build) uses
  `numcodecs.shuffle` then `gzip` level 1. Non-precision float columns keep
  today's default (raw) and today's knob.
- **D1.6** Where declared: frame/system column → the column array's
  attribute `precision`; trajectory column → its `sequence_schema` entry only;
  LMDB → the frame-bytes column header (`system`, `index`) or the collection's
  `sequence_schema` (trajectory frames).
- **D1.7** Carry-forward compares the **stored** (rounded) presentation with
  the previous update: a change below `q/2` is no change.
- **D1.8** Readers do nothing new: no re-rounding, no grid check, no refusal.
  An off-grid value is a writer defect a validator reports.
- **D1.9** Per-step `meta` keys and the cell take no precision (out of scope).
- **D1.10** Forcefield tables take no precision (parameters are exact).

### F1.3 Expected density

Measured with molrec's environment (numcodecs 0.16.5): 3000 atoms uniform in
a 40 Å box, 40 frames, a 0.05 Å random walk per frame, one inner chunk per
column per frame (the reference extents for this size). Uniform random
placement is the worst case — real MD orders atoms by molecule — so treat
these as upper bounds. The entropy floor of this box is 5.7 B (p = 10⁻³) and
4.6 B (p = 10⁻²).

| Encoding | B / atom / frame |
|----------|-----------------:|
| f64 raw | 24.0 |
| f64 gzip-1 (prior measurement) | 22.9 |
| f64 shuffle + zstd-3, no precision | 21.4 |
| p = 10⁻³ Å (q = 2⁻¹⁰), shuffle + zstd-3 **(reference)** | **7.6** |
| p = 10⁻³ Å, shuffle + gzip-1 (wasm writer) | 7.9 |
| p = 10⁻³ Å, decimal grid instead of binary, shuffle + zstd-3 | 20.6 |
| p = 10⁻² Å (q = 2⁻⁷), shuffle + zstd-3 | 5.8 |
| p = 10⁻² Å, shuffle + gzip-1 | 6.1 |
| f32 bitround-12 + shuffle + zstd (prior; not admissible: f32) | 5.2 |
| 0.01 Å quantized + time-delta + zstd (prior; needs a delta codec) | 4.0 |

Throughput on the shuffled, quantized bytes: zstd-3 encodes at ~1.2 GB/s and
decodes at ~4.2 GB/s; gzip-1 at ~150 MB/s and ~600 MB/s.

### F1.4 Chapter edits

**E1.1 — frame.md: insert a new section after § "Nullable columns" (before
§ "Simulation box"):**

~~~markdown
## Declared precision

An `f64` column may declare a **precision** `p`: an absolute tolerance in the
column's own units (`1e-3` on coordinates in Å keeps them to a thousandth of
an ångström). It is the writer's statement about the values it stored, not a
codec and not a dtype: the column is `f64`, a reader decodes it knowing
nothing of `p`, and the values it returns are exactly the stored ones.

From `p` a writer derives the **quantum** `q`, the largest power of two not
above `p`: with `p = m · 2^e` and `0.5 ≤ m < 1`,

```text
q = 2^(e − 1)
```

and stores, for each value `x`,

```text
stored(x) = x                              when x is NaN or ±∞, or |x| ≥ 2^52 · q
stored(x) = roundTiesToEven(x / q) · q     otherwise
```

in binary64. Both operations are exact (`q` is a power of two), so two
writers store the same bits; a writer **MUST** store exactly `stored(x)`.
Every finite stored value is an integer multiple of `q`, and
`|x − stored(x)| ≤ q/2 ≤ p/2`. A null row (its validity flag false) is
unconstrained.

The grid is binary on purpose: a multiple of `2^−10` has zero low-order
mantissa bits, which a byte shuffle gathers into runs a lossless compressor
removes ([Chunking](chunking.md)); a multiple of `10^−3` has a full mantissa
and compresses no better than raw data.

- `p` is a finite binary64 with `2^−1000 ≤ p ≤ 2^1000`. Only an `f64`
  column declares one; a writer refuses any other.
- On a frame-shaped section `p` is the column array's attribute
  `precision`. On a trajectory it is the column's entry in the pinned
  [`sequence_schema`](ragged.md#the-pinned-declaration) and nowhere else.
- Absent means the values are stored as given.
- A reader preserves the declaration: a record read and written back
  declares the same `p`.
- A reader does not re-round, re-check or refuse. A stored value off the grid
  is the writer's defect; a validator **SHOULD** report it.
~~~

**E1.2 — ragged.md § "The pinned declaration": replace the bullet that
begins "`blocks`: a map of block name to …" with:**

~~~markdown
- `blocks`: a map of block name to `{columns, structural_shape?, targets?,
  aligned_with?}`, each column `{dtype, trailing, nullable?, precision?}`.
  Column `dtype`s are the closed record dtype set; `trailing` is the
  per-entity shape after the leading count axis; `nullable: true` declares a
  [nullable column](#nullable-columns) and is written only when true (absent
  means `false`); `precision` is the column's
  [declared precision](frame.md#declared-precision), the only place a
  trajectory states it, written only when declared; `targets` is the
  block's [row references](frame.md#row-references); `aligned_with` makes it
  an [aligned block](#aligned-blocks). Each of the last three is written only
  when set.
~~~

(`targets` and `aligned_with` are F4 and F5; apply this one bullet once.)

**E1.3 — ragged.md § "The three states of a block": replace the bullet
"A writer compares a presented block with its previous update **bitwise** …"
with:**

~~~markdown
- A writer compares a presented block with its previous update **bitwise**,
  after rounding every column that declares a
  [precision](frame.md#declared-precision); an identical presentation writes
  no update. A repeated `NaN` therefore counts as unchanged, and so does a
  change smaller than half the quantum.
~~~

**E1.4 — chunking.md § "Normative": replace the paragraph "**Must-decode codec
set.** …" and its code block with:**

~~~markdown
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
~~~

**E1.5 — chunking.md § "Reference writer: codecs": replace the whole section
body with:**

~~~markdown
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
~~~

**E1.6 — zarr.md § "What V3 gives a record", bullet "**One codec pipeline.**":
replace its last two sentences ("The contract names a small must-decode set
… Nothing lossy.") with:**

~~~markdown
The contract names a small must-decode set — `bytes`, `gzip`, `zstd`,
`numcodecs.shuffle`, `crc32c`, `vlen-utf8`, `sharding_indexed`, `transpose` —
that every reader of these stores, wasm32 included, decodes. Nothing lossy: a
declared precision rounds values before they are encoded. See
[Chunking](chunking.md#normative).
~~~

**E1.7 — lmdb.md § "Frame bytes": after the bullet beginning "Every numeric
column is one buffer", insert:**

~~~markdown
* A column of a `system` or `index` frame that declares a
  [precision](frame.md#declared-precision) carries `"precision": p` in its
  header entry, and its buffer holds the rounded values. A trajectory frame's
  columns carry none: the collection's `sequence_schema` declares them. No
  codec is applied: frame bytes are raw buffers.
~~~

**E1.8 — collection.md § "Model", `sequence_schema` paragraph: replace
"blocks, columns, dtypes, trailing shapes, per-step meta tags and fills" with
"blocks, columns, dtypes, trailing shapes, nullability, precisions, row
references, alignments, per-step meta tags and fills".**

### F1.5 Model (A)

New module `src/molrec/precision.py`:

```python
PRECISION_MIN: float = 2.0**-1000
PRECISION_MAX: float = 2.0**1000


def quantum(precision: float) -> float:
    """2**(e-1) for precision = m * 2**e, 0.5 <= m < 1 (math.frexp)."""


def quantize(values: np.ndarray, precision: float) -> np.ndarray:
    """stored(x) of docs/spec/frame.md#declared-precision, elementwise, float64.
    np.round is round-half-to-even; x / q and k * q are exact."""


def on_grid(values: np.ndarray, precision: float) -> bool:
    """Every finite value is a multiple of quantum(precision) (validators)."""
```

`model.py`:

```python
Precision = Annotated[float, Field(ge=PRECISION_MIN, le=PRECISION_MAX, allow_inf_nan=False)]


class ColumnModel(BaseModel):
    ...
    precision: Precision | None = None
    # validator (after, in _values_match_declaration):
    #   precision is not None and dtype != "f64"  -> ValueError
    #   precision is not None and values is not None
    #       -> object.__setattr__(self, "values", quantize(values, precision))
    # __eq__ additionally compares precision.


class SequenceColumnModel(BaseModel):
    ...
    precision: Precision | None = None
    # validator: precision only with dtype "f64"
    # serializer: omit when None (extend _nullable_only_when_true -> _omit_defaults)
```

Like `BoxModel` materializing its defaults, a validated model holds the
**stored** values; that is what a reader hands back, and every suite
comparison stays exact.

- `declare_block(block)` copies `column.precision` into the declaration.
- `TrajectoryModel._blocks_keep_one_declaration`: `_layout()` keeps
  comparing `(dtype, trailing)` only. Add: a presented column whose
  `precision` is set and differs from the declared one is refused; with
  `blocks` unstated, the derived declaration takes the first presented
  non-`None` precision of each column (union, like `nullable`).
- New validator `TrajectoryModel._declared_precision_rounds_every_frame`
  (after the declaration, before `_omission_carries_forward`): replace each
  presented column of a precision-declared column with `quantize(...)`.
  Frames' columns then carry `precision=None`; the declaration is the
  single source.

### F1.6 Codecs (A)

`core/bindings/zarr.py`:

- `PRECISION_ATTR = "precision"`;
  `_compressors(dtype, dense, precision=None)` returns
  `(Shuffle(elementsize=8), ZstdCodec(level=3), Crc32cCodec())` when
  `precision` is set, the shuffle class taken from
  `zarr.registry.get_codec_class("numcodecs.shuffle")`.
- `_create_fixed(group, name, shape, dtype, precision=None)` passes it
  through and sets `array.attrs[PRECISION_ATTR] = precision`.
  `ZarrFrameCodec._write_block` writes `column.values` (already stored
  values). `_read_column` reads `precision=array.attrs.get(PRECISION_ATTR)`.
- `ZarrTrajectoryCodec._write_block` passes the pinned column's precision to
  `_create_column`; no array attribute on the trajectory path. `_updates()`
  compares stored values (they already are, per F1.5).
- `pyproject.toml`: `zarr>=3.3` (the version verified to register
  `numcodecs.shuffle`).

`core/bindings/lmdb.py`: `encode_frame` writes `"precision"` into a column's
header entry when `column.precision` is set (system and index frames only);
`decode_frame` restores it.

### F1.7 molrs (B)

- **New** `molrs/src/core/store/precision.rs`:
  `pub const PRECISION_MIN/MAX: f64`; `pub fn quantum(p: f64) ->
  Result<f64, MolRsError>` (bounds + finiteness; via `frexp` on the bits);
  `pub fn quantize(x: f64, q: f64) -> f64` (`(x / q).round_ties_even() * q`
  under the `|x| < 2⁵²·q` and finiteness guards); `pub fn
  quantize_in_place(values: &mut [f64], q: f64)`. Unit tests: ties go to
  even, `-0.0` stays `-0.0` for small negatives, NaN/±∞/huge untouched,
  `|x − stored| ≤ q/2` on a random sweep, `quantum(1e-3) == 2^-10`,
  `quantum(0.5) == 0.5`.
- `molrs/src/core/store/block/mod.rs`: a side table `precision:
  IndexMap<String, f64>` beside the validity masks. `Block::set_precision(&mut
  self, column, p) -> Result<(), BlockError>` (refuses a non-`Float` column
  and out-of-bounds `p`), `Block::precision(&self, column) -> Option<f64>`,
  `Block::clear_precision`. Removing a column drops its entry; renaming
  carries it; replacing a column with a non-`Float` one drops it.
- `molrs/src/io/zarr/frame_io.rs`: `write_column(store, path, col,
  precision: Option<f64>)` quantizes a copy, builds the inner codecs
  `[ShuffleCodec::new(8), compressor, Crc32cCodec]` (compressor `ZstdCodec(3,
  false)` under `zarr-codecs`, else `GzipCodec(1)`), and stores the array
  attribute `precision`. `write_frame_group` passes `block.precision(name)`.
  `read_frame_group` reads the attribute back into `Block::set_precision`.
  Update the `GZIP_LEVEL` doc comment ("a precision study admits no lossy
  codec") to point at declared precision.
- `molrs/src/io/zarr/sequence.rs`:
  - `ColumnSchema { …, #[serde(default, skip_serializing_if =
    "Option::is_none")] precision: Option<f64> }`.
  - `SequenceSchema::declare_precision(&mut self, block, column, p) ->
    Result<&mut Self, MolRsError>` (refuses an undeclared or non-`f64`
    column); `from_frame` / `from_frames` take `Block::precision`.
  - `inner_codecs(compression, shuffle: Option<usize>)`: shuffle first; for a
    precision column `Compression::None` means the default (`Zstd(3)` under
    `zarr-codecs`, else `Gzip(1)`).
  - `FrameSequenceWriter::append`: quantize every precision column of the
    presented frame (copy) **before** the `same_block` comparison and before
    landing (D1.7).
  - `schema_from_store` / `pinned_schema` read `precision`.
- **wasm32 zstd decode.** New `molrs/src/io/zarr/zstd_decode.rs`,
  `#[cfg(all(feature = "zarr", not(feature = "zarr-codecs")))]`: a
  decode-only bytes-to-bytes codec over `ruzstd` (pure Rust), registered with
  zarrs' codec plugin inventory under the V3 name `zstd`; `encode` returns an
  error naming the codec. `molrs/Cargo.toml`: `ruzstd = { version = "0.8",
  optional = true }` enabled by the `zarr` feature (it compiles everywhere;
  the module is only built without `zarr-codecs`). Fallback, only if the
  plugin cannot be registered against zarrs 0.23: enable `zarrs/zstd` for
  wasm32 and build `zstd-sys` with its `wasm-shim` (needs clang with the
  wasm32 target in the wasm CI). `numcodecs.shuffle` needs nothing: zarrs
  builds it on every target.
- `Compression` doc comment: drop "wasm32 readers do not decode it".
- `molrs-python/src/core/store/block.rs`: `Block.set_precision(column,
  precision)`, `Block.precision(column) -> float | None`.
  `molrs-python/src/io/mrec.rs`: `SequenceSchema.declare_precision(block,
  column, precision)`. Stubs in `molrs-python/python/molrs/_lib.pyi`.
- Tests: `molrs/tests` — frame round trip keeps `precision` and stored values;
  trajectory sub-quantum change writes one update (`block_update_at` stays
  at 0); a store written with shuffle + zstd reads back in a
  `--no-default-features --features zarr` build (the wasm configuration);
  `molrs-wasm` reads the molrec fixture `fixtures/precision.mrec.zip`.

### F1.8 Conformance (A)

| Suite | Case | Asserts |
|-------|------|---------|
| frame | `precision-rounds-on-write` | an `f64` column with `p = 1e-3` and unrounded values reads back as `quantize(values, 1e-3)`, exactly |
| frame | `precision-declaration-survives` | the declared `p` reads back |
| frame | `precision-edge-values` | NaN, ±∞, `-0.0`, a value `≥ 2⁵²·q`, and exact ties (`2.5·q` → `2q`, `3.5·q` → `4q`) |
| frame | `precision-shuffle-zstd-decodes` | a column the reference codec wrote with `numcodecs.shuffle` + `zstd` decodes (implicit in the cases above; kept as its own id so a reader without the codecs fails by name) |
| frame | `reject-precision-on-non-f64` (write) | an `i64` column declaring `p` is refused |
| frame | `reject-precision-out-of-bounds` (write) | `p = 0`, `p = -1`, `p = inf` are refused |
| trajectory | `precision-in-sequence-schema` | the declaration pins `p`; every frame's values read back rounded |
| trajectory | `precision-sub-quantum-carries-forward` | frames 0 and 1 differ by `< q/2`; both read back as frame 0's stored values |
| trajectory | `reject-frame-precision-disagrees` (write) | a frame column stating another `p` than the pinned one is refused |
| collection | `precision-in-collection` | a precision-declared system column and trajectory column survive the LMDB binding |

### F1.9 Migration

Stores without `precision` are unchanged and read as before. A store written
with shuffle/zstd is unreadable to a reader built before the must-decode
change (see D0.1). The default writer output for float columns is unchanged
unless a precision is declared.

---

## F2. The `forcefield` root section

### F2.1 Rationale

A record that carries a typed topology cannot be evaluated without the
parameters its types name, and `system/parameters` never had a layout. A
peer root section — a JSON document plus one table per style — carries a
force field as data any frame codec can read, links to a topology by type
*name*, keeps its units instead of converting them, and maps one-to-one onto
molrs's `ForceField` (styles of a category, typed rows with endpoints and a
parameter bag, units, special bonds, combining rule) as well as onto OpenMM,
OpenFF, GROMACS and LAMMPS sources.

### F2.2 Decisions

- **D2.1** The chapter is [`forcefield.md`](../spec/forcefield.md); it is the
  normative text of this feature.
- **D2.2** Frame-shaped: group attributes = document; one block per style.
  The frame block layout (count, columns, `_validity`) is reused verbatim.
  The document is plain JSON — no `_meta_types` (F3) on this group.
- **D2.3** Block name `<category>.<pct-encoded style>`, unreserved bytes
  `A-Z a-z 0-9 - _`. The style entry carries no `block` field: the name is a
  function of `(category, style)`, so one cannot disagree with the other.
- **D2.4** Param columns are `f64` or `string` only; absent = null via
  `_validity`.
- **D2.5** `mixing` is a **style-level** param of a van-der-Waals pair style
  (molrs and LAMMPS keep it there; it is per sub-style under `hybrid`), not a
  document key.
- **D2.6** `units` is required; `special_bonds` optional (absent ≠ default).
- **D2.7** Endpoints `itom…ltom` (molrs names); `""` = wildcard (molrs
  convention); `endpoint_key ∈ {type, class, smirks}`.
- **D2.8** Hybrid = an optional relation column `style`. Several styles of a
  category holding the same name, with no `style` column, add.
- **D2.9** Per-instance parameters stay relation columns (MMFF/UFF); a
  zero-row style table declares the style.
- **D2.10** Categories beyond molrs's six: `pair14`, `constraint`,
  `virtual_site`, `drude`; any other category is preserved with arity from
  its endpoint columns. Templates (OpenMM `<Residues>`) and typing rules as a
  separate table are out of scope; typing patterns are atom-table columns
  (`smarts`, `smirks`, `overrides`).
- **D2.11** A record may consist of `meta` + `forcefield` only.
- **D2.12** A collection has at most one force field (LMDB key `ff`, frame
  bytes); records of a collection carry none.

### F2.3 Chapter edits

**E2.1 — overview.md: replace the root tree and the sentence after it
with:**

~~~markdown
```text
root
 \-- meta
 \-- (system)
 \-- (frame)
 \-- (trajectory)
 \-- (forcefield)
 \-- (observables)
 \-- (method)
 \-- (status)
 \-- (metrics)
```

A package includes `meta` and at least one of `frame`, `system`,
`trajectory`, `forcefield`, or `status`. Inside a section, every group or
array is again optional unless that section's chapter says otherwise.
~~~

**E2.2 — overview.md § "Typical compositions" table: insert a row after
"System def":**

~~~markdown
| Force field | `meta`, `forcefield` | a parameter set, distributed on its own |
~~~

**E2.3 — overview.md § "Section kinds", **Frame-shaped** paragraph: replace
"`frame` and `system` are frame-shaped; so is each named observable's data."
with "`frame`, `system` and [`forcefield`](../spec/forcefield.md) are frame-shaped;
so is each named observable's data."**

**E2.4 — overview.md § "Design principles", **Facts vs arrays**: replace the
sentence "Force-field and model tables that *define* the system live under
`system/parameters`; how a job was run lives under `method`." (or whatever the
alignment pass left in its place) with:**

~~~markdown
The parameters that *define* the energy model live in the
[`forcefield`](forcefield.md) section; how a job was run lives under
`method`.
~~~

**E2.5 — specification.md § "General organization": replace "A record must
nevertheless contain at least one of `frame`, `system`, `trajectory`, or
`status` besides `meta`." with "… at least one of `frame`, `system`,
`trajectory`, `forcefield`, or `status` besides `meta`.", and replace the
paragraph "Scientific and force-field parameters live under
`system/parameters`. How a job is run lives under `method`." with:**

~~~markdown
Force-field parameters live in the [`forcefield`](forcefield.md) section. How
a job is run lives under `method`.
~~~

**E2.6 — storage.md § "Canonical root": insert `\-- (forcefield)` after
`\-- (trajectory)` in the tree, with the comment `# document attrs + one
block per style`. In § "Section → form map" insert after the `trajectory`
row:**

~~~markdown
| `forcefield` | Force-field document + style tables | Zarr group attributes + one block group per style ([Force field](forcefield.md)) |
~~~

**and in § "Array groups" insert after the first bullet:**

~~~markdown
- `forcefield/` is laid out as a frame-shaped section whose attribute map is
  the force-field document and whose blocks are its style tables
  ([Force field](forcefield.md)).
~~~

**E2.7 — system.md: append (the alignment pass removes
`system/parameters`; this is the pointer that replaces it):**

~~~markdown
Types are linked, not embedded: `atoms.type` and each relation block's
`type` name rows of the record's [`forcefield`](forcefield.md) section (or
its collection's), and a relation block's `style` column picks among styles
of one category. Per-instance parameters (MMFF, UFF) stay columns of the
relation blocks.
~~~

**E2.8 — method.md: replace "System-defining parameter tables live under
`system/parameters`." with "Force-field parameters live in the
[`forcefield`](../spec/forcefield.md) section."**

**E2.9 — collection.md § "Model": insert `\-- (forcefield)  the one force
field every record links into` after `\-- index …` in the tree, and after the
`index` paragraph insert:**

~~~markdown
`forcefield`

Optional. The [force field](forcefield.md#collections) every record's
`atoms.type` and relation `type` columns link into. A record of a collection
carries no `forcefield` of its own.
~~~

**and in § "Conformance" add the bullet "* a collection-wide force field
round-trips;".**

**E2.10 — lmdb.md § "The file", key table: insert after the `index` row:**

~~~markdown
| `ff` | frame bytes | the collection's [force field](forcefield.md): `meta` = the document, `blocks` = the style tables; absent key = none |
~~~

**E2.11 — zensical.toml nav: insert `{ "Force field" = "spec/forcefield.md" },`
after the `System` entry.**

**E2.12 — CLAUDE.md § "Spec hygiene": replace "Parameters under
`system/parameters` or `method`." with "Force-field parameters in the
`forcefield` section (`docs/spec/forcefield.md`); how a job ran in
`method`."**

### F2.4 Model (A)

In `model.py` (after `FrameModel`; `RecordModel` and `CollectionModel`
reference it):

```python
#: Endpoint columns of a style table, in position order.
ENDPOINT_COLUMNS: tuple[str, ...] = ("itom", "jtom", "ktom", "ltom")

#: Arity of each known category (docs/spec/forcefield.md#categories).
CATEGORY_ARITY: dict[str, int] = {
    "atom": 0,
    "bond": 2,
    "angle": 3,
    "dihedral": 4,
    "improper": 4,
    "pair": 2,
    "pair14": 2,
    "constraint": 2,
    "virtual_site": 0,
    "drude": 2,
}

#: Annotation columns: string, nullable.
ANNOTATION_COLUMNS = frozenset({"class", "element", "smarts", "smirks", "overrides", "desc", "doi"})

#: Bytes of a style name kept verbatim in its block name.
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def style_block_name(category: str, style: str) -> str: ...
def parse_style_block_name(name: str) -> tuple[str, str]: ...


Category = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
EndpointKey = Literal["type", "class", "smirks"]
ParamValue = Annotated[float, Field(allow_inf_nan=False)] | str


class ForceFieldUnitsModel(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")
    preset: Literal["real", "metal", "si", "cgs", "electron", "micro", "nano", "lj"] | None = None
    length: str | None = None
    energy: str | None = None
    angle: str | None = None
    charge: str | None = None
    mass: str | None = None
    time: str | None = None
    # validator: preset or at least one quantity; a quantity stated beside a
    # preset equals the preset table's string (UNIT_PRESETS, below) after
    # pint normalization (pint is an optional dep: without it, compare the
    # strings exactly)


UNIT_PRESETS: dict[str, dict[str, str]]  # the table of forcefield.md#the-document


class ForceFieldSourceModel(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")
    format: str
    uri: str | None = None
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None


Weights3 = tuple[
    Annotated[float, Field(allow_inf_nan=False)],
    Annotated[float, Field(allow_inf_nan=False)],
    Annotated[float, Field(allow_inf_nan=False)],
]


class SpecialBondsModel(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    lj: Weights3
    coul: Weights3


class StyleModel(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")
    category: Category
    style: Annotated[str, Field(min_length=1)]
    params: dict[str, ParamValue] = Field(default_factory=dict)
    expression: str | None = None
    endpoint_key: EndpointKey = "type"

    # validator: params["special"], if present, is "lj" or "coul";
    #            params["mixing"], if present, is arithmetic|geometric|sixthpower
    @property
    def block(self) -> str:
        return style_block_name(self.category, self.style)

    @property
    def arity(self) -> int | None:
        return CATEGORY_ARITY.get(self.category)


class ForceFieldModel(BaseModel):
    """The forcefield section: the document (every field but ``tables``) and
    one style table per style, keyed by block name."""

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")
    name: str
    units: ForceFieldUnitsModel
    source: ForceFieldSourceModel | None = None
    special_bonds: SpecialBondsModel | None = None
    styles: list[StyleModel] = Field(default_factory=list)
    tables: dict[str, BlockModel] = Field(default_factory=dict)

    def document(self) -> dict[str, Any]:
        """The group attribute map: model_dump(mode="json", exclude={"tables"},
        exclude_none=True) -- extra keys included."""
```

`ForceFieldModel` validators (each one an id'd reject case):

1. `(category, style)` unique → `reject-ff-duplicate-style`.
2. Every style has `tables[style.block]` → `reject-ff-missing-table`.
3. Per style table: `structural_shape is None`; `name` present, `string`,
   no validity mask, unique values (`reject-ff-null-name`,
   `reject-ff-duplicate-type-name`).
4. Endpoints: for `endpoint_key` `smirks` no endpoint column and a `smirks`
   column without nulls; otherwise exactly `ENDPOINT_COLUMNS[:arity]` present,
   `string`, no nulls; unknown category: the endpoint columns present form a
   prefix (`reject-ff-wrong-arity`).
5. Every other column is `f64` or `string` — or, for a canonical key, its
   `CANONICAL_COLUMNS` dtype (already enforced by `BlockModel`) —
   `precision is None`, trailing shape `()` (`reject-ff-param-dtype`).
6. If any style has `endpoint_key == "class"`, every `atom` table carries
   `class` (`reject-ff-class-key-without-class`).
7. Tables not named by a style are kept (unknown content).

Also:

- `RecordModel.forcefield: ForceFieldModel | None = None`;
  `SUBSTANTIVE_SECTIONS = ("frame", "system", "trajectory", "forcefield",
  "status")`.
- `CollectionModel.forcefield: ForceFieldModel | None = None`;
  `_records_are_collection_records` refuses a record with `forcefield`.
- Linking is **not** validated by the models (forcefield.md rule 5).
- `schema_export.py`: `"core/forcefield": ForceFieldModel` →
  `schema/core/forcefield.schema.json` (StyleModel, units, source,
  special-bonds as `$defs`); regenerate `record.schema.json`.

### F2.5 Codecs (A)

`core/bindings/zarr.py`:

- `FORCEFIELD_GROUP = "forcefield"`. `ZarrForceFieldCodec(Codec)` with
  `write_into(group, model)`: `group.attrs.update(model.document())`, then
  `ZarrFrameCodec._write_block` for every table; `read_from(group)`: the
  attribute map is the document, every child group a table
  (`ZarrFrameCodec._read_block`). Factor `_write_block` / `_read_block` into
  module functions both codecs call (one description of a block).
- `ZarrForceFieldStore` / `ZarrForceFieldBinding` (`module = "forcefield"`,
  `backend = "zarr"`): the section at a store root group `forcefield/`
  beside a stamped `meta/`, the way the trajectory binding lays its section.
- `ZarrRecordCodec.write` / `read`: the `forcefield` group.

`core/bindings/lmdb.py`: key `b"ff"`; `encode_frame(blocks=model.tables,
meta=model.document())` / `decode_frame` → `ForceFieldModel(**meta,
tables=blocks)`; written in the committing transaction before `meta`.

`core/suite.py`: new `ForceFieldSuite` (`module = "forcefield"`,
`model_type = ForceFieldModel`) with the cases of
[forcefield.md § Conformance](../spec/forcefield.md#conformance); in
`RecordSuite`: `record-with-forcefield`, `forcefield-only-record`; in
`CollectionSuite`: `collection-forcefield`. Case contents:

| Case | Model |
|------|-------|
| `ff-minimal` | `name`, `units{preset: real}`, style `atom.full` with rows `CT`, `HC` (`mass`) |
| `ff-round-trip` | `atom.full` (mass, charge, element, class); `bond.harmonic`; `angle.harmonic`; `dihedral.periodic` with `k1,periodicity1,phase1,k2,periodicity2,phase2`; `improper.harmonic`; `pair.lj/cut` (`mixing geometric`, `cutoff 10`) self rows + one cross row; `pair.coul/long/pme` (0 rows, `cutoff`); `special_bonds lj [0,0,0.5] coul [0,0,0.8333]`; `source{format: "openmm-xml", sha256}` |
| `ff-wildcard-endpoints` | `dihedral.periodic` row `("", "CT", "CT", "")` |
| `ff-absent-params` | `dihedral.periodic`, row 0 has 2 terms, row 1 has 1: `k2`/`periodicity2`/`phase2` null in row 1 |
| `ff-string-params` | atom table with `class`, `element`, `smarts`, and `ptype` (non-canonical) |
| `ff-style-name-encoding` | style `pair` / `lj/cut/coul/long` at `pair.lj%2Fcut%2Fcoul%2Flong` |
| `ff-hybrid-styles` | `bond.harmonic` and `bond.morse` both define `CT-HC` (record suite: `bonds.style`) |
| `ff-per-instance-style` | `bond.mmff_bond` with 0 rows (record suite: `bonds` with `kb`, `r0` columns) |
| `ff-unknown-style-with-expression` | `bond.fene` with `expression` and params `K`, `R0`, `epsilon`, `sigma` |
| `ff-unknown-category` | `cmap.charmm`: endpoints `itom`…`ltom` (an unknown category's arity is its endpoint prefix, here 4) plus a `grid` string column |
| `ff-units-preserved` | `units{length: nm, energy: kJ/mol, angle: radian}`; `bond.harmonic` `r0 0.1090`, `k 284512.0` back bit-exact |
| `ff-lj-preset` | `units{preset: lj}` |
| `ff-smirks-keyed` | `bond.harmonic`, `endpoint_key smirks`, rows `b1`, `b2` with `smirks` |
| `ff-without-special-bonds` | no `special_bonds`; reads back absent |
| `reject-ff-no-units` … | each validator above, built with `model_construct()` and laid down by the codec (read direction) |
| `reject-ff-units-conflict` | `preset real` with `energy kJ/mol` |

### F2.6 molrs (B)

**Core (no `ff` dependency):**

- New `molrs/src/core/store/forcefield_section.rs`: `pub struct
  ForceFieldSection { pub document: JsonMap<String, JsonValue>, pub tables:
  IndexMap<String, Block> }`, `pub fn style_block_name(category, style) ->
  String`, `pub fn parse_style_block_name(&str) -> Result<(String, String),
  MolRsError>`, `ForceFieldSection::validate(&self) -> Result<(),
  MolRsError>` (validators 1–6 of F2.4). Re-exported from `store/mod.rs`.
- `molrs/src/core/store/record.rs`: `pub forcefield:
  Option<ForceFieldSection>` on `MolRec`; it counts as a substantive section.
- `molrs/src/io/zarr/frame_io.rs`: factor `write_block_group(store,
  group_path, block)` / `read_block_group(...)` out of `write_frame_group` /
  `read_frame_group` (count, structural_shape, targets (F4), columns,
  precision (F1), `_validity`). Add `write_forcefield_group(store, prefix,
  &ForceFieldSection)` (attributes = document verbatim; one block group per
  table) and `read_forcefield_group`.
- `molrs/src/io/zarr/record_io.rs`: `write_record_store` /
  `read_record_store` handle `"forcefield"`; `section_names*` list it; new
  doors `write_forcefield_file(path, &ForceFieldSection, meta)` and
  `read_forcefield_file(path) -> Result<Option<ForceFieldSection>, _>`.

**ff:** new `molrs/src/ff/forcefield/section.rs`:

```rust
impl ForceField {
    pub fn to_section(&self) -> Result<ForceFieldSection, String>;
    pub fn from_section(section: &ForceFieldSection) -> Result<ForceField, String>;
}
```

Mapping (both directions; `to_section ∘ from_section` is the identity on
every section `to_section` produces, and `from_section ∘ to_section` is the
identity on `ForceField` except that undeclared units become declared):

| molrs | Section |
|-------|---------|
| `ForceField.name` | `document.name` |
| `units()` (declared or the `"real"` default) | `document.units = {preset, length, energy, angle, charge, mass}` from the preset table (molrs presets `real`, `metal`, `lj`; `lj` writes `{preset: "lj"}` only) |
| `declared_special_bonds()` | `document.special_bonds` (absent ⇔ `None`) |
| `styles()` order | `document.styles` order |
| `Style::category()`, `name()` | `category`, `style` |
| `Style::params()` numeric | `params` numbers |
| `Style::params()` strings `expression`, `endpoint_key` | the entry fields of those names |
| other `Style::params()` strings (`mixing`, …) | `params` strings |
| `type_rows()` name | `name` (row order = definition order) |
| endpoints (atom 0, bond 2, angle 3, dihedral/improper 4, pair always 2) | `itom…` |
| row `Params` numeric / string | `f64` / `string` columns; column order: `name`, endpoints, then keys sorted bytewise (`Params` is a `HashMap`, so the order must be fixed) |
| a numeric param whose key is a canonical non-`f64` key (`atomic_number`, `id`, `type_id`, …) | a column of the canonical dtype (`u64`); every value must be a non-negative integer, else `to_section` refuses; `from_section` reads it back as `f64` |
| key absent from a row | null (`_validity`) |

`to_section` refuses (Err naming style and key): a key that is numeric in
one row and string in another; a key in both maps of one `Params`; a param
key equal to `name` or an endpoint column. `from_section` refuses: a category
outside `atom bond angle dihedral improper pair` (the record keeps it; the
`ForceField` cannot hold it); `units` that are not one of molrs's presets
after parsing with `molrs::units` (conversion is an open question, Q2.1);
`endpoint_key` other than `type`, unless every endpoint resolves to an
atom-table name (molrs's own class placeholders do).

**Canonical string-param names inside molrs** (one name per fact; the
section maps nothing): rename `class_` → `class` (OPLS reader, XML writer,
`typifier/opls/typing.rs`), `def_` → `smarts` (same files), and the GROMACS
atomtype string param `bond_type` → `class` (`readers/gromacs.rs`,
`writers/gromacs.rs`). `type_` (the placeholder marker) is untouched and
travels as a non-canonical column. Grep `"class_"`, `"def_"`, `"bond_type"`
under `molrs/src/ff` and `molrs-python/src`.

**Bug to fix while there.** `improper/harmonic` evaluates `k·(χ − χ0)²`
(`potential/improper/harmonic.rs`, `energy += ki * dchi * dchi`), which is
LAMMPS's own form, but the LAMMPS reader stores `k = 2K`
(`readers/lammps.rs`, `coeff_params` arm `("improper", "harmonic")` calls
`lammps_k_to_molrs_half_k`) and the LAMMPS writer emits `K = k/2`
(`writers/lammps.rs`, table row "`improper harmonic` … `K = k/2`"). A LAMMPS
round trip is self-consistent, but every LAMMPS-sourced improper is evaluated
at twice its energy. Fix both to `k = K` and update
`lammps_coeff_params_converts_each_kernel` (expects `k = 20` for `K = 10`;
must expect `10`). The GROMACS path (`k = k_ξ/2`) is already right.

**Python:** `molrs.io.mrec.write(path, frame, system=None, meta=None,
forcefield=None)` and `write_system(path, system, meta=None,
forcefield=None)` take a `molrs.ff.forcefield.ForceField`; new
`molrs.io.mrec.write_forcefield(path, ff, meta=None)` and
`read_forcefield(path) -> ForceField | None`; `section_names` lists
`forcefield`. Stubs in `_lib.pyi`. `tests/molrs_adapter.py` (molrec) gains a
`ForceFieldAdapter` mapping `ForceFieldModel` ↔ the Python `ForceField`
through these doors.

### F2.7 Migration

No store carries `system/parameters` (molrs never wrote it; the alignment
pass removes it). Records without `forcefield` are unchanged. A v1 reader
that predates this section preserves `forcefield/` as an unknown sibling.

---

## F3. Typed frame meta

### F3.1 Rationale

On the trajectory path every per-step value keeps its exact tag
(`meta_dtype`). On the frame path the meta document is the group's attribute
map, and the type is re-inferred from JSON on read: an `i32` comes back
`i64`, an `f64x3` comes back a JSON array, a whole-valued `f64` may come back
an integer, and NaN cannot be stored at all. A sibling attribute that maps
each key to its tag, with values in the typed JSON forms the alignment pass
already defined, makes the frame path exactly as lossless as the trajectory
path at the cost of one small JSON object.

### F3.2 Decisions

- **D3.1** The map is the attribute `_meta_types` of the frame-shaped group:
  `{key: tag}`, tags from the sixteen. One leading underscore, as
  `_validity`: binding-owned, not chemistry, and legal in every store.
- **D3.2** A writer emits an entry for **every** key (no "only when
  inference would differ" rule — one rule, no inference on the write side),
  and omits the attribute when the meta document is empty.
- **D3.3** Values are written in the typed JSON value forms
  ([conventions](../spec/conventions.md), `molrec.jsonvalue`): NaN/±∞ as
  `"NaN"`/`"Infinity"`/`"-Infinity"`, integers beyond ±2⁵³ as decimal
  strings, vectors as arrays of element forms, `json` verbatim (finite).
  Complex is not a meta tag.
- **D3.4** Reader: tagged key → decode under its tag, refuse any other form;
  untagged key → infer (today's behaviour, the back-compat path); a tag for a
  key the document lacks → ignored (a stale entry left by an unaware tool is
  harmless).
- **D3.5** `_meta_types` is reserved: a writer refuses a meta key of that
  name; a reader never surfaces it as meta.
- **D3.6** Applies to `frame`, `system` and frame-shaped observable data.
  Not to `forcefield` (plain JSON document) and not to `meta` / `status` /
  `method` documents.

Inference (untagged keys): JSON `true`/`false` → `bool`; an integer literal in
`[−2⁶³, 2⁶³)` → `i64`; in `[2⁶³, 2⁶⁴)` → `u64`; any other number → `f64`; a
string → `string`; an array, object or `null` → `json`. (A string `"NaN"` is
a `string` unless tagged `f64`.)

### F3.3 Chapter edits

**E3.1 — frame.md § "Column, block and frame": replace "A *frame* is a
snapshot: a set of named blocks, a free-form `meta` mapping, and an optional
box." with:**

~~~markdown
A *frame* is a snapshot: a set of named blocks, a `meta` document, and an
optional box. Each `meta` value is typed by one of the per-step
[tags](ragged.md#per-step-metadata) — a scalar of a column dtype, a fixed
vector (`f64x3`, `i32x3`, `bool3`, …), or `json` for a nested document — and
a frame read back carries every value at its tag.
~~~

**E3.2 — storage.md § "Array groups": insert after the first bullet:**

~~~markdown
- A frame-shaped section's `meta` document is its group's attribute map.
  The attribute `_meta_types` maps every key of the document to its tag, and
  each value is in the [typed JSON form](conventions.md#typed-json-values) of
  that tag (so an `f64` NaN is `"NaN"` and a `u64` beyond 2⁵³ a decimal
  string). A writer emits an entry for every key and omits the attribute
  for an empty document; `_meta_types` is not a meta key, and a writer
  refuses a document that has one. A reader decodes a tagged key under its
  tag and refuses any other form; it infers the tag of an untagged key —
  `bool`; an integer in `[−2⁶³, 2⁶³)` as `i64`, in `[2⁶³, 2⁶⁴)` as `u64`;
  any other number `f64`; a string `string`; anything else `json` — and
  ignores a tag whose key is absent. The `forcefield` document is plain JSON
  and carries no `_meta_types`.
~~~

**E3.3 — lmdb.md § "Frame bytes": replace the bullet "* `meta` is the frame's
meta document as JSON. A per-step key's exact type is the tag the
`sequence_schema` declares for it." with:**

~~~markdown
* `meta` is the frame's meta document, each value in its typed JSON form. A
  trajectory update's keys are typed by the `sequence_schema`; a `system`
  frame carries `"meta_types": {key: tag}` beside `meta` with the rules of
  the [Zarr frame group](storage.md#array-groups). The `ff` frame's `meta` is
  the force-field document and carries no `meta_types`.
~~~

**E3.4 — conventions.md § "Typed JSON values": in the first paragraph,
extend the list "a per-step `fill` in `sequence_schema`, a per-step value in
an LMDB frame header, a value in a live observables WAL row" with ", a
value of a frame's or system's `meta` (typed by `_meta_types`,
[Root layout](../spec/storage.md#frame-shaped-group))"; and replace the closing paragraph
"An untyped document — `meta`, `status`, `method`, a frame's `meta` — …"
with:**

~~~markdown
An untyped document — the record's `meta`, `status`, `method`, the
`forcefield` document — has no declared dtype; its numbers are plain JSON,
and a producer that needs NaN in one stores it as data, not as a document
key. A frame's `meta` is typed: every key has a tag.
~~~

### F3.4 Model (A)

```python
#: Attribute keys a frame-shaped group reserves beside its meta document.
META_TYPES_ATTR = "_meta_types"

def infer_meta_tag(value: Any) -> MetaTag:
    """The tag an untagged value reads back as (E3.2 inference)."""

class FrameModel(BaseModel):
    ...
    meta: dict[str, Any] = Field(default_factory=dict)
    meta_types: dict[str, MetaTag] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _meta_is_typed(self) -> FrameModel:
        # 1. META_TYPES_ATTR in meta -> ValueError (reserved)
        # 2. a tag for a key not in meta -> ValueError (the model is strict;
        #    the codec drops stale tags before building the model)
        # 3. every untagged key gets infer_meta_tag(value)
        # 4. meta[key] = coerce_meta_value(tag, value) for every key
        #    (refuses a value that is not its tag's)
        # object.__setattr__ both dicts, like BoxModel's defaults

    def __eq__(self, other): # blocks, box, meta_types, and meta compared in
        # encode_meta_value(tag, v) form, so NaN == NaN
```

`TrajectoryModel` frames: per-step meta stays governed by `meta` (the
series declarations); a frame inside a trajectory has `meta_types` filled
from the declaration by `_every_declared_meta_key_reaches_every_frame` (set
`meta_types = {k: series.dtype}`), so frame equality works the same in both
places.

### F3.5 Codecs (A)

- `ZarrFrameCodec.write_into`: `attrs = {k: encode_meta_value(t, v)}` plus
  `attrs[META_TYPES_ATTR] = meta_types` when non-empty; refuse a meta key
  named `_meta_types`.
- `ZarrFrameCodec.read_from`: pop `_meta_types`; decode tagged keys with
  `decode_meta_value`; infer the rest; drop stale tags; build the model.
- `lmdb.py` `encode_frame` / `decode_frame`: `meta_types` header key for
  non-trajectory frames.

### F3.6 molrs (B)

- `molrs/src/core/store/meta.rs`:
  - `pub const META_TYPES_ATTR: &str = "_meta_types";`
  - `MetaValue::to_typed_json(&self) -> serde_json::Value` — the typed JSON
    form (today's `to_attr_value` writes `json!(f64::NAN)`, which serde
    turns into `null`: a silent loss). `to_attr_value` becomes this.
  - `MetaValue::from_typed_json(tag: &str, value: &Value) -> Result<MetaValue,
    String>` — exact decode, refuses other forms, range-checks `i32`/`u32`,
    accepts a decimal string for 64-bit integers and the three non-finite
    strings for `f64` (scalar and vector elements).
  - `MetaValue::from_attr_value` stays as the inference path (its rules are
    E3.2's).
  - If the alignment pass already implemented the typed forms for
    `sequence_schema` fills in molrs, reuse that code; there is one encoder.
- `molrs/src/io/zarr/frame_io.rs`: `write_frame_group` writes
  `to_typed_json` values plus `_meta_types` (refuses a meta key named
  `_meta_types`); `read_frame_group` pops `_meta_types`, decodes tagged keys
  with `from_typed_json`, infers the rest, ignores stale tags.
- `molrs/src/io/zarr/sequence.rs`: `MetaSchema.fill` encode/decode through
  the same two functions (a NaN fill is now storable).
- Python: no API change — `frame.meta` already hands out typed `MetaValue`
  objects for tags a plain Python value cannot hold; the change is that they
  now survive the disk.
- Tests: every tag round-trips through `write_frame_group`/`read_frame_group`;
  NaN, ±∞, `u64::MAX`, `i64::MIN`; a store without `_meta_types` reads as
  today.

### F3.7 Conformance (A)

| Suite | Case | Asserts |
|-------|------|---------|
| frame | `typed-meta-every-tag` | one key per tag (16) round-trips with its tag and value |
| frame | `typed-meta-non-finite` | `f64` NaN, +∞, −∞ and an `f64x3` holding NaN |
| frame | `typed-meta-wide-integers` | `u64` 2⁶⁴−1, `i64` −2⁶³, `u64` 2⁵³+1 |
| frame | `typed-meta-integral-float` | `f64` `1.0` stays `f64` |
| frame | `untyped-meta-infers` | a store without `_meta_types` (tamper removes it) reads with E3.2's inferred tags |
| frame | `stale-meta-tag-ignored` | a tag for an absent key (tamper adds it) is ignored |
| frame | `reject-meta-tag-mismatch` | tamper sets `_meta_types[k] = "i32"` on value `1.5`; the reader refuses |
| frame | `reject-meta-out-of-range` | tamper sets `"i32"` on `2**40` |
| frame | `reject-meta-reserved-key` (write) | a meta key `_meta_types` is refused |
| frame | `reject-json-meta-non-finite` (write) | a `json` value containing NaN is refused |
| record | `system-typed-meta` | `system` meta with `i32`, `f64x3`, NaN round-trips |
| collection | `system-typed-meta-lmdb` | the same through frame bytes |

### F3.8 Migration

Absent `_meta_types` = inference = exactly what readers do today, so every
existing store reads unchanged. A reader that predates F3 surfaces
`_meta_types` as an ordinary (`json`) meta key and carries it through; if it
then edits a value under a stale tag, a new reader refuses that key's
payload. That is the only failure mode and it requires a tool that edits meta
without understanding it.

---

## F4. Topology conventions, synced with molrs

### F4.1 Rationale

molrs's committed vocabulary (`store/schema/mod.rs`) and molrec's
`conventions.md` have drifted in both directions, and both lack the
identifiers that every biomolecular, polarizable and coarse-grained format
needs. One table — the molrs schema, extended — is the source of truth for
both. Relation columns that index a block other than `atoms` need a general,
declared rule instead of a growing list of special cases.

### F4.2 Inventory and resolution

| Key / block | molrs | molrec | Resolution |
|-------------|-------|--------|------------|
| `fx fy fz` (atoms, f64) | — | yes | **adopt in molrs** (`Float`, `Of(Force)`) |
| `formal_charge` (atoms) | — | `i64` (pinned by the alignment pass) | **adopt in molrs as `i64`** (`Int64`, `NotAQuantity`); molrec unchanged |
| `atom_map` (atoms, u64) | — | yes | **adopt in molrs** (`UInt`) |
| `ix iy iz` (atoms) | `Int` = `i32` | — | **adopt in molrec**, `i32` |
| `quatw quati quatj quatk` (atoms, f64) | yes | — | **adopt in molrec** |
| `mux muy muz` (atoms, f64) | yes | — | **adopt in molrec** |
| `axis_x axis_y axis_z` (atoms, f64) | yes | — | **adopt in molrec** |
| `free` (atoms, bool) | yes | — | **adopt in molrec** |
| `type_id` on relations (u64) | yes | atoms only | **adopt in molrec** on every relation block |
| `is_14` (pairs, bool) | yes | — | **adopt in molrec** |
| `exclude_14` (dihedrals, impropers, bool) | yes | — | **adopt in molrec** |
| `exclusions` block | yes | — | **adopt in molrec** |
| `pairs` block | yes | — | **adopt in molrec** |
| `chain_id` (atoms, **string**, PDB/CIF readers) | non-canonical | — | **rename to `chain`** (string): every `*_id` key is a `u64` identifier (molrs's own vocabulary test), and a chain letter is a label |
| `res_seq` (atoms, `i32`, CIF reader) | non-canonical | — | **rename to `res_id`** (`u64`); a negative number is refused/renumbered at the reader, as PDB already does |
| `b_iso` (atoms, f64, CIF reader) | non-canonical | — | **rename to `b_factor`** |
| `occupancy` (atoms, f64, CIF reader) | non-canonical | — | **adopt in both** |
| `icode`, `altloc` (atoms, string) | parsed by PDB, dropped | — | **adopt in both**; the PDB reader stores them |
| `style` on relations (string) | — | — | **new in both** (hybrid styles, F2) |
| `constraints`, `virtual_sites`, `drudes` blocks | — | — | **new in both** |
| `members` block (`ibead`, `atom`) | written by `CoarseGrain`, unspecified | — | **adopt in both**, with `targets` |
| `residues`, `chains`, `molecules` blocks | — | — | **reject**: per-atom `res_id`/`res_name`/`chain`/`icode` and `mol_id` are what every format carries; a block would be a second carrier of one fact. Residue-level data a producer needs goes in its own block with `targets` |
| fractional coordinates | — | — | **out of scope**: positions are Cartesian; a reader converts at its boundary. `fx fy fz` are forces, never fractional |
| `bead` atom key, `beads` block | removed in molrs vocab 2 | — | stay removed: beads are `atoms` rows |
| `*_type_labels` frame-meta keys | molrs `META_KEYS` | — | **not standardized**: a LAMMPS-local inventory; with a `forcefield` section the atom table is the inventory. Preserved like any meta |
| `units` frame-meta key | molrs: a preset string | collection: a quantity map | **standardize one shape**: the [force-field `units` object](../spec/forcefield.md#the-document). A string value reads as `{"preset": value}`; molrs's LAMMPS-molecule reader/writer move to the object |
| `segment`, `ptype` etc. | — | — | not standardized; preserved |
| `targets` (block attribute) | `EndpointSpec.target` per block | — | **new general rule** (E4.3) |

### F4.3 Chapter edits

**E4.1 — conventions.md § "`atoms`": replace the tree with:**

~~~markdown
```text
atoms
 \-- (x, y, z: f64[N])
 \-- (vx, vy, vz: f64[N])
 \-- (fx, fy, fz: f64[N])
 \-- (ix, iy, iz: i32[N])
 \-- (id: u64[N])
 \-- (atomic_number: u64[N])
 \-- (element: string[N])
 \-- (type: string[N])
 \-- (type_id: u64[N])
 \-- (name: string[N])
 \-- (charge: f64[N])
 \-- (formal_charge: i64[N])
 \-- (atom_map: u64[N])
 \-- (mass: f64[N])
 \-- (mol_id: u64[N])
 \-- (res_id: u64[N])
 \-- (res_name: string[N])
 \-- (chain: string[N])
 \-- (icode: string[N])
 \-- (altloc: string[N])
 \-- (occupancy: f64[N])
 \-- (b_factor: f64[N])
 \-- (bead_type: string[N])
 \-- (free: bool[N])
 \-- (quatw, quati, quatj, quatk: f64[N])
 \-- (mux, muy, muz: f64[N])
 \-- (axis_x, axis_y, axis_z: f64[N])
```
~~~

**E4.0 — conventions.md § "Canonical dtypes": replace the table with:**

~~~markdown
| Keys | dtype |
|------|-------|
| `x` `y` `z` `vx` `vy` `vz` `fx` `fy` `fz` `charge` `mass` | `f64` |
| `quatw` `quati` `quatj` `quatk` `mux` `muy` `muz` `axis_x` `axis_y` `axis_z` `occupancy` `b_factor` | `f64` |
| `id` `atomic_number` `type_id` `mol_id` `res_id` `atom_map` | `u64` |
| `atomi` `atomj` `atomk` `atoml` `ibead` `bond_type` `bond_number` | `u64` |
| `formal_charge` | `i64` |
| `ix` `iy` `iz` | `i32` |
| `free` `is_14` `exclude_14` | `bool` |
| `element` `type` `name` `res_name` `bead_type` `chain` `icode` `altloc` `style` | `string` |
~~~

**and add `ibead` to the list of exactly-`u64` keys in the bullet "The
unsigned identifiers and relation endpoints — …".**

**E4.2 — conventions.md § "`atoms`": insert after the `atom_map` paragraph:**

~~~markdown
`ix`, `iy`, `iz`

Periodic image flags along the first, second and third lattice vector: how
many cells the atom has crossed. The continuous position is
`(x, y, z) + H · (ix, iy, iz)` with `H` the box `vectors`; the stored
coordinate stays wrapped. Signed. They travel with the coordinates: a writer
that drops one drops all three.

`res_id`, `res_name`, `chain`, `icode`, `altloc`

The residue an atom belongs to and where it came from. `res_id` is the source
file's residue number (never a row index; unsigned — a reader renumbers a
negative one at its boundary), `res_name` its name, `chain` the chain label
(PDB chain identifier, mmCIF `label_asym_id`), `icode` the insertion code and
`altloc` the alternate-location indicator, `""` for none. A residue is
identified by `(chain, res_id, icode)`. There is no `residues` or `chains`
block: the per-atom columns are the one carrier.

`occupancy`, `b_factor`

Crystallographic occupancy (a fraction) and isotropic displacement parameter
`B` (length²).

`free`

Whether an atom may move when coordinates are optimized. `false` pins it. A
block without the column has every atom free.

`quatw`, `quati`, `quatj`, `quatk`

A per-particle orientation quaternion `(w, i, j, k)`.

`mux`, `muy`, `muz`

A per-particle electric dipole moment (charge × length).

`axis_x`, `axis_y`, `axis_z`

A coarse-grained site's axis: from the first member of its group to the site
(length).

Positions are Cartesian. Fractional coordinates are not a convention: a
reader of a fractional format converts at its boundary.
~~~

**E4.3 — frame.md: insert a new section after § "Declared precision"
(E1.1):**

~~~markdown
## Row references

A column whose values are 0-based row indices into another block is a **row
reference**. By convention the relation endpoint columns `atomi`, `atomj`,
`atomk`, `atoml` reference the rows of the `atoms` block of the same
container. Every other reference — and any endpoint that references something
else — is declared by the block's attribute `targets`, a map from column name
to target:

| Target | Rows it indexes |
|--------|-----------------|
| `<block>` | that block of the same frame (on a trajectory: of the same resolved frame) |
| `/<section>/<block>` | that block of a frame-shaped section of the same record (`/frame/atoms`, `/system/atoms`) |

- A referencing column is `u64`; a null row (validity) references nothing.
- A same-container target **MUST** exist wherever the referencing block has
  rows, and every non-null value **MUST** be below its row count; a reader
  refuses a store that breaks either. An absolute target is checked the same
  way when that section is present; a trajectory block is never a target
  (its row count is not fixed).
- A `u64` column that is neither an endpoint nor declared is a plain number
  (an opaque handle, an identifier), never a reference.
- Tools that renumber rows (subset, replicate) renumber every same-container
  reference and leave absolute ones unchanged.
- On a trajectory, `targets` is part of the block's entry in
  `sequence_schema`; on a frame it is the block group's attribute.
~~~

**E4.4 — conventions.md § "Relations": replace the paragraph "Tuple blocks
reference atoms …", the `bonds` tree, and the block table with:**

~~~markdown
Relation blocks reference atoms by 0-based `u64` row indices into the
`atoms` block (`atomi` … `atoml`); a relation that references another block
says so with [`targets`](frame.md#row-references).

```text
bonds
 \-- atomi: u64[E]
 \-- atomj: u64[E]
 \-- (type: string[E])
 \-- (type_id: u64[E])
 \-- (style: string[E])
 \-- (bond_type: u64[E])
 \-- (bond_number: u64[E])
```

| Block | Endpoints | Optional |
|-------|-----------|----------|
| `bonds` | `atomi`, `atomj` | `type`, `type_id`, `style`, `bond_type`, `bond_number` |
| `angles` | `atomi`, `atomj` (vertex), `atomk` | `type`, `type_id`, `style` |
| `dihedrals` | `atomi` … `atoml` | `type`, `type_id`, `style`, `exclude_14` |
| `impropers` | `atomi` … `atoml` | `type`, `type_id`, `style`, `exclude_14` |
| `pairs` | `atomi`, `atomj` | `type`, `type_id`, `style`, `is_14` |
| `exclusions` | `atomi`, `atomj` | — |
| `constraints` | `atomi`, `atomj` | `type`, `type_id`, `style` |
| `virtual_sites` | `atomi` (the site), `atomj`, `atomk`, `atoml` (constructing atoms) | `type`, `type_id`, `style` |
| `drudes` | `atomi` (core), `atomj` (Drude particle) | `type`, `type_id`, `style` |
| `members` | `ibead` → `atoms`, `atom` (declared) | — |

`type` names a row of the record's [force field](forcefield.md#linking-a-system)
and `style` picks the style when several hold that name. `type_id` is a
format-local ordinal (LAMMPS) and plays no part in linking. A relation may
carry per-instance parameters as further columns named as its style names
them (`r0` on `constraints`, `kb` on an MMFF `bonds`).

`is_14` marks a `pairs` row as a 1-4 pair; `exclude_14` marks a torsion whose
1-4 non-bonded term is suppressed (AMBER's negative third index).
`exclusions` lists pairs excluded from non-bonded interaction.

A `virtual_sites` row constructs the particle `atomi` (an `atoms` row,
usually massless) from up to three others; a site built from fewer leaves
the trailing endpoints null. A `drudes` row pairs a core atom with its Drude
particle; both are `atoms` rows.

A coarse-grained frame stores its beads as `atoms` rows (with `bead_type`)
and its bonds in `bonds`. `members` maps beads to the atoms they group, one
row per (bead, atom): `ibead` references `atoms` of the same frame; `atom`
references the all-atom block named by `targets` (`/frame/atoms`, …), and
without a declared target it is an opaque handle.
~~~

**E4.5 — conventions.md: insert a section before § "Composition and identity
keys":**

~~~markdown
## Units on a frame

The meta key `units` (`json`) on a `frame` or `system` says what unit system
the frame's numbers are in. Its value has the shape of the
[force-field `units`](forcefield.md#the-document) object
(`{"preset": "real"}`, `{"length": "nm", "energy": "kJ/mol"}`). A string
value is read as `{"preset": <string>}`. Absent means the frame states none
(a collection states them once, in its `meta.units`).
~~~

**E4.6 — storage.md § "Array groups": in the bullet "A frame-shaped section
… is a group of named blocks; each block is a group of named columns", append
"A block group carries the attributes `count`, `structural_shape` (when set)
and `targets` (when set, [Row references](../spec/frame.md#row-references))."**

**E4.7 — lmdb.md § "Frame bytes", header example and rules: a block entry
may carry `"targets": {column: target}` beside `count` and
`structural_shape`; insert the sentence "* A block's `targets`, when set, is
its header entry's `targets`." after the `string` bullet.**

### F4.4 Model (A)

```python
#: The relation endpoint columns and their conventional target.
ENDPOINTS: tuple[str, ...] = ("atomi", "atomj", "atomk", "atoml")
DEFAULT_TARGET = "atoms"
Target = Annotated[str, Field(pattern=r"^(/[^/]+/[^/]+|[^/]+)$")]


class BlockModel(BaseModel):
    ...
    targets: dict[str, Target] | None = None
    # validator: every key names a column of the block; that column is u64


class SequenceBlockModel(BaseModel):
    ...
    targets: dict[str, Target] | None = None  # omit when None
    aligned_with: str | None = None  # F5; omit when None
```

- `FrameModel._references_resolve` (after): for each block with rows, for
  each declared same-container target (and, for `atomi…atoml` without a
  declaration, nothing — the default rule stays SHOULD): the target block is
  in the frame and every non-null value `< target.count`.
- `TrajectoryModel`: the same check per resolved frame (after carry-forward);
  a declared target that names a trajectory block is legal only as a
  same-container target (same resolved frame); an absolute target naming
  `/trajectory/...` is refused at declaration.
- `RecordModel._absolute_references_resolve`: absolute targets into a present
  frame-shaped section (`frame`, `system`) are range-checked;
  `/trajectory/<block>` is refused.
- `declare_block` copies `targets`.
- `CANONICAL_COLUMNS` gains every key of E4.0 it lacks (`quat*`, `mu*`,
  `axis_*`, `occupancy`, `b_factor` → `f64`; `ibead` → `u64`, also in
  `CANONICAL_U64`; `ix iy iz` → `i32`; `free is_14 exclude_14` → `bool`;
  `chain icode altloc style` → `string`). `check_canonical` then enforces
  them in every block of every section — force-field tables included, which
  is why a force-field `atomic_number` column is `u64` (forcefield.md).
- Which block a canonical key belongs in stays a recommendation; the models
  check dtypes, not placement.

`schema_export.py`: export `CANONICAL_COLUMNS` as
`schema/core/vocabulary.json` (`{key: dtype}`), the file molrs's vocabulary
gate (F4.6) compares against.

### F4.5 Codecs (A)

`zarr.py`: block group attribute `targets` written/read on the frame path;
on the trajectory path it lives in the pinned `sequence_schema` only.
`lmdb.py`: block header `targets`.

### F4.6 molrs (B)

`molrs/src/core/store/schema/mod.rs` (`columns!` stays sorted):

| Key | DType | Shape | Dimension | Doc (abridged) |
|-----|-------|-------|-----------|----------------|
| `altloc` | `String` | Scalar | NotAQuantity | alternate-location indicator, `""` none |
| `atom_map` | `UInt` | Scalar | NotAQuantity | atom-map number in `mapped_smiles`, 0 unmapped |
| `b_factor` | `Float` | Scalar | `Product(Length, Length)` | isotropic B |
| `chain` | `String` | Scalar | NotAQuantity | chain label |
| `formal_charge` | `Int64` | Scalar | NotAQuantity | integer formal charge, e |
| `fx`, `fy`, `fz` | `Float` | Scalar | `Of(Force)` | force components |
| `icode` | `String` | Scalar | NotAQuantity | insertion code, `""` none |
| `occupancy` | `Float` | Scalar | Dimensionless | crystallographic occupancy |
| `ibead` | `UInt` | Scalar | NotAQuantity | `members`: the bead's `atoms` row |
| `style` | `String` | Scalar | NotAQuantity | force-field style of a relation row |

`KEY_GROUPS` gains `FORCES = [FX, FY, FZ]`. `ATOMS.optional` gains every
atom key of E4.1 it lacks (`ix iy iz quat* mu* axis_* fx fy fz chain icode
altloc occupancy b_factor formal_charge atom_map`). Every relation spec's
optional list gains `style` (and `type_id` where missing).

Blocks (`blocks!`, sorted): `constraints` (Relation 2), `drudes` (Relation
2), `members` (Relation 2, see targets below), `virtual_sites` (Relation 4;
`atomk`, `atoml` nullable).

**Targets.** Replace `EndpointSpec { target, columns }` by
`EndpointSpec { columns: &'static [(&'static str, Target)] }` with
`pub enum Target { Block(&'static str), Declared }` — `members` is
`[("ibead", Block(ATOMS)), ("atom", Declared)]`, every other relation
`(atomX, Block(ATOMS))`. `Block` gains `targets: IndexMap<String, String>`
(`Block::set_target`, `Block::targets`), persisted by `frame_io` as the
block group attribute and by `SequenceSchema` (`BlockSchema.targets`,
`declare_target(block, column, target)`). `relation_endpoints` returns
per-column targets, honouring a block's declared `targets` over the default.
`Validator` range-checks same-container targets and skips null endpoints.
`Frame::subset` / `Frame::replicate` renumber same-container references and
drop the `members` refusal (lines ~529 and ~664 of `store/frame.rs`): with
`ibead` declared, `members` renumbers like any relation; `atom` (absolute or
undeclared) is left as is. `CoarseGrain::to_frame` writes `targets {"ibead":
"atoms"}`.

**Readers/writers.** `io/data/pdb.rs`: `chain_id` → `chain` (reader line
~426, writer ~689); store `altloc`, `icode`, `occupancy`, `b_factor` (parsed
today, dropped) and write them back. `io/data/cif.rs`: `chain_id` → `chain`,
`res_seq` (`i32`) → `res_id` (`u64`, refusing a negative number as PDB does),
`b_iso` → `b_factor`. `io/data/lammps_molecule.rs` and `store/keys.rs`
(`UNITS` doc): the `units` meta value becomes the object
`MetaValue::Json({"preset": …})`; a string is still accepted on read.
`io/data/xyz.rs` (`res_id`, `resname`): leave the extxyz names at the I/O
boundary, canonicalizing `resname` → `res_name` on read.

**Vocabulary gate.** `molrs/tests/vocabulary_matches_molrec.rs` (or the
existing gate script): compare `SCHEMA_COLUMNS` with molrec's exported
vocabulary — every key in both, same dtype. Not a build dependency: it reads
a checked-in copy of `vocabulary.json`.

`FRAME_VOCAB_VERSION` stays 2: keys are added; the renamed keys were never in
the table.

### F4.7 Conformance (A)

| Suite | Case | Asserts |
|-------|------|---------|
| frame | `canonical-topology` | every E4.1 atom column and every E4.4 block at its canonical dtype round-trips, including a `virtual_sites` row with null `atoml` |
| frame | `targets-declared` | `members` with `targets {"ibead": "atoms"}` round-trips the attribute |
| frame | `reject-target-out-of-range` | `members.ibead = 5` with 3 atoms; reader refuses |
| frame | `reject-target-missing-block` | `targets {"site": "sites"}`, no `sites` block |
| frame | `reject-target-not-u64` | a declared `i64` column |
| record | `targets-absolute` | `system/members.atom` → `/frame/atoms`, in range |
| record | `reject-target-into-trajectory` (write) | `targets {"atom": "/trajectory/atoms"}` |
| trajectory | `targets-pinned` | a block's `targets` is part of the pinned declaration and holds per resolved frame |

### F4.8 Migration

All additions are optional columns and blocks. molrs output changes key
names for PDB/CIF `chain_id`, CIF `res_seq`/`b_iso`; readers of molrs
records that looked for `chain_id` must look for `chain` (no store in the
wild carries a canonical `chain_id`). molrs's string `units` meta keeps
reading. The new canonical dtypes make a store that used one of the new key
names at another dtype (`ix` as `i64`) unreadable as canonical; no molrs or
molrec writer ever produced one.

---

## F5. Aligned trajectory blocks

### F5.1 Rationale

Some per-atom state changes rarely while coordinates change every frame:
atom types under proton hopping, species under grand-canonical insertion,
charge states under constant-pH. Putting `type` in `trajectory/atoms`
rewrites strings every frame; putting it in its own block makes it sparse,
but nothing then says its rows *are* the atoms' rows. `aligned_with` says
it, and lets writers and readers hold the two to one row count.

### F5.2 Decisions

- **D5.1** Declared only (never derived): `aligned_with: "<block>"` on the
  block's `sequence_schema` entry.
- **D5.2** The target is a declared trajectory block other than itself, and
  is not itself aligned (no chains). The aligned block declares no
  `structural_shape`. The two blocks' column names are disjoint.
- **D5.3** The rule is on **resolved** frames (after carry-forward): at
  every ordinal where the aligned block is present or empty, the target is
  present or empty with the same row count. Hence a frame whose target
  update changes the row count **must** restate the aligned block; one
  whose count is unchanged may let it carry forward. Row identity under an
  unchanged count is the producer's responsibility (a producer that reorders
  or swaps rows restates the aligned block); if both blocks carry `id`, the
  values are equal row for row.
- **D5.4** The aligned block may be absent while the target is present; the
  target may not be absent while the aligned block is present.
- **D5.5** Writers refuse a violating frame at append; readers refuse a
  store that violates the rule.
- **D5.6** Presentation: two blocks. A reader **MAY** offer the union view
  (columns are disjoint, so it is well defined); none is required.
- **D5.7** With `system`: an aligned block **MUST NOT** share a name with a
  `system` block. Its target may (then the target's count is the system's,
  and so is the aligned block's).
- **D5.8** In a collection the rule holds per record on that record's
  resolved frames (carry-forward never crosses a record). A record whose
  first frame presents the target and not the aligned block is valid (D5.4).

### F5.3 Chapter edits

(The `sequence_schema` bullet is E1.2.)

**E5.1 — ragged.md: insert a new section after § "System and trajectory side
by side":**

~~~markdown
## Aligned blocks

A block may declare `aligned_with: "<target>"` in its `sequence_schema`
entry. Its rows are then the target's rows, one for one, at every frame:
a sparse companion of a block that changes more often — atom types beside
coordinates under proton hopping, species under grand-canonical insertion.

- The target is a declared block of the same trajectory, not the aligned
  block itself, and not itself aligned. The aligned block declares no
  `structural_shape`, and no column name appears in both.
- At every frame ordinal where the aligned block is present or empty, the
  target is present or empty **with the same row count**, both resolved by
  [carry-forward](#the-three-states-of-a-block). A frame whose target
  update changes the row count therefore restates the aligned block; a frame
  that keeps the count may let it carry forward.
- The aligned block may be absent while its target is present, never the
  reverse.
- Rows correspond by position. A producer that reorders or replaces rows
  without changing their count restates the aligned block. When both blocks
  carry `id`, the values are equal row for row.
- A writer refuses a frame that breaks the rule; a reader refuses a store
  that does.
- A reader hands back two blocks. It **MAY** also offer them joined; the
  column sets are disjoint, so the join is the union of columns.
- An aligned block never shares a name with a `system` block. Its target
  may: the target's row count is then the `system` block's, and so is the
  aligned block's.
~~~

**E5.2 — trajectory.md § "Blocks over time": append:**

~~~markdown
A block may be declared [aligned](ragged.md#aligned-blocks) with another:
its rows are the other block's rows, so it can change rarely beside a block
that changes every frame, and it is restated whenever the other's row count
changes.
~~~

**E5.3 — collection.md § "Conformance": add the bullets "* an aligned block
that carries forward while its target moves, and one restated on growth;"
and "* refusal of an aligned block whose row count differs from its
target's;".**

**E5.4 — lmdb.md § "Frames", first bullet: append "An
[aligned](../spec/ragged.md#aligned-blocks) block is held to its target's row count
at every resolved ordinal of the record."**

### F5.4 Model (A)

`SequenceBlockModel.aligned_with: str | None = None` (serializer omits
`None`; shown in F4.4). In `TrajectoryModel`:

- `_blocks_keep_one_declaration`: after `declared` is final, for each block
  with `aligned_with`: the target is declared, `!= name`, has no
  `aligned_with`; the block has no `structural_shape`; `set(columns) &
  set(target.columns) == ∅`. A frame that presents blocks while `blocks` is
  unstated cannot declare alignment (D5.1) — nothing to check.
- New `_aligned_blocks_track_their_target` (after
  `_omission_carries_forward`): for each ordinal and aligned block `a` with
  target `t`: if `a` in `frame.blocks` then `t` in `frame.blocks` and
  `frame.blocks[a].count == frame.blocks[t].count`.
- `RecordModel` (new validator) and `CollectionModel._system_and_trajectory_align`:
  an aligned trajectory block's name is not a `system` block name.

### F5.5 Codecs (A)

Nothing changes in the layout: `aligned_with` rides in `sequence_schema`.
`ZarrTrajectoryCodec.read_from` / `LmdbCollectionCodec.read` build the
model, whose validator enforces the rule (that is the reader refusal). The
write side already refuses through the model.

### F5.6 molrs (B)

- `molrs/src/io/zarr/sequence.rs`: `BlockSchema.aligned_with:
  Option<String>` (`serde(default, skip_serializing_if = "Option::is_none")`);
  `SequenceSchema::declare_aligned(block, target) -> Result<&mut Self,
  MolRsError>` checking D5.2 (also re-checked when columns are declared
  later: a column added to either block that collides is refused).
- `FrameSequenceWriter::append`: after resolving the presented frame against
  the carried state, refuse (`MolRsError::Zarr`, naming both blocks, the
  ordinal and both counts) when D5.3/D5.4 fail.
- `FrameSequence::open`: validate every aligned pair once from the indexes:
  for each update ordinal of either block, the resolved counts agree (both
  `BlockIndex` searches are `O(log n)`; regular blocks answer in `O(1)`).
- `molrs-python/src/io/mrec.rs`: `SequenceSchema.declare_aligned(block,
  target)`; `_lib.pyi`.
- System/trajectory: the record writer (`write_record_store`,
  `FrameSequenceWriter` with a system) refuses an aligned block named like a
  system block.

### F5.7 Conformance (A)

| Suite | Case | Asserts |
|-------|------|---------|
| trajectory | `aligned-carries-forward` | `atoms` (3 rows, x every frame) and `atom_types` (aligned, updated at 0 and 3 only) read back with `atom_types` resolved at every frame |
| trajectory | `aligned-restated-on-growth` | `atoms` grows 3 → 4 at ordinal 2, `atom_types` restated there with 4 rows |
| trajectory | `aligned-absent-then-present` | `atom_types` first appears at ordinal 1 |
| trajectory | `aligned-empty-target` | `atoms` empties at ordinal 2, `atom_types` restated empty |
| trajectory | `reject-aligned-not-restated` (write) | `atoms` grows at ordinal 2 and `atom_types` is omitted |
| trajectory | `reject-aligned-count-mismatch` (read) | the codec lays down a consistent store; tamper rewrites `atom_types/offset` so ordinal 1 holds 2 rows |
| trajectory | `reject-aligned-target-undeclared` (write) | `aligned_with: "nope"` |
| trajectory | `reject-aligned-chain` (write) | `a` aligned with `b`, `b` aligned with `atoms` |
| trajectory | `reject-aligned-shared-column` (write) | both blocks carry `type` |
| trajectory | `reject-aligned-target-absent` (write) | `atom_types` presented at ordinal 0, `atoms` first at 1 |
| collection | `aligned-in-collection` | two records, each restating on growth; carry-forward does not cross records |
| collection | `reject-aligned-shares-system-name` | `system/atom_types` and an aligned `trajectory/atom_types` |

### F5.8 Migration

Purely additive: a store without `aligned_with` is unchanged. A reader that
predates F5 reads the blocks as two independent blocks (correct, unchecked).
A writer that predates F5 reopening a store to append does not enforce the
rule; that is the only way such a store can be produced.

---

## Decisions (summary)

| Id | Decision |
|----|----------|
| D0.1 | All five are `molrec_version` 1 (contingency: 2, stamped only when shuffle/zstd is used) |
| D1.2 | Absolute precision on a **binary** grid, `q = 2^(e−1)` from `frexp(p)`, round half to even; exact, deterministic |
| D1.4 | Must-decode += `zstd`, `numcodecs.shuffle`; `blosc` rejected (C on wasm via `blusc → zstd`, five-compressor surface) |
| D1.5 | Reference: shuffle(8) + zstd-3 for precision columns; shuffle + gzip-1 on a writer without a zstd encoder; float default otherwise unchanged |
| D1.6 | Precision: column attribute (frame/system), `sequence_schema` only (trajectory), header (LMDB) |
| — | wasm32 decodes zstd with `ruzstd` (pure Rust) registered as a zarrs codec plugin |
| D2.3 | Style table block name is a function of `(category, style)`, percent-encoded; no `block` field |
| D2.4 | Table params `f64` or `string`; absent = null |
| D2.5 | `mixing` is a style param, not a document key |
| D2.6 | `units` required (preset and/or quantities; radians in every preset); `special_bonds` optional |
| D2.8 | Hybrid via relation `style` column; same name in several styles without it = additive |
| D2.10 | Categories: molrs's six + `pair14`, `constraint`, `virtual_site`, `drude`; templates out |
| D2.12 | One force field per collection, LMDB key `ff` (frame bytes) |
| — | molrs renames `class_`→`class`, `def_`→`smarts`, GROMACS `bond_type`→`class`; fixes the LAMMPS improper-harmonic factor 2 |
| D3.1–3 | `_meta_types` on the frame group, complete, typed JSON forms; absent = inference |
| F4 | `chain` (not `chain_id`), `icode`, `altloc`, `occupancy`, `b_factor`; `formal_charge` stays `i64`, `ix/iy/iz` `i32`; no `residues`/`chains`/`molecules` blocks; fractional coordinates out of scope; `targets` as the one rule for non-default references; `members` canonical |
| F4 | Frame-meta `units` = the force-field units object |
| D5.3 | Alignment is checked on resolved frames: restate on count change, carry forward otherwise |

## Open questions

- **Q0.1** If version 1 has already shipped when F1 lands, confirm the D0.1
  contingency (version 2, stamped only when shuffle/zstd is used).
- **Q1.1** A time-delta codec (the 4.0 B/atom/frame measurement) would need a
  transform across frames inside a chunk; there is no portable Zarr codec for
  it. Deferred; it would be a new must-decode codec, i.e. a version bump.
- **Q2.1** `ForceField::from_section` refuses units that are not a molrs
  preset. Converting via the registry's parameter dimensions (every
  registered style has them) would let molrs import OpenMM-native and
  GROMACS-native records directly. Implement now or later?
- **Q2.2** OpenMM `<Residues>` templates (and virtual-site / Drude
  definitions that live in them) have no home. A `templates` table is the
  natural next addition once a consumer needs it.
