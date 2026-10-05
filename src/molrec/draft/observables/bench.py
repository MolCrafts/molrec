"""Observables workloads.

Append rate is what a live run feels; densify throughput decides whether
settling a finished run is worth doing at all.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

import numpy as np

from molrec.bench import Bench, Workload
from molrec.draft.observables.model import Array, ObservableModel, ObservablesModel
from molrec.registry import REGISTRY


def _array(dims: tuple[str, ...], data: np.ndarray, dtype: str, unit: str | None = None) -> Array:
    return Array(dims=dims, dtype=dtype, shape=data.shape, data=data, unit=unit)


@REGISTRY.bench
class ObservableBench(Bench):
    module: ClassVar[str] = "draft/observables"

    def workloads(self) -> Iterable[Workload]:
        yield self._curves(count=3, points=20_000)
        yield self._curves(count=100, points=2_000)
        yield self._grid(side=256)

    def _curves(self, count: int, points: int) -> Workload:
        rng = np.random.default_rng(0)
        step = np.arange(points, dtype="int64")
        coordinates = {"step": _array(("point",), step, "i64")}

        model = ObservablesModel(
            coordinates=coordinates,
            observables={
                f"train/m{index}": ObservableModel(
                    values=_array(("point",), rng.random(points), "f64")
                )
                for index in range(count)
            },
        )
        # One shared step column plus one f64 column per curve.
        nbytes = points * 8 * (count + 1)
        return Workload(
            id=f"{count}-curves-x-{points}-points",
            model=model,
            nbytes=nbytes,
            baseline="TensorBoard tfevents",
        )

    def _grid(self, side: int) -> Workload:
        rng = np.random.default_rng(1)
        values = rng.random((side, side))
        model = ObservablesModel(
            coordinates={
                "phi": _array(("phi",), np.linspace(-3, 3, side), "f64", "rad"),
                "psi": _array(("psi",), np.linspace(-3, 3, side), "f64", "rad"),
            },
            observables={
                "free_energy": ObservableModel(
                    values=_array(("phi", "psi"), values, "f64", "kJ/mol")
                )
            },
        )
        return Workload(
            id=f"free-energy-{side}x{side}",
            model=model,
            nbytes=values.nbytes,
            baseline="plumed / npz",
        )
