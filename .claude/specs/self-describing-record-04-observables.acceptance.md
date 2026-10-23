---
slug: self-describing-record-04-observables
criteria:
  - id: ac-001
    summary: Array accepts matching dims and rejects a rank mismatch
    type: code
    pass_when: |
      tests/test_observables/test_model.py::TestArray accepts
      dims=("bin",), shape=(3,), dtype="f64", data=[0.0, 0.1, 0.2],
      unit="angstrom" with extent == {"bin": 3}, and constructing an Array
      whose len(dims) differs from len(shape) raises ValueError.
    status: pending
  - id: ac-002
    summary: One dimension name has one length, and dims is derived
    type: code
    pass_when: |
      tests/test_observables/test_model.py::TestObservablesModel raises
      ValueError when dim "phi" is length 3 on a coordinate and length 2 on
      an observable, accepts equal lengths, and model_dump() of that model
      has no "dims" key while the dims property equals the map taken from
      the arrays.
    status: pending
  - id: ac-003
    summary: Zarr array attrs carry dims and unit and no kind flag
    type: code
    pass_when: |
      tests/test_observables/test_bindings/test_zarr.py::TestZarrObservablesCodec
      writes one coordinate and one observable, and a zarr open of those
      arrays shows attrs["dims"] as the dimension-name list whose length
      equals the array ndim, unit present only when Array.unit is set, and
      neither "kind" nor "time_dependent" in the attribute map.
    status: pending
  - id: ac-004
    summary: A shared coordinate is stored as one array
    type: code
    pass_when: |
      The same TestZarrObservablesCodec test writes 50 observables over one
      coordinate and the store has exactly one array under coordinates/ and
      50 arrays under observables/.
    status: pending
  - id: ac-005
    summary: Reading observables/meta plus kind raises and does not convert
    type: code
    pass_when: |
      ZarrObservablesCodec.read on a store whose observables group contains
      a child group meta/<name> with attributes kind and time_dependent
      raises ValueError and does not return an ObservablesModel.
    status: pending
  - id: ac-006
    summary: ObservablesSuite cases pin dims and drop kind cases
    type: code
    pass_when: |
      ObservablesSuite.cases() includes free-energy-grid, scattered-samples,
      dimension-without-coordinate, reject-dimension-conflict, and
      reject-kind-layout, and includes none of scalar-and-vector,
      unknown-kind-and-keys-preserved, reject-missing-kind,
      reject-data-without-meta, reject-meta-without-data, or reject-name-meta.
    status: pending
  - id: ac-007
    summary: A default conformance run judges the dims observables module
    type: runtime
    pass_when: |
      REGISTRY.modules() contains "observables" and does not contain
      "draft/observables". ConformanceSuite of the reference zarr adapter
      with modules left unset yields a result whose module is "observables"
      and whose case_id is "free-energy-grid", and no result module starts
      with "draft/".
    status: pending
  - id: ac-008
    summary: A record stores coordinates beside observables and round-trips
    type: code
    pass_when: |
      ZarrRecordCodec write of a RecordModel that has one observable over
      one shared coordinate creates root groups coordinates/ and
      observables/ as siblings, does not create observables/meta, reads
      back equal to the model, and does not place coordinates in
      RecordModel's extra keys.
    status: pending
  - id: ac-009
    summary: PUBLISHED emits the dims observables schemas only
    type: code
    pass_when: |
      PUBLISHED["observables"] is Array, Source, ObservableModel, and
      ObservablesModel from molrec.observables.model; PUBLISHED has no
      "draft/observables" key; schema/draft/observables/ and
      schema/observables/observable-meta.schema.json are absent;
      schema/observables/source.schema.json exists; and
      schema/observables/array.schema.json declares properties dims and
      data and does not require kind.
    status: pending
  - id: ac-010
    summary: Kind fixtures and the draft observables package are gone
    type: code
    pass_when: |
      fixtures/schema/draft/observables/ and
      fixtures/schema/observables/observable-meta/ are absent;
      fixtures/schema/observables/source/ contains valid-one-ref.json and
      invalid-refs-not-a-list.json; src/molrec/draft/observables/ is absent;
      and molrec.observables.model defines neither KNOWN_KINDS nor
      ObservableMetaModel.
    status: pending
  - id: ac-011
    summary: Observables prose no longer specifies the kind layout
    type: docs
    pass_when: |
      docs/spec/observables.md states that coordinates/ and observables/
      are sibling groups, that dims and unit are array attributes, and that
      a reader refuses the meta/<name> plus kind layout without converting
      it. The published-schema table in docs/spec/specification.md has no
      schema/draft/observables/ row. docs/spec/storage.md does not tell a
      reader to use observables/meta/<name>.
    status: pending
  - id: ac-012
    summary: Array.unit docstring says the unit string is not converted
    type: docs
    pass_when: |
      The Array docstring in src/molrec/observables/model.py says unit is a
      unit string stored as given and not converted, and that the number of
      dims equals the rank of shape.
    status: pending
  - id: ac-013
    summary: Metrics stay pointwise scalars and are not edited
    type: code
    pass_when: |
      docs/spec/metrics.md still specifies metrics/series/<safe_name> as
      one f64 per point, and neither docs/spec/metrics.md nor
      docs/spec/metrics-wal.md is modified by this change.
    status: pending
  - id: ac-014
    summary: Regression shows dims on the array without a kind flag
    type: runtime
    pass_when: |
      regressions/self-describing-record-04-observables.py exits 0. It
      writes, via the public observables API and with no molrs import,
      coordinate bin data [0.0, 0.1, 0.2] unit "angstrom" and observable
      rdf data [0.0, 0.8, 1.9]. A zarr open of the arrays, not the codec
      read, sees attrs["dims"] == ["bin"] and shape (3,) on both
      coordinates/bin and observables/rdf, len(dims) equal to each array's
      ndim, and no "kind" or "time_dependent" attribute.
    status: pending
---

# Acceptance criteria

`ac-001` 到 `ac-005` 是模型与 Zarr codec 的单元条。`ac-006` 到 `ac-008` 是套件与记录根：默认运行判定 dims，旧的 `meta` + `kind` 不再是用例，记录上两个组并列且能读回。`ac-009` 与 `ac-010` 是发布面：`PUBLISHED` 只发 dims 四模型，草案 schema、kind 夹具和 `src/molrec/draft/observables/` 都不在。`ac-011` 与 `ac-012` 是散文和 docstring。`ac-013` 钉住 metrics 未被改成观测量。`ac-014` 是唯一的回归例：字面量 `[0.0, 0.1, 0.2]` 与 `[0.0, 0.8, 1.9]`，第二方用 zarr 在数组属性上看到 `dims == ["bin"]`，没有 `kind`。
