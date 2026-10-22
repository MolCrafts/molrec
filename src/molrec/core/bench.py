"""Core-module workloads.

Deliberately the same models the conformance suite uses, only large: what is
measured is what was proven correct.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

import numpy as np

from molrec.bench import Bench, Workload
from molrec.core.model import BlockModel, ColumnModel, FrameModel
from molrec.registry import REGISTRY


@REGISTRY.bench
class FrameBench(Bench):
    module: ClassVar[str] = "core"

    def workloads(self) -> Iterable[Workload]:
        yield self._positions(natoms=100_000)
        yield self._grid(side=64)

    def _positions(self, natoms: int) -> Workload:
        values = np.random.default_rng(0).random((3, natoms))
        model = FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=natoms,
                    columns={
                        axis: ColumnModel(dtype="f64", shape=(natoms,), values=values[index])
                        for index, axis in enumerate("xyz")
                    },
                )
            }
        )
        return Workload(
            id=f"positions-{natoms}-xyz-f64",
            model=model,
            nbytes=values.nbytes,
            baseline="HDF5 / XTC",
        )

    def _grid(self, side: int) -> Workload:
        count = side**3
        values = np.random.default_rng(1).random(count)
        model = FrameModel(
            blocks={
                "density": BlockModel(
                    count=count,
                    structural_shape=(side, side, side),
                    columns={
                        "electron_density": ColumnModel(dtype="f64", shape=(count,), values=values)
                    },
                )
            }
        )
        return Workload(
            id=f"grid-{side}cubed-f64",
            model=model,
            nbytes=values.nbytes,
            baseline="CHGCAR / cube",
        )
