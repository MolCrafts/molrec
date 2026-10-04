"""The trajectory binding's self-description: the ``sequence_schema`` attribute.

The reference Zarr binding writes down what a sequence holds. The set of
blocks, columns, dtypes, trailing shapes and per-step meta keys is declared
when the sequence is created and fixed for its lifetime; the reference writer
pins that declaration as the ``trajectory/`` group attribute
``sequence_schema`` (see ``docs/spec/ragged.md``).

The models themselves live in :mod:`molrec.core.model`, beside the
``TrajectoryModel`` whose ``blocks`` / ``meta`` fields *are* that declaration.
This module is the published-schema entry point (``schema/binding/``) and keeps
the historical import path.
"""

from __future__ import annotations

from molrec.core.model import (
    META_TAGS,
    MetaSeriesModel,
    MetaTag,
    SequenceBlockModel,
    SequenceColumnModel,
    SequenceSchemaModel,
    meta_tag,
    meta_tag_parts,
)

__all__ = [
    "META_TAGS",
    "MetaSeriesModel",
    "MetaTag",
    "SequenceBlockModel",
    "SequenceColumnModel",
    "SequenceSchemaModel",
    "meta_tag",
    "meta_tag_parts",
]
