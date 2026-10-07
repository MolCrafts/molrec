"""The ``observables`` section (``docs/spec/observables.md``).

Each observable is a pair -- a metadata document and one data array -- and
the pair is mandatory. ``kind`` says how the array is read: ``scalar`` (one
value per sample) or ``vector`` (an ordered tuple of components per sample),
with ``axes`` naming trailing axes for higher-rank data. A kind the contract
does not define is **carried through unchanged**, and so is every metadata
key it does not name. The dims-based redesign is the draft in
:mod:`molrec.draft.observables`, not part of the contract.

The data array is a :class:`molrec.core.model.ArrayModel`, the record's one
typed array of any shape.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from molrec.core.model import ArrayModel, DocumentModel

#: The kinds the contract defines. Others are carried through, never refused.
KNOWN_KINDS: tuple[str, ...] = ("scalar", "vector")

#: The child of ``observables/`` that holds the metadata groups. An
#: observable cannot take the name.
OBSERVABLES_META_GROUP = "meta"


def check_observable_name(name: str) -> None:
    """An observable is one array and one metadata group named ``name``: a
    single Zarr node name that is not the reserved ``meta``."""
    if (
        not name
        or name in (".", "..", OBSERVABLES_META_GROUP)
        or "/" in name
        or name.startswith("__")
    ):
        raise ValueError(
            f"observable name {name!r} is not a single node name (non-empty, no '/', not "
            f"'.', '..' or {OBSERVABLES_META_GROUP!r}, no leading '__')"
        )


class ObservableMetaModel(DocumentModel):
    """The ``observables/meta/<name>`` document.

    ``kind``, ``description`` and ``time_dependent`` are required; the rest
    are written only when set. Every other key is a producer's and is kept
    verbatim (``extra="allow"``).
    """

    kind: Annotated[str, Field(min_length=1)]
    description: str
    time_dependent: bool
    unit: str | None = None
    axes: list[str] | None = None
    sampling: str | None = None
    domain: str | None = None
    target: str | None = None


class ObservableModel(BaseModel):
    """One named result: its metadata document and its data array -- the two
    halves the layout stores side by side."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    meta: ObservableMetaModel
    data: ArrayModel

    @model_validator(mode="after")
    def _time_runs_along_the_leading_axis(self) -> ObservableModel:
        if self.meta.time_dependent and not self.data.shape:
            raise ValueError(
                "a time-dependent observable's leading axis is the trajectory axis; a 0-d "
                "array has none"
            )
        return self


class ObservablesModel(BaseModel):
    """The section: every named observable of the record."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    observables: dict[str, ObservableModel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _names_are_node_names(self) -> ObservablesModel:
        for name in self.observables:
            check_observable_name(name)
        return self
