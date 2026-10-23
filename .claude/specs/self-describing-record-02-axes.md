---
title: 块的结构轴名
status: approved
created: 2026-10-09
---

# 块的结构轴名

## Summary

带 `structural_shape` 的块必须在同一声明里给出同长度的 `structural_axes`：一组字符串，按形状从左到右为每一秩命名。没有形状就不得有轴名。模型拒绝缺轴、多轴和长度不一致；Zarr 块组属性、轨迹的 `sequence_schema` 与块组属性、LMDB 帧头都跟形状走同一条路，往返不得丢掉轴名。列的 dtype 仍然不携带轴义，单位、kind 与 observables 不动。

## Design

轴名是块级声明，不是列，也不是列的 trailing 轴。`structural_shape[i]` 由 `structural_axes[i]` 命名。名字只是字符串标识，不是物理量，不带单位，不解释成 x/y/z 词汇，也不跟列名对齐。块拥有这对字段；模型冻结后不再改写。codec 只负责照形状已有的路径抄出去、再抄回来，不另起一组数组或一种新节。

`BlockModel` 与 `SequenceBlockModel` 各增加字段 `structural_axes: tuple[str, ...] | None = None`，默认 `None`。配对在两边的既有 `model_validator` 里完成（块侧是 `_columns_share_the_count`，声明侧是 `_targets_are_declared_u64_columns`），可以抽一个模块私有函数供两处调用，但不新设公开类型，也不把轴名做成第二套形状：

- `structural_shape is None` 且 `structural_axes is not None` → `ValueError`，文案含 `structural_axes` 与 “requires structural_shape”。
- `structural_shape is not None` 且 `structural_axes is None` → `ValueError`，文案含 `structural shape`、该形状，以及 “requires structural_axes”。
- 两者都有但 `len(structural_axes) != len(structural_shape)` → `ValueError`，文案含两边的长度。
- 元素不是 `str` 时由字段类型拒绝，不另写一套解析。

构造器抛出的是 `pydantic.ValidationError`（内部为上述 `ValueError`），与今天形状乘积对不上 `count` 的报错方式相同。形状乘积必须等于 `count` 的旧规则不变。`model_construct` 仍绕过校验并套用默认值，因此只写了 `structural_shape=None`、没写轴的旁路构造保持「两者皆无」，不必逐一改。

`declare_block` 在拷贝 `structural_shape` 的同一处拷贝 `structural_axes`。`same_bits` 在比较 `structural_shape` 的同一布尔式里比较 `structural_axes`：只改轴名也是另一次呈现。轨迹钉住声明时，现有的 `presented.structural_shape != pinned.structural_shape` 旁增加轴名不等即 `ValueError`（文案含块名与两边的 `structural_axes`）。对齐块已经禁止 `structural_shape`；没有形状就不可能有轴，对齐规则不另写。力场表禁止形状，因此也到不了轴名。

四条持久化路径与 `structural_shape` 今天的拼法相同，属性名 / 键名都是 `structural_axes`：

- 帧路径块组（`write_block` / `read_block`，`system` 与 `forcefield` 表也走这里）：常量 `STRUCTURAL_AXES_ATTR = "structural_axes"`，紧挨 `STRUCTURAL_SHAPE_ATTR`。非 `None` 时写成 JSON 字符串数组；`None` 时不写该属性（不写 `null`）。读回 `attrs.pop` 后收成 `tuple`，与形状一样。
- 轨迹：`SequenceBlockModel` 是 `DocumentModel`，`None` 不进入 `sequence_schema` 的 `model_dump`。形状与轴名要么一起出现在 `sequence_schema.blocks.<name>`，要么一起缺席。轨迹块组属性在 `_write_block` 写 `structural_shape` 的同一 `attrs` 里写轴名；`_resolve` 在把 `structural_shape` 填进每个 update 的同一处填轴名。只放进 `sequence_schema`、不放进块组，读回的 `BlockModel` 会因有形状无轴而失败。
- LMDB 帧头：`encode_frame` 在每个块对象里、`structural_shape` 键旁写 `structural_axes`。与形状相同，键始终存在：无轴时 JSON `null`，有轴时为字符串数组。`decode_frame` 用 `entry.get("structural_axes")`，缺键视为 `None`（旧字节仍能解码）。无形状的旧帧头因此仍合法；有形状却无轴的旧字节在建成 `BlockModel` 时按上面的 `ValueError` 拒绝。1.0 前无版本、无迁移。

Zarr 往返指帧路径 `write_block`/`read_block`，以及轨迹 codec 的 `write`/`read`：读回的模型上 `structural_axes == ("a", "b", "c")` 当写入为此时。列 trailing 轴仍然匿名。

本改动让所有非空 `structural_shape` 的现成构造在校验期失败，因此这些调用点要带上同秩轴名，并从「按字段重造块」的 `_recast` 里把轴名一并拷上，否则官方 codec 读回该帧时会因缺轴拒绝，纯测试套件变红。`docs/layout.md` 的生成树由这些模型写出，必须重生成，不能手改树。

### Reuse decision

- generalize `BlockModel.structural_shape`：轴名接在该字段已有的模型校验、`declare_block`、`same_bits` 与轨迹钉住比较上，不新造块类型或第二套形状字段。
- generalize `SequenceBlockModel.structural_shape`：同一字段在声明模型、`sequence_schema` 的文档序列化，以及轨迹块组属性上带上 `structural_axes`；不另写一条声明路径。

## Files to create or modify

- `docs/spec/frame.md`
- `docs/spec/storage.md`
- `docs/spec/ragged.md`
- `docs/spec/lmdb.md`
- `docs/layout.md`
- `src/molrec/core/model.py`
- `src/molrec/core/bindings/zarr.py`
- `src/molrec/core/bindings/lmdb.py`
- `src/molrec/core/suite.py`
- `src/molrec/core/bench.py`
- `scripts/layout_examples.py`
- `schema/core/block.schema.json`
- `schema/core/frame.schema.json`
- `schema/core/trajectory.schema.json`
- `schema/core/record.schema.json`
- `schema/core/collection.schema.json`
- `schema/core/forcefield.schema.json`
- `schema/binding/sequence-schema.schema.json`
- `fixtures/schema/core/block/valid-structural-axes.json` (new)
- `fixtures/schema/core/block/invalid-structural-axes-not-strings.json` (new)
- `fixtures/schema/binding/sequence-schema/valid-structural-axes.json` (new)
- `fixtures/schema/binding/sequence-schema/invalid-structural-axes-not-strings.json` (new)
- `tests/test_core/test_model.py`
- `tests/test_core/test_bindings/test_zarr.py`
- `tests/test_core/test_bindings/test_lmdb.py`
- `tests/test_suite_harness.py`
- `regressions/self-describing-record-02-axes.py` (new)

## Tasks

- [ ] Write failing unit tests for the structural_axes pairing in tests/test_core/test_model.py (TestBlockModel, TestSequenceBlockModel, TestTrajectoryModel), tests/test_core/test_bindings/test_zarr.py (TestWriteBlock, TestReadBlock, TestZarrTrajectoryCodec), and tests/test_core/test_bindings/test_lmdb.py (TestFrameBytes)
- [ ] Generalize BlockModel.structural_shape and SequenceBlockModel.structural_shape in src/molrec/core/model.py to require and copy structural_axes
- [ ] Generalize the structural_shape attribute path in src/molrec/core/bindings/zarr.py to carry structural_axes on frame groups and trajectory block groups
- [ ] Generalize the structural_shape frame-header field in src/molrec/core/bindings/lmdb.py to carry structural_axes
- [ ] State structural_axes beside structural_shape in docs/spec/frame.md, docs/spec/storage.md, docs/spec/ragged.md, and docs/spec/lmdb.md
- [ ] Pass structural_axes at existing non-null grids in src/molrec/core/suite.py, src/molrec/core/bench.py, scripts/layout_examples.py, tests/test_core/test_model.py, and tests/test_suite_harness.py, then regenerate docs/layout.md
- [ ] Add docstring per plain style on structural_axes in src/molrec/core/model.py stating the names are identifiers with no units
- [ ] Regenerate schema via python -m molrec.schema_export schema and add the four structural_axes fixtures under fixtures/schema/core/block and fixtures/schema/binding/sequence-schema
- [ ] Add regression example regressions/self-describing-record-02-axes.py (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

单元测试只打一个模块里的一个函数或方法。单测命令是 `uv run --locked pytest -q tests/<file>.py::<test>`。不在 `tests/` 下加端到端套件。

- `tests/test_core/test_model.py` → `TestBlockModel`：`BlockModel` 的校验器。快乐路径是 `count=8`、`structural_shape=(2, 2, 2)`、`structural_axes=("a", "b", "c")`、一列 `rho`（`f64`，`shape=(8,)`，`values` 可空）构造成功，两字段等于这两个字面量。边界：只有形状、只有轴名、`("a", "b")` 配 `(2, 2, 2)`，三处均为 `ValidationError`。无形状且无轴的普通表仍然成功，`structural_axes is None`。
- 同文件 → `TestSequenceBlockModel`：对 `SequenceBlockModel` 重复上述四则（快乐路径加三则拒绝）。`model_dump(mode="json")` 在无轴时不含 `structural_axes` 键，在快乐路径时该键为 `["a", "b", "c"]`。
- 同文件 → `TestTrajectoryModel`：两帧同一 `(2, 2, 2)`，轴名分别为 `("a", "b", "c")` 与 `("x", "y", "z")`，构造 `TrajectoryModel` 失败且信息含 `structural_axes`。既有 `test_structural_shape_fixes_the_row_count` 改为在两格上带同秩轴名，失败原因仍是行数被形状钉住。
- `tests/test_core/test_bindings/test_zarr.py` → `TestWriteBlock.test_write_block`：网格写入后块组属性 `structural_axes` 为 `["a", "b", "c"]`，且无形状的块组没有这个属性键。→ `TestReadBlock.test_read_block`：同一网格 `read_block` 得到 `("a", "b", "c")`。→ `TestZarrTrajectoryCodec`：`write` 后 `sequence_schema` 与该块组属性都有这三名；`read` 回到的对应块上 `structural_axes == ("a", "b", "c")`。
- `tests/test_core/test_bindings/test_lmdb.py` → `TestFrameBytes`：`encode_frame` 的块对象在无轴时含 `"structural_axes": null`，在网格时为 `["a", "b", "c"]` 且与 `structural_shape` 并列；`decode_frame` 还原为 `("a", "b", "c")`。
- JSON Schema 只描述类型（字符串数组或 null），不编码配对。配对只由模型保证，与形状乘积不进 schema 的现状相同。`valid-structural-axes.json` 使用 `[2, 2, 2]` 与 `["a", "b", "c"]`；`invalid-structural-axes-not-strings.json` 把轴写成 `[1, 2, 3]`，jsonschema 拒绝。既有 `structural_shape: null` 且不带轴的 fixture 仍然合法。
- 回归例 `regressions/self-describing-record-02-axes.py`：只通过 `molrec.core.model` 的 `FrameModel` / `BlockModel` / `ColumnModel`。帧内一块 `density`，`structural_shape=(2, 2, 2)`，`structural_axes=("a", "b", "c")`，`count=8`。`FrameModel.model_validate(frame.model_dump(mode="json"))` 之后，这两字段仍是这两个字面量。脚本注释写明无第三方 oracle、无 molrs。不导入 zarr、lmdb 或 molrs。

全套检查是 `uvx ruff@0.16.5 format --check . && uvx ruff@0.16.5 check .`，以及 `uv run --locked pytest -q -m "not molrs"`。布局漂移由 `tests/test_layout_doc.py` 覆盖：密度块的生成树里出现 `structural_axes`。

## Out of scope

- 不改单位、kind、observables，也不采纳 draft observables。不给列的 trailing 轴命名，不改 dtype、precision、targets、validity、`aligned_with`。
- 不规定轴名词汇，不拒绝空串或重复名。秩 0 的空形状不单独立例。
- 不引入 schema 版本或旧字节迁移。有形状无轴的旧字节直接被模型拒绝。
- 不改 molrs，也不改 `tests/molrs_adapter.py`。伙伴还没有轴名的读写口；带形状的一致性用例经 molrs 往返会在读回校验失败。本规格的单测与回归不启动 molrs。
- 不手改 `schema/`。导出器会改写内联了 `BlockModel` / `SequenceBlockModel` 的已发布 schema；只提交导出结果。
