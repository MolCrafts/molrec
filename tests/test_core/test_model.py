"""MetaModel versioning.

Mirrors ``src/molrec/core/model.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from molrec.core.model import MetaModel


class TestMetaModel:
    def test_requires_molrec_version(self) -> None:
        meta = MetaModel(molrec_version=1)
        assert meta.molrec_version == 1

    def test_rejects_missing_version(self) -> None:
        with pytest.raises(ValidationError, match="molrec_version"):
            MetaModel.model_validate({})

    def test_rejects_version_below_one(self) -> None:
        with pytest.raises(ValidationError, match="molrec_version"):
            MetaModel.model_validate({"molrec_version": 0})

    def test_preserves_unknown_keys(self) -> None:
        meta = MetaModel.model_validate({"molrec_version": 1, "x_vendor_local": "kept"})
        assert meta.model_extra == {"x_vendor_local": "kept"}
