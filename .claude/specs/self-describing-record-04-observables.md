---
title: 自描述记录：用 dims 替换 observables 契约
status: approved
created: 2026-10-09
---

# 自描述记录：用 dims 替换 observables 契约

## Summary

`observables` 改为 dims 契约：一节里的坐标只存一份，维名与形状是同一事实，`kind` 与 `time_dependent` 退出契约。参考绑定只保留 Zarr，`coordinates/` 与 `observables/` 在根上并列，`dims` 与 `unit` 写在数组属性上。这是替换，不是两套并存。1.0 之前没有版本键，也没有迁移：读到旧的 `observables/meta/<name>` + `kind` 布局就拒绝，不把它转换成新布局。不点名模块的一致性运行判定的是这套 dims 布局，不再把它当成 `draft/` 跳过。

## Design

散文是规范，模型跟着散文，schema 只由导出器从模型生成。不手改 `schema/`。记录不带 schema 版本，读端不提供把旧布局改写成新布局的函数。

模型树从 `src/molrec/draft/observables/model.py` 原样升到 `src/molrec/observables/model.py`，替换该文件里的 kind 契约。升上去的符号仍叫 `Array`、`Source`、`ObservableModel`、`ObservablesModel`。不要另写一套同义类型，也不要把 `Array` 改名为 `ArrayModel`（那个名字属于 `molrec.core.model.ArrayModel`，继续只给未识别子树的 `ArrayNodeModel` 用）。删除并不再导出 `KNOWN_KINDS`、`OBSERVABLES_META_GROUP`、`check_observable_name`、`ObservableMetaModel`。

`Array` 仍是 frozen pydantic：`dims: tuple[str, ...]`、`dtype`（现有闭集 `DType`）、`shape`、`data`（`molrec.arrays.NdArray`）、`unit: str | None`。构造时 `_shape_dims_and_dtype_agree` 要求 `len(dims) == len(shape)`、`data.shape == shape`、`values_dtype(data) == dtype`，否则 `ValueError`。`extent` 仍是 `{维名: 长度}`。`unit` 是调用方给的单位字符串，照写照读，不换算，也不走列 `unit` 的规则。未设置则模型里是 `None`，Zarr 属性里不写这个键。0 维数组（`dims=()` 且 `shape=()`）合法。

`ObservableModel` 仍是 `extra="forbid"`：只有 `values: Array`、可选 `source: Source`、可选 `payload: str`、可选 `description: str`。它自己不携带坐标。`dims` 与 `leading_dim` 从 `values` 派生。`Source` 仍是 `DocumentModel`（未知键照单保留），字段仍是 `refs` 与 `method_ref`。来源是沿革，不是分类。

`ObservablesModel` 仍是 `extra="forbid"`：`coordinates: dict[str, Array]` 与 `observables: dict[str, ObservableModel]`。`dims` 只由数组现算，不入库，因此 `model_dump` 没有 `dims` 键。`_dimensions_are_consistent` 要求同一维名在全节只有一个长度，冲突时 `ValueError`（沿用草案的措辞：维名、已见长度、当前长度、标签）。`coordinates_on`、`observables_on`、`row_dims` 随类迁入，但是结构查询，不是 WAL API。坐标与观测量是两个名字空间，可以同名。节点名继续交给已有的 `safe_name` / `original_name`（metrics 系列那条百分号编码），不新写编码器。

生命周期：`RecordModel.observables is None` 表示这一节不存在，记录根上既不写 `coordinates/` 也不写 `observables/`。`ObservablesModel()`（两个映射都空）表示节存在且为空，两个组都写出来。读端在两个组都不存在时得到 `None`；只有其中一个时仍构成模型，缺的那一侧是空映射。模型不碰存储。

参考绑定只升 Zarr，类名保持规范侧已有的 `ZarrObservablesCodec`、`ZarrObservableStorage`、`ZarrObservableBinding`。`ZarrObservableBinding.module` 仍是 `"observables"`，`backend` 仍是 `"zarr"`，`new_storage` 仍用 `*.mrec` 后缀，不用草案的 `*.zarr`。行为以草案 `ZarrObservableCodec` 为准，并入这一个类，不留第二份 codec。

节自身的存储根上，布局是：

```text
<root>/
 \-- coordinates/<safe_name>    数组；属性 dims，以及有单位时的 unit
 \-- observables/<safe_name>    数组；属性 dims，有则 unit、description、payload、source
```

`write` 先 `clear` 再写这两个组，不另造记录的 `meta/`。`dims` 以 JSON 字符串数组写在该数组的属性上，不另存一张维表。`source` 用现有的 `document()`。组内只有数组：出现子组即拒绝。

记录集成仍走这一个 codec，但调用点改在 `src/molrec/core/bindings/zarr.py`。`write_into(root, model)` 在已经打开的记录根上写上述两个兄弟组，不 `clear` 记录，不动 `meta`、`frame`、`metrics` 及其他节；若这两个组已在，先去掉再写。`read_from(root)` 从记录根读这两个组。`ZarrRecordCodec` 不得再 `create_group("observables")` 然后把整节塞进那个组。`"coordinates"` 加入 `RECORD_SECTIONS`，这样它不会再被当成未知根节收成 `NodeModel`。不要给 `RecordModel` 加 `coordinates` 字段：磁盘上它是兄弟组，模型里它只是 `ObservablesModel.coordinates`。

退役的布局是 `observables/meta/<name>` 组属性上的 `kind`、`description`、`time_dependent`（以及 `axes`、`sampling`、`domain`、`target`），旁边一个没有 `dims` 的数据数组。`read` / `read_from` 在构成模型之前拒绝，抛 `ValueError`，消息点明这是退役的 kind 布局。触发条件：`observables/` 或 `coordinates/` 下有子组，或任一侧数组属性含 `kind` 或 `time_dependent`。拒绝之后不得返回丢掉 `meta`、只留下数值的模型，也不得补写 `dims`。缺 `dims` 键且没有上述退役标记时，按空维名元组交给模型校验（秩不一致则 `ValueError`），这不是转换。

一致性套件仍是 `ObservablesSuite`，`module` 仍是 `"observables"`。删掉所有断言 `kind` 或 `time_dependent` 的用例（`scalar-and-vector`、`unknown-kind-and-keys-preserved`、`reject-data-without-meta`、`reject-meta-without-data`、`reject-missing-kind`、`reject-name-meta`）。用下面这些用例替换，序列名用科学量，不用 `train/loss`、`eval/MAE` 或主机计数：

- `empty-section`：空节。
- `shared-coordinate`：坐标 `distance`（`("bin",)`，长度 3）只存一份；`rdf` 与 `running_integral` 都是 `("bin",)`。
- `two-coordinates-one-dimension`：`time`（ps，f64）与 `frame`（i64）同在维 `point` 上；观测量 `temperature`（K）也是 `("point",)`。
- `different-cadences`：`time` / `point` 上的 `temperature` 与 `sample_time` / `sample` 上的 `mean_energy`，两个维，不是分组类型。
- `derived-with-provenance`：`rdf` 带 `Source`。
- `free-energy-grid`：`phi` 在 `("phi",)`、`psi` 在 `("psi",)`，`free_energy` 是 `("phi", "psi")`。
- `scattered-samples`：同样两个坐标名落在 `("sample",)` 上，值也是 `("sample",)`。
- `dimension-without-coordinate`：`time` 在 `("point",)`，`dipole` 是 `("point", "component")`，`component` 没有坐标数组。
- `shared-name`：坐标与观测量都叫 `energy`。
- `name-needs-encoding`：`structure/rdf` 与 `径向分布`。
- `width-is-preserved`：`contacts` 的 dtype 为 `i32`，读回仍是 `i32`。
- `every-dtype`：`f64`、`i32`、`u64`、`string`、`bool`、`c128` 各一个数组，`dims` 与秩一致，无 `kind`。
- `reject-dimension-conflict`：`model_construct` 绕过校验，`phi` 一侧长度 3、另一侧长度 2；`expect_violation` 为 `dimension_conflict`；读端拒绝。
- `reject-kind-layout`：codec 先写下合法 dims 节，`tamper` 再在 `observables/` 下建子组 `meta/<name>`，属性至少含 `kind` 与 `time_dependent`；`expect_violation` 为 `retired_kind_layout`；读端 `ValueError`，不返回模型。

`ObservableAdapter.module` 仍是 `"observables"`。参考适配器只声明 `zarr`。`REGISTRY` 里这套模型的模块名就是 `observables`，因此 `modules()` 在默认 `drafts=False` 时包含它。`DRAFT_PREFIX` 机制留下，给以后真正的草案用；本规格不再注册 `draft/observables`。不点名模块的 `ConformanceSuite` 走 `REGISTRY.modules()`，结果里有 `observables` 的 dims 用例，没有任何 `draft/` 模块。声明了该适配器的实现必须被这些用例判定。没声明适配器时，该模块是「no adapter」的 skip，而不是被前缀滤掉。

`PUBLISHED["observables"]` 改为 `(Array, Source, ObservableModel, ObservablesModel)`，四者都来自 `molrec.observables.model`。删掉键 `draft/observables`。导出器因此重写 `schema/observables/`（含新的 `source.schema.json`，`array.schema.json` 变为带 `dims` 与 `data` 的那份），删掉 `observable-meta.schema.json`，并因 `RecordModel` 内嵌该节而重写 `schema/core/record.schema.json`。`schema/draft/observables/` 整树删除。夹具把草案四对 valid/invalid 挪到已发布路径，kind 夹具删除。`fixtures/schema/core/record/` 不动，那些实例不含 observables，再生后仍须通过。

`src/molrec/__init__.py` 不再 import `molrec.draft.observables`。`src/molrec/draft/__init__.py` 留下（以后的草案包），其下 `observables/` 整包删除，包括 `bindings/jsonl.py` 与 `bench.py`。JSONL 不注册、不发布、不在散文里当作绑定。

### Reuse decision

- generalize `molrec.draft.observables.model.ObservablesModel` 与 `Array`：迁入 `molrec.observables.model` 并替换 `KNOWN_KINDS` / `ObservableMetaModel`。`Source` 与 `ObservableModel` 属于同一棵模型，一起迁，不平行再实现。
- generalize 草案 Zarr codec：数组布局、`dims`/`unit` 属性与 `safe_name` 并入现有 `ZarrObservablesCodec`。不保留 `draft/observables` 上的第二份 codec。
- generalize `schema_export.PUBLISHED`：`observables` 键改发上述四者，删除 `draft/observables` 键。不新写导出器。
- reuse metrics 逐点标量布局：不改 `docs/spec/metrics.md`、`docs/spec/metrics-wal.md`，也不改 metrics 的 catalog / series / WAL。损失曲线仍是 metrics 的逐点标量，不进本规格的用例名。

## Files to create or modify

- `docs/spec/observables.md`
- `docs/spec/specification.md`（只改 Published schemas 表）
- `docs/spec/overview.md`
- `docs/spec/storage.md`
- `docs/spec/conventions.md`（只删「live observables WAL row」这一处指称）
- `docs/layout.md`
- `CLAUDE.md`（只改 Spec hygiene 里把 observables 写成 kind 草案的那一条）
- `scripts/layout_examples.py`
- `src/molrec/observables/model.py`
- `src/molrec/observables/__init__.py`
- `src/molrec/observables/storage.py`
- `src/molrec/observables/adapter.py`
- `src/molrec/observables/bindings/zarr.py`
- `src/molrec/observables/suite.py`
- `src/molrec/core/bindings/zarr.py`
- `src/molrec/schema_export.py`
- `src/molrec/registry.py`
- `src/molrec/__init__.py`
- `src/molrec/binding.py`
- `src/molrec/jsonvalue.py`
- `src/molrec/draft/observables/__init__.py` (delete)
- `src/molrec/draft/observables/adapter.py` (delete)
- `src/molrec/draft/observables/bench.py` (delete)
- `src/molrec/draft/observables/model.py` (delete)
- `src/molrec/draft/observables/storage.py` (delete)
- `src/molrec/draft/observables/suite.py` (delete)
- `src/molrec/draft/observables/bindings/__init__.py` (delete)
- `src/molrec/draft/observables/bindings/jsonl.py` (delete)
- `src/molrec/draft/observables/bindings/zarr.py` (delete)
- `tests/test_observables/test_model.py` (new)
- `tests/test_observables/test_bindings/test_zarr.py` (new)
- `tests/test_observables_conformance.py`
- `tests/test_safe_name.py` (new)
- `tests/test_draft_observables.py` (delete)
- `tests/test_suite_harness.py`
- `schema/observables/array.schema.json`
- `schema/observables/observable.schema.json`
- `schema/observables/observables.schema.json`
- `schema/observables/source.schema.json` (new)
- `schema/observables/observable-meta.schema.json` (delete)
- `schema/core/record.schema.json`
- `schema/draft/observables/array.schema.json` (delete)
- `schema/draft/observables/observable.schema.json` (delete)
- `schema/draft/observables/observables.schema.json` (delete)
- `schema/draft/observables/source.schema.json` (delete)
- `fixtures/schema/observables/array/valid-three.json` (delete)
- `fixtures/schema/observables/array/invalid-narrow-float.json` (delete)
- `fixtures/schema/observables/array/valid-curve.json` (new)
- `fixtures/schema/observables/array/invalid-no-data.json` (new)
- `fixtures/schema/observables/observable/valid-ir.json` (delete)
- `fixtures/schema/observables/observable/invalid-no-data.json` (delete)
- `fixtures/schema/observables/observable/valid-provenance.json` (new)
- `fixtures/schema/observables/observable/invalid-no-values.json` (new)
- `fixtures/schema/observables/observables/valid-ir.json` (delete)
- `fixtures/schema/observables/observables/invalid-bad-entry.json` (delete)
- `fixtures/schema/observables/observables/valid-one.json` (new)
- `fixtures/schema/observables/observables/invalid-bad-coordinates.json` (new)
- `fixtures/schema/observables/observable-meta/valid-unknown-kind.json` (delete)
- `fixtures/schema/observables/observable-meta/invalid-no-kind.json` (delete)
- `fixtures/schema/observables/source/valid-one-ref.json` (new)
- `fixtures/schema/observables/source/invalid-refs-not-a-list.json` (new)
- `fixtures/schema/draft/observables/array/valid-curve.json` (delete)
- `fixtures/schema/draft/observables/array/invalid-no-data.json` (delete)
- `fixtures/schema/draft/observables/observable/valid-provenance.json` (delete)
- `fixtures/schema/draft/observables/observable/invalid-no-values.json` (delete)
- `fixtures/schema/draft/observables/observables/valid-one.json` (delete)
- `fixtures/schema/draft/observables/observables/invalid-bad-coordinates.json` (delete)
- `fixtures/schema/draft/observables/source/valid-one-ref.json` (delete)
- `fixtures/schema/draft/observables/source/invalid-refs-not-a-list.json` (delete)
- `regressions/self-describing-record-04-observables.py` (new)

## Tasks

- [ ] Write failing unit tests for Array and ObservablesModel (tests/test_observables/test_model.py → TestArray, TestObservablesModel)
- [ ] Write failing unit tests for ZarrObservablesCodec (tests/test_observables/test_bindings/test_zarr.py → TestZarrObservablesCodec) and rewrite tests/test_observables_conformance.py to the dims suite; move the safe_name cases into tests/test_safe_name.py and delete tests/test_draft_observables.py
- [ ] Implement Array, Source, ObservableModel, and ObservablesModel in src/molrec/observables/model.py by moving the draft classes onto that module, drop KNOWN_KINDS and ObservableMetaModel, and add plain docstrings that state Array.unit is an unconverted unit string
- [ ] Implement the sibling Zarr layout on ZarrObservablesCodec in src/molrec/observables/bindings/zarr.py and the record-root write_into/read_from path in src/molrec/core/bindings/zarr.py; point src/molrec/observables/__init__.py, adapter.py, and storage.py at that layout
- [ ] Replace kind and time_dependent cases in src/molrec/observables/suite.py with the dims cases, including reject-kind-layout
- [ ] Generalize PUBLISHED in src/molrec/schema_export.py, regenerate schema/observables and schema/core/record.schema.json, move the dims fixtures onto fixtures/schema/observables, delete schema/draft/observables, fixtures/schema/draft/observables, and src/molrec/draft/observables, and stop registering that module (src/molrec/__init__.py, registry.py, binding.py, tests/test_suite_harness.py)
- [ ] Update docs/spec/observables.md, the published-schema table in docs/spec/specification.md, the kind-layout sentences in docs/spec/overview.md and docs/spec/storage.md, the observables WAL phrase in docs/spec/conventions.md and src/molrec/jsonvalue.py, the Spec hygiene bullet in CLAUDE.md, and scripts/layout_examples.py, then regenerate docs/layout.md
- [ ] Add regression example regressions/self-describing-record-04-observables.py (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

单元测试只打一个模块里的一个方法，用 `uv run --locked pytest -q tests/<file>.py::<test>`。不在 `tests/` 下加 e2e。

- `tests/test_observables/test_model.py` 的 `TestArray` 只构造 `Array`，从而打到 `_shape_dims_and_dtype_agree` 与 `extent`。通过：`dims=("bin",)`、`shape=(3,)`、`dtype="f64"`、`data=[0.0, 0.1, 0.2]`、`unit="angstrom"`，`extent == {"bin": 3}`。边界：`dims` 与秩不一致、`data.shape` 与 `shape` 不一致、dtype 不一致，都是 `ValueError`；`dims=()` 且 `shape=()` 的 0 维数组通过；`unit is None` 保持 `None`。
- 同文件 `TestObservablesModel` 只打 `_dimensions_are_consistent` 与派生的 `dims`。通过：同一维名两侧长度都是 3，`model_dump` 不含键 `dims`，`dims` 属性等于由数组算出的映射。边界：坐标侧长度 3、观测量侧长度 2，`ValueError`。
- `tests/test_observables/test_bindings/test_zarr.py` 的 `TestZarrObservablesCodec` 分开打 `write` 与 `read`。`write`：一个共享坐标加一个观测量之后，用 zarr 直接看数组属性，`dims` 是字符串列表且长度等于数组秩，有单位时有 `unit`，没有 `kind` 也没有 `time_dependent`；五十个观测量共用一个坐标时 `coordinates/` 下只有一个数组、`observables/` 下有五十个。`read`：`observables/meta/<name>` 带 `kind` 与 `time_dependent` 时抛 `ValueError`，不返回模型。同名坐标与观测量落在两个组里，互不覆盖。
- `tests/test_observables_conformance.py` 是已有的套件门，不是新的端到端包。参考适配器只走 zarr，`ObservablesSuite` 全绿。丢掉 `unit`、丢掉 `coordinates`、丢掉 `source`、把网格读成一维 `sample` 的适配器，分别失败在带单位的用例、`shared-coordinate` 或 `free-energy-grid`、`derived-with-provenance`、以及 `free-energy-grid` 与 `dimension-without-coordinate`。不点名模块的 `ConformanceSuite` 结果含模块 `observables` 和用例 `free-energy-grid`，不含任何 `draft/` 模块；`REGISTRY.modules()` 含 `observables`、不含 `draft/observables`。记录往返：根上 `coordinates/` 与 `observables/` 是兄弟，没有 `observables/meta`，读回等于写入，且 `coordinates` 不进 `RecordModel` 的额外键。文件不再引用 `ObservableMetaModel`、`KNOWN_KINDS`、`molrec.draft` 或 JSONL。
- `tests/test_safe_name.py` 只搬走现有的 `safe_name` / `original_name` 用例（可逆、`.` / `..` / `__x`、空串与坏转义拒绝）。不改编码规则。
- 黄金值都写死在测试里。没有第三方神谕，测试时不 import、不 subprocess molrs。
- 回归例：`regressions/self-describing-record-04-observables.py`。公开 API 写下坐标 `bin`（`dims=("bin",)`，`dtype="f64"`，`shape=(3,)`，`data=[0.0, 0.1, 0.2]`，`unit="angstrom"`）和观测量 `rdf`（`dims=("bin",)`，`dtype="f64"`，`shape=(3,)`，`data=[0.0, 0.8, 1.9]`，无 `unit`）。脚本再用 zarr 打开数组属性，而不是再走 codec 的 `read`：`coordinates/bin` 与 `observables/rdf` 的 `dims` 都是 `["bin"]`，形状都是 `(3,)`，`len(dims)` 等于秩，属性里没有 `kind` 或 `time_dependent`。这些数是本规格的字面量，不是外部工具算出来的。

## Out of scope

- metrics 的逐点标量、catalog、series、WAL，以及 `docs/spec/metrics.md` 与 `docs/spec/metrics-wal.md`。训练损失仍在 metrics，不改成观测量，也不推广草案里的 `ObservableBench`。
- 列 `unit` 与记录单位规则（已由 01 落地）。观测量只用 `Array.unit` 这个字符串。
- `structural_axes`，以及 metrics `type` / `meta/modules` 的 kind 分发。本规格删掉观测量的 `kind`，不另做一套分发。
- JSONL 草案绑定：删除，不升为规范，也不保留「活观测量 WAL」的契约句子。
- `molrec.core.model.ArrayModel` 与 `ArrayNodeModel` 的字段和行为。
- 固定尺寸数组的分块公式。坐标数组继续走现有的 `plan`，不改 `docs/spec/chunking.md`。
- `DRAFT_PREFIX` 这一机制本身。只是这一套模型不再挂在 `draft/` 下。
- molrs 仓库里的适配器。本仓库的参考 codec 是仲裁者；伙伴适配器不在本规格。
- LMDB 键、`README.md`、`docs/index.md`，以及 `/mol:map` 生成的 `.claude/notes/architecture.md`。
- schema 版本与任何形式的旧布局转换。
