"""Observables: a named quantity as a function of its coordinates.

**DRAFT (a proposal), not the record contract.** The normative
``observables/`` section is the kind-based layout in
``docs/spec/observables.md`` (``kind`` / ``time_dependent`` / ``axes`` /
``target`` metadata beside a data array), implemented by molrs. This module
is the dims-based redesign; its schemas publish under ``schema/draft/`` and
adopting it is a normative change to the ``observables/`` section.

Everything a run measures or an analysis computes is a function -- a training
loss over steps, a temperature over wall-clock time, an RDF over distance, a
free energy over two dihedrals, a density over a spatial grid. Writing that
as ``coordinates -> values`` makes the shape of the data enforce the idea,
rather than leaving it to a convention someone has to remember.

Dimensions are what make the shape unambiguous, and the ambiguity is real:
given coordinates ``phi`` and ``psi``, is the value a ``(n_phi, n_psi)`` grid
or ``n`` scattered samples? Naming dimensions answers it, and makes the
answer checkable::

    grid       phi.dims=(phi,)    psi.dims=(psi,)    values.dims=(phi, psi)
    scattered  phi.dims=(sample,) psi.dims=(sample,) values.dims=(sample,)
    a curve    step.dims=(point,) wall_time.dims=(point,) values.dims=(point,)

The third line is why a training curve needs no special case: ``step`` and
``wall_time`` are two coordinates over one dimension, which is a structural
fact rather than a convention.

Coordinates are held once for the whole section, as in an xarray ``Dataset``,
so a hundred curves sharing one axis store that axis once.

What is deliberately absent:

* **No rendering preference.** Whether an RDF is drawn as a line or a heatmap
  is decided later, by someone else, and differs between consumers -- so it
  is not contractual, and there is no wrong value to validate against.
* **No ``kind`` of scalar-versus-vector, and no ``time_dependent`` flag.**
  ``dims`` and ``shape`` already say both, and a fact stated twice is a fact
  that can disagree with itself.

What is *not* an observable: a **relation** (a bond joins two atoms; that is
not ``coordinate -> value``) and a **document** (``meta``, ``method`` and
``status`` have no domain at all). Topology stays in ``frame``.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, ConfigDict, Field, model_validator

from molrec.arrays import NDArray, arrays_equal
from molrec.core.model import DocumentModel, DType, values_dtype
from molrec.ref import Ref


class Array(BaseModel):
    """A named-dimension array: the one building block observables are made of."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    dims: tuple[str, ...] = ()
    dtype: DType
    shape: tuple[int, ...] = ()
    data: NDArray
    unit: str | None = None

    @model_validator(mode="after")
    def _shape_dims_and_dtype_agree(self) -> Array:
        if len(self.dims) != len(self.shape):
            raise ValueError(f"{len(self.dims)} dims for a {len(self.shape)}-d shape")
        if tuple(self.data.shape) != self.shape:
            raise ValueError(f"data has shape {self.data.shape}, declared {self.shape}")
        carried = values_dtype(self.data)
        if carried != self.dtype:
            raise ValueError(f"data carries dtype {carried!r}, declared {self.dtype!r}")
        return self

    @property
    def extent(self) -> dict[str, int]:
        """Length this array claims for each dimension it spans."""
        return dict(zip(self.dims, self.shape, strict=True))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Array):
            return NotImplemented
        return (
            self.dims == other.dims
            and self.dtype == other.dtype
            and self.shape == other.shape
            and self.unit == other.unit
            and arrays_equal(self.data, other.data)
        )

    __hash__ = None  # type: ignore[assignment]


class Source(DocumentModel):
    """Where an observable came from.

    Derivedness is not a property of a number -- it is a property of its
    history, and it is recursive with no fixed point. So it is recorded as
    provenance rather than used to classify anything.
    """

    refs: tuple[Ref, ...] = ()
    method_ref: Ref | None = None


class ObservableModel(BaseModel):
    """One quantity and where it came from.

    It carries no coordinates of its own. Its domain is named by
    ``values.dims``, and the arrays for those dimensions live once at the
    section level -- which is what keeps a hundred curves sharing one ``step``
    from storing a hundred identical copies of it.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="forbid")

    values: Array
    source: Source | None = None
    payload: str | None = None
    description: str | None = None

    @property
    def dims(self) -> tuple[str, ...]:
        return self.values.dims

    @property
    def leading_dim(self) -> str | None:
        """The dimension a live writer appends along."""
        return self.values.dims[0] if self.values.dims else None


class ObservablesModel(BaseModel):
    """The section: shared coordinates plus the quantities over them.

    This is xarray's ``Dataset`` -- shared dimensions, shared coordinates, and
    many variables defined over them -- and it is shaped that way for a
    measured reason. With coordinates held per-observable, a hundred curves
    on one ``step`` axis stored a hundred identical copies: half the bytes on
    disk and four times the write cost, for information that was the same
    every time.

    Different cadences need no grouping concept. They are simply different
    dimensions: a training curve over ``point`` and an evaluation curve over
    ``eval_point`` coexist because the dimension name *is* the grouping.

    ``dims`` is derived, never stored. A dimension table beside the arrays
    would be the same fact written twice, and two copies of a fact can
    disagree.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="forbid")

    coordinates: dict[str, Array] = Field(default_factory=dict)
    observables: dict[str, ObservableModel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _dimensions_are_consistent(self) -> ObservablesModel:
        extents: dict[str, int] = {}
        for label, array in self._arrays():
            for dim, length in array.extent.items():
                seen = extents.setdefault(dim, length)
                if seen != length:
                    raise ValueError(
                        f"dimension {dim!r} is {seen} elsewhere but {length} in {label!r}"
                    )
        return self

    def _arrays(self) -> Iterator[tuple[str, Array]]:
        for name, array in self.coordinates.items():
            yield f"coordinates/{name}", array
        for name, observable in self.observables.items():
            yield f"observables/{name}", observable.values

    @property
    def dims(self) -> dict[str, int]:
        """Every dimension in play and its length, derived from the arrays."""
        extents: dict[str, int] = {}
        for _, array in self._arrays():
            extents.update(array.extent)
        return extents

    def coordinates_on(self, dim: str) -> dict[str, Array]:
        """Coordinates that advance with ``dim`` -- what a row carries."""
        return {name: array for name, array in self.coordinates.items() if array.dims == (dim,)}

    def observables_on(self, dim: str) -> dict[str, ObservableModel]:
        """Observables whose leading dimension is ``dim``."""
        return {
            name: observable
            for name, observable in self.observables.items()
            if observable.leading_dim == dim
        }

    @property
    def row_dims(self) -> tuple[str, ...]:
        """Dimensions a live writer appends along, in first-seen order."""
        seen: dict[str, None] = {}
        for observable in self.observables.values():
            if observable.leading_dim is not None:
                seen.setdefault(observable.leading_dim, None)
        return tuple(seen)
