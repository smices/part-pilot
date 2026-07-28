import cadquery as cq

from ai_cad_designer.core import create_assembly, create_part
from ai_cad_designer.validation import validate_assembly_interference


def test_assembly_interference_reports_clearance() -> None:
    first = create_part("first", (10, 10, 10))
    second = create_part("second", (10, 10, 10))
    assembly = create_assembly(
        "clear",
        [
            first,
            (second, cq.Location(cq.Vector(11, 0, 0))),
        ],
    )

    report = validate_assembly_interference(assembly)

    assert report["passed"]
    assert report["pairs"][0]["overlap_mm3"] == 0


def test_assembly_interference_rejects_overlapping_solids() -> None:
    first = create_part("first", (10, 10, 10))
    second = create_part("second", (10, 10, 10))
    assembly = create_assembly(
        "overlap",
        [
            first,
            (second, cq.Location(cq.Vector(9, 0, 0))),
        ],
    )

    report = validate_assembly_interference(assembly)

    assert not report["passed"]
    assert report["pairs"][0]["overlap_mm3"] > 9.9
