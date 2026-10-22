# System

## Purpose

`system/` is a **recommended record section** that answers:

> What chemical / physical **system** is this record about?

It holds identity of the particle set, connectivity, typing, and the default
cell — not the instantaneous coordinates of a time step.

`system/` is a convention layered on the general model (see
[Overview](overview.md)). It is first-class at the **Record** root (see
[Record](record.md)), not a private product layout.

## system vs frame

| | `system/` | `frame/` |
|---|---|---|
| Question | What **is** the system? | What is the state **now**? |
| Coordinates | Instantaneous Cartesian `x`/`y`/`z` are **not** required system content | Typical content |
| Box | Optional default cell: the section's `box` | Instantaneous box on the frame |
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
└── box/                       # optional default cell (the frame box)
```

Writers MAY flatten topology blocks directly under `system/` (e.g.
`system/atoms`, `system/bonds`) when a `topology/` group adds no value.

Field names for topology blocks **reuse** [Conventions](conventions.md)
(`element`, `atomi`/`atomj`, …). This chapter does not invent a second
topology vocabulary.

The default cell is this section's `box`. Particle identity across `system`,
`frame`, and `trajectory` follows
[Conventions](conventions.md#particle-identity).

## Parameters vs the force field vs method

| Location | Holds |
|----------|--------|
| `forcefield/` | The force-field document and one parameter table per style |
| `system/` | The topology and type labels that use that force field |
| `method/` | Narrative context: engine name, description, stage order |

`method.type` does not choose a layout. A record is read from the sections it
actually contains.

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
- [Force field](forcefield.md)
- [Units](units.md)
