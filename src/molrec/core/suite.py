"""What the core module is pinned down by.

Each case is one claim about the contract, and each runs in both directions.
The negative cases matter as much as the positive ones: a reader that accepts
everything conforms to nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

import numpy as np

from molrec.case import Case
from molrec.core.model import (
    NUMPY_DTYPE,
    BlockModel,
    BoxModel,
    ColumnModel,
    ForceFieldModel,
    FrameModel,
    MeshModel,
    MetaModel,
    RecordModel,
    StyleEntryModel,
    UnitsModel,
)
from molrec.registry import REGISTRY
from molrec.suite import Suite


def _column(dtype: str, values: list, shape: tuple[int, ...] | None = None) -> ColumnModel:
    array = np.array(values, dtype=NUMPY_DTYPE[dtype])
    return ColumnModel(dtype=dtype, shape=shape or array.shape, values=array)


@REGISTRY.suite
class FrameSuite(Suite):
    module: ClassVar[str] = "core"
    model_type: ClassVar[type[FrameModel]] = FrameModel

    def cases(self) -> Iterable[Case]:
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
                            "c_f16": _column("f16", [1.0, -2.0]),
                            "c_f32": _column("f32", [1.5, -2.5]),
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
            exercises="f32 must come back f32 -- widening doubles the file, narrowing loses data",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=3,
                        columns={
                            "x": _column("f32", [0.0, 1.5, 3.0]),
                            "step": _column("i32", [0, 1, 2]),
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
            id="validity-mask",
            exercises="a false validity flag is data; the filler under it is not a value",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=2,
                        columns={
                            "charge": ColumnModel(
                                dtype="f64",
                                shape=(2,),
                                values=np.array([0.5, 0.0], dtype="float64"),
                                validity=(True, False),
                            )
                        },
                    )
                }
            ),
        )

        yield Case(
            id="reject-column-named-validity",
            exercises="_validity names the mask subgroup; a column taking it must be refused",
            expect_violation="reserved_column_name",
            model=FrameModel(
                blocks={
                    "atoms": BlockModel(
                        count=1,
                        columns={"_validity": _column("i64", [1])},
                    )
                }
            ),
        )

        yield Case(
            id="reject-block-named-box",
            exercises="box names the cell; a block taking it must be refused, not silently lost",
            expect_violation="reserved_block_name",
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
            id="block-mesh",
            exercises="a grid with its own origin and axis steps is not the frame box",
            model=FrameModel(
                blocks={
                    "density": BlockModel(
                        count=8,
                        structural_shape=(2, 2, 2),
                        sample="corner",
                        mesh=MeshModel(
                            origin=np.zeros(3, dtype="float64"),
                            vectors=np.eye(3, dtype="float64") * 0.2,
                            boundary=(False, False, False),
                            unit="bohr",
                        ),
                        columns={"values": _column("f64", [0.0] * 8)},
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
                        sample="center",
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
            exercises="the frame's free-form meta document survives, nesting included",
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
        meta = MetaModel(record_schema_version=1, format_name="molrec")
        for case in FrameSuite().cases():
            yield Case(
                id=f"frame/{case.id}",
                exercises=case.exercises,
                expect_violation=case.expect_violation,
                backends=case.backends,
                model=RecordModel.model_construct(meta=meta, frame=case.model, system=None),
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

        yield Case(
            id="forcefield",
            exercises="a force-field package is meta plus forcefield and needs no frame",
            model=RecordModel(
                meta=MetaModel(
                    record_schema_version=1,
                    format_name="molrec",
                    units=UnitsModel(preset="real"),
                ),
                forcefield=ForceFieldModel(
                    name="demo",
                    units=UnitsModel(preset="real"),
                    styles=[StyleEntryModel(category="bond", style="harmonic")],
                    tables={
                        "bond.harmonic": BlockModel(
                            count=1,
                            columns={
                                "name": _column("string", ["A-B"]),
                                "itom": _column("string", ["A"]),
                                "jtom": _column("string", ["B"]),
                                "k": _column("f64", [300.0]),
                                "r0": _column("f64", [1.5]),
                            },
                        )
                    },
                ),
            ),
        )

        yield Case(
            id="run",
            exercises="a run is meta plus a status document and needs no frame",
            model=RecordModel.model_validate(
                {
                    "meta": {"record_schema_version": 1, "format_name": "molrec"},
                    "status": {"state": "succeeded", "stage": "train"},
                }
            ),
        )

        yield Case(
            id="structure",
            exercises="the minimum interchange unit: meta plus one frame",
            model=RecordModel(
                meta=MetaModel(record_schema_version=1, format_name="molrec"),
                frame=atoms,
            ),
        )

        yield Case(
            id="system-and-frame",
            exercises="a system definition and a snapshot are separate sections",
            model=RecordModel(
                meta=MetaModel(record_schema_version=1, format_name="molrec"),
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
                    record_schema_version=1,
                    format_name="molrec",
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
                        "record_schema_version": 1,
                        "format_name": "molrec",
                        "creator": {"name": "molrec-suite", "version": "0.1.0"},
                        "x_vendor_local": {"anything": [1, 2, 3]},
                    }
                ),
                frame=atoms,
            ),
        )

        yield Case(
            id="record-with-box",
            exercises="the cell rides on the frame section, under the name box",
            model=RecordModel(
                meta=MetaModel(record_schema_version=1, format_name="molrec"),
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
