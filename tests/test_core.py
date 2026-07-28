from pathlib import Path

import cadquery as cq
import pytest

from ai_cad_designer import (
    CADPart,
    create_assembly,
    create_part,
    export_step,
    export_stl,
    generate_joint,
    validate_geometry,
    validate_printability,
)
from ai_cad_designer.validation import validate_pythonocc_bridge


def test_create_export_and_validate_part(tmp_path: Path) -> None:
    part = create_part(
        "tray",
        (30, 20, 10),
        wall_thickness_mm=2,
        open_top=True,
    )
    assert validate_geometry(part)["valid"]
    assert validate_printability(part)["printable"]
    assert export_step(part, tmp_path / "tray.step").stat().st_size > 0
    assert export_stl(part, tmp_path / "tray.stl").stat().st_size > 0


@pytest.mark.parametrize(
    "joint_type", ["snap_fit", "dovetail", "mortise_tenon", "sliding_rail", "magnet"]
)
def test_generate_supported_joints(joint_type: str) -> None:
    pair = generate_joint(joint_type)
    assert validate_geometry(pair.male)["valid"]
    assert validate_geometry(pair.female)["valid"]


def test_create_assembly(tmp_path: Path) -> None:
    first = create_part("first", (10, 10, 2))
    second = create_part("second", (8, 8, 2))
    assembly = create_assembly("pair", [first, second])
    assert export_step(assembly, tmp_path / "pair.step").stat().st_size > 0


def test_pythonocc_core_binding() -> None:
    assert validate_pythonocc_bridge()["valid"]


def test_disconnected_bodies_are_not_one_printable_part() -> None:
    first = cq.Workplane("XY").box(10, 10, 2)
    second = (
        cq.Workplane("XY")
        .box(10, 10, 2)
        .translate((20, 0, 0))
    )
    disconnected = CADPart(
        "disconnected",
        cq.Workplane(
            obj=cq.Compound.makeCompound(
                [first.val(), second.val()]
            )
        ),
        {
            "wall_thickness_mm": 2.0,
            "material": "PETG",
        },
    )

    report = validate_printability(disconnected)

    assert not report["printable"]
    assert report["geometry"]["solid_count"] == 2
    assert report["mesh"]["components"] == 2
