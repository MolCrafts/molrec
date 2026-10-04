"""What the core module is pinned down by.

Each case is one claim about the contract, and each runs in both directions.
The negative cases matter as much as the positive ones: a reader that accepts
everything conforms to nothing.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, ClassVar

import numpy as np
from pydantic import BaseModel

from molrec.case import Case
from molrec.compare import diff, lookup
from molrec.core.model import (
    META_TAGS,
    META_TYPES_ATTR,
    MOLREC_VERSION,
    NUMPY_DTYPE,
    STORED,
    BlockModel,
    BoxModel,
    BoxUpdateModel,
    CellModel,
    CollectionMetaModel,
    CollectionModel,
    ColumnModel,
    FrameModel,
    MetaModel,
    MetaSeriesModel,
    RecordModel,
    SequenceBlockModel,
    SequenceColumnModel,
    TrajectoryBoxModel,
    TrajectoryModel,
)
from molrec.precision import quantum
from molrec.registry import REGISTRY
from molrec.report import Violation
from molrec.suite import Suite


def _column(
    dtype: str,
    values: list,
    shape: tuple[int, ...] | None = None,
    validity: list[bool] | None = None,
) -> ColumnModel:
    array = np.array(values, dtype=NUMPY_DTYPE[dtype])
    return ColumnModel(
        dtype=dtype,
        shape=shape or array.shape,
        values=array,
        validity=None if validity is None else np.array(validity, dtype="bool"),
    )


def _replace_array(path: str, values: np.ndarray) -> Any:
    """A tamper that replaces the array at ``path`` with ``values``.

    How a store whose content the models cannot express -- a mask of the wrong
    length, a mask that is not ``bool`` -- reaches the reader under test.
    """

    def tamper(store: Any) -> None:
        import zarr

        root = zarr.open_group(store=store.path, mode="r+")
        parent, name = path.rsplit("/", 1)
        group = root[parent]
        del group[name]
        group.create_array(name, shape=values.shape, dtype=values.dtype)[...] = values

    return tamper


def _atoms(*xs: float) -> BlockModel:
    return BlockModel(count=len(xs), columns={"x": _column("f64", list(xs))})


def _raw_column(dtype: str, values: list, precision: float | None) -> ColumnModel:
    """A column as a producer hands it to a writer: values not yet rounded to
    the precision it declares (the validated model would round them)."""
    array = np.array(values, dtype=NUMPY_DTYPE[dtype])
    return ColumnModel.model_construct(
        dtype=dtype, shape=array.shape, values=array, validity=None, precision=precision
    )


def _raw_frame(blocks: dict[str, dict[str, ColumnModel]]) -> FrameModel:
    """A frame of :func:`_raw_column` columns, built around the validators."""
    return FrameModel.model_construct(
        blocks={
            name: BlockModel.model_construct(
                count=next(iter(columns.values())).count if columns else 0,
                columns=columns,
                structural_shape=None,
            )
            for name, columns in blocks.items()
        },
        box=None,
        meta={},
    )


def _set_array(path: str, values: np.ndarray) -> Any:
    """A tamper that overwrites the values of the array at ``path`` in place,
    keeping its attributes and codecs."""

    def tamper(store: Any) -> None:
        import zarr

        zarr.open_group(store=store.path, mode="r+")[path][...] = values

    return tamper


#: The precision the precision cases declare, and its quantum (2**-10).
_P = 1e-3
_Q = quantum(_P)
#: Values that are not on the grid of :data:`_P`.
_UNROUNDED = [0.12345678, -1.00049, 2.718281828, 1e-5]


@REGISTRY.suite
class FrameSuite(Suite):
    module: ClassVar[str] = "core"
    model_type: ClassVar[type[FrameModel]] = FrameModel

    def cases(self) -> Iterable[Case]:
        return self.rooted("")

    def rooted(self, prefix: str) -> Iterable[Case]:
        """The cases, with every tamper addressing the frame group at ``prefix``.

        A bare frame lives at the store root; a record's frame lives under
        ``frame/``. The cases are the same claims either way, so the record
        suite runs them again through this door rather than dropping the ones
        that tamper.
        """
        yield Case(
            id="nullable-columns",
            exercises="a validity mask rides beside its column, for every dtype, and a column "
            "nobody masked stays unmasked",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=3,
                        columns={
                            "x": _column("f64", [0.0, 1.0, 2.0]),
                            "charge": _column(
                                "f64", [0.5, 0.0, -0.5], validity=[True, False, True]
                            ),
                            "element": _column(
                                "string", ["", "H", "O"], validity=[False, True, True]
                            ),
                            "mol_id": _column("u64", [1, 1, 0], validity=[True, True, False]),
                        },
                    ),
                    "bonds": BlockModel(
                        count=2,
                        columns={
                            "atomi": _column("u64", [0, 1]),
                            "atomj": _column("u64", [1, 2]),
                            "bond_type": _column("u64", [0, 1], validity=[False, True]),
                        },
                    ),
                }
            ),
        )

        masked = FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=3,
                    columns={
                        "charge": _column("f64", [0.5, 0.0, -0.5], validity=[True, False, True])
                    },
                )
            }
        )
        yield Case(
            id="reject-mask-length-mismatch",
            exercises="a mask carries exactly one flag per row; padding or truncating it would "
            "invent the answer it exists to give",
            expect_violation="bad_validity",
            backends=("zarr",),
            tamper=_replace_array(f"{prefix}atoms/_validity/charge", np.array([True, False])),
            model=masked,
        )

        yield Case(
            id="reject-mask-not-bool",
            exercises="a mask is one bool per row, never an integer array",
            expect_violation="bad_validity",
            backends=("zarr",),
            tamper=_replace_array(
                f"{prefix}atoms/_validity/charge", np.array([1, 0, 1], dtype="uint8")
            ),
            model=masked,
        )

        for case_id, column, dtype in (
            ("reject-narrow-identifier", "atomi", "u32"),
            ("reject-signed-identifier", "atomic_number", "i64"),
        ):
            values = np.array([0, 1], dtype=NUMPY_DTYPE[dtype])
            yield Case(
                id=case_id,
                exercises=f"{column} is u64 wherever it appears; one stored as {dtype} is "
                "refused, not widened",
                expect_violation="canonical_dtype",
                model=FrameModel.model_construct(
                    blocks={
                        "bonds": BlockModel.model_construct(
                            count=2,
                            columns={
                                column: ColumnModel.model_construct(
                                    dtype=dtype, shape=(2,), values=values, validity=None
                                )
                            },
                            structural_shape=None,
                        )
                    },
                    box=None,
                    meta={},
                ),
            )

        yield Case(
            id="reject-fixed-length-string",
            exercises="a string column is the variable-length string type; a fixed-length one "
            "is no column dtype and is refused",
            expect_violation="unknown_dtype",
            backends=("zarr",),
            tamper=_replace_array(f"{prefix}atoms/element", np.array(["H", "O"], dtype="<U4")),
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(count=2, columns={"element": _column("string", ["H", "O"])})
                }
            ),
        )

        yield Case(
            id="reject-column-named-validity",
            exercises="_validity names a block's masks; a column taking it is refused, not merged",
            expect_violation="reserved_column_name",
            rejects_on="write",
            model=FrameModel.model_construct(
                blocks={
                    "atoms": BlockModel.model_construct(
                        count=1,
                        columns={"_validity": _column("bool", [True])},
                        structural_shape=None,
                    )
                },
                box=None,
                meta={},
            ),
        )

        yield from _frame_precision_cases(prefix)
        yield from _frame_typed_meta_cases(prefix)

        yield Case(
            id="empty-frame",
            exercises="a frame with no blocks is still a frame",
            model=FrameModel(),
        )

        yield Case(
            id="coordinates",
            exercises="the ordinary case: one block, three float columns",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=3,
                        columns={
                            "x": _column("f64", [0.0, 1.5, 3.0]),
                            "y": _column("f64", [0.0, 0.0, 0.0]),
                            "z": _column("f64", [0.0, -1.5, 0.0]),
                        },
                    )
                }
            ),
        )

        yield Case(
            id="every-dtype",
            exercises="the whole closed dtype set survives, each at its declared width",
            model=FrameModel(
                blocks={
                    "everything": BlockModel(
                        count=2,
                        columns={
                            "c_f64": _column("f64", [1.008, 15.999]),
                            "c_i8": _column("i8", [-128, 127]),
                            "c_i16": _column("i16", [-32768, 32767]),
                            "c_i32": _column("i32", [-1, 7]),
                            "c_i64": _column("i64", [-1, 7]),
                            "c_u8": _column("u8", [0, 255]),
                            "c_u16": _column("u16", [0, 65535]),
                            "c_u32": _column("u32", [1, 2]),
                            "c_u64": _column("u64", [1, 2]),
                            "c_bool": _column("bool", [True, False]),
                            "c_string": _column("string", ["H", "O"]),
                            "c_c64": _column("c64", [1 + 2j, -3j]),
                            "c_c128": _column("c128", [1 + 2j, -3j]),
                        },
                    )
                }
            ),
        )

        yield Case(
            id="no-silent-widening",
            exercises="an integer comes back at its own width -- i32 stays i32, u8 stays u8",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=3,
                        columns={
                            "x": _column("f64", [0.0, 1.5, 3.0]),
                            "step": _column("i32", [0, 1, 2]),
                            "flag": _column("u8", [0, 1, 255]),
                        },
                    )
                }
            ),
        )

        yield Case(
            id="block-named-meta",
            exercises="meta is the frame's attributes, so a block may take the name",
            model=FrameModel(
                blocks={"meta": BlockModel(count=1, columns={"whatever": _column("i64", [2])})},
                box=BoxModel(vectors=np.eye(3, dtype="float64")),
            ),
        )

        yield Case(
            id="reject-block-named-box",
            exercises="box names the cell; a block taking it must be refused, not silently lost",
            expect_violation="reserved_block_name",
            # A write-direction rule: no layout can hold a block named box
            # beside the cell, so there is no malformed store to hand a
            # reader -- the writer is the door that must refuse.
            rejects_on="write",
            model=FrameModel(
                blocks={"box": BlockModel(count=1, columns={"whatever": _column("i64", [1])})},
                box=BoxModel(vectors=np.eye(3, dtype="float64")),
            ),
        )

        yield Case(
            id="trailing-axis",
            exercises="Float[count][3] is one column, not three",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=2,
                        columns={
                            "velocity": ColumnModel(
                                dtype="f64",
                                shape=(2, 3),
                                values=np.arange(6, dtype="float64").reshape(2, 3),
                            )
                        },
                    )
                }
            ),
        )

        yield Case(
            id="structural-shape",
            exercises="a volumetric block reads back reshapable -- nx,ny,nz must survive",
            model=FrameModel(
                blocks={
                    "density": BlockModel(
                        count=64,
                        structural_shape=(4, 4, 4),
                        columns={
                            "electron_density": _column("f64", [0.25] * 64),
                        },
                    )
                }
            ),
        )

        yield Case(
            id="block-without-columns",
            exercises="count is stored, not inferred -- an empty block still has one",
            model=FrameModel(blocks={"atoms": BlockModel(count=5)}),
        )

        yield Case(
            id="independent-block-counts",
            exercises="a frame enforces no relationship between blocks",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(count=3, columns={"x": _column("f64", [0.0, 1.0, 2.0])}),
                    "bonds": BlockModel(
                        count=2,
                        columns={
                            "atomi": _column("u64", [0, 1]),
                            "atomj": _column("u64", [1, 2]),
                        },
                    ),
                }
            ),
        )

        yield Case(
            id="triclinic-box",
            exercises="columns of vectors are the lattice vectors; origin and pbc survive",
            model=FrameModel(
                blocks={"atoms": BlockModel(count=1, columns={"x": _column("f64", [0.5])})},
                box=BoxModel(
                    vectors=np.array(
                        [[1.0, 0.0, 0.0], [0.5, 0.8660254, 0.0], [0.0, 0.0, 1.0]],
                        dtype="float64",
                    ),
                    origin=np.zeros(3, dtype="float64"),
                    boundary=(True, True, False),
                ),
            ),
        )

        undefined = FrameModel(
            blocks={"atoms": BlockModel(count=1, columns={"x": _column("f64", [0.5])})},
            box=BoxModel(
                vectors=np.zeros((3, 3)),
                origin=np.array([1.0, 2.0, 3.0]),
                boundary=(False, False, False),
                cell_defined=False,
            ),
        )
        yield Case(
            id="undefined-cell",
            exercises="an undefined cell keeps its origin, is periodic on no axis, and carries "
            "the identity as its vectors",
            model=undefined,
        )

        yield Case(
            id="undefined-cell-ignores-vectors",
            exercises="a reader ignores an undefined cell's vectors: zeros there open, and read "
            "back as the identity",
            model=undefined,
            directions=("read",),
            backends=("zarr",),
            tamper=_replace_array(f"{prefix}box/vectors", np.zeros((3, 3))),
        )

        yield Case(
            id="unknown-names-preserved",
            exercises="a reader must preserve blocks and columns it does not recognize",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=2,
                        columns={
                            "x": _column("f64", [0.0, 1.0]),
                            "x_vendor_local": _column("f64", [9.0, 9.0]),
                        },
                    ),
                    "nobody_knows_this_block": BlockModel(
                        count=1, columns={"whatever": _column("i64", [42])}
                    ),
                }
            ),
        )

        yield Case(
            id="frame-meta-preserved",
            exercises="the frame's meta document survives, a nested json value included",
            model=FrameModel(
                blocks={"atoms": BlockModel(count=1, columns={"x": _column("f64", [0.0])})},
                meta={"title": "test", "source": {"tool": "molrec", "run": 3}},
            ),
        )

        # Negative: the codec lays down a block whose stored count disagrees
        # with its column, and the implementation is required to refuse it.
        yield Case(
            id="reject-row-count-mismatch",
            exercises="a block count that disagrees with its columns must be rejected",
            expect_violation="row_count_mismatch",
            model=FrameModel.model_construct(
                blocks={
                    "atoms": BlockModel.model_construct(
                        count=9,
                        columns={"x": _column("f64", [0.0, 1.0])},
                        structural_shape=None,
                    )
                },
                box=None,
                meta={},
            ),
        )


def _frame_precision_cases(prefix: str) -> Iterable[Case]:
    """Declared precision on the frame path (``docs/spec/frame.md``)."""
    raw = _raw_frame({"atoms": {"x": _raw_column("f64", _UNROUNDED, _P)}})
    # The validated model holds what a writer stores: quantize(values, p).
    rounded = FrameModel(
        blocks={
            "atoms": BlockModel(
                count=len(_UNROUNDED),
                columns={
                    "x": ColumnModel(
                        dtype="f64",
                        shape=(len(_UNROUNDED),),
                        values=np.array(_UNROUNDED),
                        precision=_P,
                    )
                },
            )
        }
    )
    yield Case(
        id="precision-rounds-on-write",
        exercises="a writer stores an f64 column declaring a precision rounded to its binary "
        "grid -- exactly quantize(values), within p/2 of the values and on the grid",
        model=raw,
        expected=rounded,
    )

    yield Case(
        id="precision-declaration-survives",
        exercises="the declared precision reads back beside the values; a column declaring "
        "none stays undeclared",
        model=FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=3,
                    columns={
                        "x": ColumnModel(
                            dtype="f64",
                            shape=(3,),
                            values=np.array([0.0, 1.5, -3.25]),
                            precision=0.01,
                        ),
                        "charge": _column("f64", [0.4, -0.8, 0.4]),
                    },
                )
            }
        ),
    )

    edges = [math.nan, math.inf, -math.inf, -0.0, -1e-4, 2.0**43 + 2.0**-9]
    edges += [2.5 * _Q, 3.5 * _Q, -2.5 * _Q]
    stored = [math.nan, math.inf, -math.inf, -0.0, -0.0, 2.0**43 + 2.0**-9]
    stored += [2 * _Q, 4 * _Q, -2 * _Q]
    yield Case(
        id="precision-edge-values",
        exercises="NaN and the infinities are kept, a value at or beyond 2**52 q is kept, "
        "-0.0 stays -0.0, and a tie rounds to even (2.5q -> 2q, 3.5q -> 4q)",
        model=_raw_frame({"atoms": {"x": _raw_column("f64", edges, _P)}}),
        expected=FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=len(stored),
                    columns={
                        "x": ColumnModel.model_validate(
                            {
                                "dtype": "f64",
                                "shape": (len(stored),),
                                "values": np.array(stored),
                                "precision": _P,
                            },
                            context=STORED,
                        )
                    },
                )
            }
        ),
    )

    walk = np.cumsum(np.full(3 * 64, 0.0123456789))
    yield Case(
        id="precision-shuffle-zstd-decodes",
        exercises="a column the reference writer stored with numcodecs.shuffle + zstd (the "
        "must-decode set) decodes",
        model=_raw_frame({"atoms": {"x": _raw_column("f64", walk.tolist(), _P)}}),
        expected=FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=walk.size,
                    columns={
                        "x": ColumnModel(dtype="f64", shape=walk.shape, values=walk, precision=_P)
                    },
                )
            }
        ),
        directions=("read",),
    )

    off_grid = np.array([0.1, 0.2, 0.3])
    yield Case(
        id="precision-reader-keeps-stored-values",
        exercises="a reader hands back the stored values exactly: it does not re-round a "
        "value a writer left off the grid",
        model=FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=3,
                    columns={
                        "x": ColumnModel(dtype="f64", shape=(3,), values=off_grid, precision=_P)
                    },
                )
            }
        ),
        expected=FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=3,
                    columns={
                        "x": ColumnModel.model_validate(
                            {"dtype": "f64", "shape": (3,), "values": off_grid, "precision": _P},
                            context=STORED,
                        )
                    },
                )
            }
        ),
        directions=("read",),
        backends=("zarr",),
        tamper=_set_array(f"{prefix}atoms/x", off_grid),
    )

    yield Case(
        id="reject-precision-on-non-f64",
        exercises="only an f64 column declares a precision; an i64 column declaring one is refused",
        expect_violation="bad_precision",
        rejects_on="write",
        model=_raw_frame({"atoms": {"n": _raw_column("i64", [1, 2], _P)}}),
    )

    for suffix, bad in (("", 0.0), ("-negative", -1.0), ("-infinite", math.inf)):
        yield Case(
            id=f"reject-precision-out-of-bounds{suffix}",
            exercises=f"a precision is finite, in [2**-1000, 2**1000]; p = {bad} is refused",
            expect_violation="bad_precision",
            rejects_on="write",
            model=_raw_frame({"atoms": {"x": _raw_column("f64", [0.5], bad)}}),
        )


def _edit_attrs(path: str, edit: Any) -> Any:
    """A tamper that rewrites the attributes of the group at ``path`` (``""``
    is the store root) with ``edit(attrs) -> attrs``."""

    def tamper(store: Any) -> None:
        import zarr

        root = zarr.open_group(store=store.path, mode="r+")
        group = root[path.rstrip("/")] if path else root
        attrs = edit(dict(group.attrs))
        group.attrs.clear()
        group.attrs.update(attrs)

    return tamper


#: One meta key per tag, in :data:`META_TAGS` order.
_EVERY_TAG_VALUE: dict[str, Any] = {
    "flag": True,
    "count": -7,
    "big": -(2**40),
    "small": 7,
    "id": 2**64 - 1,
    "pe": -1.25,
    "phase": "nvt",
    "note": {"restarts": [1, 2]},
    "pbc": [True, False, True],
    "image": [-1, 0, 1],
    "shift": [-(2**40), 0, 2**40],
    "grid": [1, 2, 3],
    "ids": [0, 2**63, 2**64 - 1],
    "com": [0.0, 0.5, 1.0],
    "stress": [1.0, 2.0, 3.0, 0.1, 0.2, 0.3],
    "cell": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
}
_EVERY_TAG = dict(zip(_EVERY_TAG_VALUE, META_TAGS, strict=True))


def _typed_frame(meta: dict[str, Any], tags: dict[str, str]) -> FrameModel:
    return FrameModel(
        blocks={"atoms": BlockModel(count=1, columns={"x": _column("f64", [0.0])})},
        meta=meta,
        meta_types=tags,
    )


def _frame_typed_meta_cases(prefix: str) -> Iterable[Case]:
    """A frame's meta document, typed by ``_meta_types`` (``docs/spec/storage.md``)."""
    yield Case(
        id="typed-meta-every-tag",
        exercises="each of the sixteen tags keeps its exact element type and width in a "
        "frame's meta document",
        model=_typed_frame(_EVERY_TAG_VALUE, _EVERY_TAG),
    )

    yield Case(
        id="typed-meta-non-finite",
        exercises="an f64 NaN, +inf and -inf, and an f64x3 holding NaN, survive as their "
        "typed JSON forms",
        model=_typed_frame(
            {"nan": math.nan, "inf": math.inf, "ninf": -math.inf, "v": [math.nan, 0.0, 1.0]},
            {"nan": "f64", "inf": "f64", "ninf": "f64", "v": "f64x3"},
        ),
    )

    yield Case(
        id="typed-meta-wide-integers",
        exercises="integers beyond 2**53 keep every digit: u64 2**64-1, i64 -2**63, u64 2**53+1",
        model=_typed_frame(
            {"max": 2**64 - 1, "min": -(2**63), "odd": 2**53 + 1},
            {"max": "u64", "min": "i64", "odd": "u64"},
        ),
    )

    yield Case(
        id="typed-meta-integral-float",
        exercises="an f64 whose value is whole stays f64; an i32 stays i32",
        model=_typed_frame({"t": 1.0, "n": 3}, {"t": "f64", "n": "i32"}),
    )

    # Only values whose typed JSON form is plain JSON: an untagged u64 beyond
    # 2**53 is stored as a decimal string and reads back a string -- which is
    # why a writer tags every key.
    tagged = _typed_frame(
        {"n": 3, "t": 2.0, "v": [1.0, 2.0, 3.0], "name": "a", "ok": True},
        {"n": "i32", "t": "f64", "v": "f64x3", "name": "string", "ok": "bool"},
    )
    yield Case(
        id="untyped-meta-infers",
        exercises="a store without _meta_types reads with inferred tags: an integer i64, any "
        "other number f64 (2.0 included), a string string, a bool bool, anything else json",
        model=tagged,
        expected=_typed_frame(
            dict(tagged.meta),
            {"n": "i64", "t": "f64", "v": "json", "name": "string", "ok": "bool"},
        ),
        directions=("read",),
        backends=("zarr",),
        tamper=_edit_attrs(
            prefix, lambda attrs: {k: v for k, v in attrs.items() if k != META_TYPES_ATTR}
        ),
    )

    yield Case(
        id="stale-meta-tag-ignored",
        exercises="a tag for a key the document lacks is ignored, not surfaced and not refused",
        model=tagged,
        directions=("read",),
        backends=("zarr",),
        tamper=_edit_attrs(
            prefix,
            lambda attrs: {
                **attrs,
                META_TYPES_ATTR: {**attrs[META_TYPES_ATTR], "gone": "f64x9"},
            },
        ),
    )

    for case_id, value, why in (
        ("reject-meta-tag-mismatch", 1.5, "1.5 is not an i32"),
        ("reject-meta-out-of-range", 2**40, "2**40 is out of range for i32"),
    ):
        yield Case(
            id=case_id,
            exercises=f"a tagged key is decoded under its tag and nothing else: {why}",
            expect_violation="meta_tag_mismatch",
            backends=("zarr",),
            model=_typed_frame({"k": 1}, {"k": "i64"}),
            tamper=_edit_attrs(
                prefix,
                lambda attrs, value=value: {
                    **attrs,
                    "k": value,
                    META_TYPES_ATTR: {**attrs[META_TYPES_ATTR], "k": "i32"},
                },
            ),
        )

    def unvalidated(meta: dict[str, Any], tags: dict[str, str]) -> FrameModel:
        return FrameModel.model_construct(blocks={}, box=None, meta=meta, meta_types=tags)

    yield Case(
        id="reject-meta-reserved-key",
        exercises="_meta_types is the binding's; a meta key taking the name is refused",
        expect_violation="reserved_meta_key",
        rejects_on="write",
        model=unvalidated({META_TYPES_ATTR: {"a": "f64"}, "a": 1.0}, {}),
    )

    yield Case(
        id="reject-json-meta-non-finite",
        exercises="a json value is finite JSON; one holding NaN is refused, not nulled",
        expect_violation="meta_tag_mismatch",
        rejects_on="write",
        model=unvalidated({"doc": {"x": math.nan}}, {"doc": "json"}),
    )


#: The declaration of the aligned-block cases: ``atom_types`` rides ``atoms``.
_ALIGNED = {
    "atoms": SequenceBlockModel(columns={"x": SequenceColumnModel(dtype="f64")}),
    "atom_types": SequenceBlockModel(
        columns={"type": SequenceColumnModel(dtype="string")}, aligned_with="atoms"
    ),
}


def _types(*names: str) -> BlockModel:
    return BlockModel(count=len(names), columns={"type": _column("string", list(names))})


def _aligned_run(
    *frames: tuple[list[float] | None, list[str] | None],
    blocks: dict[str, SequenceBlockModel] | None = None,
    validated: bool = True,
) -> TrajectoryModel:
    """A run of ``(atoms x, atom_types)`` presentations, ``None`` omitting one;
    built around the trajectory's validators when ``validated`` is false."""
    built = [
        FrameModel(
            blocks={
                **({} if xs is None else {"atoms": _atoms(*xs)}),
                **({} if types is None else {"atom_types": _types(*types)}),
            }
        )
        for xs, types in frames
    ]
    fields = {
        "frames": built,
        "step": list(range(len(built))),
        "blocks": _ALIGNED if blocks is None else blocks,
    }
    if validated:
        return TrajectoryModel(**fields)
    return TrajectoryModel.model_construct(**fields, time=None, meta={}, box=None)


def _drop_last_row(path: str, update: int) -> Any:
    """A tamper that moves ``offset[update]`` of the block at ``path`` one row
    back, so the update before it holds one row fewer."""

    def tamper(store: Any) -> None:
        import zarr

        offset = zarr.open_group(store=store.path, mode="r+")[f"{path}/offset"]
        values = offset[...]
        values[update] -= 1
        offset[...] = values

    return tamper


def _aligned_cases() -> Iterable[Case]:
    """Aligned blocks (``docs/spec/ragged.md``): one block's rows are another's."""
    three = ["CT", "HC", "HC"]
    yield Case(
        id="aligned-carries-forward",
        exercises="an aligned block updated at 0 and 3 resolves at every frame beside a target "
        "that moves every frame",
        model=_aligned_run(
            ([0.0, 1.0, 2.0], three),
            ([0.1, 1.1, 2.1], None),
            ([0.2, 1.2, 2.2], None),
            ([0.3, 1.3, 2.3], ["CT", "HC", "OH"]),
            ([0.4, 1.4, 2.4], None),
        ),
    )

    yield Case(
        id="aligned-restated-on-growth",
        exercises="a frame that grows the target restates the aligned block with the new count",
        model=_aligned_run(
            ([0.0, 1.0, 2.0], three),
            ([0.1, 1.1, 2.1], None),
            ([0.2, 1.2, 2.2, 3.2], [*three, "OW"]),
            ([0.3, 1.3, 2.3, 3.3], None),
        ),
    )

    yield Case(
        id="aligned-absent-then-present",
        exercises="an aligned block may be absent while its target is present; it first "
        "appears at ordinal 1",
        model=_aligned_run(
            ([0.0, 1.0, 2.0], None), ([0.1, 1.1, 2.1], three), ([0.2, 1.2, 2.2], None)
        ),
    )

    yield Case(
        id="aligned-empty-target",
        exercises="a target emptied at ordinal 2 takes the aligned block with it, restated empty",
        model=_aligned_run(([0.0, 1.0, 2.0], three), ([0.1, 1.1, 2.1], None), ([], []), ([], None)),
    )

    yield Case(
        id="reject-aligned-not-restated",
        exercises="a frame that grows the target without restating the aligned block is refused",
        expect_violation="aligned_count_mismatch",
        rejects_on="write",
        model=_aligned_run(
            ([0.0, 1.0, 2.0], three),
            ([0.1, 1.1, 2.1], None),
            ([0.2, 1.2, 2.2, 3.2], None),
            validated=False,
        ),
    )

    yield Case(
        id="reject-aligned-count-mismatch",
        exercises="a reader refuses a store whose aligned block holds another row count than "
        "its target at a resolved frame",
        expect_violation="aligned_count_mismatch",
        backends=("zarr",),
        tamper=_drop_last_row("trajectory/atom_types", 1),
        model=_aligned_run(
            ([0.0, 1.0, 2.0], three), ([0.1, 1.1, 2.1], None), ([0.2, 1.2, 2.2], ["OW", "HW", "HW"])
        ),
    )

    def declared(**aligned: SequenceBlockModel) -> dict[str, SequenceBlockModel]:
        return {"atoms": _ALIGNED["atoms"], **aligned}

    for case_id, why, blocks, frames in (
        (
            "reject-aligned-target-undeclared",
            "an aligned block's target is a declared block",
            declared(
                atom_types=SequenceBlockModel(
                    columns={"type": SequenceColumnModel(dtype="string")}, aligned_with="nope"
                )
            ),
            [([0.0], ["CT"])],
        ),
        (
            "reject-aligned-chain",
            "an aligned block's target is not itself aligned",
            declared(
                atom_types=_ALIGNED["atom_types"],
                charges=SequenceBlockModel(
                    columns={"q": SequenceColumnModel(dtype="f64")}, aligned_with="atom_types"
                ),
            ),
            [([0.0], ["CT"])],
        ),
        (
            "reject-aligned-shared-column",
            "an aligned block's columns are its own: both blocks carrying type is refused",
            {
                "atoms": SequenceBlockModel(
                    columns={
                        "x": SequenceColumnModel(dtype="f64"),
                        "type": SequenceColumnModel(dtype="string"),
                    }
                ),
                "atom_types": _ALIGNED["atom_types"],
            },
            [],
        ),
        (
            "reject-aligned-target-absent",
            "an aligned block is never present while its target is absent",
            _ALIGNED,
            [(None, ["CT"]), ([0.0], None)],
        ),
    ):
        yield Case(
            id=case_id,
            exercises=why,
            expect_violation="bad_alignment",
            rejects_on="write",
            model=_aligned_run(*frames, blocks=blocks, validated=False),
        )


def _break_offset(store: Any) -> None:
    """Make ``atoms/offset`` non-monotonic in a store the codec just wrote.

    The models cannot express this -- row counts are never stored, they are
    ``diff(offset)`` -- so the malformation is applied to the bytes, after the
    fact, with the backend's own API.
    """
    import zarr

    offset = zarr.open_group(store=store.path, mode="r+")["trajectory/atoms/offset"]
    values = offset[...]
    values[1], values[2] = values[2], values[1]
    offset[...] = values


def _narrow(path: str, dtype: str = "float32") -> Any:
    """A tamper that rewrites the float array at ``path`` as a narrow float.

    What a producer that stored less precision than the record claims leaves
    on disk; the models cannot express it, because a narrow real is not a
    column dtype.
    """

    def tamper(store: Any) -> None:
        import zarr

        root = zarr.open_group(store=store.path, mode="r+")
        parent, name = path.rsplit("/", 1)
        values = root[path][...]
        group = root[parent]
        del group[name]
        group.create_array(name, shape=values.shape, dtype=dtype)[...] = values.astype(dtype)

    return tamper


def _carries(value: Any, name: str) -> bool:
    """Whether a returned duck states ``name`` at all (``fill`` may be ``null``)."""
    if isinstance(value, MetaSeriesModel):
        return value.has_fill if name == "fill" else True
    if isinstance(value, dict):
        return name in value
    return hasattr(value, name)


def _undeclared_as_returned(expected: TrajectoryModel, actual: Any) -> TrajectoryModel:
    """``expected`` without the parts of the declaration ``actual`` does not surface."""
    update: dict[str, Any] = {}
    if lookup(actual, "blocks") is None:
        update["blocks"] = None
    returned_meta = lookup(actual, "meta")
    declared = {}
    for key, series in expected.meta.items():
        returned = lookup(returned_meta, key)
        surfaced = returned is None or _carries(returned, "fill")
        declared[key] = series if surfaced else MetaSeriesModel(dtype=series.dtype)
    if declared != expected.meta:
        update["meta"] = declared
    return expected.model_copy(update=update) if update else expected


@REGISTRY.suite
class TrajectorySuite(Suite):
    """What a sequence of frames is pinned down by.

    Every positive case is a whole round trip of the *logical* sequence: the
    frames, in order, with their step numbers, their per-step meta and their
    cell. What no case looks at is how any of it was indexed on disk. A
    conforming reader hands these frames back whatever it wrote, and two
    conforming stores of one trajectory are expected to differ byte for byte.

    The cases are chosen for what the indexing has to *survive*: ragged
    frames, a section that never changes, the three states of a block
    (present / empty / absent, with omission carrying forward), a key a
    frame did not supply, and a producer's own step numbering. The negative
    cases are every MUST in ``docs/spec/ragged.md``: what a writer refuses at
    declaration or at append, and what a reader refuses on disk.
    """

    module: ClassVar[str] = "trajectory"
    model_type: ClassVar[type[TrajectoryModel]] = TrajectoryModel

    def compare(self, expected: BaseModel, actual: Any) -> tuple[Violation, ...]:
        """Everything is compared exactly; the declaration is compared when returned.

        The declaration -- each meta key's fill, and the ``blocks`` it pins --
        is recorded in the ``sequence_schema`` attribute, so a reader *can*
        hand it back and the reference codec does. An implementation whose
        reading door surfaces the frames but not the declaration is not
        failed for that: the frames themselves -- every carried-forward block
        and every filled value -- are compared like anything else.
        """
        if isinstance(expected, TrajectoryModel):
            expected = _undeclared_as_returned(expected, actual)
        return diff(expected, actual)

    def cases(self) -> Iterable[Case]:
        yield from self._positive_cases()
        yield from self._precision_cases()
        yield from _aligned_cases()
        yield from self._writer_refusals()
        yield from self._reader_refusals()

    def _precision_cases(self) -> Iterable[Case]:
        """Declared precision on the trajectory path: the declaration states it,
        every frame is rounded to it, and the change check sees rounded values."""
        declared = {
            "atoms": SequenceBlockModel(
                columns={"x": SequenceColumnModel(dtype="f64", precision=_P)}
            )
        }

        def raw(*rows: list[float]) -> list[FrameModel]:
            return [_raw_frame({"atoms": {"x": _raw_column("f64", row, None)}}) for row in rows]

        def logical(*rows: list[float]) -> TrajectoryModel:
            return TrajectoryModel(
                frames=[FrameModel(blocks={"atoms": _atoms(*row)}) for row in rows],
                step=list(range(len(rows))),
                blocks=declared,
            )

        rows = ([0.12345678, -1.00049, 2.718281828], [0.2468, -1.0011, 2.7])
        yield Case(
            id="precision-in-sequence-schema",
            exercises="the pinned declaration states a column's precision, and every frame's "
            "values read back rounded to it",
            model=TrajectoryModel.model_construct(
                frames=raw(*rows), step=[0, 1], time=None, blocks=declared, meta={}, box=None
            ),
            expected=logical(*rows),
        )

        # Frame 0 sits on the grid; frame 1 moves every atom by less than q/2,
        # so after rounding it is frame 0 again.
        on_grid = [0.125, -1.0, 2.75]
        nudged = [x + 0.4 * _Q * (-1) ** i for i, x in enumerate(on_grid)]
        yield Case(
            id="precision-sub-quantum-carries-forward",
            exercises="the change check compares rounded presentations: a change below half the "
            "quantum is no change, and both frames read back as frame 0's stored values",
            model=TrajectoryModel.model_construct(
                frames=raw(on_grid, nudged),
                step=[0, 1],
                time=None,
                blocks=declared,
                meta={},
                box=None,
            ),
            expected=logical(on_grid, on_grid),
        )

        yield Case(
            id="reject-frame-precision-disagrees",
            exercises="a frame column stating another precision than the pinned one is refused",
            expect_violation="precision_mismatch",
            rejects_on="write",
            model=TrajectoryModel.model_construct(
                frames=[_raw_frame({"atoms": {"x": _raw_column("f64", [0.5], 1e-2)}})],
                step=[0],
                time=None,
                blocks=declared,
                meta={},
                box=None,
            ),
        )

    def _positive_cases(self) -> Iterable[Case]:
        #: One object, presented by several frames: identical content is what
        #: earns a section a single update instead of one per step.
        bonds = BlockModel(
            count=2,
            columns={"atomi": _column("u64", [0, 1]), "atomj": _column("u64", [1, 2])},
        )
        #: The same block with no rows: present and empty, not absent.
        no_bonds = BlockModel(
            count=0,
            columns={"atomi": _column("u64", []), "atomj": _column("u64", [])},
        )

        yield Case(
            id="ragged-frames",
            exercises="frames of different lengths -- rows are indexed, never padded",
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(*(float(row) for row in range(count)))})
                    for count in (3, 5, 4)
                ],
                step=[0, 1, 2],
            ),
        )

        yield Case(
            id="constant-block",
            exercises="a topology that never changes is stated once and resolves at every step",
            model=TrajectoryModel(
                frames=[
                    FrameModel(
                        blocks={"atoms": _atoms(shift, shift + 1.0, shift + 2.0), "bonds": bonds}
                    )
                    for shift in (0.0, 0.25, 0.5, 0.75)
                ],
                step=[0, 1, 2, 3],
            ),
        )

        yield Case(
            id="fixed-cell",
            exercises="one cell update, however many steps resolve to it",
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(shift)})
                    for shift in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
                ],
                step=[0, 1, 2, 3, 4, 5],
                box=TrajectoryBoxModel(
                    updates=[
                        BoxUpdateModel(
                            step_index=0,
                            box=CellModel(
                                vectors=np.diag([10.0, 10.0, 12.0]),
                                boundary=(True, True, False),
                            ),
                        )
                    ]
                ),
            ),
        )

        undefined = TrajectoryModel(
            frames=[FrameModel(blocks={"atoms": _atoms(shift)}) for shift in (0.0, 0.1, 0.2)],
            step=[0, 1, 2],
            box=TrajectoryBoxModel(
                cell_defined=False,
                updates=[
                    BoxUpdateModel(
                        step_index=0,
                        box=CellModel(vectors=np.zeros((3, 3)), boundary=(False, False, False)),
                    ),
                    BoxUpdateModel(
                        step_index=2,
                        box=CellModel(
                            vectors=np.zeros((3, 3)),
                            origin=np.array([1.0, 0.0, 0.0]),
                            boundary=(False, False, False),
                        ),
                    ),
                ],
            ),
        )
        yield Case(
            id="undefined-cell",
            exercises="the section's one cell_defined covers every update; an undefined cell "
            "carries the identity and is periodic on no axis",
            model=undefined,
        )

        yield Case(
            id="undefined-cell-ignores-vectors",
            exercises="a reader ignores an undefined cell's vectors on the trajectory path too",
            model=undefined,
            directions=("read",),
            backends=("zarr",),
            tamper=_replace_array("trajectory/box/vectors", np.zeros((2, 3, 3))),
        )

        yield Case(
            id="per-step-meta",
            exercises="a declared fill stands in for an omitted key -- there is no implicit NaN",
            model=TrajectoryModel(
                frames=[
                    FrameModel(
                        blocks={"atoms": _atoms(0.0)},
                        meta={"temperature": 300.0, "pressure": 1.0, "ensemble": "nvt"},
                    ),
                    FrameModel(
                        blocks={"atoms": _atoms(0.5)},
                        # `pressure` omitted: the declared fill is written for it.
                        meta={"temperature": 301.5, "ensemble": "nvt"},
                    ),
                    FrameModel(
                        blocks={"atoms": _atoms(1.0)},
                        meta={"temperature": 299.25, "pressure": 1.25, "ensemble": "npt"},
                    ),
                ],
                step=[0, 1, 2],
                meta={
                    "temperature": MetaSeriesModel(dtype="f64"),
                    "pressure": MetaSeriesModel(dtype="f64", fill=0.0),
                    "ensemble": MetaSeriesModel(dtype="string"),
                },
            ),
        )

        yield Case(
            id="vector-meta",
            exercises="fixed-width per-step vectors: f64x3, f64x6 and bool3 keep their tags",
            model=TrajectoryModel(
                frames=[
                    FrameModel(
                        blocks={"atoms": _atoms(0.0)},
                        meta={
                            "com": [0.0, 0.5, 1.0],
                            "stress": [1.0, 2.0, 3.0, 0.1, 0.2, 0.3],
                            "flags": [True, False, True],
                        },
                    ),
                    FrameModel(
                        blocks={"atoms": _atoms(0.5)},
                        meta={
                            "com": [0.1, 0.6, 1.1],
                            "stress": [1.1, 2.1, 3.1, 0.1, 0.2, 0.3],
                            "flags": [False, False, True],
                        },
                    ),
                ],
                step=[0, 1],
                meta={
                    "com": MetaSeriesModel(dtype="f64x3"),
                    "stress": MetaSeriesModel(dtype="f64x6"),
                    "flags": MetaSeriesModel(dtype="bool3"),
                },
            ),
        )

        every_tag = _EVERY_TAG_VALUE
        tags = _EVERY_TAG
        yield Case(
            id="every-meta-tag",
            exercises="each of the sixteen per-step tags keeps its exact element type and width",
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(0.0)}, meta=every_tag),
                    FrameModel(blocks={"atoms": _atoms(0.5)}, meta=every_tag),
                ],
                step=[0, 1],
                meta={key: MetaSeriesModel(dtype=tag) for key, tag in tags.items()},
            ),
        )

        yield Case(
            id="json-null-fill",
            exercises="a json key may declare the document null as its fill; stating null is "
            "not the same as declaring no fill",
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(0.0)}, meta={"note": {"ok": True}}),
                    FrameModel(blocks={"atoms": _atoms(0.5)}, meta={}),
                ],
                step=[0, 1],
                meta={"note": MetaSeriesModel(dtype="json", fill=None)},
            ),
        )

        yield Case(
            id="json-meta",
            exercises="a json meta key carries one JSON document per step, as a string array",
            model=TrajectoryModel(
                frames=[
                    FrameModel(
                        blocks={"atoms": _atoms(0.0)},
                        meta={"note": {"phase": "equilibration", "restarts": [1, 2]}},
                    ),
                    FrameModel(
                        blocks={"atoms": _atoms(0.5)},
                        meta={"note": {"phase": "production", "restarts": []}},
                    ),
                    FrameModel(
                        blocks={"atoms": _atoms(1.0)},
                        # omitted: the declared fill (itself a JSON document) is written.
                        meta={},
                    ),
                ],
                step=[0, 1, 2],
                meta={"note": MetaSeriesModel(dtype="json", fill={"phase": None})},
            ),
        )

        yield Case(
            id="block-appears-late",
            exercises=(
                "no update at or before an ordinal is absence -- a block before its first update"
            ),
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(0.0, 1.0)}),
                    FrameModel(blocks={"atoms": _atoms(1.0, 2.0), "bonds": bonds}),
                    FrameModel(blocks={"atoms": _atoms(2.0, 3.0), "bonds": bonds}),
                ],
                step=[0, 1, 2],
            ),
        )

        yield Case(
            id="omitted-block-carries-forward",
            exercises=(
                "a frame that omits a declared block writes no update; the block carries forward"
            ),
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(0.0, 1.0), "bonds": bonds}),
                    FrameModel(blocks={"atoms": _atoms(1.0, 2.0)}),
                    FrameModel(blocks={"atoms": _atoms(2.0, 3.0)}),
                ],
                step=[0, 1, 2],
            ),
        )

        yield Case(
            id="zero-row-update-is-present-and-empty",
            exercises=(
                "a zero-row update reads back present and "
                "empty, distinct from absent, until the next update"
            ),
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(0.0, 1.0), "bonds": bonds}),
                    FrameModel(blocks={"atoms": _atoms(1.0, 2.0), "bonds": no_bonds}),
                    FrameModel(blocks={"atoms": _atoms(2.0, 3.0)}),
                    FrameModel(blocks={"atoms": _atoms(3.0, 4.0), "bonds": bonds}),
                ],
                step=[0, 1, 2, 3],
            ),
        )

        def charged(values: list[float], validity: list[bool] | None) -> BlockModel:
            return BlockModel(
                count=len(values),
                columns={
                    "x": _column("f64", [float(i) for i in range(len(values))]),
                    "charge": _column("f64", values, validity=validity),
                },
            )

        yield Case(
            id="nullable-column",
            exercises="a nullable column's mask rides its CSR rows: holed in one frame, whole in "
            "the next, and a whole frame reads back unmasked",
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": charged([0.5, 0.0], [True, False])}),
                    FrameModel(blocks={"atoms": charged([0.5, -0.5, 0.25], None)}),
                    FrameModel(blocks={"atoms": charged([0.0, 0.0, 1.0], [False, False, True])}),
                    FrameModel(blocks={"atoms": charged([], None)}),
                ],
                step=[0, 1, 2, 3],
            ),
        )

        yield Case(
            id="structural-shape-block",
            exercises="a grid block has a fixed row count, the product of its structural shape",
            model=TrajectoryModel(
                frames=[
                    FrameModel(
                        blocks={
                            "density": BlockModel(
                                count=8,
                                structural_shape=(2, 2, 2),
                                columns={"rho": _column("f64", [level] * 8)},
                            )
                        }
                    )
                    for level in (0.25, 0.5)
                ],
                step=[0, 1],
            ),
        )

        yield Case(
            id="step-numbers-and-times",
            exercises="step numbers are the producer's own counter and may skip; time rides beside",
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(shift, shift + 1.0)})
                    for shift in (0.0, 5.0, 10.0)
                ],
                step=[0, 5, 10],
                time=[0.0, 0.5, 1.0],
            ),
        )

    def _writer_refusals(self) -> Iterable[Case]:
        """Every rule the layout places on the writer, handed to the writer."""

        def sequence(frames: list[FrameModel], **overrides: Any) -> TrajectoryModel:
            fields: dict[str, Any] = {
                "frames": frames,
                "step": list(range(len(frames))),
                "time": None,
                "blocks": None,
                "meta": {},
                "box": None,
            }
            fields.update(overrides)
            return TrajectoryModel.model_construct(**fields)

        yield Case(
            id="reject-reserved-block-name",
            exercises="step / time / meta / box are the sequence's own; a block cannot take them",
            expect_violation="reserved_block_name",
            rejects_on="write",
            model=sequence([FrameModel(blocks={"step": _atoms(0.0)})]),
        )

        yield Case(
            id="reject-reserved-column-name",
            exercises="offset / step_index are a block's own index; a column cannot take them",
            expect_violation="reserved_column_name",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(
                        blocks={
                            "atoms": BlockModel(
                                count=1,
                                columns={"x": _column("f64", [0.0]), "offset": _column("u64", [0])},
                            )
                        }
                    )
                ]
            ),
        )

        yield Case(
            id="reject-undeclared-block",
            exercises=(
                "the declaration is fixed at creation; a frame cannot present a block outside it"
            ),
            expect_violation="undeclared_block",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(blocks={"atoms": _atoms(0.0)}),
                    FrameModel(
                        blocks={
                            "atoms": _atoms(1.0),
                            "bonds": BlockModel(count=1, columns={"atomi": _column("u64", [0])}),
                        }
                    ),
                ],
                blocks={
                    "atoms": SequenceBlockModel(columns={"x": SequenceColumnModel(dtype="f64")})
                },
            ),
        )

        yield Case(
            id="reject-undeclared-column",
            exercises="a block presents all of its declared columns or none; never a new one",
            expect_violation="undeclared_column",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(blocks={"atoms": _atoms(0.0)}),
                    FrameModel(
                        blocks={
                            "atoms": BlockModel(
                                count=1,
                                columns={"x": _column("f64", [1.0]), "y": _column("f64", [0.0])},
                            )
                        }
                    ),
                ]
            ),
        )

        yield Case(
            id="reject-mask-on-non-nullable-column",
            exercises="a frame that masks a column the declaration pins non-nullable is refused, "
            "not landed without its mask",
            expect_violation="undeclared_nullable",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(
                        blocks={
                            "atoms": BlockModel(
                                count=2,
                                columns={"q": _column("f64", [0.5, 0.0], validity=[True, False])},
                            )
                        }
                    )
                ],
                blocks={
                    "atoms": SequenceBlockModel(columns={"q": SequenceColumnModel(dtype="f64")})
                },
            ),
        )

        yield Case(
            id="reject-undeclared-meta-key",
            exercises="a per-step meta key is declared once, when the sequence is created",
            expect_violation="undeclared_meta_key",
            rejects_on="write",
            model=sequence(
                [FrameModel(blocks={"atoms": _atoms(0.0)}, meta={"temperature": 300.0})]
            ),
        )

        yield Case(
            id="reject-omitted-meta-without-fill",
            exercises="a frame may omit a declared key only if it was declared with a fill",
            expect_violation="missing_meta_value",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(blocks={"atoms": _atoms(0.0)}, meta={"temperature": 300.0}),
                    FrameModel(blocks={"atoms": _atoms(0.5)}, meta={}),
                ],
                meta={"temperature": MetaSeriesModel(dtype="f64")},
            ),
        )

        yield Case(
            id="reject-duplicate-step",
            exercises="step numbers increase strictly; a repeated one is refused",
            expect_violation="step_not_increasing",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(blocks={"atoms": _atoms(0.0)}),
                    FrameModel(blocks={"atoms": _atoms(1.0)}),
                ],
                step=[4, 4],
            ),
        )

        yield Case(
            id="reject-decreasing-step",
            exercises="step numbers increase strictly; a smaller one is refused",
            expect_violation="step_not_increasing",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(blocks={"atoms": _atoms(0.0)}),
                    FrameModel(blocks={"atoms": _atoms(1.0)}),
                ],
                step=[4, 3],
            ),
        )

        yield Case(
            id="reject-time-gained-midway",
            exercises=(
                "time is all-or-nothing: a sequence that starts without times cannot gain them"
            ),
            expect_violation="partial_time",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(blocks={"atoms": _atoms(0.0)}),
                    FrameModel(blocks={"atoms": _atoms(1.0)}),
                ],
                time=[None, 0.5],
            ),
        )

        yield Case(
            id="reject-time-dropped-midway",
            exercises="time is all-or-nothing: a sequence that starts with times cannot drop them",
            expect_violation="partial_time",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(blocks={"atoms": _atoms(0.0)}),
                    FrameModel(blocks={"atoms": _atoms(1.0)}),
                ],
                time=[0.0, None],
            ),
        )

        yield Case(
            id="reject-structural-shape-row-count",
            exercises=(
                "a grid block's row count is fixed by "
                "its structural shape; a different one is refused"
            ),
            expect_violation="structural_shape_mismatch",
            rejects_on="write",
            model=sequence(
                [
                    FrameModel(
                        blocks={
                            "density": BlockModel(
                                count=8,
                                structural_shape=(2, 2, 2),
                                columns={"rho": _column("f64", [0.25] * 8)},
                            )
                        }
                    ),
                    FrameModel(
                        blocks={
                            "density": BlockModel(
                                count=27,
                                structural_shape=(3, 3, 3),
                                columns={"rho": _column("f64", [0.5] * 27)},
                            )
                        }
                    ),
                ]
            ),
        )

    def _reader_refusals(self) -> Iterable[Case]:
        """What a reader must refuse on disk."""
        bonds = BlockModel(
            count=2,
            columns={"atomi": _column("u64", [0, 1]), "atomj": _column("u64", [1, 2])},
        )
        yield Case(
            id="reject-narrow-endpoint",
            exercises="a relation endpoint is u64 on the trajectory path too; one stored as u32 "
            "is refused, not widened",
            expect_violation="canonical_dtype",
            backends=("zarr",),
            tamper=_narrow("trajectory/bonds/atomi", "uint32"),
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(0.0, 1.0, 2.0), "bonds": bonds}),
                    FrameModel(blocks={"atoms": _atoms(0.5, 1.5, 2.5)}),
                ],
                step=[0, 1],
            ),
        )

        yield Case(
            id="reject-mask-not-bool",
            exercises="a nullable column's mask is one bool per row, never an integer array",
            expect_violation="bad_validity",
            backends=("zarr",),
            tamper=_replace_array(
                "trajectory/atoms/_validity/q", np.array([1, 0, 1, 1], dtype="uint8")
            ),
            model=TrajectoryModel(
                frames=[
                    FrameModel(
                        blocks={
                            "atoms": BlockModel(
                                count=2,
                                columns={"q": _column("f64", [q, 0.0], validity=[True, False])},
                            )
                        }
                    )
                    for q in (0.5, 0.25)
                ],
                step=[0, 1],
            ),
        )

        yield Case(
            id="reject-narrow-float-column",
            exercises="floats are f64 only; a column stored as binary32 is refused, not widened",
            expect_violation="narrow_float",
            backends=("zarr",),
            tamper=_narrow("trajectory/atoms/x"),
            model=TrajectoryModel(
                frames=[FrameModel(blocks={"atoms": _atoms(0.0, 1.0)}) for _ in range(2)],
                step=[0, 1],
            ),
        )

        yield Case(
            id="reject-non-monotonic-offset",
            exercises=(
                "row counts are diff(offset) with checked "
                "subtraction; a decreasing offset is refused"
            ),
            expect_violation="non_monotonic_offset",
            backends=("zarr",),
            tamper=_break_offset,
            model=TrajectoryModel(
                frames=[
                    FrameModel(blocks={"atoms": _atoms(*(float(row) for row in range(count)))})
                    for count in (3, 5, 4)
                ],
                step=[0, 1, 2],
            ),
        )


#: Marks a key a tamper removes rather than sets.
_DELETE = object()


def _set_record_meta(key: str, value: Any) -> Any:
    """A tamper that sets (or, with :data:`_DELETE`, removes) one ``meta/`` attribute.

    What a writer of another contract version -- or a broken one -- would have
    left there; molrec's own codec always stamps a valid version.
    """

    def tamper(store: Any) -> None:
        import zarr

        group = zarr.open_group(store=store.path, mode="r+")["meta"]
        attrs = dict(group.attrs)
        if value is _DELETE:
            attrs.pop(key, None)
        else:
            attrs[key] = value
        group.attrs.clear()
        group.attrs.update(attrs)

    return tamper


@REGISTRY.suite
class RecordSuite(Suite):
    """The record root -- the shape a real producer actually writes.

    A bare frame at a store root is worth pinning down on its own, but nothing
    ships one. What crosses between tools is a record: a meta document plus
    frame-shaped sections. These cases exist so an implementation is judged on
    the thing it emits.
    """

    module: ClassVar[str] = "record"
    model_type: ClassVar[type[RecordModel]] = RecordModel

    def cases(self) -> Iterable[Case]:
        yield from self._own_cases()
        yield from self._frames_inside_a_record()

    def _frames_inside_a_record(self) -> Iterable[Case]:
        """Every frame case again, this time where frames actually live.

        A bare frame at a store root is a clean unit to specify, but no
        implementation has a door for one -- what ships is a record with a
        frame section. Running the frame cases through a record is what puts
        them in front of a real implementation instead of only in front of
        molrec's own codec.
        """
        meta = MetaModel(molrec_version=MOLREC_VERSION)
        for case in FrameSuite().rooted("frame/"):
            yield Case(
                id=f"frame/{case.id}",
                exercises=case.exercises,
                expect_violation=case.expect_violation,
                rejects_on=case.rejects_on,
                backends=case.backends,
                directions=case.directions,
                tamper=case.tamper,
                model=RecordModel.model_construct(meta=meta, frame=case.model, system=None),
                expected=None
                if case.expected is None
                else RecordModel.model_construct(meta=meta, frame=case.expected, system=None),
            )

    def _own_cases(self) -> Iterable[Case]:
        atoms = FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=3,
                    columns={
                        "x": _column("f64", [0.0, 1.5, 3.0]),
                        "element": _column("string", ["H", "O", "H"]),
                    },
                )
            }
        )

        meta = MetaModel(molrec_version=MOLREC_VERSION)

        yield Case(
            id="writer-stamps-version",
            exercises="a writer stamps molrec_version on a meta document that carries none",
            model=RecordModel(meta=MetaModel(), frame=atoms),
            expected=RecordModel(meta=meta, frame=atoms),
        )

        yield Case(
            id="version-present",
            exercises="a store carrying molrec_version 1 validates and hands it back",
            model=RecordModel(meta=meta, frame=atoms),
        )

        yield Case(
            id="absent-version-opens",
            exercises="a store written before version 1 has no molrec_version: no version "
            "check, read best-effort, and nothing is invented",
            model=RecordModel(meta=meta, frame=atoms),
            expected=RecordModel(meta=MetaModel(), frame=atoms),
            directions=("read",),
            tamper=_set_record_meta("molrec_version", _DELETE),
        )

        for case_id, value, why in (
            ("reject-version-zero", 0, "an integer >= 1"),
            ("reject-version-newer", MOLREC_VERSION + 1, "no newer than the reader supports"),
            ("reject-version-null", None, "never null: present means validated"),
            ("reject-version-string", "1", "an integer, not a string"),
            ("reject-version-float", 1.0, "an integer, not a float"),
        ):
            yield Case(
                id=case_id,
                exercises=f"molrec_version, when present, is {why}",
                expect_violation="bad_version",
                model=RecordModel(meta=meta, frame=atoms),
                tamper=_set_record_meta("molrec_version", value),
            )

        yield Case(
            id="system-and-frame",
            exercises="a system definition and a snapshot are separate sections",
            model=RecordModel(
                meta=meta,
                system=FrameModel(
                    blocks={
                        "atoms": BlockModel(
                            count=3, columns={"type": _column("string", ["ht", "ot", "ht"])}
                        ),
                        "bonds": BlockModel(
                            count=2,
                            columns={
                                "atomi": _column("u64", [0, 1]),
                                "atomj": _column("u64", [1, 2]),
                            },
                        ),
                    }
                ),
                frame=atoms,
            ),
        )

        yield Case(
            id="meta-identity-preserved",
            exercises="record identity and content hash survive the round trip",
            model=RecordModel(
                meta=MetaModel(
                    molrec_version=MOLREC_VERSION,
                    record_id="8f14e45f-ea8f-4b6d-9c1a-000000000001",
                    content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                ),
                frame=atoms,
            ),
        )

        yield Case(
            id="meta-unknown-keys-preserved",
            exercises="a reader must keep meta keys it does not recognize",
            model=RecordModel(
                meta=MetaModel.model_validate(
                    {
                        "molrec_version": MOLREC_VERSION,
                        "creator": {"name": "molrec-suite", "version": "0.1.0"},
                        "x_vendor_local": {"anything": [1, 2, 3]},
                    }
                ),
                frame=atoms,
            ),
        )

        yield Case(
            id="reject-narrow-float",
            exercises="floats are f64 only; a frame column stored as binary32 is refused, "
            "not widened",
            expect_violation="narrow_float",
            backends=("zarr",),
            tamper=_narrow("frame/atoms/x"),
            model=RecordModel(meta=meta, frame=atoms),
        )

        yield Case(
            id="system-typed-meta",
            exercises="a system's meta document is typed like a frame's: an i32, an f64x3 and "
            "a NaN survive",
            model=RecordModel(meta=meta, system=_typed_system()),
        )

        yield Case(
            id="record-with-box",
            exercises="the cell rides on the frame section, under the name box",
            model=RecordModel(
                meta=meta,
                frame=FrameModel(
                    blocks={"atoms": BlockModel(count=1, columns={"x": _column("f64", [0.5])})},
                    box=BoxModel(
                        vectors=np.array(
                            [[1.0, 0.0, 0.0], [0.5, 0.8660254, 0.0], [0.0, 0.0, 1.0]],
                            dtype="float64",
                        ),
                        origin=np.zeros(3, dtype="float64"),
                        boundary=(True, True, False),
                    ),
                ),
            ),
        )


def _typed_system() -> FrameModel:
    """A system whose meta needs its tags to read back exactly."""
    return FrameModel(
        blocks={"atoms": BlockModel(count=1, columns={"element": _column("string", ["O"])})},
        meta={"charge": -1, "dipole": [0.0, 0.5, math.nan], "energy": math.nan, "name": "ion"},
        meta_types={"charge": "i32", "dipole": "f64x3", "energy": "f64", "name": "string"},
    )


def _break_first_frame(store: Any) -> None:
    """Rewrite the index so ``first_frame`` is no longer the prefix sum."""
    from molrec.core.bindings.lmdb import INDEX_BLOCK, INDEX_KEY, decode_frame, encode_frame

    env = store.open(write=True)
    try:
        with env.begin(write=True) as txn:
            block = decode_frame(txn.get(INDEX_KEY)).blocks[INDEX_BLOCK]
            first = np.array(block.columns["first_frame"].values, dtype="uint64")
            first[-1] += 1
            columns = {
                **block.columns,
                "first_frame": ColumnModel(dtype="u64", shape=first.shape, values=first),
            }
            txn.put(
                INDEX_KEY,
                encode_frame({INDEX_BLOCK: BlockModel(count=block.count, columns=columns)}, {}),
            )
    finally:
        env.close()


@REGISTRY.suite
class CollectionSuite(Suite):
    """Many records under one declaration (``docs/spec/collection.md``).

    Positive cases are round trips of the logical collection: its units,
    its one declaration, its index columns and every record -- topology held
    once in a system, state per frame, a topology block that changes
    mid-record, a record with no system and one with no trajectory. Negative
    cases are the chapter's MUSTs.
    """

    module: ClassVar[str] = "collection"
    model_type: ClassVar[type[CollectionModel]] = CollectionModel

    UNITS: ClassVar[dict[str, str]] = {"length": "angstrom", "energy": "kcal/mol"}

    def cases(self) -> Iterable[Case]:
        schema_meta = {"pe": MetaSeriesModel(dtype="f64")}
        system = FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=3,
                    columns={
                        "element": _column("string", ["O", "H", "H"]),
                        "atomic_number": _column("u64", [8, 1, 1]),
                    },
                ),
                "bonds": BlockModel(
                    count=2,
                    columns={"atomi": _column("u64", [0, 0]), "atomj": _column("u64", [1, 2])},
                ),
            },
            meta={"molecule_id": "water", "total_charge": 0},
        )

        def state(x: float, pe: float) -> FrameModel:
            return FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=3,
                        columns={
                            "x": _column("f64", [x, x + 1.0, x - 1.0]),
                            "fx": _column("f64", [0.5, -0.25, -0.25]),
                        },
                    )
                },
                meta={"pe": pe},
            )

        relaxation = TrajectoryModel(
            frames=[state(0.0, -1.0), state(0.1, -1.5), state(0.15, -1.6)],
            step=[0, 1, 2],
            meta=schema_meta,
        )
        record = RecordModel(meta=MetaModel(), system=system, trajectory=relaxation)
        meta = CollectionMetaModel(units=self.UNITS, molrec_version=MOLREC_VERSION)

        yield Case(
            id="writer-stamps-version",
            exercises="the collection document carries molrec_version, stamped by the writer",
            model=CollectionModel(meta=CollectionMetaModel(units=self.UNITS), records=[record]),
            expected=CollectionModel(meta=meta, records=[record]),
        )

        yield Case(
            id="topology-once-state-per-frame",
            exercises="system holds the topology once; each frame holds only state; units and "
            "index columns round-trip",
            model=CollectionModel(
                meta=meta,
                records=[record, record.model_copy(update={"meta": MetaModel(record_id="b")})],
                index=BlockModel(
                    count=2,
                    columns={
                        "molecule": _column("i64", [0, 0]),
                        "element_mask": _column("u64", [(1 << 1) | (1 << 8)] * 2),
                    },
                ),
            ),
        )

        yield Case(
            id="system-only-and-trajectory-only",
            exercises="a record may lack a trajectory, or a system, but not both",
            model=CollectionModel(
                meta=meta,
                records=[
                    RecordModel(meta=MetaModel(), system=system),
                    RecordModel(meta=MetaModel(), trajectory=relaxation),
                ],
            ),
        )

        def bonded(pairs: list[tuple[int, int]], x: float) -> FrameModel:
            return FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=3, columns={"x": _column("f64", [x, x + 1.0, x + 2.0])}
                    ),
                    "bonds": BlockModel(
                        count=len(pairs),
                        columns={
                            "atomi": _column("u64", [i for i, _ in pairs]),
                            "atomj": _column("u64", [j for _, j in pairs]),
                        },
                    ),
                },
                meta={"pe": x},
            )

        reaction = TrajectoryModel(
            frames=[bonded([(0, 1)], 0.0), bonded([(0, 1)], 0.1), bonded([(1, 2)], 0.2)],
            step=[0, 1, 2],
            meta=schema_meta,
        )
        yield Case(
            id="topology-changes-mid-record",
            exercises="a changing topology block is a sparse update series: written where it "
            "changes, carried forward elsewhere, never across records",
            model=CollectionModel(
                meta=meta,
                records=[
                    RecordModel(meta=MetaModel(), trajectory=reaction),
                    RecordModel(meta=MetaModel(), trajectory=reaction),
                ],
            ),
        )

        yield Case(
            id="empty-collection",
            exercises="a collection of no records still has units and an index",
            model=CollectionModel(meta=meta, records=[]),
        )

        other = TrajectoryModel(
            frames=[state(0.0, -1.0)],
            step=[0],
            meta={"pe": MetaSeriesModel(dtype="f64", fill=0.0)},
        )
        yield Case(
            id="reject-two-declarations",
            exercises="every record's trajectory uses the one sequence_schema",
            expect_violation="declaration_mismatch",
            rejects_on="write",
            model=CollectionModel.model_construct(
                meta=meta,
                sequence_schema=None,
                index=BlockModel(count=2),
                records=[
                    RecordModel(meta=MetaModel(), system=system, trajectory=relaxation),
                    RecordModel(meta=MetaModel(), system=system, trajectory=other),
                ],
            ),
        )

        short = TrajectoryModel(
            frames=[
                FrameModel(
                    blocks={
                        "atoms": BlockModel(count=2, columns={"x": _column("f64", [0.0, 1.0])})
                    },
                    meta={"pe": 0.0},
                )
            ],
            step=[0],
            meta=schema_meta,
        )
        yield Case(
            id="reject-misaligned-system",
            exercises="a trajectory block sharing a name with a system block has its row count",
            expect_violation="row_count_mismatch",
            rejects_on="write",
            model=CollectionModel.model_construct(
                meta=meta,
                sequence_schema=None,
                index=BlockModel(count=1),
                records=[
                    RecordModel.model_construct(
                        meta=MetaModel(), system=system, trajectory=short, frame=None
                    )
                ],
            ),
        )

        with_bonds = TrajectoryModel(
            frames=[
                FrameModel(
                    blocks={**state(x, -x).blocks, "bonds": system.blocks["bonds"]},
                    meta={"pe": -x},
                )
                for x in (0.0, 0.5)
            ],
            step=[0, 1],
            meta=schema_meta,
        )
        yield Case(
            id="records-present-subsets",
            exercises="a record may present a subset of the collection's declaration; the "
            "declaration is every record's",
            model=CollectionModel(
                meta=meta,
                records=[
                    RecordModel(meta=MetaModel(), trajectory=relaxation),
                    RecordModel(meta=MetaModel(), trajectory=with_bonds),
                ],
            ),
        )

        yield Case(
            id="zero-frame-trajectory",
            exercises="a record whose trajectory has no frames still has a trajectory",
            model=CollectionModel(
                meta=meta,
                records=[
                    RecordModel(
                        meta=MetaModel(),
                        trajectory=TrajectoryModel(frames=[], step=[], meta=schema_meta),
                    ),
                    record,
                ],
            ),
        )

        yield Case(
            id="reject-no-units",
            exercises="a collection declares its units",
            expect_violation="missing_units",
            rejects_on="write",
            model=CollectionModel.model_construct(
                meta=CollectionMetaModel.model_construct(),
                sequence_schema=None,
                index=BlockModel(count=1),
                records=[record],
            ),
        )

        precise_system = FrameModel(
            blocks={
                "atoms": BlockModel(
                    count=3,
                    columns={
                        **system.blocks["atoms"].columns,
                        "mass": ColumnModel(
                            dtype="f64",
                            shape=(3,),
                            values=np.array([15.9994, 1.00794, 1.00794]),
                            precision=_P,
                        ),
                    },
                )
            }
        )
        precise = TrajectoryModel.model_construct(
            frames=[
                _raw_frame({"atoms": {"x": _raw_column("f64", [x, x + 1.0, x - 1.0], None)}})
                for x in (0.1234567, 0.2345678)
            ],
            step=[0, 1],
            time=None,
            blocks={
                "atoms": SequenceBlockModel(
                    columns={"x": SequenceColumnModel(dtype="f64", precision=_P)}
                )
            },
            meta={},
            box=None,
        )
        yield Case(
            id="precision-in-collection",
            exercises="a precision-declared system column (its header entry) and trajectory "
            "column (the collection's sequence_schema) survive the LMDB binding, rounded",
            model=CollectionModel.model_construct(
                meta=meta,
                sequence_schema=None,
                index=BlockModel(count=1),
                records=[
                    RecordModel.model_construct(
                        meta=MetaModel(), system=precise_system, trajectory=precise, frame=None
                    )
                ],
            ),
            expected=CollectionModel(
                meta=meta,
                records=[
                    RecordModel(
                        meta=MetaModel(),
                        system=precise_system,
                        trajectory=TrajectoryModel.model_validate(precise.model_dump()),
                    )
                ],
            ),
        )

        yield Case(
            id="system-typed-meta-lmdb",
            exercises="a system's typed meta survives the frame-bytes header (meta_types)",
            model=CollectionModel(
                meta=meta, records=[RecordModel(meta=MetaModel(), system=_typed_system())]
            ),
        )

        three = ["CT", "HC", "HC"]
        yield Case(
            id="aligned-in-collection",
            exercises="each record holds its aligned block to its target on its own resolved "
            "frames, restating on growth; carry-forward never crosses a record",
            model=CollectionModel(
                meta=meta,
                records=[
                    RecordModel(
                        meta=MetaModel(),
                        trajectory=_aligned_run(
                            ([0.0, 1.0, 2.0], three),
                            ([0.1, 1.1, 2.1, 3.1], [*three, "OW"]),
                            ([0.2, 1.2, 2.2, 3.2], None),
                        ),
                    ),
                    # Its first frame presents the target and not the aligned
                    # block: valid, and nothing carries over from record 0.
                    RecordModel(
                        meta=MetaModel(),
                        trajectory=_aligned_run(([0.0, 1.0], None), ([0.5, 1.5], ["OW", "HW"])),
                    ),
                ],
            ),
        )

        yield Case(
            id="reject-aligned-count-mismatch",
            exercises="a record whose aligned block is not restated when its target grows is "
            "refused",
            expect_violation="aligned_count_mismatch",
            rejects_on="write",
            model=CollectionModel.model_construct(
                meta=meta,
                sequence_schema=None,
                index=BlockModel(count=1),
                records=[
                    RecordModel.model_construct(
                        meta=MetaModel(),
                        system=None,
                        trajectory=_aligned_run(
                            ([0.0, 1.0, 2.0], three),
                            ([0.1, 1.1, 2.1, 3.1], None),
                            validated=False,
                        ),
                        frame=None,
                    )
                ],
            ),
        )

        yield Case(
            id="reject-aligned-shares-system-name",
            exercises="an aligned trajectory block never shares a name with a system block",
            expect_violation="bad_alignment",
            rejects_on="write",
            model=CollectionModel.model_construct(
                meta=meta,
                sequence_schema=None,
                index=BlockModel(count=1),
                records=[
                    RecordModel.model_construct(
                        meta=MetaModel(),
                        system=FrameModel(blocks={"atom_types": _types("CT", "HC", "HC")}),
                        trajectory=_aligned_run(([0.0, 1.0, 2.0], three)),
                        frame=None,
                    )
                ],
            ),
        )

        yield Case(
            id="reject-broken-index",
            exercises="first_frame is the prefix sum of n_frames; a reader refuses otherwise",
            expect_violation="broken_index",
            backends=("lmdb",),
            tamper=_break_first_frame,
            model=CollectionModel(meta=meta, records=[record, record]),
        )
