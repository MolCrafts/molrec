---
title: 记录与集合的单位
status: in-progress
created: 2026-10-09
---

# 记录与集合的单位

## Summary

记录根与集合各持有一份单位，而且只此一份。记录写在 `meta.units`；集合写在集合的 `meta.units`，对每条成员生效，成员的 `meta.units` 必须缺席。连续量一旦在帧、`system` 或轨迹里出现，对应项就必须是单位字符串，否则 `ValueError`；没有任何这些量时，单位对象可以整个缺席。列上可选的 `unit` 只覆盖该列，存放位置与帧路径上的 `precision` 相同（Zarr 数组属性、LMDB 帧头）。`mass` 不再默认成 amu，`charge` 不再默认成 `e`。力场的 `forcefield.units` 与 `ForceFieldUnitsModel` 保持原样。

## Design

单位的主人只有两个，而且互斥。独立记录的主人是记录根上的 `MetaModel.units`。集合的主人是 `CollectionMetaModel.units`，成员记录不得再写一份。`FrameModel.meta` 与 `system` 的 `meta` 里如果出现键 `units`，它仍是普通 meta 值：按现有 meta 标签保存，不解释成单位，也不因此拒绝。扫描时忽略这个键。

新模型 `UnitsModel`（`DocumentModel`，`extra="allow"`）只有九个可选字符串字段，没有 `preset`：`length`、`energy`、`force`、`angle`、`charge`、`mass`、`time`、`pressure`、`temperature`。未给出的字段序列化时缺席，不写成 `null`。未命名的键原样保留。它不是 `ForceFieldUnitsModel`，也不读 `UNIT_QUANTITIES` / `UNIT_PRESETS`。单位字符串是生产者写下的标签，读入方不换算，本片也不要求 pint 能解析它。

`MetaModel.units` 与 `CollectionMetaModel.units` 都是 `UnitsModel | None`，默认 `None`。集合的 `units` 不再是必填的 `dict[str, str]`。`None` 与「对象在、但某个量是 `None`」对必填检查是同一件事：该项没有陈述。

检查函数放在 `src/molrec/core/model.py`，名为 `require_stated_units(record, units)`。它只看 `record.frame`、`record.system`、`record.trajectory`（各帧的块，以及轨迹声明块 `trajectory.blocks` 的列名；逐步 meta 看 `trajectory.meta` 的键和每一帧的 `meta`）。不看 `forcefield` 的表、集合 `index`、`observables`、`metrics`。出现则该项必填：

| 出现 | 必填 |
| --- | --- |
| 列名 `x`、`y` 或 `z` | `length` |
| meta 键 `pe`、`ke` 或 `etotal` | `energy` |
| 列名 `fx`、`fy` 或 `fz` | `force` |
| `TrajectoryModel.time is not None` | `time` |
| meta 键 `press` | `pressure` |
| meta 键 `temp` | `temperature` |
| 列名 `mass` | `mass` |
| 列名 `charge` | `charge` |

`angle` 可以写在 `UnitsModel` 上，本片没有触发它的列或键。列名或 meta 键 `energy`、`charge`、`volume`，以及 `vx`/`vy`/`vz`、盒子向量、`total_charge`、`formal_charge`，都不触发。轨迹声明了列、或声明了逐步 meta 键，即使帧数是 0，也算出现。`ValueError` 的消息里带上缺的字段名（如 `length`），便于测试匹配。pydantic 把模型校验里的 `ValueError` 包成 `ValidationError`。

`RecordModel` 自己的校验器不调用 `require_stated_units`。同一类既是记录根，也是集合成员；成员必须能在没有 `meta.units` 的情况下构造。记录根的执行点是 `ZarrRecordCodec.write` 与 `read`：写出前、读回模型之后各调用一次 `require_stated_units(record, record.meta.units)`。`CollectionModel` 的校验器对每条成员调用同一函数，主人是集合的 `units`；任一成员 `meta.units is not None`（含空的 `UnitsModel`）即 `ValueError`，即使该成员没有连续量。

`ColumnModel` 增加 `unit: str | None = None`，与 `precision` 并列。`__eq__` 计入 `unit`。它不参与量化，也不代替主人的必填项：列上写了 `unit="nm"`，主人仍然必须有 `length`。`None` 表示该列用主人映射到的那一项；不是这八个触发名的列也可以带 `unit`，只是不触发必填。不把 `unit` 放进 `SequenceColumnModel`，也不放进 `sequence_schema`。轨迹上各帧对同一列至多陈述一个 `unit`：后一帧给出不同字符串则 `ValueError`；只在部分帧上陈述时，校验后每一帧里该列都带上这一个字符串。精度仍只归声明，帧上的 `precision` 照旧被清掉；这个校验不得改那条行为。

存放与帧路径的 `precision` 相同，并且按本片的两个点，轨迹列也写在数组上，而不是写进声明：

- Zarr：帧路径数组属性 `unit`（`write_block` / `_read_column`，与 `PRECISION_ATTR` 并列，仅在非 `None` 时写入）。轨迹列在分片数组上同样写这个属性；`ZarrTrajectoryCodec._resolve` 读回后写到该帧的 `ColumnModel.unit`。
- LMDB：`encode_frame` / `decode_frame` 的列头项 `"unit"`，与 `"precision"` 并列，系统帧和轨迹更新都写。轨迹帧头今天不写 `precision`，是因为模型把精度留在声明里；`unit` 留在列上，所以帧头要写。

力场表的列是参数，不存单位。`ForceFieldUnitsModel` 不增加 `force`、`pressure`、`temperature`，`UNIT_QUANTITIES` 与预设表不动。`ForceFieldModel` 校验任一 style 表列的 `unit is not None` 则 `ValueError`。`ZarrForceFieldCodec.write_into` 在调用 `write_block` 之前做同一检查，避免绕过模型把属性写出去。参数列上的 `mass` / `charge` 不参与记录或集合的必填扫描。

裸轨迹没有单位字段，本片不给 `TrajectoryModel` 加。`LmdbTrajectoryCodec` 把裸轨迹包成单记录集合，今天用空的 `UNITS`。包装不是生产者写下的集合：`LmdbCollectionCodec.write` 仅接受该 codec 传入的内部参数以跳过 `revalidated`，`read` 使用 `context={**STORED, "bare_trajectory": True}`，`CollectionModel` 只在这个上下文里跳过单位检查（其它校验照旧，`STORED` 仍表示不要再量化）。其它调用方不得传这个参数。磁盘上这份包装可以继续没有单位。

既有全套测试、布局示例和 `fixtures/precision.mrec.zip` 里已有坐标、`pe`、`temp`、`time`、`mass`、`fx` 或 `charge` 列、却没有对应单位。规则落地后这些构造会在集合校验或记录 codec 上失败，必须在本片改到合法，并重生成因此改变的布局章与精度金样。这不是新的顶层节。

### Reuse decision

- generalize `docs/spec/conventions.md` 的 “Units on a frame”，以及 `charge` / `mass` 的静默默认：单位改到记录 `meta.units`；帧或 `system` 的 `meta.units` 不再被读成单位；删掉 mass 默认 amu、charge 默认 `e`。
- generalize `docs/spec/collection.md` 的 `meta.units`：从「永远必填、列上没有单位、省略的 mass/charge 用默认」改为「无连续量可缺席、九个量、成员不另写、列 `unit` 只覆盖该列」。
- reuse `ForceFieldUnitsModel`：力场文档继续用它，本片不改字段、不改预设、不在参数列上重写一套单位。
- generalize `ColumnModel`（`unit` 照 `precision`）：可选字段，相等性计入，Zarr 数组属性与 LMDB 帧头仅在有值时写入、读回缺席则为 `None`。
- reuse 只有 f64、无 schema 版本：`precision` 仍只许 `f64` 列声明（`_precision_on_f64` 与 schema 的 if/then 不动）；不增加 schema version，不写迁移，不放宽 dtype 闭集。`unit` 是标签，不借精度规则变成第二套 dtype 限制。

## Files to create or modify

- `docs/spec/conventions.md`
- `docs/spec/collection.md`
- `src/molrec/core/model.py`
- `src/molrec/core/bindings/zarr.py`
- `src/molrec/core/bindings/lmdb.py`
- `schema/core/meta.schema.json`（由导出器生成，禁止手改）
- `schema/core/collection-meta.schema.json`（由导出器生成，禁止手改）
- `schema/core/column.schema.json`（由导出器生成，禁止手改）
- `fixtures/schema/core/meta/valid-units.json` (new)
- `fixtures/schema/core/meta/invalid-units-not-object.json` (new)
- `fixtures/schema/core/collection-meta/invalid-no-units.json`（删除：`{}` 在单位可缺席后是合法文档）
- `fixtures/schema/core/collection-meta/invalid-units-not-object.json` (new)
- `fixtures/schema/core/column/valid-unit.json` (new)
- `fixtures/schema/core/column/invalid-unit-not-string.json` (new)
- `tests/test_core/test_model.py`
- `tests/test_core/test_bindings/test_zarr.py`
- `tests/test_core/test_bindings/test_lmdb.py`
- `src/molrec/core/suite.py`
- `tests/test_precision.py`
- `scripts/layout_examples.py`
- `docs/layout.md`（只经 `python scripts/layout_examples.py --write` 重生成）
- `fixtures/precision.mrec.zip`（只经 `python tests/test_precision.py` 重写）
- `regressions/self-describing-record-01-units.py` (new)

## Tasks

- [x] Write failing unit tests for the units rules in `tests/test_core/test_model.py` → `TestUnitsModel`
- [x] Implement `UnitsModel`, `require_stated_units`, `ColumnModel.unit`, and the collection, force-field, and trajectory checks in `src/molrec/core/model.py` (plain docstrings; unit strings are labels, not converted, and have no default)
- [x] Write failing unit tests for column-unit persistence, record-root refusal, and the bare-trajectory LMDB round trip in `tests/test_core/test_bindings/test_zarr.py` → `TestColumnUnit` and `tests/test_core/test_bindings/test_lmdb.py` → `TestColumnUnit`
- [x] Implement unit persistence and the record-root / bare-trajectory wiring in `src/molrec/core/bindings/zarr.py` and `src/molrec/core/bindings/lmdb.py`
- [ ] Generalize the units prose in `docs/spec/conventions.md` and `docs/spec/collection.md`
- [ ] Regenerate `schema/core/meta.schema.json`, `schema/core/collection-meta.schema.json`, and `schema/core/column.schema.json` with `python -m molrec.schema_export schema` (do not hand-edit JSON); add `fixtures/schema/core/meta/valid-units.json`, `fixtures/schema/core/meta/invalid-units-not-object.json`, `fixtures/schema/core/collection-meta/invalid-units-not-object.json`, `fixtures/schema/core/column/valid-unit.json`, and `fixtures/schema/core/column/invalid-unit-not-string.json`; delete `fixtures/schema/core/collection-meta/invalid-no-units.json`
- [ ] Update callers the new check rejects: `src/molrec/core/suite.py` (`RecordSuite` metas and `CollectionSuite.UNITS`), `tests/test_core/test_bindings/test_lmdb.py` (`_collection` must state `energy` because `pe` is present), `tests/test_precision.py`, and `scripts/layout_examples.py`; regenerate `docs/layout.md` and `fixtures/precision.mrec.zip`
- [ ] Add regression example `regressions/self-describing-record-01-units.py` (public models only; hard-coded goldens; no molrs)
- [ ] Run full check + test suite

## Testing strategy

单元测试只打一个模块里的一个函数或方法。模型规则在 `tests/test_core/test_model.py` 的 `TestUnitsModel`，绑定在 `tests/test_core/test_bindings/test_zarr.py` 与 `tests/test_core/test_bindings/test_lmdb.py` 的 `TestColumnUnit`。单测命令是 `uv run --locked pytest -q tests/<file>.py::<test>`。不在 `tests/` 下加端到端测试，也不新写 conformance 用例。`reject-no-units` 仍应拒绝那条带 `x`、`fx` 和 `pe`、却没有单位的集合。

`TestUnitsModel` 用硬编码的列名和 meta 键，期望 `ValidationError` 或 `require_stated_units` 的 `ValueError` 消息含缺项之名：

- 快乐路径：只有 `element` 的 `system`，`units` 为 `None` 的 `CollectionModel` 构造成功；九个字段都写上的 `UnitsModel` 被保留；未知键（单位对象内与 `meta` 上）原样还回。
- 必填：列 `x`/`y`/`z` → `length`；meta 键 `pe`/`ke`/`etotal` → `energy`；列 `fx`/`fy`/`fz` → `force`；`time=[0.0]` → `time`；meta 键 `press` → `pressure`；meta 键 `temp` → `temperature`；列 `mass` → `mass`；列 `charge` → `charge`。只写了别的项不算数。轨迹声明块里的列名、以及 `trajectory.meta` 里的键，在零帧时也算出现。
- 边界：`meta` 键 `energy`、`charge`、`volume` 不触发；`vx` 与盒子不触发 `length`；列 `unit="nm"` 不免除 `length`；成员 `MetaModel(units={})` 被拒绝，成员 `MetaModel()` 不被这条拒绝；`frame.meta["units"]` 或 `system.meta["units"]` 为 `{"length": "nm"}` 时记录仍因缺 `length` 失败，且该键还在 meta 里；`mass` / `charge` 不会被填成 `"amu"` 或 `"e"`；力场表列带 `unit` 则 `ForceFieldModel` 失败，且 `ForceFieldUnitsModel` 仍没有 `force`、`pressure`、`temperature` 字段；两帧对同一列给出 `"nm"` 与 `"angstrom"` 则失败，只在一帧给出 `"nm"` 时校验后每帧该列都是 `"nm"`；非 `f64` 列的 `precision` 仍被拒绝。

`TestColumnUnit`：帧路径 Zarr 数组在 `unit="nm"` 时有属性 `unit`，缺席时没有该属性；轨迹列的分片数组同样往返，读回后每帧 `ColumnModel.unit` 为 `"nm"`。LMDB 帧头在 `"precision"` 旁有 `"unit"`。带列 `x`、没有 `meta.units` 的记录，`ZarrRecordCodec.write` 抛出匹配 `length` 的 `ValueError`。`LmdbTrajectoryCodec` 仍能写出并读回一条带列 `x`、包装集合没有单位的裸轨迹。

既有门不加新断言：`tests/test_schema_export.py` 与 `tests/test_schema_fixtures.py`。`collection-meta` 的 `{}` 必须被 schema 接受，所以删掉 `invalid-no-units.json`。`valid-angstrom.json` 与 `fixtures/schema/core/meta/valid-empty.json` 保持合法。

回归示例是仓库根下的 `regressions/self-describing-record-01-units.py`。它只用公开模型构造一条记录：`meta.units.length` 为 `"angstrom"`，`meta.units.force` 为 `"kcal/mol/angstrom"`，`frame` 里列 `x` 的 `unit` 为 `"nm"`，列 `fx` 的 `unit` 为 `None`。这些字符串写死在脚本里。不导入 molrs，不把第三方当测试时的预言机。脚本不是 pytest 套件的一部分；交付时直接运行它。

## Out of scope

- `kind`、`structural_axes`、`observables`，以及 observables 上已有的 `unit` 字段。
- 给 `ForceFieldUnitsModel` 增加 `force`、`pressure`、`temperature`，或改预设；参数列不存单位。
- 把 `unit` 放进 `SequenceColumnModel` 或 `sequence_schema`（不改 `schema/binding/`）。
- 改写 `docs/spec/storage.md`、`frame.md`、`lmdb.md`、`ragged.md`、`zarr.md`。布局章只因示例记录多了 `meta.units` 而重生成。
- 给裸轨迹增加单位字段。LMDB 包装跳过检查是编码缝，不是生产者集合的豁免，`collection.md` 不把它写成第二种集合。
- 单位换算，以及用 pint 校验记录单位字符串。
- 用盒子、速度、`volume`、`total_charge`、`formal_charge` 或任何角度列去触发 `length` / `angle`。本片不定义谁必须填写 `angle`。
- 新的 conformance 用例、schema version、迁移。
