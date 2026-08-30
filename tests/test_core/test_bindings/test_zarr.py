"""Store-level pins for the core Zarr binding.

Mirrors ``src/molrec/core/bindings/zarr.py``.

The store here is built by hand with zarr-python rather than through
``ZarrFrameCodec.write``, because the conformance suite structurally cannot
produce it: ``BoxModel._square_and_filled_in`` (``core/model.py:194``)
materializes ``boundary`` on every validation, and ``_write_box``
(``core/bindings/zarr.py:180``) then writes it out whenever it is not None.
A box group carrying no ``boundary`` attribute is therefore unreachable from
a model -- which is precisely why the reader's behaviour on one was never
judged, even though a foreign writer produces exactly that store.

The contract (``docs/spec/conventions.md``, and ``BoxModel``'s own docstring):
an absent boundary is periodic on every axis. The molrs half of this claim --
the two implementations must not read one store as two different physical
systems -- is in ``tests/test_core_conformance.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import zarr

from molrec.core.bindings.zarr import ZarrFrameCodec, ZarrFrameStore


def _box_group_without_boundary(path: Path) -> ZarrFrameStore:
    """A frame whose box declares vectors and origin and nothing else.

    ``origin`` is written on purpose: the only thing absent is the attribute
    under test.
    """
    root = zarr.open_group(store=path, mode="w")
    box = root.create_group("box")
    box.create_array("vectors", shape=(3, 3), dtype="float64")[...] = np.eye(3)
    box.create_array("origin", shape=(3,), dtype="float64")[...] = np.zeros(3)
    return ZarrFrameStore(path)


def test_a_box_group_without_boundary_reads_all_periodic(tmp_path: Path) -> None:
    store = _box_group_without_boundary(tmp_path / "absent-boundary.mrec")
    assert "boundary" not in store.root(mode="r")["box"].attrs, (
        "the store under test must not carry the attribute"
    )

    box = ZarrFrameCodec().read(store).box

    assert box is not None
    assert box.boundary == (True, True, True)
