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
    # The codec refuses malformed content with ValueError (pydantic's
    # ValidationError included).
    refusal_types = (ValueError,)

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


class WidensIntegersAdapter(CodecFrameAdapter):
    """Reads every i32 column back as i64 -- the classic silent widening."""

    def read(self, store: ZarrFrameStore) -> molrec.FrameModel:
        model = super().read(store)
        widened = {
            name: block.model_copy(
                update={
                    "columns": {
                        key: (
                            column.model_copy(
                                update={
                                    "dtype": "i64",
                                    "values": None
                                    if column.values is None
                                    else column.values.astype("int64"),
                                }
                            )
                            if column.dtype == "i32"
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


class WidensIntegers(molrec.Implementation):
    name = "widens-integers"
    version = "0"
    frame = WidensIntegersAdapter()


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
    assert [r.status for r in report.results] == ["skip"]
    assert not report.failures
    # ...but a run that judged nothing is not a green run either.
    assert not report.ok


def test_silent_integer_widening_is_caught():
    report = molrec.ConformanceSuite(WidensIntegers(), modules=["core"]).run()
    # canonical-topology: the image flags ix / iy / iz are i32.
    assert _failed_case_ids(report) == {"every-dtype", "no-silent-widening", "canonical-topology"}


def test_both_directions_run_for_every_positive_case():
    report = molrec.ConformanceSuite(Reference(), modules=["core"]).run()
    directions = {r.direction for r in report.results}
    assert directions == {"write", "read"}


# ---------------------------------------------------------------------------
# ac-029 -- the (suite x implementation) matrix, actually collected.
#
# The codec-only rows import nothing optional. The molrs rows reach the
# reference implementation through the ``molrs_implementation`` fixture in
# ``conftest.py`` (``pytest.importorskip``): absent molrs skips *only* them,
# and a stale molrs build fails them -- it never hides the codec-only rows.
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
    trajectory.
    """

    backends: ClassVar[tuple[str, ...]] = ("zarr", "lmdb")
    refusal_types: ClassVar[tuple[type[Exception], ...]] = (ValueError,)

    def _codec(self, store: molrec.Store) -> molrec.Codec:
        return REGISTRY.bindings_for(self.module)[store.backend]().codec()

    def write(self, model: BaseModel, store: molrec.Store) -> None:
        self._codec(store).write(model, store)

    def read(self, store: molrec.Store) -> Any:
        return self._codec(store).read(store)


def _codec_implementation(module: str) -> molrec.Implementation:
    bound = type(f"{module}CodecAdapter", (_CodecAdapter,), {"module": module})()
    return type(
        "MolrecCodec",
        (molrec.Implementation,),
        {"name": "molrec-codec", "version": molrec.__version__, "adapter": bound},
    )()


def _assert_clean(report: molrec.Report, module: str, implementation: str) -> None:
    assert report.results, f"module {module!r} registered no suite -- nothing ran"
    assert [r.status for r in report.results] != ["skip"], (
        f"{implementation} declares no adapter for module {module!r}"
    )
    assert report.ok, report.table()


CODEC_MATRIX = ["core", "record", TRAJECTORY_MODULE, "collection", "forcefield"]

#: ``core`` is deliberately absent: molrs ships no door for a bare frame at a
#: store root, and `tests/molrs_adapter.py` says so in as many words. The
#: frame cases reach molrs inside records instead.
MOLRS_MATRIX = ["record", TRAJECTORY_MODULE]


@pytest.mark.parametrize("module", CODEC_MATRIX)
def test_the_suite_runs_clean(module: str) -> None:
    """One (suite x molrec-codec) pair, run end to end with zero violations."""
    report = molrec.ConformanceSuite(_codec_implementation(module), modules=[module]).run()
    _assert_clean(report, module, "molrec-codec")


@pytest.mark.parametrize("module", MOLRS_MATRIX)
def test_molrs_runs_clean(module: str, molrs_implementation: molrec.Implementation) -> None:
    """One (suite x molrs) pair, run end to end with zero violations."""
    report = molrec.ConformanceSuite(molrs_implementation, modules=[module]).run()
    _assert_clean(report, module, "molrs")


def test_the_trajectory_suite_judges_the_trajectory_model() -> None:
    """The two symbols ac-029 adds, and the wiring between them."""
    from molrec.core.model import TrajectoryModel
    from molrec.core.suite import TrajectorySuite

    assert TrajectorySuite.module == TRAJECTORY_MODULE
    assert TrajectorySuite.model_type is TrajectoryModel
    assert REGISTRY.suite_for(TRAJECTORY_MODULE) is TrajectorySuite
    assert "zarr" in REGISTRY.bindings_for(TRAJECTORY_MODULE)
    assert list(TrajectorySuite().cases()), "a suite with no cases judges nothing"


def test_every_ragged_must_has_a_negative_case() -> None:
    """The MUSTs of ``docs/spec/ragged.md``, each pinned by a refusal case."""
    from molrec.core.suite import TrajectorySuite

    negatives = {case.id: case for case in TrajectorySuite().cases() if case.expect_violation}
    on_write = {name for name, case in negatives.items() if case.rejects_on == "write"}
    assert {
        "reject-reserved-block-name",
        "reject-reserved-column-name",
        "reject-undeclared-block",
        "reject-undeclared-column",
        "reject-undeclared-meta-key",
        "reject-omitted-meta-without-fill",
        "reject-duplicate-step",
        "reject-decreasing-step",
        "reject-time-gained-midway",
        "reject-time-dropped-midway",
        "reject-structural-shape-row-count",
    } <= on_write
    assert negatives["reject-non-monotonic-offset"].rejects_on == "read"
    assert negatives["reject-non-monotonic-offset"].tamper is not None


def test_molrs_reads_an_absent_boundary_as_all_periodic(tmp_path, molrs) -> None:
    """ac-030 (a), the molrs half -- the two implementations must agree.

    The store is built by hand because no model can produce it: ``BoxModel``
    materializes ``boundary`` on validation, and the codec then omits the
    array only at its default. A foreign writer can lay down a box group with
    no ``boundary`` at all, and the two implementations used to read it as
    two different physical systems -- periodic here, vacuum in Rust.

    The molrec-codec half of this claim is
    ``tests/test_core/test_bindings/test_zarr.py``.
    """
    path = tmp_path / "absent-boundary.mrec"
    root = zarr.open_group(store=path, mode="w")
    root.create_group("meta").attrs.update({"molrec_version": 1})
    frame = root.create_group("frame")

    atoms = frame.create_group("atoms")
    atoms.attrs["count"] = 1
    atoms.create_array("x", shape=(1,), dtype="float64")[...] = np.zeros(1)

    box = frame.create_group("box")
    box.create_array("vectors", shape=(3, 3), dtype="float64")[...] = np.eye(3)
    box.create_array("origin", shape=(3,), dtype="float64")[...] = np.zeros(3)
    assert "boundary" not in box, "the store under test must not carry the array"

    frame = molrs.io.read_mrec(path)
    assert [bool(flag) for flag in np.asarray(frame.box.pbc)] == [True, True, True]


def test_molrs_declares_only_real_cases_unsupported(molrs_implementation) -> None:
    """Every case id the molrs adapter declares out of scope is a case of its
    module, so a typo cannot silently skip nothing (or the wrong thing)."""
    for module, adapter in molrs_implementation.adapters().items():
        known = {case.id for case in REGISTRY.suite_for(module)().cases()}
        assert set(adapter.unsupported) <= known, sorted(set(adapter.unsupported) - known)
