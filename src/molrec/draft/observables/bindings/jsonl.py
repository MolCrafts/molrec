"""The JSONL binding -- the live write-ahead log.

One UTF-8 JSON object per line, newline-terminated, append-only. Nothing
rewrites a historical line, which is what lets a crashed run still be read:
keep the file, skip the torn tail.

Three line kinds, discriminated by ``$``:

``coord``
    A coordinate declared once -- dims, dtype, unit. One that does not
    advance with an appended dimension carries its data here too: the ``psi``
    axis of a free-energy surface is known before the first sample arrives.
    One that *does* advance is declared here and filled in by rows.
``obs``
    A name declared once: its dimensions, dtype, unit, provenance. A
    dimensionless observable carries its value here too, since there is
    nothing to append to.
``row``
    One slice along a dimension -- the coordinates that advance with it and
    the corresponding value of *every* observable defined over it.

That last line is the important one, and it is TensorBoard's ``Event``: a row
is a moment of the run, not a point of one curve. A hundred curves sharing a
``step`` axis produce one line per step rather than a hundred, and ``step``
is written once per row rather than once per curve per row.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from molrec.binding import Binding, Codec
from molrec.core.model import NUMPY_DTYPE
from molrec.draft.observables.model import Array, ObservableModel, ObservablesModel, Source
from molrec.draft.observables.store import ObservableStore
from molrec.registry import REGISTRY

FILENAME = "observables.jsonl"


class JsonlObservableStore(ObservableStore):
    """A directory holding one append-only WAL."""

    backend: ClassVar[str] = "jsonl"

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def uri(self) -> str:
        return str(self._path)

    @property
    def wal(self) -> Path:
        return self._path / FILENAME

    def append(self, *lines: str) -> None:
        """The only write operation. History is never touched.

        Variadic because a live logger appends one line and a bulk writer
        appends thousands; reopening the file per line turns a settle into an
        O(n) syscall storm.
        """
        if not lines:
            return
        self._path.mkdir(parents=True, exist_ok=True)
        with self.wal.open("a", encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in lines))

    def lines(self) -> list[str]:
        if not self.wal.exists():
            return []
        return self.wal.read_text(encoding="utf-8").splitlines()

    def clear(self) -> None:
        if self._path.exists():
            shutil.rmtree(self._path)


class JsonlObservableCodec(Codec):
    """The official translation for the WAL."""

    def write(self, model: ObservablesModel, store: JsonlObservableStore) -> None:
        store.clear()
        rows = set(model.row_dims)

        store.append(
            *(
                _dump(
                    {
                        "$": "coord",
                        "name": name,
                        **_spec(array, data=not _advances_with_a_row(array, rows)),
                    }
                )
                for name, array in model.coordinates.items()
            )
        )
        store.append(
            *(
                _dump(self._declaration(name, observable))
                for name, observable in model.observables.items()
            )
        )

        extents = model.dims
        for dim in model.row_dims:
            coordinates = model.coordinates_on(dim)
            observables = model.observables_on(dim)
            store.append(
                *(
                    _dump(self._row(dim, coordinates, observables, index))
                    for index in range(extents[dim])
                )
            )

    def read(self, store: JsonlObservableStore) -> ObservablesModel:
        coordinate_specs: dict[str, dict] = {}
        declarations: dict[str, dict] = {}
        gathered_coordinates: dict[str, list] = {}
        gathered_values: dict[str, list] = {}

        for line in store.lines():
            record = _parse(line)
            if record is None:
                continue
            kind = record.get("$")
            if kind == "coord":
                coordinate_specs[record["name"]] = record
            elif kind == "obs":
                declarations[record["name"]] = record
            elif kind == "row":
                for name, value in record.get("c", {}).items():
                    gathered_coordinates.setdefault(name, []).append(value)
                for name, value in record.get("v", {}).items():
                    gathered_values.setdefault(name, []).append(value)

        coordinates = {
            name: _array(
                spec,
                spec["data"] if "data" in spec else gathered_coordinates.get(name, []),
            )
            for name, spec in coordinate_specs.items()
        }

        return ObservablesModel(
            coordinates=coordinates,
            observables={
                name: self._rebuild(declaration, gathered_values.get(name, []))
                for name, declaration in declarations.items()
            },
        )

    def _declaration(self, name: str, observable: ObservableModel) -> dict[str, Any]:
        line: dict[str, Any] = {
            "$": "obs",
            "name": name,
            **_spec(observable.values, data=observable.leading_dim is None),
        }
        if observable.description is not None:
            line["description"] = observable.description
        if observable.payload is not None:
            line["payload"] = observable.payload
        if observable.source is not None:
            line["source"] = observable.source.model_dump(mode="json", exclude_none=True)
        return line

    def _row(
        self,
        dim: str,
        coordinates: dict[str, Array],
        observables: dict[str, ObservableModel],
        index: int,
    ) -> dict[str, Any]:
        return {
            "$": "row",
            "dim": dim,
            "c": {name: _plain(array.data[index]) for name, array in coordinates.items()},
            "v": {
                name: _plain(observable.values.data[index])
                for name, observable in observables.items()
            },
        }

    def _rebuild(self, declaration: dict, payload: list) -> ObservableModel:
        values = (
            _array(declaration, declaration["data"])
            if "data" in declaration
            else _array(declaration, payload)
        )
        source = declaration.get("source")
        return ObservableModel(
            values=values,
            source=Source.model_validate(source) if source is not None else None,
            payload=declaration.get("payload"),
            description=declaration.get("description"),
        )


def _advances_with_a_row(array: Array, rows: set[str]) -> bool:
    """A coordinate is carried by rows only when it is exactly one row dimension."""
    return len(array.dims) == 1 and array.dims[0] in rows


def _spec(array: Array, *, data: bool) -> dict[str, Any]:
    spec: dict[str, Any] = {"dims": list(array.dims), "dtype": array.dtype}
    if array.unit is not None:
        spec["unit"] = array.unit
    if data:
        spec["data"] = array.data.tolist()
    return spec


def _array(spec: dict, payload: Any) -> Array:
    data = np.array(payload, dtype=NUMPY_DTYPE[spec["dtype"]])
    return Array(
        dims=tuple(spec["dims"]),
        dtype=spec["dtype"],
        shape=data.shape,
        data=data,
        unit=spec.get("unit"),
    )


def _plain(value: Any) -> Any:
    """numpy scalars and slices are not JSON-serializable; their Python twins are."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value.item() if isinstance(value, np.generic) else value


def _dump(record: dict) -> str:
    return json.dumps(record, separators=(",", ":"))


def _parse(line: str) -> dict | None:
    """A blank or torn line is skipped, never fatal.

    A reader tailing a file a writer is still appending to will see a
    half-written last line; crashing on it would defeat the one job a WAL has.
    """
    if not line.strip():
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


@REGISTRY.binding
class JsonlObservableBinding(Binding):
    module: ClassVar[str] = "draft/observables"
    backend: ClassVar[str] = "jsonl"

    def new_store(self, workdir: Path) -> JsonlObservableStore:
        store = JsonlObservableStore(workdir)
        store.clear()
        return store

    def codec(self) -> JsonlObservableCodec:
        return JsonlObservableCodec()
