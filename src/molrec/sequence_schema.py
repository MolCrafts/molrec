"""The trajectory binding's self-description: ``molrs_sequence_schema``.

The reference Zarr binding writes down what a sequence holds. The set of blocks,
columns, dtypes and trailing shapes is declared when the sequence is created
and fixed for its lifetime; the reference writer pins that declaration as the
``trajectory/`` group attribute ``molrs_sequence_schema`` and requires it when
reopening a sequence (see ``docs/spec/trajectory.md``).

That attribute is the store's *only* self-description, and until now the one
document a reader had to trust carried no published schema of its own -- it was
vendor-namespaced ``molrs_`` for a format branded ``mrec``. This module gives it
a published schema. The dtype vocabulary is not redefined here: it is the one
closed :data:`~molrec.core.model.DType` set every column and meta key in the
contract already draws from. Like the rest of the record's layout it carries no
version of its own -- the sole ``meta["molrec_version"]`` versions it.

These models live in their own module rather than in ``binding.py`` for one
concrete reason: ``binding.py`` is imported during package initialization
(``bench`` -> ``binding``), before ``molrec.core`` finishes its eager suite/
bench registration, so importing :data:`~molrec.core.model.DType` from there
would close an import cycle. This module is only imported after ``core`` is
fully initialized (by ``schema_export`` and by the package ``__init__``).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from molrec.core.model import DType


class SequenceColumnModel(BaseModel):
    """One column's type in a sequence declaration.

    A column is fixed for the run by its ``dtype`` -- the same closed
    vocabulary as :class:`~molrec.core.model.ColumnModel` -- and its
    ``trailing`` axes, the per-entity structure after the leading count axis. A
    ``Float[count][3]`` column declares ``trailing = [3]``; a scalar column
    declares ``trailing = []``.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    dtype: DType
    trailing: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)


class SequenceBlockModel(BaseModel):
    """One block's declaration: its columns, each pinned by dtype and trailing shape."""

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    columns: dict[str, SequenceColumnModel] = Field(default_factory=dict)


class SequenceSchemaModel(BaseModel):
    """The ``trajectory/`` group attribute ``molrs_sequence_schema``.

    ``blocks`` mirrors the frame blocks; ``meta`` declares each per-step meta
    key by its dtype tag (the ``molrs_meta_dtype`` an array carries), drawn from
    the same closed dtype vocabulary as everywhere else.

    The attribute carries no version of its own. Like the rest of the record it
    is versioned by the sole ``meta["molrec_version"]`` -- MolRec has no
    parallel version key, so a change to how the sequence declares itself is a
    bump of that one integer. The literal key ``molrs_sequence_schema`` is the
    reference writer's and is not renamed here. This schema describes the
    sequence declaration only. Record identity lives in
    :class:`~molrec.core.model.MetaModel` (``molrec_version``), not in this
    attribute.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="allow")

    blocks: dict[str, SequenceBlockModel] = Field(default_factory=dict)
    meta: dict[str, DType] = Field(default_factory=dict)
