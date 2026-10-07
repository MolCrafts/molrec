# Trajectory

Time-dependent data consist of a series of samples (frames) referring to
multiple time steps. They are stored in the `trajectory` group of the
[root](overview.md). The logical model is an ordered sequence of frames
sharing a declared set of blocks and columns, together with an integer step
index and an optional physical time.

`trajectory` is a record section. The canonical entity remains the
[frame](frame.md).

```text
trajectory
 +-- sequence_schema
 +-- nstep
 +-- (step_progression: {start, stride})
 +-- (time_progression: {start, stride})
 \-- (step: i64[nstep])
 \-- (time: f64[nstep])
 \-- (meta)
 |    \-- <key>: <dtype>[nstep][...]
 \-- (box)
 \-- <block>
      \-- ...
```

This is the logical picture; the full on-disk tree, with the elisions that
make the common run cost one array per column, is
[Ragged trajectory](ragged.md#layout).

`step`

The producer's iteration counter at each committed frame, strictly
increasing — a repeated or smaller step number is rejected when the frame is
appended. On the reference binding it is the `step_progression` attribute
while the numbering is arithmetic and a `step` array otherwise; the number
of committed frames is the trajectory group's `nstep` attribute, written
last in a commit ([Ragged trajectory](ragged.md#the-commit-marker-nstep)).

`time`

An optional dataset that is the same as `step`, except it is `f64`-valued
and contains the simulation time. It is all-or-nothing: a run either
supplies a time for every frame or for none, and a writer refuses a frame
that breaks either way.

Two integers index a trajectory and they are not the same one. The *frame
ordinal* `i` is a frame's position in the sequence, `0 <= i < nstep`. The
*step number* is the value stored at `step[i]`. It may start anywhere and
may skip values.

`meta`

Per-step scalars and small fixed vectors, one typed array per key. The
standard keys — `pe`, `ke`, `etotal`, `temp`, `press`, `volume`, all
`f64` — are [standardized identifiers](conventions.md#per-step-scalars).
Their declaration and tag set are in [Ragged trajectory](ragged.md#per-step-metadata).

## Blocks over time

Every block the run may carry is declared when the trajectory is created.
At each frame a declared block is **present** (it has rows), **empty** (its
most recent update had zero rows) or **absent** (it has not appeared yet).
A frame that omits a block does not change it: the block carries forward
from the previous frame. A frame that presents a zero-row block makes it
empty from then on. Once a block has appeared it is never absent again. The
cell carries forward the same way. The full rules are
[The three states of a block](ragged.md#the-three-states-of-a-block).

A block may be declared [aligned](ragged.md#aligned-blocks) with another:
its rows are the other block's rows, so it can change rarely beside a block
that changes every frame, and it is restated whenever the other's row count
changes.

## With and without `system`

A record may omit `system` and still carry `trajectory` (frames may embed
full blocks, including topology). When both `system` and `trajectory` are
present, trajectory should update state only (coordinates, instantaneous
properties, instantaneous box) and not restate topology held in `system`.

When `system/<block>` and `trajectory/<block>` coexist, they are aligned
**1:1 by row order**:

- every update of `trajectory/<block>` holds exactly as many rows as
  `system/<block>`;
- if both carry an `id` column, the values are equal row for row, so a
  reader may join on `id` as well as on position;
- a ragged trajectory block (row count varying per frame) **MUST NOT**
  share a name with a `system` block.

Evolving frame-like state belongs in `trajectory`. Reduced scientific
statistics belong in [observables](observables.md); run-local monitoring
belongs in [metrics](metrics.md).

Time-independent data are stored as arrays or document objects without a
leading `[nstep]` axis. A `frame` section is one snapshot. Topology and
types that do not change in time belong in [system](system.md).

The reference binding stores each block as a sparse update series (an
append-first CSR layout). That encoding is specified under
[Ragged trajectory](ragged.md); the reference streaming writer is
`molrs.io.mrec.FrameSequenceWriter`, the whole-sequence doors
`molrs.io.mrec.write_trajectory` / `read_trajectory`.
