"""The harness has to be held to the same standard it enforces.

Two adapters run the core suite: one that delegates to the official codec and
must pass everything, and one deliberately broken in named ways that must
fail exactly those cases and no others. Without the second, a harness that
silently passes everything would look healthy.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pytest
import zarr
from pydantic import BaseModel

import molrec
from molrec.core.bindings.zarr import ZarrFrameCodec, ZarrFrameStore
from molrec.registry import REGISTRY


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
    assert _failed_case_ids(report) == {"structural-shape"}


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


# ---------------------------------------------------------------------------
# ac-029 -- the (suite x implementation) matrix, actually collected.
#
# Two holes closed here. `tests/molrs_adapter.py` was imported by no collected
# test, so molrs was never judged by the suite that exists to judge it; and
# there was no trajectory suite at all, so the section `docs/spec/trajectory.md`
# specifies was pinned by nothing.
#
# The imports that can fail -- `molrs` and the trajectory symbols -- are made
# inside test bodies deliberately. At module level either one turns this file
# into a collection error, which would hide the tests above instead of failing
# the tests below.
# ---------------------------------------------------------------------------

#: The registry key the trajectory suite claims. `docs/spec/trajectory.md`
#: names the section `trajectory`, so its suite registers under that name just
#: as the frame suite registers under `core` and the record suite under
#: `record`. Asserted against the symbol rather than trusted.
TRAJECTORY_MODULE = "trajectory"


class _CodecAdapter(molrec.Adapter):
    """molrec judged against itself, for whichever module it is bound to.

    The codec is fetched from the registry by ``(module, backend)`` rather
    than imported by class name, so one adapter serves core, record and
    trajectory -- and no test here pins a binding class name that the
    trajectory binding has not been given yet.
    """

    backends: ClassVar[tuple[str, ...]] = ("zarr",)

    def _codec(self, store: molrec.Store) -> molrec.Codec:
        return REGISTRY.bindings_for(self.module)[store.backend]().codec()

    def write(self, model: BaseModel, store: molrec.Store) -> None:
        self._codec(store).write(model, store)

    def read(self, store: molrec.Store) -> Any:
        return self._codec(store).read(store)


def _implementation(name: str, module: str) -> molrec.Implementation:
    if name == "molrs":
        # pytest puts `tests/` on sys.path, so the sibling adapter module is
        # importable by name. This import is the whole point of ac-029.
        import molrs_adapter

        return molrs_adapter.Molrs()

    bound = type(f"{module}CodecAdapter", (_CodecAdapter,), {"module": module})()
    return type(
        "MolrecCodec",
        (molrec.Implementation,),
        {"name": "molrec-codec", "version": molrec.__version__, "adapter": bound},
    )()


#: ("core", "molrs") is deliberately absent: molrs ships no door for a bare
#: frame at a store root, and `tests/molrs_adapter.py` says so in as many
#: words. The frame cases reach molrs inside records instead.
MATRIX = [
    ("core", "molrec-codec"),
    ("record", "molrec-codec"),
    (TRAJECTORY_MODULE, "molrec-codec"),
    ("record", "molrs"),
    (TRAJECTORY_MODULE, "molrs"),
]


@pytest.mark.parametrize(("module", "implementation"), MATRIX, ids=lambda value: value)
def test_the_suite_runs_clean(module: str, implementation: str) -> None:
    """One (suite x implementation) pair, run end to end with zero violations."""
    report = molrec.ConformanceSuite(
        _implementation(implementation, module), modules=[module]
    ).run()

    assert report.results, f"module {module!r} registered no suite -- nothing ran"
    assert [r.status for r in report.results] != ["skip"], (
        f"{implementation} declares no adapter for module {module!r}"
    )
    assert report.ok, report.table()


def test_the_trajectory_suite_judges_the_trajectory_model() -> None:
    """The two symbols ac-029 adds, and the wiring between them."""
    from molrec.core.model import TrajectoryModel
    from molrec.core.suite import TrajectorySuite

    assert TrajectorySuite.module == TRAJECTORY_MODULE
    assert TrajectorySuite.model_type is TrajectoryModel
    assert REGISTRY.suite_for(TRAJECTORY_MODULE) is TrajectorySuite
    assert "zarr" in REGISTRY.bindings_for(TRAJECTORY_MODULE)
    assert list(TrajectorySuite().cases()), "a suite with no cases judges nothing"


def test_molrs_reads_an_absent_boundary_as_all_periodic(tmp_path) -> None:
    """ac-030 (a), the molrs half -- the two implementations must agree.

    The store is built by hand because no model can produce it: ``BoxModel``
    materializes ``boundary`` on validation, so the suite structurally cannot
    lay down a box group without the attribute. A foreign writer can, and the
    two implementations used to read it as two different physical systems --
    periodic here, vacuum in Rust.

    The molrec-codec half of this claim is
    ``tests/test_core/test_bindings/test_zarr.py``.
    """
    import molrs

    path = tmp_path / "absent-boundary.mrec"
    root = zarr.open_group(store=path, mode="w")
    root.create_group("meta").attrs.update({"record_schema_version": 1, "format_name": "mrec"})
    frame = root.create_group("frame")

    atoms = frame.create_group("atoms")
    atoms.attrs["count"] = 1
    atoms.create_array("x", shape=(1,), dtype="float64")[...] = np.zeros(1)

    box = frame.create_group("box")
    box.create_array("vectors", shape=(3, 3), dtype="float64")[...] = np.eye(3)
    box.create_array("origin", shape=(3,), dtype="float64")[...] = np.zeros(3)
    assert "boundary" not in box.attrs, "the store under test must not carry the attribute"

    record = molrs.io.mrec.read_record(str(path))
    assert [bool(flag) for flag in np.asarray(record.frame.box.pbc)] == [True, True, True]
