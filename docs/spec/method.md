# Method group

Scientific or training context is stored in the `method` group. Result
arrays stay in `frame`, `trajectory`, or `observables`. Force-field
parameters: see [Force field](forcefield.md).

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
rules are declared under `meta/modules`.

`description`

Required when the group exists.

`engine.name`

Required when the group exists.

When `type` is `workflow`, `method.order` is an ordered list of stage ids
and each `method.stages.<stage_id>` is itself a typed method block.
