"""What the ``observables`` section is pinned down by.

The kind-based layout of ``docs/spec/observables.md``: a metadata document
beside one data array per name, unknown kinds and keys carried through, and
the pairing refused when it is broken.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, ClassVar

import numpy as np

from molrec.case import Case
from molrec.core.model import (
    NUMPY_DTYPE,
    ArrayModel,
)
from molrec.observables.model import (
    ObservableMetaModel,
    ObservableModel,
    ObservablesModel,
)
from molrec.registry import REGISTRY
from molrec.suite import Suite


def _data(dtype: str, values: Any) -> ArrayModel:
    array = np.array(values, dtype=NUMPY_DTYPE[dtype])
    return ArrayModel(dtype=dtype, shape=array.shape, values=array)


def _observable(kind: str, data: ArrayModel, **meta: Any) -> ObservableModel:
    return ObservableModel(
        meta=ObservableMetaModel.model_validate(
            {"kind": kind, "description": meta.pop("description", kind), "time_dependent": False}
            | meta
        ),
        data=data,
    )


def _tamper_group(path: str, *, drop: str | None = None, attrs: dict | None = None) -> Any:
    """A tamper that removes ``drop`` under ``path``, or replaces its attributes."""

    def tamper(store: Any) -> None:
        import zarr

        group = zarr.open_group(store=store.path, mode="r+")[path]
        if drop is not None:
            del group[drop]
        if attrs is not None:
            group.attrs.clear()
            group.attrs.update(attrs)

    return tamper


@REGISTRY.suite
class ObservablesSuite(Suite):
    module: ClassVar[str] = "observables"
    model_type: ClassVar[type[ObservablesModel]] = ObservablesModel

    def cases(self) -> Iterable[Case]:
        yield Case(
            id="empty-section",
            exercises="a section that observed nothing is still a section",
            model=ObservablesModel(),
        )

        energy = _observable(
            "scalar", _data("f64", -76.4), description="total energy", unit="hartree"
        )
        yield Case(
            id="scalar-and-vector",
            exercises="kind says how the array reads: a 0-d scalar, a per-frame vector with "
            "named axes, an entity-aligned vector with a target",
            model=ObservablesModel(
                observables={
                    "energy": energy,
                    "dipole": ObservableModel(
                        meta=ObservableMetaModel(
                            kind="vector",
                            description="dipole moment per frame",
                            time_dependent=True,
                            unit="debye",
                            axes=["component"],
                            sampling="per_frame",
                        ),
                        data=_data("f64", np.arange(12.0).reshape(4, 3)),
                    ),
                    "charges": _observable(
                        "vector",
                        _data("f64", [0.4, -0.2, -0.2]),
                        description="partial charges",
                        target="/frame/atoms",
                        domain="atoms",
                    ),
                }
            ),
        )

        yield Case(
            id="every-dtype",
            exercises="an observable's array takes any column dtype, at its own width",
            model=ObservablesModel(
                observables={
                    "count": _observable("scalar", _data("i32", [3, 4])),
                    "ids": _observable("vector", _data("u64", [2**64 - 1, 0])),
                    "labels": _observable("vector", _data("string", ["a", "b"])),
                    "flags": _observable("vector", _data("bool", [True, False])),
                    "spectrum": _observable("vector", _data("c128", [1 + 2j, -1j])),
                }
            ),
        )

        yield Case(
            id="unknown-kind-and-keys-preserved",
            exercises="a kind the contract does not define, and keys it does not name, are "
            "carried through unchanged -- a null-valued one included",
            model=ObservablesModel(
                observables={
                    "ir": _observable(
                        "spectrum",
                        _data("f64", [[1000.0, 0.1], [1600.0, 0.9]]),
                        x_vendor={"resolution": 4, "window": [400, 4000]},
                        x_reviewed=None,
                    )
                }
            ),
        )

        yield Case(
            id="reject-data-without-meta",
            exercises="the pairing is mandatory: a data array without its metadata is refused",
            expect_violation="unpaired_observable",
            tamper=_tamper_group("observables/meta", drop="energy"),
            model=ObservablesModel(observables={"energy": energy}),
        )

        yield Case(
            id="reject-meta-without-data",
            exercises="the pairing is mandatory: metadata without its data array is refused",
            expect_violation="unpaired_observable",
            tamper=_tamper_group("observables", drop="energy"),
            model=ObservablesModel(observables={"energy": energy}),
        )

        yield Case(
            id="reject-missing-kind",
            exercises="kind is required; a document without it cannot say how the array reads",
            expect_violation="missing_kind",
            tamper=_tamper_group(
                "observables/meta/energy", attrs={"description": "x", "time_dependent": False}
            ),
            model=ObservablesModel(observables={"energy": energy}),
        )

        yield Case(
            id="reject-name-meta",
            exercises="meta names the metadata group; an observable cannot take it",
            expect_violation="reserved_name",
            rejects_on="write",
            model=ObservablesModel.model_construct(observables={"meta": energy}),
        )
