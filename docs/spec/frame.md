# Frame

## Purpose

`frame` stores a canonical snapshot.

It is the place for structure-like data:

- per-entity arrays for any canonical collection
- per-bond arrays
- per-angle arrays
- per-dihedral arrays
- volumetric grids (charge density, electrostatic potential, etc.)
- the simulation cell (box)
- other snapshot-resolved arrays tied to the canonical configuration

`frame` is not restricted to atoms only.

## Structure

```text
frame
\-- atoms
|   \-- meta
|   |   +-- count: Integer[]
|   |   +-- entity_kind: String[] = "atom"
|   \-- (id: Integer[N])
|   \-- (element: String[N])
|   \-- (atomic_number: Integer[N])
|   \-- (name: String[N])
|   \-- (position: Float[N][ndim])
|   \-- (mass: Float[N])
|   \-- (charge: Float[N])
|   \-- ...
\-- (bonds)
|   \-- meta
|   |   +-- count: Integer[]
|   |   +-- entity_kind: String[] = "bond"
|   \-- (index: Integer[count][2])
|   \-- ...
\-- (angles)
|   \-- meta
|   |   +-- count: Integer[]
|   |   +-- entity_kind: String[] = "angle"
|   \-- (index: Integer[count][3])
|   \-- ...
\-- (dihedrals)
|   \-- meta
|   |   +-- count: Integer[]
|   |   +-- entity_kind: String[] = "dihedral"
|   \-- (index: Integer[count][4])
|   \-- ...
\-- (grids)
|   \-- <grid_name>
|       +-- dim: Integer[3]
|       +-- origin: Float[3]
|       +-- cell: Float[3][3]
|       +-- pbc: Bool[3]
|       \-- <array_name>: Float[nx][ny][nz]
|       \-- ...
\-- (box)
|   +-- vectors: Float[ndim][ndim]
|   +-- (origin: Float[ndim])
|   +-- (boundary: Bool[ndim])
\-- ...
```

The names above are examples. A canonical collection may represent atoms, beads, fragments, rigid
bodies, virtual sites, QM atoms, coarse-grained sites, or any other named entity set.

## Canonical collections

Each collection under `frame` is a collection of aligned per-entity arrays.

Rules:

- `frame/<collection>/meta/count` defines the canonical entity count for that collection
- every dataset in `frame/<collection>` except `meta` has leading dimension `count`
- `frame/<collection>` defines the canonical entity order reused by aligned trajectory or
  observable data

The conventional `atoms` collection is still common, but it is not privileged over other
collections in the specification.

## Coordinates

If a collection stores positions, MolRec accepts either:

- a packed Cartesian vector field such as `frame/atoms/position`
- split-axis Cartesian coordinate triplets

For atom-like split-axis data, both of these triplets are legal MolRec coordinates:

- `x`, `y`, `z`
- `xu`, `yu`, `zu`

MolRec does not require readers to synthesize `x/y/z` from `xu/yu/zu`, or vice versa. Source
columns should be preserved as-is unless a consumer intentionally derives new coordinates.

## Tuple-based collections

MolRec allows tuple-based collections directly under `frame`.

This includes:

- `frame/bonds`
- `frame/angles`
- `frame/dihedrals`
- other implementation-defined tuple collections

Each collection may contain:

- an `index` array defining the participating entity tuples
- aligned arrays of labels, parameters, or properties

Tuple collections are not restricted to atom tuples. The same pattern may be used for bead tuples,
fragment tuples, or other implementation-defined relations.

Examples:

- bond order
- equilibrium length
- angle equilibrium value
- dihedral periodicity

## Grids

`frame` may contain named volumetric grids under `frame/grids/<name>`.

A grid represents values on a uniform 3-D spatial domain. Each grid stores:

- `dim`: grid dimensions `[nx, ny, nz]`
- `origin`: Cartesian origin of the grid
- `cell`: cell vectors defining the spatial extent (columns are lattice vectors)
- `pbc`: periodic boundary flags for each axis
- one or more named scalar arrays, each of shape `[nx][ny][nz]`

Grid is a pure data structure. It carries no unit or description. When the same data appears in
`observables`, the semantic metadata (unit, description, sampling, domain) belongs on the observable
wrapper, not on the Grid itself.

## Box

`box` is a property of each frame.

Each frame carries its own simulation cell:

```text
frame/box
+-- vectors: Float[ndim][ndim]       # cell vectors
+-- (origin: Float[ndim])            # cell origin
+-- (boundary: Bool[ndim])           # periodic boundary conditions
```

For trajectory data, each frame stores its own box, naturally supporting both fixed-cell and
variable-cell simulations.

## Interpretation

`frame` should be read as:

> the canonical stored snapshot of the system, including collections, grids, and the simulation cell.
