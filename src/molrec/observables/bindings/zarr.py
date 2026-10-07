"""The Zarr V3 binding of the ``observables`` section.

Layout (``docs/spec/observables.md``), inside a record root::

    observables/
    ├── meta/
    │   └── <name>/         group attributes = the observable's metadata document
    └── <name>              the data array, any shape, a closed-set dtype

The metadata document is the named keys (``kind``, ``description``,
``time_dependent``, then ``unit`` / ``axes`` / ``sampling`` / ``domain`` /
``target`` when set) plus every key the producer added, kept verbatim. A
kind the contract does not define is written and read back unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import zarr

from molrec.binding import Binding, Codec
from molrec.core.bindings.zarr import ZarrStore, create_fixed, stored_dtype
from molrec.core.model import ArrayModel, document
from molrec.observables.model import (
    OBSERVABLES_META_GROUP,
    ObservableMetaModel,
    ObservableModel,
    ObservablesModel,
    check_observable_name,
)
from molrec.observables.store import ObservableStore
from molrec.registry import REGISTRY

#: The section's name at the record root.
OBSERVABLES_GROUP = "observables"


class ZarrObservableStore(ZarrStore, ObservableStore):
    """A record root holding ``meta`` and an ``observables`` section."""


class ZarrObservablesCodec(Codec):
    """The official translation of the section."""

    def write(self, model: ObservablesModel, store: ZarrObservableStore) -> None:
        store.clear()
        root = store.root(mode="w")
        root.create_group("meta")
        self.write_into(root.create_group(OBSERVABLES_GROUP), model)

    def read(self, store: ZarrObservableStore) -> ObservablesModel:
        root = store.root(mode="r")
        if OBSERVABLES_GROUP not in root:
            return ObservablesModel()
        return self.read_from(root[OBSERVABLES_GROUP])

    def write_into(self, group: zarr.Group, model: ObservablesModel) -> None:
        """Lay the section out under an already-opened ``observables/`` group."""
        meta = group.create_group(OBSERVABLES_META_GROUP)
        for name, observable in model.observables.items():
            check_observable_name(name)
            meta.create_group(name).attrs.update(document(observable.meta))
            data = observable.data
            array = create_fixed(group, name, data.shape, data.dtype)
            if data.values is not None:
                array[...] = data.values

    def read_from(self, group: zarr.Group) -> ObservablesModel:
        arrays = {
            name: member for name, member in group.members() if isinstance(member, zarr.Array)
        }
        documents: dict[str, dict[str, Any]] = {}
        if OBSERVABLES_META_GROUP in group:
            documents = {
                name: dict(member.attrs)
                for name, member in group[OBSERVABLES_META_GROUP].members()
                if isinstance(member, zarr.Group)
            }
        unpaired = sorted(set(arrays) ^ set(documents))
        if unpaired:
            raise ValueError(
                f"{group.name}: observables {unpaired} lack their pair -- every observable is a "
                f"data array beside {OBSERVABLES_META_GROUP}/<name>"
            )
        return ObservablesModel(
            observables={
                name: ObservableModel(
                    meta=ObservableMetaModel.model_validate(documents[name]),
                    data=ArrayModel(
                        dtype=stored_dtype(array),
                        shape=tuple(int(n) for n in array.shape),
                        values=array[...],
                    ),
                )
                for name, array in arrays.items()
            }
        )


@REGISTRY.binding
class ZarrObservableBinding(Binding):
    module: ClassVar[str] = "observables"
    backend: ClassVar[str] = "zarr"

    def new_store(self, workdir: Path) -> ZarrObservableStore:
        store = ZarrObservableStore(workdir.with_suffix(".mrec"))
        store.clear()
        return store

    def codec(self) -> ZarrObservablesCodec:
        return ZarrObservablesCodec()
