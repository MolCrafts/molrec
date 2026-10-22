"""Backends the core module can land in.

Importing a binding registers it. Adding a backend is adding a file here --
no model changes, no harness changes.
"""

from molrec.core.bindings import lmdb as _lmdb  # noqa: F401  (registers on import)
from molrec.core.bindings import zarr as _zarr  # noqa: F401  (registers on import)
