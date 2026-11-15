---
title: 未命名根节用 kind 自描述
status: approved
created: 2026-10-09
---

# 未命名根节用 kind 自描述

## Summary

读者打开一份记录，只凭文件和本规范就能判断每个根节的种类：保留名仍按名字解释，规范没有命名的根组则用组属性 `kind`（`document`、`frame`、`sequence`、`array` 之一）选择已有布局。没有 `kind` 的未命名根节继续按不解释字节原样往返。自定义的 method `type` 与 metrics `type` 不再表示必须去 `meta/modules` 取解码规则；模块只作引用。metrics 仍是逐点 `f64` 标量。

## Design

散文是规范，模型与 Zarr 编解码跟随。不引入 schema 版本，不迁移旧布局。未知键按既有文档规则原样保留。

保留根名不带节种属性 `kind`，集合与今日 `RECORD_SECTIONS` 相同，不增不减：`meta`、`system`、`frame`、`trajectory`、`forcefield`、`observables`、`method`、`status`、`metrics`。它们仍由名字进入现有字段与现有编解码。本规范不要求读者拒绝保留组上碰巧出现的键 `kind`：具名 `frame` / `system` 今日会把它当成 meta 键，该行为保持不变。记录「除 `meta` 外至少有 `frame`、`system`、`trajectory`、`forcefield`、`status` 之一」的规则不改；未命名节不算这一条。

未命名根组是 `RecordModel` 的 extra（名字不在上述集合里）。闭集常量 `SECTION_KINDS = ("document", "frame", "sequence", "array")` 放在 `src/molrec/core/model.py`，Zarr 侧导入，不另抄一份。组属性 `kind` 缺失则不是节种。值不在闭集中（含非字符串、空字符串）拒绝。模型校验器抛 `ValueError`（经 `RecordModel.model_validate` 时为 `ValidationError`，消息点名该值与闭集）。`ZarrRecordCodec.read` 对盘上非法 `kind` 直接抛 `ValueError`。

`RecordModel` 的字段集不改，extra 仍是 `extra="allow"`，以便生成的 `schema/core/record.schema.json` 不漂移。新类型不登记进 `schema_export.PUBLISHED`。`_unknown_sections_are_subtrees` 仍是唯一收口，按 extra 的值分流，不另写解析器：

- 已是下面某一节模型，或 `NodeModel`：保持。
- dict 且顶层有 `kind`：按闭集构造对应节模型。
- 其余（含 `{"attributes": {"kind": ...}, "arrays": ..., "groups": ...}`）：与今日相同，`NodeModel.model_validate`。顶层没有 `kind` 时，属性里的 `kind` 只是字节，不提升为节种。
- 直接传入裸 `FrameModel` 或裸 `TrajectoryModel`：`ValueError`。调用方传带 `kind` 的 dict，或传下面的节模型，避免 dump 后丢掉节种。

节模型均为 frozen pydantic，命名与构造对齐 `FrameModel` / `ObservableModel` / `DocumentModel`；错误一律 `ValueError`。`model_dump` 再 `model_validate` 必须回到同一节种。

- `DocumentSectionModel(DocumentModel)`：字段 `kind: Literal["document"]`，其余键 `extra="allow"`（`null` 保留）。扁平 dict 即文档。
- `FrameSectionModel`：载荷是 `FrameModel`。对外 dict 为 `{"kind": "frame", **frame 字段}`，不是再包一层 `frame`。`meta` 里不得再有键 `kind`（该名是节种，不是 meta）；`_meta_types` 仍由既有帧规则拒绝作为 meta 键。
- `SequenceSectionModel`：载荷是 `TrajectoryModel`。对外 dict 为 `{"kind": "sequence", **trajectory 字段}`。轨迹既有规则全部适用。
- `ArrayEntryModel`：字段顺序对齐 `ObservableModel`，为 `meta` 然后 `data`。`meta` 是自由 `DocumentModel`（无必填键，空文档合法，未知键保留），`data` 是已有 `ArrayModel`。不使用 `ObservableMetaModel`，不使用草稿 dims 模型。
- `ArraySectionModel`：`kind: Literal["array"]`，`entries: dict[str, ArrayEntryModel]`，`attributes: dict`（组上除 `kind` 以外的属性，空则 dump 省略）。`attributes` 不得含 `kind`。名字规则与 observables 的节点名相同，但在 `model.py` 本地检查，不调用 `check_observable_name`，也不导入 `molrec.observables`：非空、无 `/`、不是 `.` / `..`、不以 `__` 开头、不是 `meta`。

磁盘上的未命名根组（参考绑定）：

- `document`：属性映射就是文档，与 `status` / `method` 相同，经已有 `document()` 写入与读回；`kind` 是文档的一个键。子数组或子组是畸形，`ValueError`。非有限数仍由 `document()` 在写入时拒绝。
- `frame`：既有 frame-shaped 布局。`ZarrRecordCodec` 调用 `ZarrFrameCodec.write_into` 与 `read_from`，不复制 `write_block`。`kind` 在 `write_into` 之前写入组属性。`read_from` 增加仅关键字参数 `drop_attrs: tuple[str, ...] = ()`，默认空，因此具名 `frame` / `system` 的调用与字节解释不变；未命名节以 `drop_attrs=("kind",)` 调用，只从属性副本里去掉 `kind` 再 `decode_typed_meta`，不改存储（压缩包只读，禁止读路径上删属性）。`kind` 不是 meta 键，也不进入 `_meta_types`。`box`、`structural_shape`、`targets`、validity 仍走既有帧规则。
- `sequence`：既有轨迹布局。调用 `ZarrTrajectoryCodec.write_into` / `read_from`。`kind` 在 `write_into` 之前写入，使 `nstep` 仍是最后写入的组属性。`read_from` 不把 `kind` 收进 `sequence_schema`。`kind` 不是块名。
- `array`：`<section>/` 组属性 `kind` 为 `array`，另加 `attributes`。每个名字一个数组 `<section>/<name>`（`create_fixed` + `stored_dtype`，dtype/shape/values 即 `ArrayModel`）和旁路文档 `<section>/meta/<name>` 的属性映射。配对强制：有数组无旁路、有旁路无数组、或出现除 `meta` 以外的子组，均为 `ValueError`，消息点名未配对的名字，句式对齐 observables codec 的 “lack their pair”。不调用 `ZarrObservablesCodec`。
- 无 `kind`：`read_node` / `write_node` 原样。子组即使属性里有 `kind` 也不解释。

`read_node` 增加 `interpret_kind: bool = False`。默认与今日相同，返回 `NodeModel`，递归调用不传该标志。只有 `ZarrRecordCodec.read` 里 `name not in RECORD_SECTIONS` 的那一次调用传 `interpret_kind=True`。`metrics` 仍走不带该标志的 `read_node`。`write_node` 仍只接受 `NodeModel`。`ZarrRecordCodec.write` 的 extra 循环按节模型类型分流；禁止把 frame 或轨迹布局写进 `write_node`。

`meta/modules` 只标识记录使用的模块（可带 `spec` URL）。它不提供节的解码规则，不新增版本或兼容规则。method 的自定义 `type`、metrics 的自定义 `type` 都是名字。method 组的结构仍是 method 章；metrics 闭合形式仍是逐点 `f64`，自定义 `type` 不改变 dtype，也不指向模块。

规范目标句（写入 `docs/spec/specification.md` 首段，英文）必须让读者看见：种类来自文件加本规范。存储格式那一段不得再把 `frame` / `system` / `trajectory` 笼统称为 Array sections。overview 里「QM basis 要靠模块才能读懂」的草图改为带 `kind` 的 `frame` 或 `array`。

落地到英文规范的句子：

`docs/spec/specification.md` 首段在现有自描述句之后加上：`A reader tells each root section's kind from the file and this specification alone. The reserved names have the kind their own chapters define. Every other root group states a group attribute kind of document, frame, sequence, or array, and that value selects the layout. No module is consulted to discover the kind.`

同文 Storage format 段改为：`Document sections (meta, status, method, and an unnamed root group of kind document) are stored as group attributes. Frame-shaped sections (frame, system, forcefield's style tables, and an unnamed root group of kind frame) and sequence sections (trajectory, and an unnamed root group of kind sequence) are stored as groups and arrays under those layouts. An array section (observables, and an unnamed root group of kind array) stores one array per name beside a metadata document. forcefield remains a document beside one table of arrays per style. Live metrics may use an append-only JSONL buffer; closed metrics densify to Zarr series of one f64 per point.`

`docs/spec/overview.md` 的 Section kinds：四种种类保留，并写明未命名根组用属性 `kind` 选择其中之一；无 `kind` 则整组不解释。具名例子不改（`meta` / `status` / `method` 为 document，`frame` / `system` / `forcefield` 为 frame-shaped，`observables` 为具名 array 节，`trajectory` 为 sequence，`metrics` 仍是该章的混合布局）。原则 “Modules name extra rules” 改为模块只是引用，节结构以本规范为准。Adding your own content 第 3 点要求新根节写出 `kind`，无 `kind` 则原样保留；第 4 点的模块只为共享词汇，不为发现种类。QM 草图改为：行表用 `kind` `frame`（一块、若干列）；一个数组加一份小文档（例如基函数指数）用 `kind` `array`。读者看到 `kind` 即知布局。模块可以给列或旁路键命名，但不是可读的前提。

`docs/spec/storage.md` 在既有 Frame-shaped group 上改「declares itself frame-shaped」：`frame/`、`system/` 以及 `kind` 为 `frame` 的未命名根组共用该布局；`kind` 与 `_meta_types` 一样不是 meta 键。同章用一小节写未命名根组的五种情况（无 `kind`、四种合法值、非法值），不另起一套 block 树。规则 2 与不变量 4 不再把 `frame` / `system` / `trajectory` 统称 array sections。Section → form map 下加一句：未命名根组不是表中的行，形式由 `kind` 决定。

`docs/spec/method.md` 的 `type`：标准值仍是 `classical`、`ml`、`electronic_structure`、`workflow`。自定义值是任意其他字符串。结构始终是本章。`meta/modules` 只是引用，读者不加载模块来解析 `method`。删掉 “valid if its parse rules are declared under `meta/modules`”。workflow 的 `order` / `stages` 不改。

`docs/spec/metrics.md` 的 `type`：`scalar` 表示有限数；自定义 `type` 只是目录里的名字，不指向 `meta/modules`，不改变布局。`metrics/series/<safe_name>` 始终是 `f64[n]`。删掉 “a custom type names a module”。WAL、重复 step、catalog 水位不改。

所有权：生产者写入 `kind`；`RecordModel` 持有校验后的节对象；`ZarrRecordCodec` 只做字节与这些对象的翻译，不另立第五种。具名节的写入顺序（先 `meta/`，再既有节）不改，以免 `docs/layout.md` 的生成树漂移。

### Reuse decision

- generalize overview Section kinds：改 `docs/spec/overview.md` 既有 Section kinds，不新开并列章。
- generalize storage frame-shaped group：扩展 `docs/spec/storage.md` 既有 Frame-shaped group 及根布局规则，使 `kind=frame` 的未命名根组走同一布局；不重写 block 树。
- generalize `RecordModel._unknown_sections_are_subtrees`：仍由该校验器收口；无 `kind` 继续 `NodeModel`；有 `kind` 转为上面的节模型。
- generalize zarr `read_node`：用 `interpret_kind` 扩展这一个函数；仅记录根上的未命名节打开；递归与 `metrics` 保持逐字节原样。
- reuse `ZarrFrameCodec`：`write_into` / `read_from`（后者只加默认空的 `drop_attrs`）。不复制 `write_block`，不改具名 `frame` / `system`。
- reuse `ZarrTrajectoryCodec`：`write_into` / `read_from`。`kind` 在 `write_into` 之前写入，保证 `nstep` 最后提交。
- reuse document attrs：`document()` 与 `status` / `method` 的「属性映射即文档」。
- generalize array section：overview / storage 的 array 节扩到未命名 `kind=array`（一名字、一 `ArrayModel`、一份旁路文档）。数据用已有 `ArrayModel`，写数组用本模块 `create_fixed`。不调用 `ZarrObservablesCodec`，不把 observables 的必填元数据或 dims 草稿套到未命名节，也不改 `observables/` 文件。
- generalize `meta/modules`：overview、method、metrics 改为只作引用；解码规则不在模块里。
- generalize overview QM sketch：同一 Adding your own content 列表内改为 `kind` `frame` 或 `array`。
- generalize specification.md wording：改目标句，并去掉把 `frame` / `system` / `trajectory` 写成 Array sections 的句子。

## Files to create or modify

- `docs/spec/overview.md`
- `docs/spec/specification.md`
- `docs/spec/storage.md`
- `docs/spec/method.md`
- `docs/spec/metrics.md`
- `src/molrec/core/model.py`
- `src/molrec/core/bindings/zarr.py`
- `tests/test_core/test_model.py`
- `tests/test_core/test_bindings/test_zarr.py`
- `regressions/self-describing-record-03-kind.py` (new)

## Tasks

- [ ] Write failing unit tests for RecordModel 的未命名根节 kind（`tests/test_core/test_model.py` → `TestRecordModel`）
- [ ] Generalize `RecordModel._unknown_sections_are_subtrees` in `src/molrec/core/model.py` to cover kind `document`、`frame`、`sequence`、`array`，无 kind 仍为 `NodeModel`
- [ ] Write failing unit tests for `ZarrRecordCodec` 的 kind 分流（`tests/test_core/test_bindings/test_zarr.py` → `TestZarrRecordCodec`）
- [ ] Generalize `read_node` in `src/molrec/core/bindings/zarr.py`，使未命名根节按 kind 调用 `ZarrFrameCodec`、`ZarrTrajectoryCodec`、`document()` 或 array 配对，无 kind 仍逐字节原样
- [ ] Add docstring per plain style with units，写在 `src/molrec/core/model.py` 的节模型与 `src/molrec/core/bindings/zarr.py` 的 `read_node` 上（英文，与既有 docstring 一致；`kind` 不是物理量，本节列值不带单位）
- [ ] Generalize Section kinds、QM 草图与 Array-sections 措辞 in `docs/spec/overview.md`、`docs/spec/specification.md`、`docs/spec/storage.md`
- [ ] Generalize `meta/modules` 的措辞 in `docs/spec/method.md` 与 `docs/spec/metrics.md`，metrics 仍写明逐点 `f64`
- [ ] Add regression example `regressions/self-describing-record-03-kind.py`（只走公开的 `RecordModel` 与 `ZarrRecordCodec` / `ZarrRecordStorage`；金样写死；不导入 molrs）
- [ ] Verify kpoints 的 `kx`、`ky`、`kz` 与字面量 `[0.0, 0.5]`、`[0.0, 1.0]`、`[-0.25, 0.5]` 一致（`tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_kind_frame_round_trips_through_the_frame_codec`）
- [ ] Run full check + test suite

## Testing strategy

单元测试只放在与 `src/` 镜像的路径，不在 `tests/` 下做端到端。每个测试只打一个方法。模型侧加在既有 `TestRecordModel`；Zarr 侧新增类 `TestZarrRecordCodec`，不改写该文件里已有的函数测试。单测变绿只跑 `uv run --locked pytest -q tests/<file>.py::<test>`。

`TestRecordModel`（都经 `RecordModel.model_validate` / `model_dump`）：

- `test_a_kind_frame_section_round_trips`：`meta` 空，`status.state` 为 `ok`，extra `kpoints` 为 `kind` `frame`，块 `grid`、`count` 2，列 `kx`/`ky`/`kz` 皆 `f64`，值为 `[0.0, 0.5]`、`[0.0, 1.0]`、`[-0.25, 0.5]`。dump 再校验后三列与这些字面量逐元素相等，且节种仍是 `frame`。这些数在 binary64 中可精确表示，用相等，不用容差。
- `test_a_kind_document_keeps_a_null_key`：`{"kind": "document", "note": None}` 经 `document()` 后 `note` 仍为 `null`，`kind` 仍为 `document`。
- `test_a_kind_sequence_round_trips`：`kind` `sequence`，`step` `[0]`，一帧空 `FrameModel`；再校验后 `kind` 与 `step` 不变。
- `test_an_array_section_pairs_an_array_with_sidecar_meta`：`entries.basis.data` 为 `f64`、shape `(2,)`、values `[1.0, 2.0]`，`meta` 为 `{"unit": "bohr"}`；再校验后两者都在。
- `test_an_illegal_kind_is_refused`：`kind` 为 `basis`、`1`、`""` 均 `ValidationError`，消息含该值与闭集。
- `test_an_unknown_root_section_is_a_subtree`：保持今日 `x_vendor` → `NodeModel(attributes={"a": 1})`。另加 `test_attributes_kind_does_not_promote`：`attributes` 里的 `kind` 仍留在 `NodeModel` 里。
- `test_a_kinded_section_does_not_count_as_substantive`：仅 `meta` 与 `kpoints`（`kind` `frame`）仍因 “at least one of” 失败。
- `test_a_frame_section_meta_key_named_kind_is_refused`：`meta` 含键 `kind` 则 `ValidationError`。

`TestZarrRecordCodec`（`ZarrRecordCodec` 与 `ZarrRecordStorage`；保留已有 `test_the_record_codec_carries_unknown_content_through`）：

- `test_kind_frame_round_trips_through_the_frame_codec`：同上 kpoints 金样。读回 `==` 写入的记录。盘上 `kpoints` 的组属性 `kind` 为 `frame`，子组 `grid` 是块（`count` 2），三列数组等于字面量。若有 meta 键，本测试用空 meta：`_meta_types` 不存在或不含 `kind`。
- `test_kind_frame_keeps_a_meta_key_beside_kind`：meta `{"label": "G"}` 读回为该键；属性 `kind` 为 `frame`；`_meta_types` 的键只有 `label`。
- `test_kind_document_is_group_attributes`：属性即文档，含 `kind` 与 `note: null`；组下无子节点。
- `test_kind_document_with_a_child_is_refused`：`kind` `document` 且有子数组时 `read` 抛 `ValueError`。
- `test_kind_sequence_round_trips_through_the_trajectory_codec`：读回 `step == [0]`；组属性 `kind` 为 `sequence` 且 `nstep` 为 1（证明走了轨迹编解码，不是 `write_node`）。
- `test_kind_array_round_trips_data_and_sidecar`：`basis` 的值为 `[1.0, 2.0]`，`meta/basis` 属性含 `unit` `bohr`，组属性 `kind` 为 `array`。
- `test_kind_array_without_its_sidecar_is_refused`：只有数组没有 `meta/<name>` 时 `ValueError`。
- `test_an_illegal_kind_on_read_is_refused`：未命名组属性 `kind` 为 `widget` 时 `read` 抛 `ValueError`。
- `test_a_nested_kind_attribute_is_not_a_section`：无 `kind` 的未命名根组，其子组属性含 `kind` `frame`；读回仍是 `NodeModel`，子组不被当成帧。
- `test_reserved_sections_are_written_without_kind`：普通 `frame` + `status` 记录写入后，`frame`、`status`、`meta`、`trajectory` 这些已写组的属性里没有作为节种的 `kind`（`frame` 若无 meta 键 `kind`，则属性中无 `kind`）。

回归脚本 `regressions/self-describing-record-03-kind.py`：构造上述 kpoints 记录（`status.state` `ok`，空 `meta`），先 `model_dump` 再 `model_validate`，再用 `ZarrRecordCodec` 写入临时目录并读回。断言三列等于字面量、组属性 `kind` 为 `frame`、读回与原记录相等。注释写明：无第三方 oracle；字面量为 binary64 精确值；日期 2026-10-09。不导入 molrs，不在运行时调用外部程序。

本规范不声明物理定律，`science.required` 为 false，故无教科书对照值。金样就是上面的 `f64` 字面量。

## Out of scope

- 不改单位规则，不引入或修改 `structural_axes`，不替换 `observables/` 及其 scalar/vector 元数据，不采纳草稿 dims 模型，不新造能量模型节。
- 不给保留名增加必填 `kind`，不把未命名节算进「至少一节」规则，不在无 `kind` 的子树上猜测布局。
- 不改 LMDB、conformance suite、molrs 适配器、`schema_export.PUBLISHED`、`schema/`、`fixtures/`、`docs/layout.md`。实现不得改具名节的写入顺序或已发布模型字段，以免这些生成物漂移；若漂移，由既有漂移测试判定失败，而不是去手改生成物。
- 不改 metrics 的 WAL、重复 step 规则或 catalog 形状，只改「自定义 type 要去模块取解码规则」这一句；数组仍是逐点 `f64`。
- 不改 method 的 workflow `order` / `stages`，不给 `meta/modules` 加版本或兼容规则。
- 曾经考虑过用 `ZarrObservablesCodec` 读 `kind=array`，这会套上 observables 必填字段，故不做。也考虑过无 `kind` 时按内容猜测 frame 或 array，这会破坏今日不解释字节，故不做。
