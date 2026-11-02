---
slug: self-describing-record-03-kind
criteria:
  - id: ac-001
    summary: Kind-frame extra section round-trips through RecordModel
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_model.py::TestRecordModel::test_a_kind_frame_section_round_trips
      exits 0. The test builds kpoints kind frame, block grid, count 2, f64 columns
      kx=[0.0, 0.5], ky=[0.0, 1.0], kz=[-0.25, 0.5], dumps and validates again, and
      those three columns still equal the literals.
    status: pending
  - id: ac-002
    summary: Kind-document extra keeps a null key
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_model.py::TestRecordModel::test_a_kind_document_keeps_a_null_key
      exits 0, and the asserted document is exactly {kind: document, note: null}.
    status: pending
  - id: ac-003
    summary: Kind-sequence extra round-trips step [0]
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_model.py::TestRecordModel::test_a_kind_sequence_round_trips
      exits 0, and the revalidated extra still has kind sequence and step [0].
    status: pending
  - id: ac-004
    summary: Kind-array extra pairs ArrayModel with sidecar meta
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_model.py::TestRecordModel::test_an_array_section_pairs_an_array_with_sidecar_meta
      exits 0. Entry basis has f64 values [1.0, 2.0] and sidecar meta unit bohr.
    status: pending
  - id: ac-005
    summary: Illegal kind strings and non-strings fail validation
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_model.py::TestRecordModel::test_an_illegal_kind_is_refused
      exits 0. kind basis, kind 1, and kind "" each raise ValidationError whose
      message names the bad value and the set document, frame, sequence, array.
    status: pending
  - id: ac-006
    summary: Missing kind stays an uninterpreted NodeModel
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_model.py::TestRecordModel::test_an_unknown_root_section_is_a_subtree
      tests/test_core/test_model.py::TestRecordModel::test_attributes_kind_does_not_promote
      exits 0. x_vendor without a top-level kind is NodeModel(attributes={a: 1}),
      and a kind key nested under attributes is still NodeModel payload.
    status: pending
  - id: ac-007
    summary: Kinded extras do not replace substantive-section or meta rules
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_model.py::TestRecordModel::test_a_kinded_section_does_not_count_as_substantive
      tests/test_core/test_model.py::TestRecordModel::test_a_frame_section_meta_key_named_kind_is_refused
      exits 0. meta plus only kpoints fails the at-least-one substantive-section
      rule, and a frame-section meta key named kind is ValidationError.
    status: pending
  - id: ac-008
    summary: Zarr kind=frame uses the frame codec and the kpoints literals
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_kind_frame_round_trips_through_the_frame_codec
      tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_kind_frame_keeps_a_meta_key_beside_kind
      exits 0. Read model equals the written record; kpoints attrs kind is frame;
      grid kx/ky/kz equal [0.0, 0.5], [0.0, 1.0], [-0.25, 0.5]; _meta_types does
      not list kind; meta label G survives beside kind.
    status: pending
  - id: ac-009
    summary: Zarr kind=document is attributes only
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_kind_document_is_group_attributes
      tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_kind_document_with_a_child_is_refused
      exits 0. A childless document round-trips kind and note null; a document
      group that has a child array makes ZarrRecordCodec.read raise ValueError.
    status: pending
  - id: ac-010
    summary: Zarr kind=sequence uses the trajectory codec
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_kind_sequence_round_trips_through_the_trajectory_codec
      exits 0. The read model has step [0], and the group attrs include kind
      sequence and nstep 1.
    status: pending
  - id: ac-011
    summary: Zarr kind=array stores the pair and refuses a half pair
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_kind_array_round_trips_data_and_sidecar
      tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_kind_array_without_its_sidecar_is_refused
      exits 0. basis values are [1.0, 2.0], meta/basis unit is bohr, group kind
      is array; a data array without meta/<name> makes read raise ValueError.
    status: pending
  - id: ac-012
    summary: Illegal and nested kind stay on the uninterpreted path rules
    type: code
    pass_when: |
      uv run --locked pytest -q tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_an_illegal_kind_on_read_is_refused
      tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_a_nested_kind_attribute_is_not_a_section
      tests/test_core/test_bindings/test_zarr.py::TestZarrRecordCodec::test_reserved_sections_are_written_without_kind
      exits 0. kind widget raises ValueError; a nested kind attribute inside a
      no-kind root group is still a NodeModel; a normal record writes frame,
      status, and meta without a section-kind attribute.
    status: pending
  - id: ac-013
    summary: Overview, objective, and storage name kind without Array-section lumping
    type: docs
    pass_when: |
      docs/spec/specification.md states that a reader learns root-section kind
      from the file and this specification, and it does not call frame, system,
      and trajectory "Array sections". docs/spec/overview.md's QM sketch is a
      kind frame or kind array section, not a tree readable only via a module.
      docs/spec/storage.md's frame-shaped group covers an unnamed root group
      whose kind is frame, and says kind is not a meta key.
    status: pending
  - id: ac-014
    summary: Method and metrics types no longer require a module decode rule
    type: docs
    pass_when: |
      docs/spec/method.md does not say a custom type is valid only when parse
      rules are declared under meta/modules. docs/spec/metrics.md does not say
      a custom type names a module, and it still says each dense series value
      is f64.
    status: pending
  - id: ac-015
    summary: Kind models and read_node document that kind is not a unit
    type: docs
    pass_when: |
      DocumentSectionModel, FrameSectionModel, SequenceSectionModel,
      ArraySectionModel, and read_node each have a plain English docstring
      stating that kind is the closed discriminator document|frame|sequence|array
      and that this section does not attach a unit to values.
    status: pending
  - id: ac-016
    summary: Regression script reproduces the hard-coded kpoints frame
    type: runtime
    pass_when: |
      uv run --locked python regressions/self-describing-record-03-kind.py exits 0.
      The script does not import molrs. It round-trips a record whose extra
      root section kpoints is kind frame, block grid, f64 columns
      kx=[0.0, 0.5], ky=[0.0, 1.0], kz=[-0.25, 0.5] through RecordModel and
      ZarrRecordCodec, and those literals match with exact equality.
    status: pending
  - id: ac-017
    summary: Full check and the locked test suite pass
    type: runtime
    pass_when: |
      uvx ruff@0.16.5 format --check . && uvx ruff@0.16.5 check .
      and uv run --locked pytest -q both exit 0, including the existing
      schema-export and layout-doc drift tests.
    status: pending
---

# Acceptance criteria

- ac-001 至 ac-007 锁住 `RecordModel`：四种 `kind`、非法值、无 `kind` 仍是 `NodeModel`、未命名节不充当实质节、帧 meta 不得占用键 `kind`。
- ac-008 至 ac-012 锁住 `ZarrRecordCodec`：frame / document / sequence / array 走已有布局，非法 `kind` 与半对 array、document 带子节点为 `ValueError`，嵌套 `kind` 不解释，保留名不写节种。
- ac-013 至 ac-015 锁住英文规范与 docstring 的目标句、Array sections 措辞、QM 草图、模块只作引用、metrics 仍为逐点 `f64`。
- ac-016 是本规范唯一的回归脚本，金样为 binary64 精确字面量，精确相等。
- ac-017 是仓库既有的 check 与 pytest。
