"""The annotated trees of ``docs/layout.md``, generated from molrec's own codecs.

Every example is built from molrec's models and written by molrec's reference
codecs (Zarr V3 and LMDB) into a temporary directory; what is printed is read
back off disk -- each group's and array's ``zarr.json``, the leading values of
every array, the keys and value bytes of an LMDB file, the entries of a zip.
Nothing here is a hand-written tree, so the chapter cannot drift from the
bytes the codecs write without ``tests/test_layout_doc.py`` noticing.

Usage::

    python scripts/layout_examples.py            # print every generated block
    python scripts/layout_examples.py --write    # regenerate the blocks in docs/layout.md
    python scripts/layout_examples.py --check    # exit 1 when docs/layout.md has drifted

A generated block sits between ``<!-- BEGIN generated:<name> -->`` and
``<!-- END generated:<name> -->`` in the chapter. Output is deterministic:
fixed seeds, no timestamps, no temporary paths.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import sys
import tempfile
import textwrap
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lmdb
import numpy as np
import zarr

from molrec.core.bindings.lmdb import (
    ALIGN,
    FF_KEY,
    INDEX_KEY,
    META_KEY,
    LmdbCollectionCodec,
    LmdbCollectionStore,
)
from molrec.core.bindings.zarr import (
    FROM_ZARR,
    PackedRecordStore,
    ZarrRecordCodec,
    ZarrRecordStore,
    ZarrTrajectoryCodec,
    ZarrTrajectoryStore,
    pack,
)
from molrec.core.model import (
    ArrayModel,
    ArrayNodeModel,
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    ForceFieldModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    MethodModel,
    NodeModel,
    RecordModel,
    SequenceBlockModel,
    SequenceColumnModel,
    SequenceSchemaModel,
    StatusModel,
    StyleModel,
    TrajectoryBoxModel,
    TrajectoryModel,
    parse_style_block_name,
)
from molrec.observables.model import (
    ObservableMetaModel,
    ObservableModel,
    ObservablesModel,
)
from molrec.safe_name import safe_name

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "layout.md"
RUN_FIXTURE = REPO / "fixtures" / "run-minimal"

#: Widest line a generated tree aims for.
WIDTH = 88
#: Leading values shown per array (rows of the leading axis).
LEADING = 6


# ---------------------------------------------------------------------------
# Examples -- molrec models, nothing else
# ---------------------------------------------------------------------------


_NUMPY = {"f64": "float64", "u64": "uint64", "i64": "int64", "i32": "int32", "bool": "bool"}


def column(dtype: str, values: Any, **extra: Any) -> ColumnModel:
    array = np.asarray(values, dtype=None if dtype == "string" else _NUMPY[dtype])
    return ColumnModel(dtype=dtype, shape=array.shape, values=array, **extra)


def block(columns: dict[str, ColumnModel], **extra: Any) -> BlockModel:
    count = next(iter(columns.values())).count if columns else 0
    return BlockModel(count=count, columns=columns, **extra)


def cube(side: float) -> np.ndarray:
    return np.eye(3) * side


def water_frame() -> FrameModel:
    """One water molecule: atoms with a declared precision on x/y/z and a
    nullable B-factor, its two bonds, a 2x2x2 density grid, a cubic box and a
    typed meta document."""
    atoms = block(
        {
            "element": column("string", ["O", "H", "H"]),
            "x": column("f64", [0.0, 0.0, 0.0], precision=1e-3),
            "y": column("f64", [0.0, 0.7572, -0.7572], precision=1e-3),
            "z": column("f64", [0.1173, -0.4692, -0.4692], precision=1e-3),
            "mass": column("f64", [15.999, 1.008, 1.008]),
            # An X-ray structure resolves the oxygen only: no B-factor for H.
            "b_factor": column("f64", [11.8, 0.0, 0.0], validity=np.array([True, False, False])),
        }
    )
    bonds = block(
        {
            "atomi": column("u64", [0, 0]),
            "atomj": column("u64", [1, 2]),
            "bond_type": column("u64", [1, 1]),
        }
    )
    rng = np.random.default_rng(7)
    density = block(
        {"rho": column("f64", np.round(rng.uniform(0.0, 0.05, 8), 4))}, structural_shape=(2, 2, 2)
    )
    return FrameModel(
        blocks={"atoms": atoms, "bonds": bonds, "density": density},
        box=BoxModel(vectors=cube(10.0)),
        meta={
            "smiles": "O",
            "total_charge": 0,
            "units": {"length": "angstrom", "mass": "dalton"},
        },
    )


#: Hydrogen peroxide, H-O-O-H: rows 0..3 of every H2O2 ``atoms`` block.
H2O2_ELEMENTS = ["H", "O", "O", "H"]
H2O2_TYPES = ["H1", "O1", "O1", "H1"]
H2O2_XYZ = np.array(
    [[0.839, 0.880, 0.422], [0.0, 0.734, 0.0], [0.0, -0.734, 0.0], [-0.839, -0.880, 0.422]]
)


def h2o2_system(full: bool = True) -> FrameModel:
    """The H2O2 topology, typed against :func:`h2o2_forcefield`."""
    blocks = {
        "atoms": block(
            {"element": column("string", H2O2_ELEMENTS), "type": column("string", H2O2_TYPES)}
        ),
        "bonds": block(
            {
                "atomi": column("u64", [0, 1, 2]),
                "atomj": column("u64", [1, 2, 3]),
                "type": column("string", ["O1-H1", "O1-O1", "O1-H1"]),
            }
        ),
    }
    if full:
        blocks["angles"] = block(
            {
                "atomi": column("u64", [0, 3]),
                "atomj": column("u64", [1, 2]),
                "atomk": column("u64", [2, 1]),
                "type": column("string", ["H1-O1-O1", "H1-O1-O1"]),
            }
        )
        blocks["dihedrals"] = block(
            {
                "atomi": column("u64", [0]),
                "atomj": column("u64", [1]),
                "atomk": column("u64", [2]),
                "atoml": column("u64", [3]),
                "type": column("string", ["H1-O1-O1-H1"]),
            }
        )
    return FrameModel(blocks=blocks, meta={"smiles": "OO", "total_charge": 0})


def h2o2_forcefield() -> ForceFieldModel:
    """A small force field for H2O2: one table per style, a wildcard torsion
    row, a string parameter (``ptype``) and absent second-term parameters.
    The numbers are as the force-field IR defines them (LAMMPS's standard):
    an un-halved ``K``, angles and phases in degrees."""

    def names(*values: str) -> ColumnModel:
        return column("string", list(values))

    # The specific torsion has two cosine terms, the generic one only one.
    second_term = np.array([True, False])
    styles = [
        StyleModel(category="atom", style="full"),
        StyleModel(category="bond", style="harmonic"),
        StyleModel(category="angle", style="harmonic"),
        StyleModel(category="dihedral", style="periodic"),
        StyleModel(category="pair", style="lj/cut", params={"cutoff": 10.0, "mixing": "geometric"}),
    ]
    atom, bond, angle, dihedral, pair = (style.block for style in styles)
    tables = {
        atom: block(
            {
                "name": names("H1", "O1"),
                "element": names("H", "O"),
                "mass": column("f64", [1.008, 15.999]),
                "charge": column("f64", [0.41, -0.41]),
                "ptype": names("A", "A"),
            }
        ),
        bond: block(
            {
                "name": names("O1-O1", "O1-H1"),
                "itom": names("O1", "O1"),
                "jtom": names("O1", "H1"),
                "k": column("f64", [300.0, 553.0]),
                "r0": column("f64", [1.475, 0.967]),
            }
        ),
        angle: block(
            {
                "name": names("H1-O1-O1"),
                "itom": names("H1"),
                "jtom": names("O1"),
                "ktom": names("O1"),
                "k": column("f64", [50.0]),
                "theta0": column("f64", [100.2]),
            }
        ),
        dihedral: block(
            {
                "name": names("H1-O1-O1-H1", "X-O1-O1-X"),
                "itom": names("H1", ""),
                "jtom": names("O1", "O1"),
                "ktom": names("O1", "O1"),
                "ltom": names("H1", ""),
                "k1": column("f64", [1.2, 0.5]),
                "periodicity1": column("f64", [1.0, 3.0]),
                "phase1": column("f64", [0.0, 0.0]),
                "k2": column("f64", [0.8, 0.0], validity=second_term),
                "periodicity2": column("f64", [2.0, 0.0], validity=second_term),
                "phase2": column("f64", [180.0, 0.0], validity=second_term),
            }
        ),
        pair: block(
            {
                "name": names("O1-O1", "H1-H1"),
                "itom": names("O1", "H1"),
                "jtom": names("O1", "H1"),
                "epsilon": column("f64", [0.17, 0.0]),
                "sigma": column("f64", [3.0, 1.0]),
            }
        ),
    }
    return ForceFieldModel(
        name="h2o2-demo",
        units={"preset": "real"},
        special_bonds={"lj": [0.0, 0.0, 0.5], "coul": [0.0, 0.0, 0.8333]},
        styles=styles,
        tables=tables,
    )


def xyz_block(positions: np.ndarray, **extra: ColumnModel) -> BlockModel:
    return block(
        {
            **extra,
            **{axis: column("f64", positions[:, i].copy()) for i, axis in enumerate("xyz")},
        }
    )


def fixed_trajectory() -> TrajectoryModel:
    """H2O2 vibrating for 4 frames: positions only (the topology is ``system``),
    dumped every 100 steps at 0.5 time units apart, a fixed cell, two per-step
    scalars."""
    rng = np.random.default_rng(11)
    frames = []
    for i in range(4):
        positions = np.round(H2O2_XYZ + rng.normal(0.0, 0.02, H2O2_XYZ.shape), 4)
        frames.append(
            FrameModel(
                blocks={"atoms": xyz_block(positions)},
                meta={
                    "pe": round(-12.4 + 0.3 * math.sin(i), 4),
                    "temp": [300.0, 302.5, 297.1][i % 3],
                },
            )
        )
    return TrajectoryModel(
        frames=frames,
        step=[0, 100, 200, 300],
        time=[0.5 * i for i in range(4)],
        meta={"pe": MetaSeriesModel(dtype="f64"), "temp": MetaSeriesModel(dtype="f64")},
        box=TrajectoryBoxModel(
            updates=[BoxUpdateModel(step_index=0, box=CellModel(vectors=cube(20.0)))]
        ),
    )


def variable_trajectory() -> TrajectoryModel:
    """Two OH radicals recombine to H2O2 at frame 2 (bonds and types change);
    an argon atom is inserted at frame 3 (grand-canonical); the barostat
    resizes the cell at frame 4."""
    rng = np.random.default_rng(23)
    argon = np.array([[3.0, 3.0, 3.0]])

    def positions(n: int) -> np.ndarray:
        base = H2O2_XYZ if n == 4 else np.vstack([H2O2_XYZ, argon])
        return np.round(base + rng.normal(0.0, 0.02, base.shape), 4)

    def atoms(n: int) -> BlockModel:
        elements = column("string", (H2O2_ELEMENTS + ["Ar"])[:n])
        return xyz_block(positions(n), element=elements)

    def types(values: list[str]) -> BlockModel:
        return block({"type": column("string", values)})

    def bonds(pairs: list[tuple[int, int]]) -> BlockModel:
        return block(
            {
                "atomi": column("u64", [i for i, _ in pairs]),
                "atomj": column("u64", [j for _, j in pairs]),
            }
        )

    def insertions(rows: list[int]) -> BlockModel:
        return block({"atomi": column("u64", rows)})

    radicals = ["HO", "OH", "OH", "HO"]
    peroxide = ["H1", "O1", "O1", "H1"]
    frames = [
        {"atoms": atoms(4), "bonds": bonds([(0, 1), (2, 3)]), "atom_types": types(radicals)},
        {"atoms": atoms(4)},
        {
            "atoms": atoms(4),
            "bonds": bonds([(0, 1), (1, 2), (2, 3)]),
            "atom_types": types(peroxide),
        },
        {"atoms": atoms(5), "atom_types": types(peroxide + ["Ar"]), "insertions": insertions([4])},
        {"atoms": atoms(5), "insertions": insertions([])},
    ]
    pe = [-4.1, -4.3, -12.2, -12.4, -12.3]
    declared = {
        "atoms": SequenceBlockModel(
            columns={
                "element": SequenceColumnModel(dtype="string"),
                **{axis: SequenceColumnModel(dtype="f64") for axis in "xyz"},
            }
        ),
        "bonds": SequenceBlockModel(
            columns={name: SequenceColumnModel(dtype="u64") for name in ("atomi", "atomj")}
        ),
        "atom_types": SequenceBlockModel(
            columns={"type": SequenceColumnModel(dtype="string")}, aligned_with="atoms"
        ),
        "insertions": SequenceBlockModel(columns={"atomi": SequenceColumnModel(dtype="u64")}),
    }
    return TrajectoryModel(
        frames=[FrameModel(blocks=blocks, meta={"pe": pe[i]}) for i, blocks in enumerate(frames)],
        step=[0, 10, 20, 25, 30],
        blocks=declared,
        meta={"pe": MetaSeriesModel(dtype="f64")},
        box=TrajectoryBoxModel(
            updates=[
                BoxUpdateModel(step_index=0, box=CellModel(vectors=cube(12.0))),
                BoxUpdateModel(step_index=4, box=CellModel(vectors=cube(12.25))),
            ]
        ),
    )


def observables() -> ObservablesModel:
    return ObservablesModel(
        observables={
            "dipole": ObservableModel(
                meta=ObservableMetaModel(
                    kind="vector",
                    description="molecular dipole moment",
                    time_dependent=False,
                    unit="e*angstrom",
                ),
                data=_array(np.array([0.0, 0.0, 0.3929])),
            ),
            "msd": ObservableModel(
                meta=ObservableMetaModel(
                    kind="scalar",
                    description="mean squared displacement",
                    time_dependent=True,
                    unit="angstrom**2",
                    sampling="per_frame",
                ),
                data=_array(np.array([0.0, 0.0011, 0.0024, 0.0031])),
            ),
        }
    )


def _array(values: np.ndarray) -> ArrayModel:
    return ArrayModel(dtype="f64", shape=values.shape, values=values)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((RUN_FIXTURE / "attrs" / name).read_text())


def run_wal() -> bytes:
    """The live metrics WAL of the run-minimal fixture."""
    return (RUN_FIXTURE / "metrics" / "metrics.jsonl").read_bytes()


def metrics_node() -> NodeModel:
    """The fixture's WAL densified (``docs/spec/metrics.md``): one f64 series,
    one i64 step and one RFC 3339 time per point, per key, later duplicate
    step winning; the catalog is the fixture's own, its watermark covering
    every line."""
    points: dict[str, dict[Any, dict[str, Any]]] = {}
    for line in run_wal().decode().splitlines():
        event = json.loads(line)
        points.setdefault(event["k"], {})[event.get("s", object())] = event
    series, steps, times = {}, {}, {}
    for key, events in points.items():
        name = safe_name(key)
        rows = list(events.values())
        series[name] = _node_array("f64", [event["v"] for event in rows])
        steps[name] = _node_array("i64", [event["s"] for event in rows])
        times[name] = _node_array("string", [event["w"] for event in rows])
    return NodeModel(
        attributes=_fixture("metrics.summary.json"),
        groups={
            "series": NodeModel(arrays=series),
            "steps": NodeModel(arrays=steps),
            "wall_time": NodeModel(arrays=times),
        },
    )


def _node_array(dtype: str, values: list[Any]) -> ArrayNodeModel:
    array = np.asarray(values, dtype=None if dtype == "string" else _NUMPY[dtype])
    return ArrayNodeModel(dtype=dtype, shape=array.shape, values=array)


def run_record() -> RecordModel:
    return RecordModel(
        meta=MetaModel.model_validate(_fixture("meta.json")),
        status=StatusModel.model_validate(_fixture("status.json")),
        method=MethodModel(
            type="training",
            description="fit a potential to the H2O2 conformers",
            engine={"name": "molnex", "version": "0.0.0"},
        ),
        metrics=metrics_node(),
    )


def overview_record() -> RecordModel:
    """Every root section at once -- more than a real record carries."""
    run = run_record()
    return RecordModel(
        meta=run.meta,
        frame=water_frame(),
        system=h2o2_system(),
        trajectory=fixed_trajectory(),
        forcefield=h2o2_forcefield(),
        observables=observables(),
        status=run.status,
        method=run.method,
        metrics=run.metrics,
    )


def collection() -> CollectionModel:
    """Two H2O2 conformer records sharing one declaration and one force field."""
    rng = np.random.default_rng(31)

    def conformer(frames: int, record_id: str, repeat_last: bool) -> RecordModel:
        steps, meta, blocks = [], [], []
        positions = H2O2_XYZ
        for i in range(frames):
            if not (repeat_last and i == frames - 1):
                positions = np.round(H2O2_XYZ + rng.normal(0.0, 0.03, H2O2_XYZ.shape), 3)
            steps.append(i)
            meta.append({"pe": round(-12.4 + 0.1 * i, 3)})
            blocks.append({"atoms": xyz_block(positions)})
        return RecordModel(
            meta=MetaModel(record_id=record_id),
            system=h2o2_system(full=False),
            trajectory=TrajectoryModel(
                frames=[FrameModel(blocks=b, meta=m) for b, m in zip(blocks, meta, strict=True)],
                step=steps,
                meta={"pe": MetaSeriesModel(dtype="f64")},
            ),
        )

    schema = SequenceSchemaModel(
        blocks={
            "atoms": SequenceBlockModel(
                columns={axis: SequenceColumnModel(dtype="f64", precision=1e-3) for axis in "xyz"}
            )
        },
        meta={"pe": MetaSeriesModel(dtype="f64")},
    )
    records = [conformer(3, "h2o2-0", repeat_last=True), conformer(2, "h2o2-1", repeat_last=False)]
    return CollectionModel(
        meta=CollectionMetaModel(units={"length": "angstrom", "energy": "kcal/mol"}),
        sequence_schema=schema,
        index=block({"smiles": column("string", ["OO", "OO"])}),
        forcefield=h2o2_forcefield(),
        records=records,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def fmt_scalar(value: Any) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number):
            return "NaN"
        if math.isinf(number):
            return "Infinity" if number > 0 else "-Infinity"
        text = f"{number:.10g}"
        return text + ".0" if re.fullmatch(r"-?\d+", text) else text
    return json.dumps(str(value), ensure_ascii=False)


def fmt_values(array: Any, limit: int = LEADING, leading: bool = True) -> str:
    """The first ``limit`` entries of ``array``'s leading axis as a JSON-ish
    list; a trailing axis (a 3-vector, a 3x3 cell) is shown whole up to 3."""
    array = np.asarray(array)
    if array.ndim == 0:
        return fmt_scalar(array[()])
    rows = limit if leading else (len(array) if len(array) <= 3 else 2)
    items = [fmt_values(row, limit, leading=False) for row in array[:rows]]
    tail = ", …" if len(array) > rows else ""
    return "[" + ", ".join(items) + tail + "]"


def shape_text(dtype: str, shape: list[int] | tuple[int, ...]) -> str:
    return dtype + "".join(f"[{n}]" for n in shape) if shape else f"{dtype}[]"


def _elide(value: Any) -> Any:
    """Long strings and long lists cut short with an ellipsis."""
    if isinstance(value, str) and len(value) > 44:
        return value[:40] + "…"
    if isinstance(value, list):
        items = [_elide(item) for item in value[:8]]
        return [*items[:6], Ellipsis] if len(value) > 8 else items
    if isinstance(value, dict):
        return {key: _elide(item) for key, item in value.items()}
    return value


def compact(value: Any) -> str:
    if value is Ellipsis:
        return "…"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(k)}: {compact(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(compact(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def pretty(value: Any, width: int, lead: int = 0) -> list[str]:
    """``value`` as JSON in ``width`` columns (its first line after ``lead``
    columns of label): one line when it fits, otherwise one member per line,
    each nested member that fits kept on one line."""
    return _pretty(_elide(value), width, lead)


def _pretty(value: Any, width: int, lead: int) -> list[str]:
    flat = compact(value)
    if lead + len(flat) <= width or not isinstance(value, (dict, list)) or not value:
        return [flat]
    pairs = (
        [(json.dumps(k) + ": ", v) for k, v in value.items()]
        if isinstance(value, dict)
        else [("", v) for v in value]
    )
    lines = ["{" if isinstance(value, dict) else "["]
    for index, (head, item) in enumerate(pairs):
        inner = _pretty(item, width - 2, len(head))
        inner[0] = head + inner[0]
        if index < len(pairs) - 1:
            inner[-1] += ","
        lines += ["  " + line for line in inner]
    lines.append("}" if isinstance(value, dict) else "]")
    return lines


def fence(lines: list[str], info: str = "text") -> str:
    return "\n".join([f"```{info}", *lines, "```"])


# ---------------------------------------------------------------------------
# Zarr trees, read off disk
# ---------------------------------------------------------------------------


@dataclass
class Item:
    """One line of a tree (plus its continuation lines and children)."""

    kind: str  # "attr" | "child" | "note"
    lines: list[str]
    children: list[Item] = field(default_factory=list)


def render(items: list[Item], prefix: str = " ") -> list[str]:
    out: list[str] = []
    for index, item in enumerate(items):
        last = index == len(items) - 1
        rest = prefix + ("     " if last else "|    ")
        if item.kind == "note":
            out += [prefix + line for line in item.lines]
            continue
        connector = "+-- " if item.kind == "attr" else "\\-- "
        out.append(prefix + connector + item.lines[0])
        out += [rest + line for line in item.lines[1:]]
        out += render(item.children, rest)
    return out


_FIRST = [
    "meta",
    "system",
    "frame",
    "trajectory",
    "forcefield",
    "observables",
    "method",
    "status",
    "metrics",
    "step_index",
    "offset",
    "step",
    "time",
    "atoms",
    "bonds",
    "name",
    "itom",
    "jtom",
    "ktom",
    "ltom",
    "mtom",
    "atomi",
    "atomj",
    "atomk",
    "atoml",
    "atomm",
    "series",
    "steps",
    "wall_time",
]


def _order(path: Path) -> tuple[int, str]:
    name = path.name
    if name in _FIRST:
        return _FIRST.index(name), name
    if name == "box":
        return 200, name
    if name == "_validity":
        return 300, name
    if not (path / "zarr.json").exists():
        return 250, name
    return 100, name


def _codec(codec: dict[str, Any]) -> str:
    name, config = codec["name"], codec.get("configuration", {})
    if name == "gzip":
        return f"gzip({config['level']})"
    if name == "zstd":
        return f"zstd({config['level']})"
    if name == "numcodecs.shuffle":
        return f"shuffle({config['elementsize']})"
    return name


def storage(meta: dict[str, Any]) -> str:
    """An array's chunking and codec pipeline, abbreviated."""
    grid = meta["chunk_grid"]["configuration"]["chunk_shape"]
    codecs = meta["codecs"]
    if codecs[0]["name"] == "sharding_indexed":
        inner = codecs[0]["configuration"]
        pipeline = " → ".join(_codec(codec) for codec in inner["codecs"])
        return f"zarr: shard {list(grid)}, chunk {list(inner['chunk_shape'])} · {pipeline}"
    return f"zarr: chunk {list(grid)} · " + " → ".join(_codec(codec) for codec in codecs)


def attr_items(attrs: dict[str, Any], indent: int) -> list[Item]:
    items = []
    for key, value in attrs.items():
        head = f"{key}: "
        lines = pretty(value, WIDTH - indent, len(head))
        lines[0] = head + lines[0]
        items.append(Item("attr", lines))
    return items


def node_items(path: Path, indent: int, notes: bool, depth: int | None) -> list[Item]:
    """The children of the group at ``path``: its attributes, then its members."""
    meta = json.loads((path / "zarr.json").read_text())
    items = attr_items(meta.get("attributes", {}), indent)
    if depth == 0:
        return items
    for child in sorted((p for p in path.iterdir() if p.name != "zarr.json"), key=_order):
        items.append(member(child, indent + 5, notes, None if depth is None else depth - 1))
    return items


def member(path: Path, indent: int, notes: bool, depth: int | None) -> Item:
    metadata = path / "zarr.json"
    if not metadata.exists():
        return Item("child", [f"{path.name}    (a plain file, not a Zarr node)"])
    meta = json.loads(metadata.read_text())
    if meta["node_type"] == "group":
        return Item("child", [path.name + "/"], node_items(path, indent, notes, depth))
    dtype = FROM_ZARR[meta["data_type"]]
    values = zarr.open_array(store=path, mode="r")[...]
    label = f"{path.name}: {shape_text(dtype, meta['shape'])} ="
    lines = [f"{label} {fmt_values(values)}"]
    if len(lines[0]) > WIDTH - (indent - 1):
        # A row-per-entity array keeps its rows whole on a line of their own;
        # a flat one shows fewer leading values.
        split = values.ndim >= 2
        room = WIDTH - indent if split else WIDTH - (indent - 1) - len(label) - 1
        limit = LEADING if values.ndim == 1 else 3
        while len(fmt_values(values, limit)) > room and limit > 1:
            limit -= 1
        text = fmt_values(values, limit)
        lines = [label, text] if split else [f"{label} {text}"]
    children = [Item("note", [storage(meta)])] if notes else []
    children += attr_items(meta.get("attributes", {}), indent + 5)
    return Item("child", lines, children)


def zarr_tree(
    root: Path,
    label: str,
    only: list[str] | None = None,
    notes: bool = True,
    depth: int | None = None,
) -> list[str]:
    """``root`` as an annotated tree; ``only`` keeps those root members."""
    meta = json.loads((root / "zarr.json").read_text())
    items = attr_items(meta.get("attributes", {}), 1)
    for child in sorted((p for p in root.iterdir() if p.name != "zarr.json"), key=_order):
        if only is None or child.name in only:
            items.append(member(child, 6, notes, depth))
    return [label, *render(items)]


# ---------------------------------------------------------------------------
# The blocks of docs/layout.md
# ---------------------------------------------------------------------------

#: What each root section is (docs/spec/overview.md, section kinds).
SECTION_KINDS = {
    "meta": "document",
    "status": "document",
    "method": "document",
    "frame": "frame-shaped",
    "system": "frame-shaped",
    "forcefield": "frame-shaped",
    "trajectory": "sequence",
    "observables": "array section",
    "metrics": "catalog + series",
}


def block_overview(work: Path) -> str:
    root = work / "tour.mrec"
    ZarrRecordCodec().write(overview_record(), ZarrRecordStore(root))
    (root / "metrics" / "metrics.jsonl").write_bytes(run_wal())
    root_attrs = json.loads((root / "zarr.json").read_text())["attributes"]
    lines = [f"tour.mrec/          the root group; its attributes: {compact(root_attrs)}"]
    sections = sorted((p for p in root.iterdir() if p.name != "zarr.json"), key=_order)
    for index, path in enumerate(sections):
        bar = " " if index == len(sections) - 1 else "|"
        attrs = list(json.loads((path / "zarr.json").read_text())["attributes"])
        children = [
            p.name + ("/" if _is_group(p) else "")
            for p in sorted((p for p in path.iterdir() if p.name != "zarr.json"), key=_order)
        ]
        head = f" \\-- {path.name + '/':<14} {SECTION_KINDS[path.name]:<17}"
        what = []
        if attrs:
            what += wrap(f"attributes: {', '.join(attrs)}", WIDTH - len(head), 12)
        if children:
            what += wrap(f"children:   {', '.join(children)}", WIDTH - len(head), 12)
        for row, text in enumerate(what):
            lead = head if row == 0 else f" {bar}" + " " * (len(head) - 2)
            lines.append(lead + text)
    return fence(lines)


def _is_group(path: Path) -> bool:
    """A Zarr group (a plain file, such as the metrics WAL, is not one)."""
    metadata = path / "zarr.json"
    return metadata.exists() and json.loads(metadata.read_text())["node_type"] == "group"


def block_frame(work: Path) -> str:
    root = work / "water.mrec"
    ZarrRecordCodec().write(
        RecordModel(meta=MetaModel(), frame=water_frame()), ZarrRecordStore(root)
    )
    return fence(zarr_tree(root, "water.mrec/"))


def block_trajectory_fixed(work: Path) -> str:
    root = work / "vibration.mrec"
    record = RecordModel(
        meta=MetaModel(), system=h2o2_system(full=False), trajectory=fixed_trajectory()
    )
    ZarrRecordCodec().write(record, ZarrRecordStore(root))
    return fence(zarr_tree(root, "vibration.mrec/"))


def block_trajectory_variable(work: Path) -> str:
    root = work / "reaction.mrec"
    ZarrTrajectoryCodec().write(variable_trajectory(), ZarrTrajectoryStore(root))
    return fence(zarr_tree(root, "reaction.mrec/"))


def _section_index(group: zarr.Group, nstep: int) -> tuple[list[int], list[int]]:
    """A trajectory section's ``(step_index, offset)``, the elided form expanded
    (``docs/spec/ragged.md``, resolving a frame)."""
    if "step_index" in group:
        ordinals = [int(v) for v in group["step_index"][...] if v < nstep]
        return ordinals, [int(v) for v in group["offset"][: len(ordinals) + 1]]
    rows = group.attrs.get("uniform_rows")
    if rows is None:
        return [], [0]  # declared, never updated: absent at every ordinal
    arrays = [m for _, m in group.members() if isinstance(m, zarr.Array)]
    n_updates = min(min(int(a.shape[0]) for a in arrays) // rows, nstep)
    return list(range(n_updates)), [j * rows for j in range(n_updates + 1)]


def block_resolve(work: Path) -> str:
    """For every frame of ``reaction.mrec``: which update of each section it
    resolves to, by the reader's binary search over the arrays on disk."""
    root = zarr.open_group(store=work / "reaction.mrec", mode="r")["trajectory"]
    nstep = root.attrs["nstep"]
    steps = [int(v) for v in root["step"][...]]
    names = list(root.attrs["sequence_schema"]["blocks"])
    header = ["frame `i`", "`step[i]`", *(f"`{name}`" for name in names), "`box`"]
    rows = [header, ["---"] * len(header)]
    for i in range(nstep):
        cells = [str(i), str(steps[i])]
        for name in names:
            ordinals, offset = _section_index(root[name], nstep)
            j = bisect.bisect_right(ordinals, i) - 1
            if j < 0:
                cells.append("absent")
                continue
            start, stop = offset[j], offset[j + 1]
            rows_ = stop - start
            state = "empty" if rows_ == 0 else f"{rows_} row" + ("s" if rows_ > 1 else "")
            cells.append(f"j={j} → `{start}:{stop}` ({state})")
        box = [int(v) for v in root["box/step_index"][...]]
        j = bisect.bisect_right(box, i) - 1
        cells.append(f"j={j} (edge {fmt_scalar(root['box/vectors'][j, 0, 0])})")
        rows.append(cells)
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


def block_forcefield(work: Path) -> str:
    root = work / "peroxide.mrec"
    record = RecordModel(meta=MetaModel(), system=h2o2_system(), forcefield=h2o2_forcefield())
    ZarrRecordCodec().write(record, ZarrRecordStore(root))
    return fence(zarr_tree(root, "peroxide.mrec/", only=["forcefield"]))


def block_ff_system(work: Path) -> str:
    return fence(zarr_tree(work / "peroxide.mrec", "peroxide.mrec/", only=["system"], notes=False))


def block_linking(work: Path) -> str:
    """Each system row's ``type``, resolved by name against the tables read back."""
    record = ZarrRecordCodec().read(ZarrRecordStore(work / "peroxide.mrec"))
    ff, system = record.forcefield, record.system
    categories = {"atoms": "atom", "bonds": "bond", "angles": "angle", "dihedrals": "dihedral"}
    rows = [
        ["system row", "`type`", "table → row", "parameters"],
        ["---"] * 4,
    ]
    for block_name, category in categories.items():
        table_block = system.blocks[block_name]
        types = table_block.columns["type"].values
        seen: set[str] = set()
        for r, name in enumerate(types.tolist()):
            if name in seen:
                continue
            seen.add(name)
            for table_name, table in ff.tables.items():
                if parse_style_block_name(table_name)[0] != category:
                    continue
                names = table.columns["name"].values.tolist()
                if name not in names:
                    continue
                t = names.index(name)
                params = [
                    f"{col} {fmt_scalar(c.values[t])}"
                    for col, c in sorted(table.columns.items())
                    if c.dtype == "f64" and (c.validity is None or c.validity[t])
                ]
                rows.append(
                    [
                        f"`{block_name}[{r}]`",
                        f"`{name}`",
                        f"`{table_name}` row {t}",
                        ", ".join(params),
                    ]
                )
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


def block_observables(work: Path) -> str:
    from molrec.observables.bindings.zarr import ZarrObservablesCodec, ZarrObservableStore

    root = work / "results.mrec"
    ZarrObservablesCodec().write(observables(), ZarrObservableStore(root))
    return fence(zarr_tree(root, "results.mrec/", only=["observables"]))


def block_metrics(work: Path) -> str:
    root = work / "fit.mrec"
    ZarrRecordCodec().write(run_record(), ZarrRecordStore(root))
    (root / "metrics" / "metrics.jsonl").write_bytes(run_wal())
    tree = zarr_tree(root, "fit.mrec/", only=["meta", "status", "method", "metrics"])
    wal = ["", "metrics/metrics.jsonl:", *run_wal().decode().splitlines()]
    return fence(tree + wal)


# -- LMDB ---------------------------------------------------------------------


def _key_text(raw: bytes) -> str:
    if raw in (META_KEY, INDEX_KEY, FF_KEY):
        return raw.decode()
    prefix, number = raw[:1].decode(), int.from_bytes(raw[1:], "big")
    return f"{prefix} ‖ u64be({number})"


def _frame_parts(value: bytes) -> tuple[dict[str, Any], int, int]:
    """``(header, header_length, payload_start)`` of a frame-bytes value."""
    length = int.from_bytes(value[4:8], "little")
    header = json.loads(value[8 : 8 + length])
    start = 8 + length
    start += (-start) % ALIGN
    return header, length, start


def _frame_summary(header: dict[str, Any]) -> list[str]:
    """A frame-bytes header in a few lines: step and meta, then one entry per
    block -- its string columns (whose values ride in the header) and its
    numeric buffers with their payload offsets."""
    lines = []
    head = []
    if "step" in header:
        head.append(
            f"step {header['step']}" + (f", time {header['time']}" if "time" in header else "")
        )
    meta = header.get("meta") or {}
    if meta:
        flat = compact(meta)
        head.append("meta " + (flat if len(flat) < 50 else "keys " + ", ".join(meta)))
    if header.get("meta_types"):
        head.append("meta_types " + compact(header["meta_types"]))
    if head:
        lines += wrap(" · ".join(head))
    for name, entry in header["blocks"].items():
        strings = [col for col, spec in entry["columns"].items() if "offset" not in spec]
        buffers = [
            f"{col} {spec['dtype']} @{spec['offset']}"
            + (f" (validity @{spec['validity']})" if "validity" in spec else "")
            for col, spec in entry["columns"].items()
            if "offset" in spec
        ]
        parts = [f"strings {', '.join(strings)}"] if strings else []
        parts += [f"buffers {', '.join(buffers)}"] if buffers else []
        lines += wrap(f"{name}[{entry['count']}]: " + "; ".join(parts))
    if not header["blocks"]:
        lines.append("no blocks: nothing changed since the previous frame")
    if "box" in header:
        lines.append("box: the cell changed here")
    return lines


def wrap(text: str, width: int = WIDTH - 4, indent: int = 4) -> list[str]:
    """``text`` cut into lines of ``width``, continuation lines indented."""
    return textwrap.wrap(text, width, subsequent_indent=" " * indent, break_on_hyphens=False) or [
        ""
    ]


def _collection_file(work: Path) -> Path:
    path = work / "conformers.mrec.lmdb"
    if not path.exists():
        LmdbCollectionCodec().write(collection(), LmdbCollectionStore(path))
    return path


def _lmdb_items(path: Path) -> list[tuple[bytes, bytes]]:
    env = lmdb.open(str(path), subdir=False, readonly=True, lock=False)
    try:
        with env.begin() as txn:
            return [(bytes(k), bytes(v)) for k, v in txn.cursor()]
    finally:
        env.close()


def block_lmdb_keys(work: Path) -> str:
    lines = ["conformers.mrec.lmdb    (one file; keys in LMDB's byte order)", ""]
    for raw, value in _lmdb_items(_collection_file(work)):
        hexed = " ".join(f"{b:02x}" for b in raw)
        lines.append(f"{_key_text(raw):<15} key bytes {hexed}")
        if value[:4] == b"MRF1":
            header, length, start = _frame_parts(value)
            pad = start - 8 - length
            lines.append(
                f"    MRF1 · header {length} B · pad {pad} B · payload {len(value) - start} B"
            )
            lines += ["    " + line for line in _frame_summary(header)]
        else:
            lines += ["    " + line for line in pretty(json.loads(value), WIDTH - 4)]
    return fence(lines)


def block_lmdb_frame(work: Path) -> str:
    """One trajectory update's value, byte range by byte range."""
    items = dict(_lmdb_items(_collection_file(work)))
    raw = b"f" + (1).to_bytes(8, "big")
    value = items[raw]
    header, length, start = _frame_parts(value)

    def span(begin: int, end: int) -> str:
        return f"[{begin}, {end})".ljust(12)

    lines = [
        f"key {_key_text(raw)} = " + " ".join(f"{b:02x}" for b in raw) + f"; value {len(value)} B",
        "",
        f"{span(0, 4)}magic           {value[:4].decode()!r}",
        f"{span(4, 8)}header_length   {length} (u32, little-endian)",
        f"{span(8, 8 + length)}header          UTF-8 JSON:",
    ]
    lines += [" " * 16 + line for line in pretty(header, WIDTH - 16)]
    lines.append(f"{span(8 + length, start)}padding         {start - 8 - length} zero bytes")
    for name, entry in header["blocks"].items():
        for col, spec in entry["columns"].items():
            if "offset" not in spec:
                continue
            count = int(np.prod(spec["shape"]))
            at = start + spec["offset"]
            values = np.frombuffer(value, dtype="<f8", count=count, offset=at)
            label = f"{name}/{col}".ljust(16)
            lines.append(f"{span(at, at + 8 * count)}{label}{spec['dtype']} = {fmt_values(values)}")
    return fence(lines)


def block_packed(work: Path) -> str:
    live = work / "water.mrec"
    archive = work / "water.mrec.zip"
    pack(live, archive)
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
    stored = all(info.compress_type == zipfile.ZIP_STORED for info in infos)
    same = ZarrRecordCodec().read(PackedRecordStore(archive)) == ZarrRecordCodec().read(
        ZarrRecordStore(live)
    )
    lines = [
        f"water.mrec.zip    {len(infos)} entries, all stored (method 0): {str(stored).lower()},"
        f" directory entries: {sum(i.is_dir() for i in infos)}",
        f"                  reads back equal to water.mrec/: {str(same).lower()}",
        "",
    ]
    for info in infos:
        name = info.filename
        if name.endswith("zarr.json"):
            node = json.loads(zipfile.ZipFile(archive).read(name))["node_type"]
            what = f"{node} metadata"
        else:
            what = "chunk " + name.rsplit("/c/", 1)[1]
        lines.append(f"  {name:<44}{what}")
    return fence(lines)


# -- cost -------------------------------------------------------------------


def block_cost_sections(work: Path) -> str:
    """What each trajectory section costs beyond its column values."""
    rows = [
        ["record", "section", "updates", "on disk beyond the column values"],
        ["---"] * 4,
    ]
    for label in ("vibration.mrec", "reaction.mrec"):
        group = zarr.open_group(store=work / label, mode="r")["trajectory"]
        nstep = group.attrs["nstep"]
        for attr, array in (("step_progression", "step"), ("time_progression", "time")):
            if attr in group.attrs:
                rows.append([label, f"`{array}`", "—", f"attribute `{attr}`"])
            elif array in group:
                rows.append([label, f"`{array}`", "—", f"`{array}` array, {nstep} entries"])
        for name in group.attrs["sequence_schema"]["blocks"]:
            section = group[name]
            ordinals, _ = _section_index(section, nstep)
            if "step_index" in section:
                cost = (
                    f"`step_index` ({len(ordinals)}) + `offset` ({len(ordinals) + 1}):"
                    f" {8 * (2 * len(ordinals) + 1)} B raw"
                )
            else:
                cost = "nothing: `uniform_rows` + `dense_updates` attributes"
            rows.append([label, f"`{name}`", str(len(ordinals)), cost])
        box = group["box"]
        if "vectors" in box:
            n = int(box["step_index"].shape[0])
            rows.append([label, "`box`", str(n), f"`step_index` ({n}) + `vectors` ({n}×3×3)"])
        else:
            rows.append([label, "`box`", "1", "nothing: attribute `vectors` on `box/`"])
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


#: The density workload: atoms uniform in a box (no molecular order -- the
#: worst case for a compressor), a random walk over the frames.
DENSITY_ATOMS, DENSITY_FRAMES = 3000, 40


def _density(work: Path, precision: float | None) -> float:
    rng = np.random.default_rng(2026)
    positions = rng.uniform(0.0, 40.0, (DENSITY_ATOMS, 3))
    frames = []
    for _ in range(DENSITY_FRAMES):
        positions = positions + rng.normal(0.0, 0.05, positions.shape)
        frames.append(FrameModel(blocks={"atoms": xyz_block(positions)}))
    declared = {
        "atoms": SequenceBlockModel(
            columns={axis: SequenceColumnModel(dtype="f64", precision=precision) for axis in "xyz"}
        )
    }
    store = ZarrTrajectoryStore(work / f"density-{precision}.mrec")
    ZarrTrajectoryCodec().write(
        TrajectoryModel(frames=frames, step=list(range(DENSITY_FRAMES)), blocks=declared), store
    )
    root = zarr.open_group(store=store.path, mode="r")
    stored = 0
    for axis in "xyz":
        array = root[f"trajectory/atoms/{axis}"]
        # The shard index (16 B per inner chunk + a crc32c) is a fixed cost
        # per shard that a 40-frame run cannot amortize; count the chunks.
        index = 16 * (array.shards[0] // array.chunks[0]) + 4
        files = (store.path / "trajectory" / "atoms" / axis / "c").rglob("*")
        stored += sum(path.stat().st_size - index for path in files if path.is_file())
    return stored / (DENSITY_ATOMS * DENSITY_FRAMES)


def block_cost_density(work: Path) -> str:
    rows = [
        ["coordinates `x`, `y`, `z`", "pipeline", "bytes per atom per frame"],
        ["---", "---", "---:"],
    ]
    for label, precision, pipeline in (
        ("lossless `f64`", None, "bytes → crc32c"),
        ("precision `p = 1e-3`", 1e-3, "bytes → shuffle(8) → zstd(3) → crc32c"),
        ("precision `p = 1e-2`", 1e-2, "bytes → shuffle(8) → zstd(3) → crc32c"),
    ):
        rows.append([label, pipeline, f"{_density(work, precision):.1f}"])
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


#: Every generated block, in chapter order. Some read what earlier ones wrote.
BLOCKS: dict[str, Callable[[Path], str]] = {
    "overview": block_overview,
    "frame": block_frame,
    "trajectory-fixed": block_trajectory_fixed,
    "trajectory-variable": block_trajectory_variable,
    "resolve": block_resolve,
    "forcefield": block_forcefield,
    "forcefield-system": block_ff_system,
    "linking": block_linking,
    "observables": block_observables,
    "metrics": block_metrics,
    "lmdb-keys": block_lmdb_keys,
    "lmdb-frame": block_lmdb_frame,
    "packed": block_packed,
    "cost-sections": block_cost_sections,
    "cost-density": block_cost_density,
}


def render_all() -> dict[str, str]:
    """Every block, built in a fresh temporary directory."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        return {name: build(work) for name, build in BLOCKS.items()}


_MARKER = re.compile(
    r"<!-- BEGIN generated:(?P<name>[\w-]+) -->\n(?P<body>.*?)\n?<!-- END generated:(?P=name) -->",
    re.DOTALL,
)


def marked(name: str, body: str) -> str:
    """One generated block between its markers."""
    return f"<!-- BEGIN generated:{name} -->\n{body}\n<!-- END generated:{name} -->"


def doc_blocks(text: str) -> dict[str, str]:
    """The generated blocks a chapter holds, by name."""
    return {match["name"]: match["body"] for match in _MARKER.finditer(text)}


def apply(text: str, blocks: dict[str, str]) -> str:
    """``text`` with every generated block replaced. A marker the generator
    does not know, or a block the chapter lacks, is an error."""
    found = doc_blocks(text)
    unknown, missing = sorted(set(found) - set(blocks)), sorted(set(blocks) - set(found))
    if unknown or missing:
        raise ValueError(f"docs/layout.md: unknown blocks {unknown}, missing blocks {missing}")
    return _MARKER.sub(lambda match: marked(match["name"], blocks[match["name"]]), text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate docs/layout.md in place")
    mode.add_argument("--check", action="store_true", help="exit 1 when docs/layout.md drifted")
    args = parser.parse_args(argv)
    blocks = render_all()
    if args.write or args.check:
        text = DOC.read_text()
        updated = apply(text, blocks)
        if args.check:
            if updated != text:
                print("docs/layout.md is out of date: run scripts/layout_examples.py --write")
                return 1
            return 0
        DOC.write_text(updated)
        return 0
    for name, body in blocks.items():
        print(marked(name, body) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
