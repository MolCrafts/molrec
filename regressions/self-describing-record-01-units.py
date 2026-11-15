"""Regression example for the units slice: a record states its units once.

Run it directly (``PYTHONPATH=src python regressions/self-describing-record-01-units.py``);
it is not part of the pytest suite. Public models only, every expected value
written out here, nothing imported from an implementation.

* ``meta.units`` is the record's unit system: ``length`` and ``force`` stated.
* A column may state its own ``unit`` label; it does not replace the record's.
* A coordinate with no ``meta.units.length`` is refused, naming what is missing.
"""

from __future__ import annotations

import numpy as np

from molrec.core.model import (
    BlockModel,
    ColumnModel,
    FrameModel,
    MetaModel,
    RecordModel,
    require_stated_units,
)

LENGTH = "angstrom"
FORCE = "kcal/mol/angstrom"
COLUMN_UNIT = "nm"


def _column(values: list[float], unit: str | None = None) -> ColumnModel:
    array = np.array(values, dtype="float64")
    return ColumnModel(dtype="f64", shape=array.shape, values=array, unit=unit)


def _record(units: dict[str, str] | None) -> RecordModel:
    atoms = BlockModel(
        count=2,
        columns={"x": _column([0.0, 0.15], unit=COLUMN_UNIT), "fx": _column([1.0, -1.0])},
    )
    return RecordModel(meta=MetaModel(units=units), frame=FrameModel(blocks={"atoms": atoms}))


def main() -> None:
    record = _record({"length": LENGTH, "force": FORCE})
    require_stated_units(record, record.meta.units)

    assert record.meta.units.length == "angstrom"
    assert record.meta.units.force == "kcal/mol/angstrom"
    atoms = record.frame.blocks["atoms"]
    assert atoms.columns["x"].unit == "nm"
    assert atoms.columns["fx"].unit is None

    # A column's own label does not stand in for the record's unit system.
    for units, missing in (({"force": FORCE}, "length"), ({"length": LENGTH}, "force")):
        bare = _record(units)
        try:
            require_stated_units(bare, bare.meta.units)
        except ValueError as refusal:
            assert missing in str(refusal), refusal
        else:
            raise AssertionError(f"a record without units.{missing} was accepted")


if __name__ == "__main__":
    main()
    print("self-describing-record-01-units: ok")
