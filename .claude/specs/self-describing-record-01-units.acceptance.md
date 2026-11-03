---
slug: self-describing-record-01-units
criteria:
  - id: ac-001
    summary: Continuous quantities require the matching units field
    type: code
    pass_when: |
      TestUnitsModel shows ValueError (ValidationError from constructors)
      whose message names the missing field: columns x/y/z require length,
      meta keys pe/ke/etotal require energy, columns fx/fy/fz require force,
      TrajectoryModel.time is not None requires time, meta press requires
      pressure, meta temp requires temperature, column mass requires mass,
      and column charge requires charge. A units object that states a
      different field does not satisfy the missing one.
    status: pending
  - id: ac-002
    summary: Units may be omitted when no continuous quantity appears
    type: code
    pass_when: |
      CollectionModel with CollectionMetaModel() (units is None) and one
      member whose only column is element (string) constructs successfully,
      and require_stated_units on that record with units None does not raise.
    status: pending
  - id: ac-003
    summary: Collection members do not restate meta.units
    type: code
    pass_when: |
      CollectionModel raises ValidationError when a member is
      MetaModel(units={}) or MetaModel(units={"length": "angstrom"}), even
      if the collection units already state every triggered field. A member
      with MetaModel() and no units field is not refused for restating.
    status: pending
  - id: ac-004
    summary: Frame or system meta.units is ordinary meta
    type: code
    pass_when: |
      A record whose frame.meta or system.meta is {"units": {"length": "nm"}}
      and whose atoms include column x still fails require_stated_units
      when record meta.units is None, and the meta key "units" is still
      present after validation. The same meta key on a frame with no
      continuous quantity does not raise.
    status: pending
  - id: ac-005
    summary: Column unit overrides one column and is not a default
    type: code
    pass_when: |
      require_stated_units still names length when column x has unit "nm"
      and meta.units has no length. A validated column does not gain
      unit "amu" or "e" for mass or charge. Two columns that differ only
      in unit compare unequal. ForceFieldModel raises ValidationError if
      any style-table column has unit set. ForceFieldUnitsModel.model_fields
      has no force, pressure, or temperature.
    status: pending
  - id: ac-006
    summary: A trajectory column states one unit string
    type: code
    pass_when: |
      TrajectoryModel raises ValidationError when two frames state unit
      "nm" and "angstrom" on the same column. When only one frame states
      unit "nm", validation succeeds and every frame that presents that
      column has unit "nm". Precision is still rejected on a non-f64 column
      with the existing "only an f64" ValueError.
    status: pending
  - id: ac-007
    summary: Zarr stores column unit as an array attribute
    type: runtime
    pass_when: |
      TestColumnUnit in tests/test_core/test_bindings/test_zarr.py shows a
      frame-path array and a trajectory column array carry attrs["unit"]
      == "nm" when the column unit is "nm", omit the attribute when unit
      is None, and a trajectory read returns ColumnModel.unit == "nm".
    status: pending
  - id: ac-008
    summary: LMDB frame header stores unit beside precision
    type: runtime
    pass_when: |
      TestColumnUnit in tests/test_core/test_bindings/test_lmdb.py shows
      encode_frame writes the column header key "unit" with the column's
      string when unit is set, next to "precision" when precision is set,
      and decode_frame restores ColumnModel.unit. A missing unit key reads
      back as None.
    status: pending
  - id: ac-009
    summary: Record codec refuses coordinates without length
    type: runtime
    pass_when: |
      ZarrRecordCodec.write of a RecordModel whose frame has column x and
      whose meta.units is None raises ValueError matching length.
      ZarrRecordCodec.read raises the same way for a store that has that
      column and no meta.units.length.
    status: pending
  - id: ac-010
    summary: Bare-trajectory LMDB wrapper still round-trips
    type: runtime
    pass_when: |
      LmdbTrajectoryCodec.write then read of a TrajectoryModel with column
      x and no units field returns equal coordinates. The wrapper is not
      refused for missing collection meta.units. A producer CollectionModel
      with that same trajectory and units None still raises ValidationError
      matching length.
    status: pending
  - id: ac-011
    summary: Generated schemas match the units objects and column unit
    type: code
    pass_when: |
      python -m molrec.schema_export schema leaves schema/core/meta.schema.json,
      schema/core/collection-meta.schema.json, and schema/core/column.schema.json
      matching the models. collection-meta no longer requires units.
      column.schema.json has optional string-or-null unit. tests/test_schema_export.py
      and tests/test_schema_fixtures.py pass. valid-units.json and valid-unit.json
      are accepted. invalid-units-not-object.json fixtures and
      invalid-unit-not-string.json are refused. invalid-no-units.json is gone.
      No schema file contains a schema version key.
    status: pending
  - id: ac-012
    summary: Conventions and collection prose match the units rule
    type: docs
    pass_when: |
      docs/spec/conventions.md no longer says mass defaults to amu or charge
      defaults to e, and no longer treats frame or system meta.units as the
      unit system. docs/spec/collection.md no longer requires units on every
      collection, no longer says omitted mass or charge keep a default, and
      states the nine quantities, member records do not carry meta.units,
      and a column unit overrides only that column.
    status: pending
  - id: ac-013
    summary: Regression script reproduces the hard-coded unit strings
    type: runtime
    pass_when: |
      python regressions/self-describing-record-01-units.py exits 0. The
      script builds a RecordModel through the public models and asserts
      meta.units.length == "angstrom", meta.units.force == "kcal/mol/angstrom",
      column x unit == "nm", and column fx unit is None. It does not import
      or subprocess molrs.
    status: pending
  - id: ac-014
    summary: Full check and test suite pass
    type: runtime
    pass_when: |
      uvx ruff@0.16.5 format --check . && uvx ruff@0.16.5 check . succeed,
      and uv run --locked pytest -q exits 0, including the record,
      collection, and trajectory suites and tests/test_layout_doc.py.
    status: pending
---

# Acceptance criteria

ac-001 到 ac-006 是 `TestUnitsModel` 的模型规则，黄金值是列名、meta 键和单位字符串本身，不是外部程序的输出。ac-007 到 ac-010 看 Zarr 属性、LMDB 帧头和 codec 的拒绝或往返。ac-011 只接受导出器写出的 schema。ac-013 的四个字符串必须出现在回归脚本的断言里。ac-014 是本仓库的 check 与 pytest，不包含 molrs 伙伴门。
