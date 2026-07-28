from pathlib import Path

import trimesh

from ai_cad_designer.core import create_part, export_stl
from ai_cad_designer.support_modifiers import create_support_modifier_parts


def test_support_modifiers_preserve_measured_regions_and_export(
    tmp_path: Path,
) -> None:
    cells = []
    for index, (z_start, interfaces) in enumerate(
        ((25.0, 11), (50.0, 22), (55.0, 33))
    ):
        cells.append(
            {
                "nominal_local_bbox_xyz_mm": [
                    float(index * 10),
                    0.0,
                    z_start,
                    float(index * 10 + 10),
                    10.0,
                    z_start + 5.0,
                ],
                "actual_local_bbox_xyz_mm": [
                    float(index * 10 + 1),
                    2.0,
                    z_start,
                    float(index * 10 + 4),
                    6.0,
                    z_start + 0.8,
                ],
                "extrusion_move_count": interfaces + 100,
                "feature_move_counts": {
                    "support": 100,
                    "support_interface": interfaces,
                },
            }
        )
    manufacturing = {
        "support_analysis": {
            "parts": {
                "fan_chassis": {
                    "support_toolpath_envelope": {
                        "xyz_cells": cells,
                    }
                }
            }
        }
    }

    chassis = create_part("fan_chassis", (132.0, 132.0, 61.0))
    modifiers = create_support_modifier_parts(
        manufacturing,
        chassis=chassis,
    )

    assert [part.name for part in modifiers] == [
        "support_modifier_controller_and_service_roofs",
        "support_modifier_main_portal_crowns",
        "support_modifier_upper_retention_details",
    ]
    assert [
        part.metadata["source_support_interface_move_count"]
        for part in modifiers
    ] == [11, 22, 33]
    assert all(part.metadata["not_a_printed_part"] for part in modifiers)
    assert all(
        part.metadata["chassis_intersection_mm3"] > 0.0
        for part in modifiers
    )
    assert all(len(part.shape.val().Solids()) == 1 for part in modifiers)

    for part in modifiers:
        path = export_stl(part, tmp_path / f"{part.name}.stl")
        mesh = trimesh.load_mesh(path, force="mesh")
        assert mesh.is_watertight
        assert mesh.volume > 0.0


def test_support_modifier_padding_must_be_non_negative() -> None:
    try:
        create_support_modifier_parts(
            {},
            padding_xy_mm=-0.1,
        )
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("negative padding was accepted")
