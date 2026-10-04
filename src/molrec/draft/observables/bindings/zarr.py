"""The Zarr V3 binding -- the settled form.

Layout::

    <root>/
    ├── coordinates/
    │   └── <safe_coord>   array; attrs: dims, unit
    └── observables/
        └── <safe_name>    array; attrs: dims, unit, description, payload, source

``dims`` rides on each array rather than being tabulated once, because a
coordinate can span a different set of dimensions than the values it indexes
-- which is exactly what separates a grid from a scatter. The dimension table
is derived on read rather than stored, so there is no second copy to fall out
of step with the arrays.

Coordinates and observables are sibling groups, so a coordinate and an
observable may share a name without colliding.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import zarr

from molrec.binding import Binding, Codec
from molrec.chunking import plan
from molrec.core.bindings.zarr import TO_ZARR, ZarrStore, stored_dtype
from molrec.draft.observables.model import (
    Array,
    ObservableModel,
    ObservablesModel,
    Source,
)
from molrec.draft.observables.store import ObservableStore
from molrec.registry import REGISTRY
from molrec.safe_name import original_name, safe_name

OBSERVABLES = "observables"
COORDINATES = "coordinates"


class ZarrObservableStore(ZarrStore, ObservableStore):
    """A Zarr V3 root holding a settled draft observables section."""


class ZarrObservableCodec(Codec):
    """The official translation."""

    def write(self, model: ObservablesModel, store: ZarrObservableStore) -> None:
        store.clear()
        root = store.root(mode="w")

        coordinates = root.create_group(COORDINATES)
        for name, array in model.coordinates.items():
            self._write_array(coordinates, safe_name(name), array)

        section = root.create_group(OBSERVABLES)
        for name, observable in model.observables.items():
            self._write_one(section, name, observable)

    def read(self, store: ZarrObservableStore) -> ObservablesModel:
        root = store.root(mode="r")
        coordinates = {}
        if COORDINATES in root:
            coordinates = {
                original_name(name): self._read_array(member)
                for name, member in root[COORDINATES].members()
                if isinstance(member, zarr.Array)
            }
        observables = {}
        if OBSERVABLES in root:
            observables = {
                original_name(name): self._read_one(member)
                for name, member in root[OBSERVABLES].members()
                if isinstance(member, zarr.Array)
            }
        return ObservablesModel(coordinates=coordinates, observables=observables)

    def _write_one(self, section: zarr.Group, name: str, observable: ObservableModel) -> None:
        stored = self._write_array(section, safe_name(name), observable.values)
        if observable.description is not None:
            stored.attrs["description"] = observable.description
        if observable.payload is not None:
            stored.attrs["payload"] = observable.payload
        if observable.source is not None:
            stored.attrs["source"] = observable.source.model_dump(mode="json", exclude_none=True)

    def _write_array(self, group: zarr.Group, name: str, array: Array) -> zarr.Array:
        chunks, shards = plan(array.shape, array.data.dtype.itemsize)
        options: dict = {}
        if chunks is not None:
            options["chunks"] = chunks
        if shards is not None:
            options["shards"] = shards

        stored = group.create_array(name, shape=array.shape, dtype=TO_ZARR[array.dtype], **options)
        stored[...] = array.data
        stored.attrs["dims"] = list(array.dims)
        if array.unit is not None:
            stored.attrs["unit"] = array.unit
        return stored

    def _read_one(self, stored: zarr.Array) -> ObservableModel:
        attrs = dict(stored.attrs)
        source = attrs.get("source")
        return ObservableModel(
            values=self._read_array(stored),
            source=Source.model_validate(source) if source is not None else None,
            payload=attrs.get("payload"),
            description=attrs.get("description"),
        )

    def _read_array(self, stored: zarr.Array) -> Array:
        attrs = dict(stored.attrs)
        return Array(
            dims=tuple(attrs.get("dims", ())),
            dtype=stored_dtype(stored),
            shape=tuple(int(n) for n in stored.shape),
            data=stored[...],
            unit=attrs.get("unit"),
        )


@REGISTRY.binding
class ZarrObservableBinding(Binding):
    module: ClassVar[str] = "draft/observables"
    backend: ClassVar[str] = "zarr"

    def new_store(self, workdir: Path) -> ZarrObservableStore:
        store = ZarrObservableStore(workdir.with_suffix(".zarr"))
        store.clear()
        return store

    def codec(self) -> ZarrObservableCodec:
        return ZarrObservableCodec()
