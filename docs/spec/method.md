# Method group

Scientific or training context is stored in the `method` group. Result
arrays stay in `frame`, `trajectory`, or `observables`. Force-field
parameters live in the [`forcefield`](forcefield.md) section.

In the reference binding the contents are group attributes (one JSON
object).

```text
method
 +-- type: string[]
 +-- description: string[]
 \-- engine
      +-- name: string[]
      +-- (version: string[])
```

`type`

Selects parse rules. Standard values are `classical`, `ml`,
`electronic_structure`, and `workflow`. A custom type is valid if its parse
rules are declared under `meta/modules`: **the custom `type` is the module's
name**, so `type: "docking"` is read under `meta/modules/docking`. A reader
that does not know the module keeps the document and interprets none of it.

`description`

Required when the group exists.

`engine.name`

Required when the group exists: a string. `engine.version` is an optional
string; other `engine` keys are preserved.

When `type` is `workflow`, `method.order` is an ordered list of stage ids
(strings) and `method.stages` an object whose `<stage_id>` entries are each
themselves a method document (`type`, `description`, `engine`). Both are
required, and `order` names **every stage exactly once**: a stage `order`
omits, an id with no stage, or an id listed twice is refused. A stage may
itself be a workflow. Under any other `type`, `order` and `stages` are a
producer's keys. Every other key is preserved.
