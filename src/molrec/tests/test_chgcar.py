"""Tests for the CHGCAR reader and its grid block on the molrs Frame.

All tests use synthetic CHGCAR content generated in-memory so no external
test-data files are required.
"""

from __future__ import annotations

import math
from pathlib import Path

import molrs
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chgcar(
    *,
    spin: bool = False,
    nx: int = 2,
    ny: int = 2,
    nz: int = 2,
    scale: float = 2.87,
    cell_rows: tuple[tuple[float, float, float], ...] | None = None,
    elements: list[str] | None = None,
    counts: list[int] | None = None,
    mode: str = "Direct",
    positions: list[tuple[float, float, float]] | None = None,
) -> str:
    """Return a minimal CHGCAR string.

    The total charge density is set to 1.0 everywhere.
    The spin density (if spin=True) is set to 0.5 everywhere.
    """
    if cell_rows is None:
        cell_rows = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    if elements is None:
        elements = ["Fe"]
    if counts is None:
        counts = [2]
    if positions is None:
        positions = [(0.0, 0.0, 0.0), (0.5, 0.5, 0.5)]

    lines: list[str] = []
    lines.append("Test CHGCAR")
    lines.append(f"   {scale:.10f}")
    for row in cell_rows:
        lines.append(f"   {row[0]:.10f}  {row[1]:.10f}  {row[2]:.10f}")
    lines.append("   " + "  ".join(elements))
    lines.append("   " + "  ".join(str(c) for c in counts))
    lines.append(mode)
    for pos in positions:
        lines.append(f"  {pos[0]:.8f}  {pos[1]:.8f}  {pos[2]:.8f}")
    lines.append("")  # blank line before grid

    n_voxels = nx * ny * nz
    lines.append(f"   {nx}   {ny}   {nz}")
    # Write all values as 1.0, five per line
    vals = [1.0] * n_voxels
    for i in range(0, n_voxels, 5):
        chunk = vals[i : i + 5]
        lines.append("  " + "  ".join(f"{v:.6f}" for v in chunk))

    if spin:
        lines.append("")
        lines.append(f"   {nx}   {ny}   {nz}")
        spin_vals = [0.5] * n_voxels
        for i in range(0, n_voxels, 5):
            chunk = spin_vals[i : i + 5]
            lines.append("  " + "  ".join(f"{v:.6f}" for v in chunk))

    return "\n".join(lines) + "\n"


@pytest.fixture
def chgcar_file(tmp_path: Path) -> Path:
    """Minimal CHGCAR file on disk (no spin)."""
    p = tmp_path / "CHGCAR"
    p.write_text(_make_chgcar())
    return p


@pytest.fixture
def chgcar_spin_file(tmp_path: Path) -> Path:
    """Spin-polarised CHGCAR file on disk."""
    p = tmp_path / "CHGCAR_spin"
    p.write_text(_make_chgcar(spin=True))
    return p


# ---------------------------------------------------------------------------
# TestReadCHGCAR
# ---------------------------------------------------------------------------


class TestReadCHGCAR:
    """Basic I/O tests for read_chgcar_file."""

    def test_returns_frame(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        assert type(frame).__name__ == "Frame"
        assert "atoms" in frame and "grid" in frame

    def test_atoms_block_present(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        assert "atoms" in frame
        assert frame["atoms"].nrows == 2

    def test_atom_symbols(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        atoms = frame["atoms"]
        syms = atoms.view("element")
        assert list(syms) == ["Fe", "Fe"]

    def test_simbox_present(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        assert frame.box is not None

    def test_title_in_meta(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        assert frame.meta.get("title") == "Test CHGCAR"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(Exception):
            molrs.read_chgcar_file(str(tmp_path / "nonexistent_CHGCAR"))


# ---------------------------------------------------------------------------
# TestCHGCARGrid
# ---------------------------------------------------------------------------


class TestCHGCARGrid:
    """Tests that the volumetric grid block on the Frame is correct."""

    def test_grid_key_exists(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        assert "grid" in frame

    def test_grid_npoints(self, chgcar_file):
        """2x2x2 grid = 8 voxels (one flat row each)."""
        frame = molrs.read_chgcar_file(str(chgcar_file))
        assert frame["grid"].nrows == 2 * 2 * 2

    def test_total_array_present(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        assert "total" in frame["grid"].keys()

    def test_total_array_shape(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        total = frame["grid"].view("total")
        assert total.shape == (2 * 2 * 2,)

    def test_total_values_uniform(self, chgcar_file):
        """All total values should be 1.0 (as set in the helper)."""
        frame = molrs.read_chgcar_file(str(chgcar_file))
        total = frame["grid"].view("total")
        np.testing.assert_allclose(total, 1.0, atol=1e-5)

    def test_no_diff_without_spin(self, chgcar_file):
        frame = molrs.read_chgcar_file(str(chgcar_file))
        assert "diff" not in frame["grid"].keys()


# ---------------------------------------------------------------------------
# TestCHGCARSpin
# ---------------------------------------------------------------------------


class TestCHGCARSpin:
    """Tests for spin-polarised CHGCAR (ISPIN=2, total + diff)."""

    def test_diff_array_present(self, chgcar_spin_file):
        frame = molrs.read_chgcar_file(str(chgcar_spin_file))
        assert "diff" in frame["grid"].keys()

    def test_diff_values_uniform(self, chgcar_spin_file):
        """Spin density set to 0.5 in the helper."""
        frame = molrs.read_chgcar_file(str(chgcar_spin_file))
        diff = frame["grid"].view("diff")
        np.testing.assert_allclose(diff, 0.5, atol=1e-5)

    def test_both_arrays_same_shape(self, chgcar_spin_file):
        frame = molrs.read_chgcar_file(str(chgcar_spin_file))
        g = frame["grid"]
        assert g.view("total").shape == g.view("diff").shape


# ---------------------------------------------------------------------------
# TestCHGCARAtomPositions
# ---------------------------------------------------------------------------


class TestCHGCARAtomPositions:
    """Verify atom coordinate conversion from Direct → Cartesian."""

    def test_origin_atom_at_zero(self, chgcar_file):
        """First atom at Direct (0,0,0) → Cartesian (0,0,0)."""
        frame = molrs.read_chgcar_file(str(chgcar_file))
        atoms = frame["atoms"]
        x = atoms.view("x")
        y = atoms.view("y")
        z = atoms.view("z")
        assert abs(float(x[0])) < 1e-4
        assert abs(float(y[0])) < 1e-4
        assert abs(float(z[0])) < 1e-4

    def test_body_center_atom_position(self):
        """BCC body-centre at Direct (0.5, 0.5, 0.5) with scale=2.87,
        orthogonal unit lattice → Cartesian (1.435, 1.435, 1.435)."""
        chgcar = _make_chgcar(scale=2.87)
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix="CHGCAR", mode="w", delete=False) as fh:
            fh.write(chgcar)
            name = fh.name
        try:
            frame = molrs.read_chgcar_file(name)
            atoms = frame["atoms"]
            x = atoms.view("x")
            assert abs(float(x[1]) - 1.435) < 1e-3, f"x={x[1]}"
        finally:
            os.unlink(name)


# ---------------------------------------------------------------------------
# TestCHGCARTriclinic
# ---------------------------------------------------------------------------


class TestCHGCARTriclinic:
    """Triclinic cell handling."""

    def test_triclinic_volume(self):
        """A triclinic cell with non-right angles should give a non-cubic volume."""
        # HCP-like cell: a1=(1,0,0), a2=(0.5, √3/2, 0), a3=(0,0,1)
        sqrt3_2 = math.sqrt(3) / 2
        chgcar = _make_chgcar(
            scale=1.0,
            cell_rows=(
                (1.0, 0.0, 0.0),
                (0.5, sqrt3_2, 0.0),
                (0.0, 0.0, 1.0),
            ),
            elements=["Mg"],
            counts=[1],
            positions=[(0.0, 0.0, 0.0)],
        )
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix="CHGCAR", mode="w", delete=False) as fh:
            fh.write(chgcar)
            name = fh.name
        try:
            frame = molrs.read_chgcar_file(name)
            assert frame.box is not None
            # Volume of HCP-like unit cell = |det(cell)| = sqrt(3)/2 ≈ 0.866
            vol = frame.box.volume()
            assert abs(vol - sqrt3_2) < 1e-4, f"volume={vol}"
        finally:
            os.unlink(name)


# ---------------------------------------------------------------------------
# TestCHGCARRoundtrip (Grid → Zarr → reload)
# ---------------------------------------------------------------------------


class TestCHGCARGridZarrRoundtrip:
    """The Grid read from a CHGCAR survives a MolRec Zarr roundtrip."""

    def test_roundtrip(self, chgcar_spin_file, tmp_zarr_path):
        frame = molrs.read_chgcar_file(str(chgcar_spin_file))

        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        g = loaded.frame["grid"]
        assert g.nrows == 2 * 2 * 2
        assert "total" in g.keys()
        assert "diff" in g.keys()
        np.testing.assert_allclose(g.view("total"), 1.0, atol=1e-5)
        np.testing.assert_allclose(g.view("diff"), 0.5, atol=1e-5)
