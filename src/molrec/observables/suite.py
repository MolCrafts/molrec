"""What the observables module is pinned down by.

The cases that matter most pin down *dimensions*, because that is the whole
idea: grid versus scatter, a shared axis versus two axes, a value dimension
with no coordinate at all. Get those wrong and two implementations write
shapes that cannot be read across.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

import numpy as np

from molrec.case import Case
from molrec.observables.model import Array, ObservableModel, ObservablesModel, Source
from molrec.ref import Ref
from molrec.registry import REGISTRY
from molrec.suite import Suite

_NUMPY = {"f64": "float64", "i32": "int32", "i64": "int64"}


def array(dims: tuple[str, ...], data, unit: str | None = None, dtype: str = "f64") -> Array:
    payload = np.asarray(data, dtype=_NUMPY[dtype])
    return Array(dims=dims, dtype=dtype, shape=payload.shape, data=payload, unit=unit)


def _observable(dims: tuple[str, ...], data, unit: str | None = None, dtype: str = "f64"):
    return ObservableModel(values=array(dims, data, unit, dtype))


def _section(path: str) -> Ref:
    return Ref(uri="./record.zarr", kind="section", select={"path": path})


@REGISTRY.suite
class ObservableSuite(Suite):
    module: ClassVar[str] = "observables"
    model_type: ClassVar[type[ObservablesModel]] = ObservablesModel

    def cases(self) -> Iterable[Case]:
        yield Case(
            id="empty-section",
            exercises="a record that observed nothing still has a valid section",
            model=ObservablesModel(),
        )

        yield Case(
            id="training-curve",
            exercises="step and wall_time are two coordinates over one dimension",
            model=ObservablesModel(
                coordinates={
                    "step": array(("point",), [0, 1, 2], dtype="i64"),
                    "wall_time": array(("point",), [0, 1_000, 2_000], "ns", "i64"),
                },
                observables={
                    "train/loss": ObservableModel(
                        values=array(("point",), [0.9, 0.7, 0.5]),
                        description="mean cross-entropy over the batch",
                    )
                },
            ),
        )

        yield Case(
            id="shared-axis",
            exercises="many quantities on one axis store that axis once",
            model=ObservablesModel(
                coordinates={"step": array(("point",), [0, 1, 2], dtype="i64")},
                observables={
                    "train/loss": _observable(("point",), [0.9, 0.7, 0.5]),
                    "train/lr": _observable(("point",), [1e-3, 1e-3, 5e-4]),
                    "train/grad_norm": _observable(("point",), [12.0, 8.0, 6.5]),
                },
            ),
        )

        yield Case(
            id="different-cadences",
            exercises="a different rate is a different dimension, not a grouping concept",
            model=ObservablesModel(
                coordinates={
                    "step": array(("point",), [0, 1, 2, 3], dtype="i64"),
                    "eval_step": array(("eval_point",), [0, 3], dtype="i64"),
                },
                observables={
                    "train/loss": _observable(("point",), [0.9, 0.7, 0.5, 0.4]),
                    "eval/MAE": _observable(("eval_point",), [1.2, 0.6]),
                },
            ),
        )

        yield Case(
            id="md-thermo",
            exercises="a simulation monitor with no notion of step is an observable too",
            model=ObservablesModel(
                coordinates={"time": array(("point",), [0.0, 0.5, 1.0], "ps")},
                observables={
                    "thermo/temperature": _observable(("point",), [300.0, 301.4, 299.8], "K")
                },
            ),
        )

        yield Case(
            id="derived-with-provenance",
            exercises="what a quantity was computed from is provenance, not a category",
            model=ObservablesModel(
                coordinates={"distance": array(("bin",), [0.0, 0.1, 0.2], "angstrom")},
                observables={
                    "structure/rdf": ObservableModel(
                        values=array(("bin",), [0.0, 0.8, 1.9]),
                        source=Source(
                            refs=(_section("/trajectory"),),
                            method_ref=_section("/method"),
                        ),
                    )
                },
            ),
        )

        yield Case(
            id="free-energy-grid",
            exercises="two coordinates on two dimensions make a grid",
            model=ObservablesModel(
                coordinates={
                    "phi": array(("phi",), [-3.0, 0.0, 3.0], "rad"),
                    "psi": array(("psi",), [-3.0, 3.0], "rad"),
                },
                observables={
                    "free_energy": _observable(
                        ("phi", "psi"), np.arange(6.0).reshape(3, 2), "kJ/mol"
                    )
                },
            ),
        )

        yield Case(
            id="scattered-samples",
            exercises="the same two coordinates on one dimension are a scatter, not a grid",
            model=ObservablesModel(
                coordinates={
                    "phi": array(("sample",), [-3.0, 0.0, 3.0], "rad"),
                    "psi": array(("sample",), [1.0, 2.0, 3.0], "rad"),
                },
                observables={
                    "sampled_energy": _observable(("sample",), [10.0, 11.0, 12.0], "kJ/mol")
                },
            ),
        )

        yield Case(
            id="dimension-without-coordinate",
            exercises="a vector's component axis needs no coordinate to be well defined",
            model=ObservablesModel(
                coordinates={"time": array(("point",), [0.0, 1.0], "ps")},
                observables={
                    "dipole": _observable(
                        ("point", "component"), np.arange(6.0).reshape(2, 3), "debye"
                    )
                },
            ),
        )

        yield Case(
            id="coordinate-and-observable-share-a-name",
            exercises="coordinates and observables are separate namespaces",
            model=ObservablesModel(
                coordinates={"energy": array(("point",), [1.0, 2.0], "kJ/mol")},
                observables={"energy": _observable(("point",), [3.0, 4.0], "kJ/mol")},
            ),
        )

        yield Case(
            id="name-needs-encoding",
            exercises="slashes and non-ASCII in a name survive the array-name mangling",
            model=ObservablesModel(
                coordinates={"step": array(("point",), [0, 1], dtype="i64")},
                observables={
                    "gpu/0/alloc_gib": _observable(("point",), [11.2, 11.9], "GiB"),
                    "损失/训练": _observable(("point",), [0.3, 0.2]),
                },
            ),
        )

        yield Case(
            id="width-is-preserved",
            exercises="i32 values stay i32 -- an integer comes back at its own width",
            model=ObservablesModel(
                coordinates={"step": array(("point",), [0, 1], dtype="i64")},
                observables={"train/count": _observable(("point",), [9, 7], dtype="i32")},
            ),
        )

        # --- negative ---

        yield Case(
            id="reject-dimension-conflict",
            backends=("zarr",),
            exercises="a dimension cannot be two lengths at once",
            expect_violation="dimension_conflict",
            model=ObservablesModel.model_construct(
                coordinates={"phi": array(("phi",), [0.0, 1.0, 2.0])},
                observables={"broken": _observable(("phi",), [0.0, 1.0])},
            ),
        )
