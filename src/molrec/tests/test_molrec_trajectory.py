from __future__ import annotations

import molrs
import numpy as np


class TestTrajectoryFromPDB:
    def test_roundtrip(self, tests_data, tmp_zarr_path):
        frame0 = molrs.read_pdb(str(tests_data / "pdb" / "water.pdb"))
        frame1 = molrs.read_pdb(str(tests_data / "pdb" / "water.pdb"))
        trajectory = molrs.Trajectory(
            [frame0, frame1],
            step=np.array([0, 1], dtype=np.int64),
            time=np.array([0.0, 1.0], dtype=np.float64),
        )
        record = molrs.MolRec()
        record.set_frame(frame0)
        record.set_trajectory(trajectory)
        record.method = {
            "type": "trajectory_import",
            "description": "synthetic pdb trajectory",
        }
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        n_atoms = frame0["atoms"].nrows
        assert loaded.count_frames() == 2
        assert loaded.trajectory[0]["atoms"].nrows == n_atoms
        assert loaded.trajectory[1]["atoms"].nrows == n_atoms
        assert loaded.method["type"] == "trajectory_import"


class TestTrajectoryFromLAMMPS:
    def test_roundtrip(self, tests_data, tmp_zarr_path):
        frames = molrs.read_lammps_traj(
            str(tests_data / "lammps" / "wrapped.lammpstrj")
        )
        record = molrs.MolRec()
        record.set_frame(frames[0])
        for frame in frames:
            record.add_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        assert loaded.count_frames() == len(frames)
        assert loaded.trajectory[0]["atoms"].nrows == frames[0]["atoms"].nrows
