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

from molrec import jsonvalue
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

        A torn tail -- the half-written last line a crash leaves -- is cut off
        first (the file is truncated to its last newline), so a new line is
        never glued onto it. Variadic because a live logger appends one line
        and a bulk writer appends thousands; reopening the file per line turns
        a settle into an O(n) syscall storm.
        """
        if not lines:
            return
        self._path.mkdir(parents=True, exist_ok=True)
        with self.wal.open("ab") as handle:
            end = handle.seek(0, 2)
            if end:
                with self.wal.open("rb") as reader:
                    content = reader.read()
                keep = content.rfind(b"\n") + 1
                if keep != end:
                    handle.truncate(keep)
            handle.write("".join(line + "\n" for line in lines).encode("utf-8"))

    def lines(self) -> list[str]:
        """Every complete line, decoded strictly as UTF-8.

        Only the unterminated tail is torn, and it is dropped; a complete line
        that is not UTF-8 is corruption, not a crash artefact, and is refused.
        """
        if not self.wal.exists():
            return []
        complete = self.wal.read_bytes().split(b"\n")[:-1]
        try:
            return [line.decode("utf-8") for line in complete]
        except UnicodeDecodeError as exc:
            raise ValueError(f"{self.wal}: a complete line is not UTF-8: {exc}") from None

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
            name: _array(spec, spec["data"])
            if "data" in spec
            else _array(spec, gathered_coordinates.get(name, []), rows=True)
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
            "c": {
                name: _encode(array.dtype, array.data[index]) for name, array in coordinates.items()
            },
            "v": {
                name: _encode(observable.values.dtype, observable.values.data[index])
                for name, observable in observables.items()
            },
        }

    def _rebuild(self, declaration: dict, payload: list) -> ObservableModel:
        values = (
            _array(declaration, declaration["data"])
            if "data" in declaration
            else _array(declaration, payload, rows=True)
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
    """An array's declaration line: dims, dtype, unit, and its full ``shape``
    -- the trailing axes of a row-carried array are known even when no row
    has arrived, so a zero-row vector still reads back ``(0, 3)``."""
    spec: dict[str, Any] = {
        "dims": list(array.dims),
        "dtype": array.dtype,
        "shape": list(array.shape),
    }
    if array.unit is not None:
        spec["unit"] = array.unit
    if data:
        spec["data"] = _encode(array.dtype, array.data)
    return spec


def _array(spec: dict, payload: Any, *, rows: bool = False) -> Array:
    """The array a declaration (and, for a row-carried one, its rows) spells."""
    dtype = spec["dtype"]
    values = [_decode(dtype, item) for item in payload] if rows else _decode(dtype, payload)
    shape = tuple(spec["shape"])
    if rows:
        shape = (len(payload), *shape[1:])
    data = np.array(values, dtype=NUMPY_DTYPE[dtype]).reshape(shape)
    return Array(
        dims=tuple(spec["dims"]), dtype=dtype, shape=shape, data=data, unit=spec.get("unit")
    )


def _encode(dtype: str, value: Any) -> Any:
    """One value (or a nested array of them) in the typed JSON form: NaN as
    ``"NaN"``, a complex as ``[re, im]``, an integer beyond 2^53 as a string."""
    if isinstance(value, np.ndarray):
        return [_encode(dtype, item) for item in value]
    return jsonvalue.encode(dtype, value)


def _decode(dtype: str, raw: Any) -> Any:
    """The inverse of :func:`_encode` for one value or a nested list of them."""
    complex_pair = dtype in ("c64", "c128") and _is_pair(raw)
    if isinstance(raw, list) and not complex_pair:
        return [_decode(dtype, item) for item in raw]
    return jsonvalue.decode(dtype, raw)


def _is_pair(raw: Any) -> bool:
    return isinstance(raw, list) and len(raw) == 2 and not any(isinstance(x, list) for x in raw)


def _dump(record: dict) -> str:
    return jsonvalue.dumps(record)


def _parse(line: str) -> dict | None:
    """A blank line is skipped; any other complete line is one JSON object.

    The torn tail a crash leaves never reaches here (:meth:`lines` drops the
    unterminated last line), so a complete line that does not parse is
    corruption and is refused rather than skipped.
    """
    if not line.strip():
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"a complete WAL line is not JSON: {exc}") from None
    if not isinstance(record, dict):
        raise ValueError("a WAL line is one JSON object")
    return record


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
