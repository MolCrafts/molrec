"""The harness must fail adapters that are broken -- including the lazy ways.

A harness that passes the reference codec proves only half of what it has to.
These adapters are each broken in one named way, and every one of them must
come out red: one that implements nothing, one that crashes, readers that
lean on the models to fill in what they dropped, writers that change a width.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest
from pydantic import BaseModel

import molrec
from molrec.core.bindings.zarr import ZarrFrameBinding, ZarrFrameCodec, ZarrFrameStore
from molrec.core.model import NUMPY_DTYPE, BlockModel, ColumnModel, FrameModel
from molrec.core.suite import FrameSuite
from molrec.refusal import as_refusal
from molrec.registry import REGISTRY
from molrec.report import Violation

MODULES = ["core", "record", "trajectory", "collection"]


def _codec(module: str, store: molrec.Store) -> molrec.Codec:
    return REGISTRY.bindings_for(module)[store.backend]().codec()


class CodecAdapter(molrec.Adapter):
    """The official codec, for whichever module a subclass binds it to."""

    backends: ClassVar[tuple[str, ...]] = ("zarr", "lmdb")
    refusal_types: ClassVar[tuple[type[Exception], ...]] = (ValueError,)

    def write(self, model: BaseModel, store: molrec.Store) -> None:
        _codec(self.module, store).write(model, store)

    def read(self, store: molrec.Store) -> Any:
        return _codec(self.module, store).read(store)


def _run(module: str, adapter_type: type[molrec.Adapter]) -> molrec.Report:
    adapter = type(f"{adapter_type.__name__}For{module}", (adapter_type,), {"module": module})()
    implementation = type(
        "Implementation", (molrec.Implementation,), {"name": "broken", "adapter": adapter}
    )()
    return molrec.ConformanceSuite(implementation, modules=[module]).run()


def _statuses(report: molrec.Report, direction: str | None = None) -> dict[str, str]:
    return {
        r.case_id: r.status for r in report.results if direction is None or r.direction == direction
    }


def _failed(report: molrec.Report, direction: str) -> set[str]:
    return {r.case_id for r in report.failures if r.direction == direction}


def _negatives(module: str) -> set[str]:
    suite = REGISTRY.suite_for(module)()
    return {case.id for case in suite.cases() if case.expect_violation}


# ---------------------------------------------------------------------------
# Adapters that implement nothing, or crash, pass nothing.
# ---------------------------------------------------------------------------


class RaisesNotImplemented(molrec.Adapter):
    backends: ClassVar[tuple[str, ...]] = ("zarr", "lmdb")
    refusal_types: ClassVar[tuple[type[Exception], ...]] = (ValueError,)

    def write(self, model: BaseModel, store: molrec.Store) -> None:
        raise NotImplementedError

    def read(self, store: molrec.Store) -> Any:
        raise NotImplementedError


class RaisesAttributeError(RaisesNotImplemented):
    def write(self, model: BaseModel, store: molrec.Store) -> None:
        return model.no_such_door  # type: ignore[attr-defined]

    def read(self, store: molrec.Store) -> Any:
        return store.no_such_door  # type: ignore[attr-defined]


class DeclaresItsDefectsRefusals(RaisesNotImplemented):
    """Declaring NotImplementedError a refusal does not make it one."""

    refusal_types: ClassVar[tuple[type[Exception], ...]] = (NotImplementedError,)


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize(
    "adapter_type", [RaisesNotImplemented, RaisesAttributeError, DeclaresItsDefectsRefusals]
)
def test_an_adapter_that_cannot_read_or_write_passes_nothing(
    module: str, adapter_type: type[molrec.Adapter]
) -> None:
    report = _run(module, adapter_type)

    assert report.results
    assert not report.ok
    assert "pass" not in _statuses(report).values(), report.table()
    negatives = {r.case_id: r.status for r in report.results if r.case_id in _negatives(module)}
    assert negatives, "the module has negative cases to run"
    assert set(negatives.values()) == {"error"}, report.table()


# ---------------------------------------------------------------------------
# Readers that lean on the models' normalizers.
# ---------------------------------------------------------------------------


def _fields(model: BaseModel, **update: Any) -> dict[str, Any]:
    """A model's own field values as a plain mapping -- a duck, not a model."""
    found = {name: getattr(model, name) for name in type(model).model_fields}
    found.update(update)
    return found


class DropsCarriedForwardBlocks(CodecAdapter):
    """Hands back only the blocks updated at each ordinal, not what carried forward."""

    def read(self, store: molrec.Store) -> Any:
        model = super().read(store)
        frames: list[FrameModel] = []
        previous: dict[str, BlockModel] = {}
        for frame in model.frames:
            updated = {
                name: block for name, block in frame.blocks.items() if previous.get(name) != block
            }
            frames.append(FrameModel.model_construct(blocks=updated, box=None, meta=frame.meta))
            previous = frame.blocks
        return _fields(model, frames=frames)


def test_a_reader_that_drops_carried_forward_blocks_fails() -> None:
    report = _run("trajectory", DropsCarriedForwardBlocks)

    assert {
        "constant-block",
        "block-appears-late",
        "omitted-block-carries-forward",
        "zero-row-update-is-present-and-empty",
    } <= _failed(report, "read"), report.table()
    assert not _failed(report, "write"), report.table()


class DropsFills(CodecAdapter):
    """Leaves a declared fill out of the frames that omitted the key."""

    def read(self, store: molrec.Store) -> Any:
        model = super().read(store)
        frames = [
            FrameModel.model_construct(
                blocks=frame.blocks,
                box=None,
                meta={
                    key: value
                    for key, value in frame.meta.items()
                    if not model.meta[key].has_fill or value != model.meta[key].fill
                },
            )
            for frame in model.frames
        ]
        return _fields(model, frames=frames)


def test_a_reader_that_drops_filled_values_fails() -> None:
    report = _run("trajectory", DropsFills)

    assert {"per-step-meta", "json-meta"} <= _failed(report, "read"), report.table()


class DropsBoxDefaults(CodecAdapter):
    """Hands back a cell's vectors only, leaving origin and boundary to the defaults."""

    def read(self, store: molrec.Store) -> Any:
        model = super().read(store)
        box = None if model.box is None else {"vectors": model.box.vectors}
        return _fields(model, box=box)


def test_a_reader_that_leaves_the_box_defaults_to_the_model_fails() -> None:
    report = _run("core", DropsBoxDefaults)

    assert _failed(report, "read") == {
        "block-named-meta",
        "triclinic-box",
        "undefined-cell",
        "undefined-cell-ignores-vectors",
    }, report.table()


class ReturnsAnEmptyFrame(CodecAdapter):
    def read(self, store: molrec.Store) -> Any:
        return FrameModel()


def test_a_reader_that_returns_an_empty_frame_for_everything_fails() -> None:
    report = _run("core", ReturnsAnEmptyFrame)

    positives = {case.id for case in FrameSuite().cases() if not case.expect_violation}
    read_negatives = {
        case.id
        for case in FrameSuite().cases()
        if case.expect_violation and case.rejects_on == "read"
    }
    assert _failed(report, "read") == (positives - {"empty-frame"}) | read_negatives, report.table()
    assert not _failed(report, "write")


# ---------------------------------------------------------------------------
# Writers that change a width.
# ---------------------------------------------------------------------------


def _recast(model: FrameModel, source: str, target: str) -> FrameModel:
    """The frame with every ``source`` column stored as ``target`` -- what a sloppy writer does."""
    numpy_target = np.dtype(NUMPY_DTYPE[target])
    blocks = {
        name: BlockModel.model_construct(
            count=block.count,
            structural_shape=block.structural_shape,
            columns={
                key: ColumnModel(
                    dtype=target, shape=column.shape, values=column.values.astype(numpy_target)
                )
                if column.dtype == source
                else column
                for key, column in block.columns.items()
            },
        )
        for name, block in model.blocks.items()
    }
    return FrameModel.model_construct(blocks=blocks, box=model.box, meta=model.meta)


class WidensU8Writer(CodecAdapter):
    def write(self, model: BaseModel, store: molrec.Store) -> None:
        super().write(_recast(model, "u8", "u64"), store)


class NarrowsI64Writer(CodecAdapter):
    def write(self, model: BaseModel, store: molrec.Store) -> None:
        super().write(_recast(model, "i64", "i32"), store)


def test_a_writer_that_widens_u8_fails() -> None:
    report = _run("core", WidensU8Writer)

    assert _failed(report, "write") == {"every-dtype", "no-silent-widening"}, report.table()
    assert not _failed(report, "read")


def test_a_writer_that_narrows_i64_fails() -> None:
    report = _run("core", NarrowsI64Writer)

    assert _failed(report, "write") == {
        "every-dtype",
        "block-named-meta",
        "unknown-names-preserved",
    }, report.table()
    assert not _failed(report, "read")


# ---------------------------------------------------------------------------
# What counts as a refusal.
# ---------------------------------------------------------------------------


def _result(report: molrec.Report, case_id: str, direction: str) -> molrec.CaseResult:
    [found] = [r for r in report.results if r.case_id == case_id and r.direction == direction]
    return found


class RefusesRowCounts(CodecAdapter):
    refusal_types: ClassVar[tuple[type[Exception], ...]] = ()

    def read(self, store: molrec.Store) -> Any:
        raise molrec.Refusal("count disagrees", kind="row_count_mismatch")


class RefusesForAnotherReason(RefusesRowCounts):
    def read(self, store: molrec.Store) -> Any:
        raise molrec.Refusal("unsupported", kind="unsupported_dtype")


class UndeclaredRefusals(CodecAdapter):
    """The codec refuses with ValueError, but the adapter never said so."""

    refusal_types: ClassVar[tuple[type[Exception], ...]] = ()


def test_a_typed_refusal_of_the_right_kind_passes() -> None:
    report = _run("core", RefusesRowCounts)

    assert _result(report, "reject-row-count-mismatch", "read").status == "pass"


def test_a_typed_refusal_of_the_wrong_kind_fails() -> None:
    report = _run("core", RefusesForAnotherReason)

    result = _result(report, "reject-row-count-mismatch", "read")
    assert result.status == "fail"
    assert [v.kind for v in result.violations] == ["wrong_refusal"]


def test_refusing_conforming_input_fails() -> None:
    report = _run("core", RefusesRowCounts)

    result = _result(report, "coordinates", "read")
    assert result.status == "fail"
    assert [v.kind for v in result.violations] == ["refused"]


def test_an_undeclared_exception_is_an_error_not_a_refusal() -> None:
    report = _run("core", UndeclaredRefusals)

    for case_id in _negatives("core"):
        assert _statuses(report)[case_id] == "error", report.table()


def test_refusal_translation() -> None:
    declared = (ValueError, KeyError)

    assert as_refusal(ValueError("no"), declared) is not None
    assert as_refusal(KeyError("no"), declared) is not None
    assert as_refusal(KeyError("no"), (ValueError,)) is None
    assert as_refusal(TypeError("no"), (TypeError,)) is None
    assert as_refusal(AttributeError("no"), (Exception,)) is None
    assert as_refusal(ValueError("no"), (Exception,)) is None

    class DtypeError(TypeError):
        """An implementation's own, deliberate refusal that happens to be a TypeError."""

    assert as_refusal(DtypeError("no"), (DtypeError,)) is not None
    assert as_refusal(TypeError("no"), (DtypeError,)) is None
    refusal = molrec.Refusal("no", kind="bad_version")
    assert as_refusal(refusal) is refusal


# ---------------------------------------------------------------------------
# A case the harness could not prepare, or judge, is an error -- never a pass.
# ---------------------------------------------------------------------------


class _OneCaseSuite(molrec.Suite):
    """Not registered: a suite built only to drive the harness."""

    module: ClassVar[str] = "core"
    model_type: ClassVar[type[FrameModel]] = FrameModel
    the_cases: ClassVar[tuple[molrec.Case, ...]] = ()

    def cases(self) -> Iterable[molrec.Case]:
        return self.the_cases


def _drive(suite_type: type[molrec.Suite], tmp_path: Path) -> list[molrec.CaseResult]:
    adapter = type("Codec", (CodecAdapter,), {"module": "core"})()
    return suite_type().run(adapter, ZarrFrameBinding(), tmp_path)


def _explode(store: ZarrFrameStore) -> None:
    raise RuntimeError("tamper broke")


def test_a_tamper_that_raises_is_an_error(tmp_path: Path) -> None:
    class Suite(_OneCaseSuite):
        the_cases = (
            molrec.Case(
                id="tampered",
                model=FrameModel(),
                expect_violation="anything",
                tamper=_explode,
            ),
        )

    [result] = _drive(Suite, tmp_path)
    assert result.status == "error"
    assert "tamper" in result.message


def test_a_store_the_codec_refuses_to_lay_down_is_an_error(tmp_path: Path) -> None:
    """The implementation was never shown the malformation, so it cannot have refused it."""

    class Suite(_OneCaseSuite):
        the_cases = (
            molrec.Case(
                id="unlayable",
                model=FrameModel.model_construct(
                    blocks={"box": BlockModel(count=0)}, box=None, meta={}
                ),
                expect_violation="reserved_block_name",
            ),
        )

    [result] = _drive(Suite, tmp_path)
    assert result.status == "error"


def test_a_comparison_that_crashes_costs_one_case(tmp_path: Path) -> None:
    class Suite(_OneCaseSuite):
        the_cases = tuple(c for c in FrameSuite().cases() if not c.expect_violation)[:2]

        def compare(self, expected: BaseModel, actual: Any) -> tuple[Violation, ...]:
            raise RuntimeError("comparison broke")

    results = _drive(Suite, tmp_path)
    assert len(results) == 4
    assert {r.status for r in results} == {"error"}


def test_the_read_direction_compares_before_validating(tmp_path: Path) -> None:
    """A duck the model would complete is still incomplete."""

    class Suite(_OneCaseSuite):
        the_cases = tuple(c for c in FrameSuite().cases() if c.id == "triclinic-box")

    class Adapter(CodecAdapter):
        module = "core"

        def read(self, store: molrec.Store) -> Any:
            model = ZarrFrameCodec().read(store)
            box = _fields(model.box)
            del box["cell_defined"]
            return _fields(model, box=box)

    read = [
        r for r in Suite().run(Adapter(), ZarrFrameBinding(), tmp_path) if r.direction == "read"
    ]
    assert [r.status for r in read] == ["fail"]
    assert [v.path for v in read[0].violations] == ["/box/cell_defined"]


# ---------------------------------------------------------------------------
# A run that judged nothing is not green.
# ---------------------------------------------------------------------------


class NoBackends(CodecAdapter):
    backends: ClassVar[tuple[str, ...]] = ()


def test_an_adapter_without_backends_is_an_error() -> None:
    report = _run("core", NoBackends)

    assert [r.status for r in report.results] == ["error"]
    assert not report.ok


def test_a_report_of_skips_only_is_not_ok() -> None:
    report = molrec.Report(
        implementation="x",
        version="0",
        results=(molrec.CaseResult(case_id="*", module="core", backend="", status="skip"),),
    )
    assert not report.ok
    assert not molrec.Report(implementation="x", version="0").ok
