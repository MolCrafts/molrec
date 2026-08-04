from __future__ import annotations

import molrs


class TestStaticBox:
    def test_roundtrip(self, tests_data, tmp_zarr_path):
        frame = molrs.read_pdb(str(tests_data / "pdb" / "1vln-triclinic.pdb"))
        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        assert loaded.frame.box is not None

    def test_simbox_cell_preserved(self, tests_data, tmp_zarr_path):
        frame = molrs.read_pdb(str(tests_data / "pdb" / "1vln-triclinic.pdb"))
        original_simbox = frame.box
        record = molrs.MolRec()
        record.set_frame(frame)
        record.write_zarr(str(tmp_zarr_path))
        loaded = molrs.MolRec.read_zarr(str(tmp_zarr_path))

        loaded_simbox = loaded.frame.box
        assert loaded_simbox is not None
        assert abs(loaded_simbox.volume() - original_simbox.volume()) < 1e-2


class TestNoBoxTrajectory:
    """LAMMPS dump frames carry box bounds → frame.box survives the roundtrip."""

    def test_roundtrip(self, tests_data, tmp_zarr_path):
        # LAMMPS dumps include BOX BOUNDS, so a box is parsed and stored.
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
        assert loaded.frame.box is not None
