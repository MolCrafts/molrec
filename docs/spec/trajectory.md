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
 \-- step: i64[nstep]
 \-- (time: f64[nstep])
 \-- (meta)
 \-- (box)
 \-- <block>
      \-- ...
```

`step`

A dataset of length `nstep` that contains the producer's iteration counter
at each committed frame. The values are strictly increasing — a repeated
step number is rejected. `step` is written last in a commit, so its length
is the number of frames that are fully on disk.

`time`

An optional dataset that is the same as `step`, except it is `f64`-valued
and contains the simulation time. It is all-or-nothing: a run either
supplies a time for every frame or for none.

Two integers index a trajectory and they are not the same one. The *frame
ordinal* `i` is a frame's position in the sequence, `0 <= i < nstep`. The
*step number* is the value stored at `step[i]`. It may start anywhere and
may skip values.

A record may omit `system` and still carry `trajectory` (frames may embed
full blocks, including topology). When both `system` and `trajectory` are
present, trajectory should update state only (coordinates, instantaneous
properties, instantaneous box) and not restate topology held in `system`.

Evolving frame-like state belongs in `trajectory`. Reduced scientific
statistics belong in [observables](observables.md); run-local monitoring
belongs in [metrics](metrics.md).

Time-independent data are stored as arrays or document objects without a
leading `[nstep]` axis. A `frame` section is one snapshot. Topology, types,
and parameters that do not change in time belong in [system](system.md).

The reference binding stores each block as a sparse update series (an
append-first CSR layout). That encoding is specified under
[Ragged trajectory](ragged.md).
