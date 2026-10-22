"""Backends the observables module can land in.

Two, with genuinely different jobs: JSONL is the live write-ahead log a
running job appends to; Zarr is the settled dense form. A record commonly
has both at once.
"""

from molrec.draft.observables.bindings import jsonl as _jsonl  # noqa: F401  (registers on import)
from molrec.draft.observables.bindings import zarr as _zarr  # noqa: F401  (registers on import)
