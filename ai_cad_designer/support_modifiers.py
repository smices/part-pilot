"""Generate slicer modifier volumes from measured support-interface toolpaths."""

from __future__ import annotations

from typing import Any

import cadquery as cq

from .core import CADPart


SUPPORT_MODIFIER_REGIONS = {
    25.0: (
        "controller_and_service_roofs",
        "控制器仓、USB 维护拱口与局部卡扣",
        [0.96, 0.62, 0.18],
    ),
    50.0: (
        "main_portal_crowns",
        "四面连续主风口拱冠",
        [1.0, 0.24, 0.18],
    ),
    55.0: (
        "upper_retention_details",
        "上层定位锚点、风扇卡钩与连续承力肋",
        [0.82, 0.22, 0.92],
    ),
}


def create_support_modifier_parts(
    manufacturing: dict[str, Any],
    *,
    chassis: CADPart | None = None,
    padding_xy_mm: float = 0.4,
    padding_z_mm: float = 0.2,
) -> list[CADPart]:
    """Build one non-printing STL modifier for each measured contact band."""

    if padding_xy_mm < 0.0 or padding_z_mm < 0.0:
        raise ValueError("support modifier padding must be non-negative")
    envelope = (
        manufacturing.get("support_analysis", {})
        .get("parts", {})
        .get("fan_chassis", {})
        .get("support_toolpath_envelope", {})
    )
    cells = envelope.get("xyz_cells", [])
    modifiers: list[CADPart] = []

    for z_start, (region_id, display_name, color_rgb) in (
        SUPPORT_MODIFIER_REGIONS.items()
    ):
        region_z_starts = (
            (45.0, 50.0)
            if region_id == "main_portal_crowns"
            else (z_start,)
        )
        region_cells = [
            cell
            for cell in cells
            if (
                float(
                    cell.get(
                        "nominal_local_bbox_xyz_mm",
                        [-1.0] * 6,
                    )[2]
                )
                in region_z_starts
                and
                int(
                    cell.get("feature_move_counts", {}).get(
                        "support_interface",
                        0,
                    )
                )
                > 0
            )
        ]
        if not region_cells:
            continue
        solids: list[cq.Shape] = []
        for cell in region_cells:
            x0, y0, z0, x1, y1, z1 = (
                float(value)
                for value in cell["actual_local_bbox_xyz_mm"]
            )
            x0 -= padding_xy_mm
            y0 -= padding_xy_mm
            z0 -= padding_z_mm
            x1 += padding_xy_mm
            y1 += padding_xy_mm
            z1 += padding_z_mm
            dimensions = (
                max(0.4, x1 - x0),
                max(0.4, y1 - y0),
                max(0.4, z1 - z0),
            )
            solids.append(
                cq.Solid.makeBox(
                    *dimensions,
                    cq.Vector(x0, y0, z0),
                )
            )
        compound = cq.Compound.makeCompound(solids)
        bounds = compound.BoundingBox()
        chassis_intersection_mm3 = (
            float(compound.intersect(chassis.solid()).Volume())
            if chassis is not None
            else None
        )
        interface_moves = sum(
            int(
                cell.get("feature_move_counts", {}).get(
                    "support_interface",
                    0,
                )
            )
            for cell in region_cells
        )
        extrusion_moves = sum(
            int(cell.get("extrusion_move_count", 0))
            for cell in region_cells
        )
        modifiers.append(
            CADPart(
                name=f"support_modifier_{region_id}",
                shape=cq.Workplane(obj=compound),
                metadata={
                    "dimensions_mm": (
                        float(bounds.xlen),
                        float(bounds.ylen),
                        float(bounds.zlen),
                    ),
                    "translation_mm": (0.0, 0.0, 0.0),
                    "rotation_deg": (0.0, 0.0, 0.0),
                    "is_reference": True,
                    "reference_kind": "support_modifier",
                    "not_a_printed_part": True,
                    "modifier_region_id": region_id,
                    "display_name": display_name,
                    "color_rgb": color_rgb,
                    "opacity": 0.62,
                    "source_cell_count": len(region_cells),
                    "source_z_band_starts_mm": list(
                        region_z_starts
                    ),
                    "source_support_extrusion_move_count": (
                        extrusion_moves
                    ),
                    "source_support_interface_move_count": (
                        interface_moves
                    ),
                    "padding_xy_mm": padding_xy_mm,
                    "padding_z_mm": padding_z_mm,
                    "chassis_intersection_mm3": (
                        chassis_intersection_mm3
                    ),
                    "coordinate_system": (
                        "fan_chassis STL local coordinates in production "
                        "orientation"
                    ),
                    "operator_use": (
                        "import together with fan_chassis.stl without moving "
                        "either mesh; assign this volume as a support enforcer "
                        "only after the matching physical coupon/fit check "
                        "fails, or as a blocker when global support is "
                        "unavoidably enabled for another region"
                    ),
                },
            )
        )
    return modifiers
