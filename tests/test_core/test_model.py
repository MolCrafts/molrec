"""L2 MetaModel format brand.

Mirrors ``src/molrec/core/model.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from molrec.core.model import MetaModel


class TestMetaModel:
    def test_accepts_mrec(self) -> None:
        meta = MetaModel(record_schema_version=1, format_name="mrec")
        assert meta.format_name == "mrec"
        assert meta.record_schema_version == 1

    def test_none_still_ok_at_l2(self) -> None:
        """L2 brand is optional; the L4 reference binding makes it required."""
        omitted = MetaModel(record_schema_version=1)
        assert omitted.format_name is None
        explicit = MetaModel(record_schema_version=1, format_name=None)
        assert explicit.format_name is None

    def test_rejects_molrec(self) -> None:
        """Hard cut: the old brand is not dual-read."""
        with pytest.raises(ValidationError, match="format_name"):
            MetaModel.model_validate({"record_schema_version": 1, "format_name": "molrec"})

    def test_rejects_other_string(self) -> None:
        with pytest.raises(ValidationError, match="format_name"):
            MetaModel.model_validate({"record_schema_version": 1, "format_name": "zarr"})

    def test_preserves_unknown_keys(self) -> None:
        meta = MetaModel.model_validate({"record_schema_version": 1, "x_vendor_local": "kept"})
        assert meta.model_extra == {"x_vendor_local": "kept"}
