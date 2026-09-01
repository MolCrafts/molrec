"""Host (non-Record) layout constants — L4 host binding.

A host directory (e.g. a molexp Run) is not a Record. Metrics are
filename-gated so UIs activate without opening Zarr. Products implement
these names in their own modules; they must not ``import molrec`` at
runtime. Tests may import this module to lock the copy.
"""

from __future__ import annotations

DEFAULT_MLP_STEM = "metrics"

MLP_JSONL_SUFFIX = ".mlp.jsonl"
MLP_ZARR_SUFFIX = ".mlp.zarr"
MLP_INDEX_SUFFIX = ".mlp.index.json"
MLP_VL_SUFFIX = ".mlp.vl.json"

METRICS_FORMAT_NAME = "molmetrics"
METRICS_BINDING = "zarr-v3"
METRICS_CATALOG_VERSION = 1
