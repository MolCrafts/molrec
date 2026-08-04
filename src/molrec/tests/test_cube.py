"""Tests for the Gaussian Cube reader and its integration with molrs Frames.

Tests use real cube files from tests-data/cube/ (from h5cube project).

Grid data is exposed as a ``"grid"`` block on the Frame: each volumetric
field (``density`` or ``mo_<n>``) is a flat column of length ``nx*ny*nz``,
accessed via ``frame["grid"].view(name)``.
"""

from __future__ import annotations

from pathlib import Path

import molrs
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# TestReadCube – basic I/O
# ---------------------------------------------------------------------------


class TestReadCube:
    """Basic I/O tests for read_cube_file."""

    def test_returns_frame(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "valtest.cube"))
        assert type(frame).__name__ == "Frame"
        assert "atoms" in frame and "grid" in frame

    def test_atoms_block_present(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "valtest.cube"))
        assert "atoms" in frame
        assert frame["atoms"].nrows == 2

    def test_atom_symbols(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "valtest.cube"))
        atoms = frame["atoms"]
        syms = atoms.view("element")
        assert list(syms) == ["H", "H"]

    def test_simbox_present(self, tests_data: Path):
        """Cube files carry voxel axis vectors, exposed as the Frame's box."""
        frame = molrs.read_cube_file(str(tests_data / "cube" / "valtest.cube"))
        assert frame.simbox is not None

    def test_units_in_meta(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20.cube"))
        assert frame.meta.get("cube_units") == "bohr"

    def test_angstrom_units(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20ang.cube"))
        assert frame.meta.get("cube_units") == "angstrom"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(Exception):
            molrs.read_cube_file(str(tmp_path / "nonexistent.cube"))


# ---------------------------------------------------------------------------
# TestCubeGrid – grid block structure
# ---------------------------------------------------------------------------


class TestCubeGrid:
    """Tests that the volumetric grid block on the Frame is correct."""

    def test_grid_key_exists(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "valtest.cube"))
        assert "grid" in frame

    def test_grid_npoints_valtest(self, tests_data: Path):
        """valtest grid is 1x1x5 = 5 points (one flat row per voxel)."""
        frame = molrs.read_cube_file(str(tests_data / "cube" / "valtest.cube"))
        assert frame["grid"].nrows == 5

    def test_grid_npoints_grid20(self, tests_data: Path):
        """grid20 grid is 20x20x20 = 8000 points."""
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20.cube"))
        assert frame["grid"].nrows == 20 * 20 * 20

    def test_density_array_present(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20.cube"))
        assert "density" in frame["grid"].keys()

    def test_density_array_shape(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20.cube"))
        density = frame["grid"].view("density")
        assert density.shape == (20 * 20 * 20,)

    def test_valtest_known_values(self, tests_data: Path):
        """Check known data values from valtest.cube."""
        frame = molrs.read_cube_file(str(tests_data / "cube" / "valtest.cube"))
        density = frame["grid"].view("density")
        # From file: -1.00000E+02 -1.00000E-02 0 1.00000E-02 1.00000E+02
        np.testing.assert_allclose(density[0], -100.0, atol=1e-5)
        np.testing.assert_allclose(density[4], 100.0, atol=1e-5)


# ---------------------------------------------------------------------------
# TestCubeMO – molecular orbital variant
# ---------------------------------------------------------------------------


class TestCubeMO:
    """Tests for MO-mode cube files (negative NATOMS)."""

    def test_mo_grid_keys(self, tests_data: Path):
        """grid20mo6-8.cube has 3 orbitals: mo_6, mo_7, mo_8."""
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20mo6-8.cube"))
        cols = frame["grid"].keys()
        assert "mo_6" in cols
        assert "mo_7" in cols
        assert "mo_8" in cols
        assert "density" not in cols

    def test_mo_indices_meta(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20mo6-8.cube"))
        assert frame.meta.get("cube_mo_indices") == "6,7,8"

    def test_mo_array_shape(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20mo6-8.cube"))
        assert frame["grid"].view("mo_6").shape == (20 * 20 * 20,)

    def test_single_mo(self, tests_data: Path):
        """grid25mo.cube has 1 orbital: mo_5."""
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid25mo.cube"))
        grid = frame["grid"]
        assert "mo_5" in grid.keys()
        assert grid.view("mo_5").shape == (25 * 25 * 25,)
        assert frame.meta.get("cube_mo_indices") == "5"

    def test_mo_atom_count(self, tests_data: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20mo6-8.cube"))
        assert frame["atoms"].nrows == 7


# ---------------------------------------------------------------------------
# TestCubeWriteRoundtrip – read → write → read
# ---------------------------------------------------------------------------


class TestCubeWriteRoundtrip:
    """Roundtrip: read cube → write cube → read back → compare."""

    def test_roundtrip_density(self, tests_data: Path, tmp_path: Path):
        path_in = str(tests_data / "cube" / "valtest.cube")
        path_out = str(tmp_path / "valtest_rt.cube")

        frame1 = molrs.read_cube_file(path_in)
        molrs.write_cube_file(path_out, frame1)
        frame2 = molrs.read_cube_file(path_out)

        assert frame2["atoms"].nrows == frame1["atoms"].nrows
        assert frame2["grid"].nrows == frame1["grid"].nrows

        d1 = frame1["grid"].view("density")
        d2 = frame2["grid"].view("density")
        np.testing.assert_allclose(d2, d1, atol=1e-4)

    def test_roundtrip_grid20(self, tests_data: Path, tmp_path: Path):
        path_in = str(tests_data / "cube" / "grid20.cube")
        path_out = str(tmp_path / "grid20_rt.cube")

        frame1 = molrs.read_cube_file(path_in)
        molrs.write_cube_file(path_out, frame1)
        frame2 = molrs.read_cube_file(path_out)

        assert frame2["atoms"].nrows == 16
        assert frame2["grid"].nrows == 20 * 20 * 20

        d1 = frame1["grid"].view("density")
        d2 = frame2["grid"].view("density")
        np.testing.assert_allclose(d2, d1, rtol=1e-4, atol=1e-20)


# ---------------------------------------------------------------------------
# TestCubeZarrRoundtrip – cube grid survives MolRec Zarr roundtrip
# ---------------------------------------------------------------------------


class TestCubeZarrRoundtrip:
    """The grid block read from a cube file survives a MolRec Zarr roundtrip."""

    def test_density_roundtrip(self, tests_data: Path, tmp_zarr_path: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "valtest.cube"))

        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        g = loaded.frame["grid"]
        assert g.nrows == 5
        assert "density" in g.keys()

        d_orig = frame["grid"].view("density")
        d_loaded = g.view("density")
        np.testing.assert_allclose(d_loaded, d_orig, atol=1e-10)

    def test_grid20_roundtrip(self, tests_data: Path, tmp_zarr_path: Path):
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20.cube"))

        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        g = loaded.frame["grid"]
        assert g.nrows == 20 * 20 * 20
        assert "density" in g.keys()
        assert g.view("density").shape == (20 * 20 * 20,)

    def test_mo_roundtrip(self, tests_data: Path, tmp_zarr_path: Path):
        """MO cube grids (multiple arrays) survive Zarr roundtrip."""
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20mo6-8.cube"))

        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        g = loaded.frame["grid"]
        cols = g.keys()
        assert "mo_6" in cols
        assert "mo_7" in cols
        assert "mo_8" in cols
        assert g.view("mo_6").shape == (20 * 20 * 20,)

        # Compare values
        g_orig = frame["grid"]
        np.testing.assert_allclose(g.view("mo_6"), g_orig.view("mo_6"), atol=1e-10)
        np.testing.assert_allclose(g.view("mo_7"), g_orig.view("mo_7"), atol=1e-10)
        np.testing.assert_allclose(g.view("mo_8"), g_orig.view("mo_8"), atol=1e-10)

    def test_atoms_preserved(self, tests_data: Path, tmp_zarr_path: Path):
        """Atoms block survives the Zarr roundtrip."""
        frame = molrs.read_cube_file(str(tests_data / "cube" / "grid20.cube"))

        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        assert "atoms" in loaded.frame
        assert loaded.frame["atoms"].nrows == 16
