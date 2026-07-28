"""OpenCascade topology validation and FDM-oriented mesh checks."""

from __future__ import annotations

import tempfile
import copy
from pathlib import Path
from typing import Any

import numpy as np
import open3d as o3d
import trimesh
import cadquery as cq

from OCP.BRepCheck import BRepCheck_Analyzer
from OCC.Core.BRepCheck import BRepCheck_Analyzer as PythonOCCBRepCheckAnalyzer
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox

from .core import CADAssembly, CADPart, export_stl


def validate_geometry(part: CADPart) -> dict[str, Any]:
    """Validate a CadQuery shape through OpenCascade's BRepCheck analyzer."""
    solid = part.solid()
    analyzer = BRepCheck_Analyzer(solid.wrapped)
    return {
        "valid": bool(analyzer.IsValid()),
        "solid_count": len(solid.Solids()),
        "volume_mm3": float(solid.Volume()),
        "area_mm2": float(solid.Area()),
        "kernel": "OpenCascade/OCP",
    }


def validate_pythonocc_bridge() -> dict[str, Any]:
    """Exercise the separately installed pythonocc-core binding and validator."""
    shape = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    analyzer = PythonOCCBRepCheckAnalyzer(shape)
    return {
        "valid": bool(analyzer.IsValid()),
        "kernel": "OpenCascade/pythonocc-core",
        "test_shape": "1mm cube",
    }


def validate_assembly_interference(
    assembly: CADAssembly,
    *,
    maximum_overlap_mm3: float = 0.01,
) -> dict[str, Any]:
    """Use OpenCascade booleans to reject pairwise solid interference."""

    placed = {
        part.name: part.solid().located(assembly.placements[part.name])
        for part in assembly.parts
    }
    names = list(placed)
    pairs: list[dict[str, Any]] = []
    for index, first_name in enumerate(names):
        for second_name in names[index + 1 :]:
            common = placed[first_name].intersect(placed[second_name])
            overlap = float(common.Volume()) if not common.isNull() else 0.0
            pairs.append(
                {
                    "parts": [first_name, second_name],
                    "overlap_mm3": round(overlap, 6),
                    "passed": overlap <= maximum_overlap_mm3,
                }
            )
    return {
        "passed": all(pair["passed"] for pair in pairs),
        "maximum_overlap_mm3": maximum_overlap_mm3,
        "pairs": pairs,
        "kernel": "OpenCascade/OCP boolean intersection",
    }


def validate_printability(
    part: CADPart,
    *,
    nozzle_diameter_mm: float = 0.4,
    layer_height_mm: float = 0.2,
    max_build_dimension_mm: float = 220.0,
) -> dict[str, Any]:
    """Run topology, watertightness, build-volume, and FDM wall checks."""
    # Exporting/meshing CadQuery solids may mutate the workplane/shapes in
    # place for some kernels/versions, which can silently inflate subsequent
    # envelope checks. Validate against an explicit copy to keep source geometry
    # immutable for later envelope/assembly review logic.
    validation_shape = part.solid().copy()
    validation_part = CADPart(
        name=part.name,
        shape=cq.Workplane(obj=validation_shape),
        metadata=copy.deepcopy(part.metadata),
    )
    geometry = validate_geometry(validation_part)
    with tempfile.TemporaryDirectory(prefix="ai-cad-check-") as temp_dir:
        stl_path = export_stl(
            validation_part, Path(temp_dir) / f"{part.name}.stl"
        )
        mesh = trimesh.load_mesh(stl_path, force="mesh", process=True)
        if not isinstance(mesh, trimesh.Trimesh):
            raise TypeError(f"{part.name} did not tessellate to a triangle mesh")
        open3d_mesh = o3d.io.read_triangle_mesh(str(stl_path), enable_post_processing=True)
        # STL repeats vertices per facet; merge them before Open3D's manifold test.
        open3d_mesh.merge_close_vertices(1e-7)
        open3d_mesh.remove_duplicated_triangles()
        open3d_mesh.remove_degenerate_triangles()
        open3d_mesh.remove_unreferenced_vertices()

    extents = np.asarray(mesh.extents, dtype=float)
    wall = part.metadata.get("wall_thickness_mm")
    wall_ok = wall is None or float(wall) >= nozzle_diameter_mm * 2
    build_volume_ok = bool(np.all(extents <= max_build_dimension_mm))
    watertight = bool(mesh.is_watertight)
    open3d_watertight = bool(open3d_mesh.is_watertight())
    winding_consistent = bool(mesh.is_winding_consistent)
    components = len(mesh.split(only_watertight=False))

    warnings: list[str] = []
    if wall is not None and not wall_ok:
        warnings.append(
            f"wall {float(wall):g}mm is below two {nozzle_diameter_mm:g}mm extrusion widths"
        )
    if not build_volume_ok:
        warnings.append(f"part exceeds {max_build_dimension_mm:g}mm build envelope")
    if components > 1:
        warnings.append(f"mesh contains {components} disconnected printable bodies")
    if geometry["solid_count"] != 1:
        warnings.append(
            "OpenCascade shape contains "
            f"{geometry['solid_count']} disconnected solids"
        )

    printable = all(
        (
            geometry["valid"],
            geometry["solid_count"] == 1,
            geometry["volume_mm3"] > 0,
            watertight,
            open3d_watertight,
            winding_consistent,
            components == 1,
            wall_ok,
            build_volume_ok,
        )
    )
    return {
        "printable": printable,
        "geometry": geometry,
        "mesh": {
            "watertight_trimesh": watertight,
            "watertight_open3d": open3d_watertight,
            "winding_consistent": winding_consistent,
            "triangle_count": int(len(mesh.faces)),
            "components": components,
        },
        "fdm": {
            "material": part.metadata.get("material", "PETG"),
            "nozzle_diameter_mm": nozzle_diameter_mm,
            "layer_height_mm": layer_height_mm,
            "wall_thickness_mm": wall,
            "wall_ok": wall_ok,
            "build_volume_ok": build_volume_ok,
            "extents_mm": extents.round(3).tolist(),
            "orientation": part.metadata.get("print_orientation", "+Z"),
            "support_strategy": part.metadata.get("support_strategy", "minimal"),
        },
        "warnings": warnings,
    }
