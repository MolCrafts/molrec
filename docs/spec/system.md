# System

## Purpose

`system/` is a **recommended record section** that answers:

> What chemical / physical **system** is this record about?

It holds identity of the particle set, connectivity, typing, force-field or
model binding, and box **policy** — not the instantaneous coordinates of a
time step.

`system/` is a convention layered on the general model (see
[Overview](overview.md)). It is first-class at the **Record** root (see
[Record](record.md)), not a private product layout.

## system vs frame

| | `system/` | `frame/` |
|---|---|---|
| Question | What **is** the system? | What is the state **now**? |
| Coordinates | Instantaneous Cartesian `x`/`y`/`z` are **not** required system content | Typical content |
| Box | Optional default cell or PBC **policy** | Instantaneous box on the frame |
| Topology | Bonds / angles / … as definition | May repeat or omit if trajectory-only |
| Types / parameters | Atom types, FF or model binding | Optional per-instance overrides |

**Rule:** Instantaneous Cartesian coordinates belong on `frame` or
`trajectory`. A conforming `system/` MAY omit coordinate columns entirely.

## Recommended tree

```text
system/
├── meta/                      # local id, description (optional attrs)
├── topology/                  # optional grouping; or flat convention blocks
│   ├── atoms/                 # rows without x/y/z are valid
│   ├── bonds/                 # atomi / atomj per conventions
│   └── …
├── parameters/                # force-field or model parameters / references
│   └── (forcefield|model)/…
└── (box_policy)/              # default cell, pbc flags, ensemble hints
```

Writers MAY flatten topology blocks directly under `system/` (e.g.
`system/atoms`, `system/bonds`) when a `topology/` group adds no value.

Field names for topology blocks **reuse** [Conventions](conventions.md)
(`element`, `atomi`/`atomj`, …). This chapter does not invent a second
topology vocabulary.

## Parameters vs method

| Location | Holds |
|----------|--------|
| `system/parameters` | Tables / types / styles that **define** the Hamiltonian or model binding for this system |
| `method/` | Narrative scientific context: engine name, stage order, workflow type |

Do **not** define a record-root section named `forcefield/` as part of MolRec.
Force-field data lives under `system/parameters` (or is referenced from there).

## Compatibility

- Records with only `frame` (no `system`) remain valid (Structure shape).
- Records with only `system` (no `frame`) are valid (System-def shape).
- Trajectory packages **MAY** omit `system/`. When `system/` is present,
  `trajectory/` **SHOULD** carry state/coordinate updates only (see
  [Trajectory](trajectory.md)).

## See also

- [Record](record.md)
- [Frame](frame.md)
- [Conventions](conventions.md)
- [Method](method.md)
