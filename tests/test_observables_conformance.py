"""The v1 ``observables`` section: the kind-based layout molrs writes.

The official codec passes its own suite; adapters broken in named ways --
one that drops unknown keys, one that rewrites an unknown kind -- fail
exactly the cases that pin them. A run that names no modules never judges
an implementation by the draft.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import zarr

import molrec
from molrec.observables.bindings.zarr import ZarrObservablesCodec, ZarrObservableStore


class CodecAdapter(molrec.ObservableAdapter):
    backends = ("zarr",)
    refusal_types = (ValueError,)

    def write(self, model: molrec.ObservablesModel, store: ZarrObservableStore) -> None:
        ZarrObservablesCodec().write(model, store)

    def read(self, store: ZarrObservableStore) -> Any:
        return ZarrObservablesCodec().read(store)


class DropsUnknownKeys(CodecAdapter):
    def read(self, store: ZarrObservableStore) -> Any:
        model = super().read(store)
        return molrec.ObservablesModel(
            observables={
                name: observable.model_copy(
                    update={
                        "meta": molrec.ObservableMetaModel(
                            **{
                                key: getattr(observable.meta, key)
                                for key in molrec.ObservableMetaModel.model_fields
                            }
                        )
                    }
                )
                for name, observable in model.observables.items()
            }
        )


class RewritesUnknownKinds(CodecAdapter):
    def read(self, store: ZarrObservableStore) -> Any:
        model = super().read(store)
        return molrec.ObservablesModel(
            observables={
                name: observable.model_copy(
                    update={
                        "meta": observable.meta.model_copy(
                            update={
                                "kind": observable.meta.kind
                                if observable.meta.kind in molrec.observables.KNOWN_KINDS
                                else "vector"
                            }
                        )
                    }
                )
                for name, observable in model.observables.items()
            }
        )


def _run(adapter: molrec.ObservableAdapter) -> molrec.Report:
    implementation = type(
        "Implementation", (molrec.Implementation,), {"name": "x", "observables": adapter}
    )()
    return molrec.ConformanceSuite(implementation, modules=["observables"]).run()


def test_the_official_codec_passes_its_own_suite() -> None:
    report = _run(CodecAdapter())
    assert report.ok, report.table()


def test_dropping_unknown_keys_is_caught() -> None:
    assert {r.case_id for r in _run(DropsUnknownKeys()).failures} == {
        "unknown-kind-and-keys-preserved"
    }


def test_rewriting_an_unknown_kind_is_caught() -> None:
    assert {r.case_id for r in _run(RewritesUnknownKinds()).failures} == {
        "unknown-kind-and-keys-preserved"
    }


def test_a_default_run_never_judges_by_the_draft() -> None:
    assert "draft/observables" not in molrec.REGISTRY.modules()
    assert "draft/observables" in molrec.REGISTRY.modules(drafts=True)
    implementation = type(
        "Implementation", (molrec.Implementation,), {"name": "x", "observables": CodecAdapter()}
    )()
    report = molrec.ConformanceSuite(implementation).run()
    assert {r.module for r in report.results} >= {"observables"}
    assert not any(r.module.startswith("draft/") for r in report.results)


def test_the_layout_is_meta_beside_data(tmp_path) -> None:
    store = ZarrObservableStore(tmp_path / "o.mrec")
    energy = molrec.ObservableModel(
        meta=molrec.ObservableMetaModel(
            kind="scalar", description="total energy", time_dependent=False, unit="eV"
        ),
        data=molrec.ArrayModel(dtype="f64", shape=(), values=np.array(-1.5)),
    )
    ZarrObservablesCodec().write(molrec.ObservablesModel(observables={"energy": energy}), store)
    root = zarr.open_group(store=store.path, mode="r")
    assert dict(root["observables/meta/energy"].attrs) == {
        "kind": "scalar",
        "description": "total energy",
        "time_dependent": False,
        "unit": "eV",
    }
    assert root["observables/energy"].shape == ()
    assert dict(root["meta"].attrs) == {"molrec_version": 1}


def test_an_observables_section_rides_in_a_record(tmp_path) -> None:
    from molrec.core.bindings.zarr import ZarrRecordCodec, ZarrRecordStore

    store = ZarrRecordStore(tmp_path / "r.mrec")
    record = molrec.RecordModel(
        meta=molrec.MetaModel(molrec_version=1),
        frame=molrec.FrameModel(),
        observables=molrec.ObservablesModel(
            observables={
                "energy": molrec.ObservableModel(
                    meta=molrec.ObservableMetaModel(
                        kind="scalar", description="e", time_dependent=False
                    ),
                    data=molrec.ArrayModel(dtype="f64", shape=(1,), values=np.array([1.0])),
                )
            }
        ),
    )
    ZarrRecordCodec().write(record, store)
    assert ZarrRecordCodec().read(store) == record
