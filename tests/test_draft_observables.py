"""The draft (v2) observables: where the dimension model has to earn its keep.

Grid versus scatter, a shared axis versus two axes, a value dimension with no
coordinate -- these are the shapes two implementations most easily disagree
about, so each has a case and each has an adapter that gets it wrong on
purpose.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import molrec
from molrec.draft import observables as draft
from molrec.draft.observables.bindings.jsonl import JsonlObservableCodec, JsonlObservableStore
from molrec.draft.observables.bindings.zarr import ZarrObservableCodec, ZarrObservableStore
from molrec.draft.observables.suite import array
from molrec.safe_name import original_name, safe_name


class CodecObservableAdapter(draft.ObservableAdapter):
    """Delegates to whichever official codec the backend calls for."""

    backends = ("jsonl", "zarr")
    refusal_types = (ValueError,)

    def _codec(self, store):
        return JsonlObservableCodec() if store.backend == "jsonl" else ZarrObservableCodec()

    def write(self, model, store):
        self._codec(store).write(model, store)

    def read(self, store):
        return self._codec(store).read(store)


class DropsUnitsAdapter(CodecObservableAdapter):
    """Loses units -- a number without one is not a physical quantity."""

    def read(self, store):
        model = super().read(store)
        return model.model_copy(
            update={
                "observables": {
                    name: observable.model_copy(
                        update={"values": observable.values.model_copy(update={"unit": None})}
                    )
                    for name, observable in model.observables.items()
                }
            }
        )


class FlattensGridAdapter(CodecObservableAdapter):
    """Reads a grid as if it were a scatter, collapsing two dims into one."""

    def read(self, store):
        model = super().read(store)
        updated = {}
        for name, observable in model.observables.items():
            values = observable.values
            if len(values.dims) < 2:
                updated[name] = observable
                continue
            flat = values.data.reshape(-1)
            updated[name] = observable.model_copy(
                update={
                    "values": values.model_copy(
                        update={"dims": ("sample",), "shape": flat.shape, "data": flat}
                    )
                }
            )
        return model.model_copy(update={"observables": updated})


class DropsProvenanceAdapter(CodecObservableAdapter):
    """Discards where a derived quantity came from."""

    def read(self, store):
        model = super().read(store)
        return model.model_copy(
            update={
                "observables": {
                    name: observable.model_copy(update={"source": None})
                    for name, observable in model.observables.items()
                }
            }
        )


class DropsCoordinatesAdapter(CodecObservableAdapter):
    """Keeps the numbers and throws away what they are a function of."""

    def read(self, store):
        return super().read(store).model_copy(update={"coordinates": {}})


def _impl(name: str, adapter: draft.ObservableAdapter) -> molrec.Implementation:
    return type(name, (molrec.Implementation,), {"name": name, "version": "0", "obs": adapter})()


REFERENCE = _impl("molrec-codec", CodecObservableAdapter())


def _failed(report):
    return {result.case_id for result in report.failures}


def _run(adapter_name, adapter):
    return molrec.ConformanceSuite(
        _impl(adapter_name, adapter), modules=["draft/observables"]
    ).run()


def test_official_codecs_pass_on_both_backends():
    report = molrec.ConformanceSuite(REFERENCE, modules=["draft/observables"]).run()
    assert report.ok, report.table()
    assert {r.backend for r in report.results} == {"jsonl", "zarr"}


def test_dropping_units_is_caught():
    assert "md-thermo" in _failed(_run("drops-units", DropsUnitsAdapter()))


def test_collapsing_a_grid_into_a_scatter_is_caught():
    assert _failed(_run("flattens-grid", FlattensGridAdapter())) == {
        "free-energy-grid",
        "dimension-without-coordinate",
    }


def test_dropping_provenance_is_caught():
    assert _failed(_run("drops-provenance", DropsProvenanceAdapter())) == {
        "derived-with-provenance"
    }


def test_dropping_coordinates_is_caught():
    failed = _failed(_run("drops-coordinates", DropsCoordinatesAdapter()))
    assert "training-curve" in failed and "free-energy-grid" in failed


def test_a_shared_axis_is_stored_once(tmp_path):
    """The reason coordinates were hoisted to the section: no duplicate axes."""
    store = ZarrObservableStore(tmp_path / "o.zarr")
    ZarrObservableCodec().write(
        draft.ObservablesModel(
            coordinates={"step": array(("point",), [0, 1, 2], dtype="i64")},
            observables={
                f"train/m{index}": draft.ObservableModel(values=array(("point",), [0.9, 0.7, 0.5]))
                for index in range(50)
            },
        ),
        store,
    )
    root = store.root(mode="r")
    assert len(list(root["coordinates"].members())) == 1
    assert len(list(root["observables"].members())) == 50


def test_grid_and_scatter_are_distinguishable():
    """The distinction the whole dimension model exists to make."""
    grid = draft.ObservablesModel(
        coordinates={"phi": array(("phi",), [0.0, 1.0]), "psi": array(("psi",), [0.0, 1.0])},
        observables={"e": draft.ObservableModel(values=array(("phi", "psi"), np.zeros((2, 2))))},
    )
    scatter = draft.ObservablesModel(
        coordinates={
            "phi": array(("sample",), [0.0, 1.0]),
            "psi": array(("sample",), [0.0, 1.0]),
        },
        observables={"e": draft.ObservableModel(values=array(("sample",), [0.0, 0.0]))},
    )
    assert molrec.diff(grid, scatter) != ()


def test_a_dimension_cannot_be_two_lengths():
    with pytest.raises(ValueError, match="elsewhere"):
        draft.ObservablesModel(
            coordinates={"phi": array(("phi",), [0.0, 1.0, 2.0])},
            observables={"e": draft.ObservableModel(values=array(("phi",), [0.0, 1.0]))},
        )


def test_dims_are_derived_not_stored():
    model = draft.ObservablesModel(
        coordinates={"step": array(("point",), [0, 1, 2], dtype="i64")},
        observables={
            "dipole": draft.ObservableModel(values=array(("point", "component"), np.zeros((3, 3))))
        },
    )
    assert model.dims == {"point": 3, "component": 3}


@pytest.mark.parametrize("name", ["train/loss", "gpu/0/util", "损失/训练", "a.b-c_d", "%"])
def test_safe_name_is_reversible(name):
    encoded = safe_name(name)
    assert "/" not in encoded
    assert original_name(encoded) == name


def test_a_row_carries_every_observable_on_its_dimension(tmp_path):
    """A WAL row is a moment of the run, not a point of one curve."""
    store = JsonlObservableStore(tmp_path / "wal")
    JsonlObservableCodec().write(
        draft.ObservablesModel(
            coordinates={"step": array(("point",), [0, 1], dtype="i64")},
            observables={
                "train/loss": draft.ObservableModel(values=array(("point",), [0.9, 0.7])),
                "train/lr": draft.ObservableModel(values=array(("point",), [1e-3, 5e-4])),
            },
        ),
        store,
    )
    rows = [json.loads(line) for line in store.lines() if json.loads(line)["$"] == "row"]
    assert len(rows) == 2, "two steps, two rows -- not one row per curve per step"
    assert set(rows[0]["v"]) == {"train/loss", "train/lr"}
    assert rows[0]["c"] == {"step": 0}


def test_a_static_grid_axis_is_not_repeated_per_row(tmp_path):
    """A free-energy surface's psi axis is known up front; it is written once."""
    store = JsonlObservableStore(tmp_path / "wal")
    JsonlObservableCodec().write(
        draft.ObservablesModel(
            coordinates={
                "phi": array(("phi",), [0.0, 1.0, 2.0]),
                "psi": array(("psi",), [0.0, 1.0]),
            },
            observables={
                "free_energy": draft.ObservableModel(values=array(("phi", "psi"), np.zeros((3, 2))))
            },
        ),
        store,
    )
    coords = {
        json.loads(line)["name"]: json.loads(line)
        for line in store.lines()
        if json.loads(line)["$"] == "coord"
    }
    assert "data" in coords["psi"], "psi does not advance with rows; it is written whole"
    assert "data" not in coords["phi"], "phi advances with rows; it is filled in by them"


def _curve(values) -> draft.ObservablesModel:
    return draft.ObservablesModel(
        coordinates={"step": array(("point",), list(range(len(values))), dtype="i64")},
        observables={"train/loss": draft.ObservableModel(values=array(("point",), values))},
    )


def test_a_torn_tail_is_skipped_and_never_glued_onto(tmp_path):
    """The WAL exists to survive a crash; a half-written tail must not be fatal."""
    store = JsonlObservableStore(tmp_path / "wal")
    codec = JsonlObservableCodec()
    codec.write(_curve([0.9, 0.7]), store)
    with store.wal.open("ab") as handle:  # a crash mid-line: no newline
        handle.write(b'{"$":"row","dim":"point","c":{"step":2},"v":{"train/loss":0.')

    assert codec.read(store).observables["train/loss"].values.shape == (2,)

    store.append(codec_row := '{"$":"row","dim":"point","c":{"step":2},"v":{"train/loss":0.5}}')
    assert store.lines()[-1] == codec_row, "the torn tail was cut off, not glued onto"
    assert codec.read(store).observables["train/loss"].values.shape == (3,)


def test_a_corrupt_complete_line_is_refused(tmp_path):
    store = JsonlObservableStore(tmp_path / "wal")
    codec = JsonlObservableCodec()
    codec.write(_curve([0.9]), store)
    with store.wal.open("ab") as handle:
        handle.write(b"\xff\xfe not utf-8\n")
    with pytest.raises(ValueError, match="UTF-8"):
        codec.read(store)


def test_typed_values_survive_the_wal(tmp_path):
    """NaN, complex values and a zero-row vector keep their meaning in JSON."""
    store = JsonlObservableStore(tmp_path / "wal")
    model = draft.ObservablesModel(
        coordinates={"step": array(("point",), [0, 1], dtype="i64")},
        observables={
            "loss": draft.ObservableModel(values=array(("point",), [float("nan"), 0.5])),
            "phase": draft.ObservableModel(
                values=draft.Array(
                    dims=("point",),
                    dtype="c128",
                    shape=(2,),
                    data=np.array([1 + 2j, -1j], dtype="complex128"),
                )
            ),
        },
    )
    JsonlObservableCodec().write(model, store)
    assert JsonlObservableCodec().read(store) == model

    empty = draft.ObservablesModel(
        observables={
            "dipole": draft.ObservableModel(
                values=draft.Array(
                    dims=("frame", "component"),
                    dtype="f64",
                    shape=(0, 3),
                    data=np.zeros((0, 3)),
                )
            )
        }
    )
    JsonlObservableCodec().write(empty, store)
    assert JsonlObservableCodec().read(store).observables["dipole"].values.shape == (0, 3)


def test_zarr_stores_dims_on_each_array(tmp_path):
    store = ZarrObservableStore(tmp_path / "o.zarr")
    ZarrObservableCodec().write(
        draft.ObservablesModel(
            coordinates={
                "phi": array(("phi",), [0.0, 1.0, 2.0], "rad"),
                "psi": array(("psi",), [0.0, 1.0], "rad"),
            },
            observables={
                "free_energy": draft.ObservableModel(
                    values=array(("phi", "psi"), np.zeros((3, 2)), "kJ/mol")
                )
            },
        ),
        store,
    )
    root = store.root(mode="r")
    assert list(root["observables"]["free_energy"].attrs["dims"]) == ["phi", "psi"]
    assert root["observables"]["free_energy"].attrs["unit"] == "kJ/mol"
    assert list(root["coordinates"]["phi"].attrs["dims"]) == ["phi"]
