"""The harness has to be held to the same standard it enforces.

Two adapters run the core suite: one that delegates to the official codec and
must pass everything, and one deliberately broken in named ways that must
fail exactly those cases and no others. Without the second, a harness that
silently passes everything would look healthy.
"""

from __future__ import annotations

import molrec
from molrec.core.bindings.zarr import ZarrFrameCodec, ZarrFrameStore


class CodecFrameAdapter(molrec.FrameAdapter):
    """Delegates to the official codec -- the self-check."""

    backends = ("zarr",)

    def write(self, model: molrec.FrameModel, store: ZarrFrameStore) -> None:
        ZarrFrameCodec().write(model, store)

    def read(self, store: ZarrFrameStore) -> molrec.FrameModel:
        return ZarrFrameCodec().read(store)


class DropsUnknownAdapter(CodecFrameAdapter):
    """Silently discards a block whose name it does not recognize."""

    UNRECOGNIZED = "nobody_knows_this_block"

    def read(self, store: ZarrFrameStore) -> molrec.FrameModel:
        model = super().read(store)
        kept = {name: block for name, block in model.blocks.items() if name != self.UNRECOGNIZED}
        return model.model_copy(update={"blocks": kept})


class WidensFloatsAdapter(CodecFrameAdapter):
    """Reads every float column back as f64 -- the classic silent widening."""

    def read(self, store: ZarrFrameStore) -> molrec.FrameModel:
        model = super().read(store)
        widened = {
            name: block.model_copy(
                update={
                    "columns": {
                        key: (
                            column.model_copy(
                                update={
                                    "dtype": "f64",
                                    "values": None
                                    if column.values is None
                                    else column.values.astype("float64"),
                                }
                            )
                            if column.dtype in ("f16", "f32")
                            else column
                        )
                        for key, column in block.columns.items()
                    }
                }
            )
            for name, block in model.blocks.items()
        }
        return model.model_copy(update={"blocks": widened})


class FlattensGridAdapter(CodecFrameAdapter):
    """Loses the structural shape, so a grid reads back unreshapable."""

    def read(self, store: ZarrFrameStore) -> molrec.FrameModel:
        model = super().read(store)
        flattened = {
            name: block.model_copy(update={"structural_shape": None})
            for name, block in model.blocks.items()
        }
        return model.model_copy(update={"blocks": flattened})


class Reference(molrec.Implementation):
    name = "molrec-codec"
    version = molrec.__version__
    frame = CodecFrameAdapter()


class DropsUnknown(molrec.Implementation):
    name = "drops-unknown"
    version = "0"
    frame = DropsUnknownAdapter()


class FlattensGrid(molrec.Implementation):
    name = "flattens-grid"
    version = "0"
    frame = FlattensGridAdapter()


class WidensFloats(molrec.Implementation):
    name = "widens-floats"
    version = "0"
    frame = WidensFloatsAdapter()


def _failed_case_ids(report: molrec.Report) -> set[str]:
    return {result.case_id for result in report.failures}


def test_official_codec_passes_its_own_suite():
    report = molrec.ConformanceSuite(Reference(), modules=["core"]).run()
    assert report.ok, report.table()
    assert report.results, "the suite ran nothing"


def test_dropping_an_unknown_block_is_caught():
    report = molrec.ConformanceSuite(DropsUnknown(), modules=["core"]).run()
    assert _failed_case_ids(report) == {"unknown-names-preserved"}


def test_losing_the_structural_shape_is_caught():
    report = molrec.ConformanceSuite(FlattensGrid(), modules=["core"]).run()
    assert _failed_case_ids(report) == {"structural-shape", "block-mesh"}


def test_a_module_without_an_adapter_is_skipped_not_failed():
    class Nothing(molrec.Implementation):
        name = "nothing"
        version = "0"

    report = molrec.ConformanceSuite(Nothing(), modules=["core"]).run()
    assert report.ok
    assert [r.status for r in report.results] == ["skip"]


def test_silent_float_widening_is_caught():
    report = molrec.ConformanceSuite(WidensFloats(), modules=["core"]).run()
    assert _failed_case_ids(report) == {"every-dtype", "no-silent-widening"}


def test_both_directions_run_for_every_positive_case():
    report = molrec.ConformanceSuite(Reference(), modules=["core"]).run()
    directions = {r.direction for r in report.results}
    assert directions == {"write", "read"}
