"""Store bases for the core module.

Array-tree semantics: named groups of named arrays, each array typed and
shaped, with attribute maps hanging off groups. Backends that can express
that -- Zarr, HDF5, an in-memory tree -- can carry a frame.

These stay abstract on purpose. The handle a codec actually needs is
backend-specific (a Zarr group, an HDF5 file, a connection), so it belongs on
the concrete subclass rather than being flattened into a universal ``uri``
that a database backend could never honor.
"""

from __future__ import annotations

from molrec.store import Store


class FrameStore(Store):
    """Where one frame lands."""


class TrajectoryStore(Store):
    """Where one sequence of frames lands.

    Same array-tree semantics as a frame, one level up: the sections are
    indexed by frame ordinal rather than written once.
    """


class RecordStore(Store):
    """Where a whole record root lands."""
