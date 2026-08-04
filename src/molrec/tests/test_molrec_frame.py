from __future__ import annotations

import molrs
import numpy as np


class TestFramePDB:
    def test_roundtrip(self, tests_data, tmp_zarr_path):
        frame = molrs.read_pdb(str(tests_data / "pdb" / "water.pdb"))
        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        assert loaded.count_frames() == 1
        assert "atoms" in loaded.frame
        assert loaded.frame["atoms"].nrows == frame["atoms"].nrows

    def test_meta_and_method_preserved(self, tests_data, tmp_zarr_path):
        frame = molrs.read_pdb(str(tests_data / "pdb" / "water.pdb"))
        record = molrs.MolRec()
        record.set_frame(frame)
        record.meta = {"version": [0, 2], "creator": {"name": "pytest"}}
        record.method = {
            "type": "static_structure",
            "description": "single-frame pdb import",
        }
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        assert loaded.meta["creator"]["name"] == "pytest"
        assert loaded.method["type"] == "static_structure"


class TestScalarObservable:
    def test_roundtrip(self, tests_data, tmp_zarr_path):
        frame = molrs.read_pdb(str(tests_data / "pdb" / "water.pdb"))
        record = molrs.MolRec()
        record.set_frame(frame)

        obs = molrs.ScalarObservable(
            "total_energy",
            np.array([1.0, 1.5, 2.0], dtype=np.float32),
            description="Total energy by step",
            unit="eV",
            axes=["timestep"],
            time_dependent=True,
            sampling="trajectory_sample",
            domain="trajectory",
        )
        record.observables.add(obs)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        assert "total_energy" in loaded.observables
        assert loaded.observables.get("total_energy").kind == "scalar"


class TestVectorObservable:
    def test_roundtrip(self, tests_data, tmp_zarr_path):
        frame = molrs.read_pdb(str(tests_data / "pdb" / "water.pdb"))
        record = molrs.MolRec()
        record.set_frame(frame)

        dipole = record.observables.add_vector(
            "dipole",
            np.array([[0.1, 0.2, 0.3]], dtype=np.float32),
            description="Dipole vector",
            unit="D",
            axes=["sample", "component"],
            domain="record",
        )
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        assert "dipole" in loaded.observables
        assert loaded.observables.get("dipole").kind == dipole.kind


class TestGridInFrame:
    """Volumetric grids live as a Frame block: flat columns of nx*ny*nz rows."""

    def test_roundtrip(self, tests_data, tmp_zarr_path):
        frame = molrs.read_pdb(str(tests_data / "pdb" / "water.pdb"))
        grid = molrs.Block()
        grid.insert("electron_density", np.full(4 * 4 * 4, 0.25, dtype=np.float32))
        grid.insert("spin_density", np.zeros(4 * 4 * 4, dtype=np.float32))
        frame["density"] = grid

        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        loaded_grid = loaded.frame["density"]
        assert loaded_grid.nrows == 4 * 4 * 4
        assert "electron_density" in loaded_grid.keys()
        assert "spin_density" in loaded_grid.keys()
        assert loaded_grid.view("electron_density").shape == (4 * 4 * 4,)
        np.testing.assert_allclose(
            loaded_grid.view("electron_density"), 0.25, atol=1e-5
        )

    def test_multi_array_grid(self, tests_data, tmp_zarr_path):
        frame = molrs.read_pdb(str(tests_data / "pdb" / "water.pdb"))
        grid = molrs.Block()
        grid.insert("total", np.arange(2 * 3 * 4, dtype=np.float32))
        grid.insert("diff", np.zeros(2 * 3 * 4, dtype=np.float32))
        frame["chgcar"] = grid

        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        g = loaded.frame["chgcar"]
        assert set(g.keys()) == {"total", "diff"}
        assert g.view("total").shape == (2 * 3 * 4,)
