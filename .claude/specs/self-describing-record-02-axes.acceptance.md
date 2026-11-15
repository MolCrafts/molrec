---
slug: self-describing-record-02-axes
criteria:
  - id: ac-001
    summary: BlockModel accepts shape (2, 2, 2) with axes ("a", "b", "c")
    type: runtime
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_model.py::TestBlockModel
      passes a test that constructs count=8, structural_shape=(2, 2, 2),
      structural_axes=("a", "b", "c") and reads those two values back unchanged.
    status: pending
  - id: ac-002
    summary: BlockModel rejects unpaired or wrong-length structural_axes
    type: runtime
    pass_when: |
      TestBlockModel shows ValidationError for shape (2, 2, 2) with no axes,
      for axes ("a", "b", "c") with no shape, and for axes ("a", "b") with
      shape (2, 2, 2); a block with neither field set still constructs.
    status: pending
  - id: ac-003
    summary: SequenceBlockModel uses the same pairing and omits null axes
    type: runtime
    pass_when: |
      TestSequenceBlockModel accepts structural_shape=(2, 2, 2) with
      structural_axes=("a", "b", "c"), rejects the three unpaired cases, and
      model_dump(mode="json") omits structural_axes when it is None and
      emits ["a", "b", "c"] when set.
    status: pending
  - id: ac-004
    summary: Trajectory pin rejects a later frame with different axis names
    type: runtime
    pass_when: |
      TestTrajectoryModel fails construction when two frames share
      structural_shape (2, 2, 2) but one has axes ("a", "b", "c") and the
      other ("x", "y", "z"), and the ValidationError text contains
      structural_axes.
    status: pending
  - id: ac-005
    summary: Zarr frame group stores and returns structural_axes
    type: runtime
    pass_when: |
      TestWriteBlock sees group attribute structural_axes == ["a", "b", "c"]
      after write_block of the (2, 2, 2) grid and no such key on a block
      with no structural_shape; TestReadBlock read_block returns
      structural_axes == ("a", "b", "c").
    status: pending
  - id: ac-006
    summary: Trajectory sequence_schema and block group keep axis names
    type: runtime
    pass_when: |
      TestZarrTrajectoryCodec writes a grid with structural_axes
      ("a", "b", "c"); sequence_schema and the trajectory block-group
      attribute both carry ["a", "b", "c"], and read() restores
      structural_axes == ("a", "b", "c") on that block.
    status: pending
  - id: ac-007
    summary: LMDB frame header carries structural_axes beside the shape
    type: runtime
    pass_when: |
      TestFrameBytes encode_frame writes "structural_axes": null when axes
      are absent and ["a", "b", "c"] beside structural_shape [2, 2, 2]
      when set; decode_frame returns structural_axes == ("a", "b", "c").
    status: pending
  - id: ac-008
    summary: Normative chapters name structural_axes next to the shape
    type: docs
    pass_when: |
      docs/spec/frame.md, docs/spec/storage.md, docs/spec/ragged.md, and
      docs/spec/lmdb.md each contain the literal structural_axes in the
      same declaration as structural_shape (block tree, frame-shaped group,
      trajectory block plus sequence_schema, LMDB frame-header object).
    status: pending
  - id: ac-009
    summary: Exported block and sequence-schema schemas type structural_axes
    type: code
    pass_when: |
      schema/core/block.schema.json and
      schema/binding/sequence-schema.schema.json each list property
      structural_axes as an array of strings or null, and
      uv run --locked pytest -q tests/test_schema_export.py passes with no
      hand-edited drift.
    status: pending
  - id: ac-010
    summary: Schema fixtures accept paired axes and reject non-strings
    type: runtime
    pass_when: |
      fixtures/schema/core/block/valid-structural-axes.json and
      fixtures/schema/binding/sequence-schema/valid-structural-axes.json
      (shape [2, 2, 2], axes ["a", "b", "c"]) validate, and the two
      invalid-structural-axes-not-strings.json fixtures with axes [1, 2, 3]
      do not; tests/test_schema_fixtures.py passes.
    status: pending
  - id: ac-011
    summary: Regression round-trips the public model with hard-coded axes
    type: runtime
    pass_when: |
      uv run --locked python regressions/self-describing-record-02-axes.py
      exits 0. The script builds a FrameModel density block with
      structural_shape (2, 2, 2) and structural_axes ("a", "b", "c"),
      restores it via model_validate(model_dump(mode="json")), and asserts
      those two literals. It does not import molrs, zarr, or lmdb.
    status: pending
  - id: ac-012
    summary: Field docstrings say axis names are not quantities
    type: docs
    pass_when: |
      BlockModel.structural_axes and SequenceBlockModel.structural_axes in
      src/molrec/core/model.py each have a plain docstring stating the
      strings name structural_shape in order and are not units.
    status: pending
  - id: ac-013
    summary: Pure check and test suite pass without molrs
    type: runtime
    pass_when: |
      uvx ruff@0.16.5 format --check . && uvx ruff@0.16.5 check .
      exits 0, and uv run --locked pytest -q -m "not molrs" exits 0,
      including tests/test_layout_doc.py.
    status: pending
---

# Acceptance criteria

- ac-001：`BlockModel` 接受 `(2, 2, 2)` 与 `("a", "b", "c")`。
- ac-002：缺轴、无形状却有轴、长度不一致，三则都是 `ValidationError`；两者皆无则通过。
- ac-003：`SequenceBlockModel` 同一配对；JSON 省略 `None`，有轴时写出 `["a", "b", "c"]`。
- ac-004：同一形状、不同轴名的两帧不能钉成一条轨迹。
- ac-005：帧路径块组属性名是 `structural_axes`；无形状则没有该键。
- ac-006：轨迹的 `sequence_schema` 与块组属性都不丢 `["a", "b", "c"]`。
- ac-007：LMDB 帧头与 `structural_shape` 并列；无轴写 `null`。
- ac-008：四章规范正文把轴名写进与形状相同的声明。
- ac-009：块与 sequence-schema 的生成 schema 含字符串数组或 null，且与导出器一致。
- ac-010：配对 fixture 被接受，轴名为数字的 fixture 被拒绝。
- ac-011：回归脚本只走公开模型，硬编码 `(2, 2, 2)` 与 `("a", "b", "c")`。
- ac-012：字段文档写明轴名不是单位。
- ac-013：ruff 与 `pytest -q -m "not molrs"` 均为绿。molrs 伙伴不在本规格内。
