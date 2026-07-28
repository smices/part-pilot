"""OrcaSlicer 3MF projects with embedded support-enforcer volumes."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PRODUCTION_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_BAMBU_NS = "http://schemas.bambulab.com/package/2021"
_IDENTITY_3MF = "1 0 0 0 1 0 0 0 1 0 0 0"
_IDENTITY_4X4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
_SUPPORT_SETTING_RANGES = {
    "support_base_pattern_spacing": (1.5, 6.0),
    "tree_support_branch_distance": (3.0, 10.0),
    "tree_support_branch_diameter": (1.2, 4.0),
    "tree_support_tip_diameter": (0.6, 1.5),
    "tree_support_brim_width": (0.0, 5.0),
}
_BOOLEAN_SUPPORT_SETTINGS = {
    "support_on_build_plate_only",
    "bridge_no_support",
}


class OrcaProjectError(RuntimeError):
    """Raised when an OrcaSlicer project cannot be generated safely."""


def create_support_enforcer_project(
    *,
    template_3mf: str | Path,
    chassis_stl: str | Path,
    modifier_stl: str | Path,
    output_3mf: str | Path,
    project_name: str,
    bed_center_xy_mm: tuple[float, float] = (128.0, 128.0),
    support_type: str = "tree(manual)",
    support_settings: dict[str, str | float | int] | None = None,
) -> dict[str, Any]:
    """Create a reloadable OrcaSlicer project with one support-enforcer volume.

    The two meshes retain their STL-local coordinates inside one 3MF object.
    Moving the object therefore moves both volumes as one assembly, eliminating
    the separate-import centering error possible with loose STL files.
    """

    template = _required_file(template_3mf, "template_3mf")
    chassis_path = _required_file(chassis_stl, "chassis_stl")
    modifier_path = _required_file(modifier_stl, "modifier_stl")
    output = Path(output_3mf).expanduser().resolve()
    if output.suffix.lower() != ".3mf":
        raise ValueError("output_3mf must use the .3mf extension")
    if not project_name.strip():
        raise ValueError("project_name must not be empty")
    if support_type not in {"normal(manual)", "tree(manual)"}:
        raise ValueError("support_type must be normal(manual) or tree(manual)")
    normalized_support_settings = _normalize_support_settings(
        support_settings or {}
    )

    chassis = _load_mesh(chassis_path)
    modifier = _load_mesh(modifier_path)
    _validate_same_coordinate_volume(chassis, modifier)

    with zipfile.ZipFile(template) as archive:
        package = {
            name: archive.read(name)
            for name in archive.namelist()
            if not name.endswith("/")
        }

    object_path = _object_model_path(package)
    required = {
        "3D/3dmodel.model",
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
        object_path,
    }
    missing = sorted(required.difference(package))
    if missing:
        raise OrcaProjectError(
            f"template 3MF is missing required entries: {', '.join(missing)}"
        )

    package[object_path] = _object_model_xml(
        chassis=chassis,
        modifier=modifier,
    ).encode("utf-8")
    package["3D/3dmodel.model"] = _root_model_xml(
        object_path=object_path,
        project_name=project_name,
        bed_center_xy_mm=bed_center_xy_mm,
    ).encode("utf-8")
    package["Metadata/model_settings.config"] = _model_settings_xml(
        project_name=project_name,
        chassis_name=chassis_path.name,
        modifier_name=modifier_path.name,
    ).encode("utf-8")
    package["Metadata/project_settings.config"] = _project_settings(
        package["Metadata/project_settings.config"],
        support_type=support_type,
        support_settings=normalized_support_settings,
    )

    for stale_name in (
        "Metadata/plate_1.gcode",
        "Metadata/plate_1.gcode.md5",
        "Metadata/plate_1.json",
    ):
        package.pop(stale_name, None)

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for name in sorted(package):
            archive.writestr(name, package[name])

    return {
        "passed": True,
        "project": str(output),
        "project_name": project_name,
        "chassis_stl": str(chassis_path),
        "modifier_stl": str(modifier_path),
        "support_type": support_type,
        "support_settings": normalized_support_settings,
        "volume_roles": {
            chassis_path.name: "normal_part",
            modifier_path.name: "support_enforcer",
        },
        "same_coordinate_system": True,
        "bed_center_xy_mm": [float(value) for value in bed_center_xy_mm],
        "chassis_bounds_mm": _bounds(chassis),
        "modifier_bounds_mm": _bounds(modifier),
        "chassis_faces": int(len(chassis.faces)),
        "modifier_faces": int(len(modifier.faces)),
        "operator_warning": (
            "Open this 3MF directly; do not import or arrange the modifier as "
            "a separate model, and do not print the support-enforcer volume."
        ),
    }


def inspect_support_enforcer_project(project_3mf: str | Path) -> dict[str, Any]:
    """Inspect archive roles and safety settings without trusting file names."""

    project = _required_file(project_3mf, "project_3mf")
    with zipfile.ZipFile(project) as archive:
        names = set(archive.namelist())
        model_settings = ET.fromstring(
            archive.read("Metadata/model_settings.config")
        )
        project_settings = json.loads(
            archive.read("Metadata/project_settings.config")
        )
        root_model = ET.fromstring(archive.read("3D/3dmodel.model"))

    parts = [
        {
            "id": part.attrib.get("id", ""),
            "subtype": part.attrib.get("subtype", ""),
            "name": next(
                (
                    item.attrib.get("value", "")
                    for item in part.findall("metadata")
                    if item.attrib.get("key") == "name"
                ),
                "",
            ),
        }
        for part in model_settings.findall("./object/part")
    ]
    component_tag = f"{{{_CORE_NS}}}component"
    build_item_tag = f"{{{_CORE_NS}}}item"
    components = root_model.findall(f".//{component_tag}")
    build_items = root_model.findall(f".//{build_item_tag}")
    stale_gcode = sorted(
        name
        for name in names
        if name.endswith(".gcode") or name.endswith(".gcode.md5")
    )
    passed = (
        [part["subtype"] for part in parts]
        == ["normal_part", "support_enforcer"]
        and project_settings.get("enable_support") == "1"
        and project_settings.get("support_type")
        in {"normal(manual)", "tree(manual)"}
        and len(components) == 2
        and len(build_items) == 1
        and not stale_gcode
    )
    return {
        "passed": passed,
        "project": str(project),
        "parts": parts,
        "enable_support": project_settings.get("enable_support"),
        "support_type": project_settings.get("support_type"),
        "support_settings": {
            key: project_settings.get(key)
            for key in (
                *_SUPPORT_SETTING_RANGES,
                "tree_support_top_rate",
                *_BOOLEAN_SUPPORT_SETTINGS,
            )
            if key in project_settings
        },
        "component_count": len(components),
        "build_item_count": len(build_items),
        "stale_gcode_entries": stale_gcode,
    }


def _required_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _load_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(path, force="mesh", process=True)
    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.to_geometry()
    if not isinstance(loaded, trimesh.Trimesh) or loaded.is_empty:
        raise OrcaProjectError(f"mesh is empty or unsupported: {path}")
    if not loaded.is_watertight:
        raise OrcaProjectError(f"mesh must be watertight: {path}")
    return loaded


def _validate_same_coordinate_volume(
    chassis: trimesh.Trimesh,
    modifier: trimesh.Trimesh,
) -> None:
    chassis_bounds = np.asarray(chassis.bounds, dtype=float)
    modifier_bounds = np.asarray(modifier.bounds, dtype=float)
    overlap = np.minimum(chassis_bounds[1], modifier_bounds[1]) - np.maximum(
        chassis_bounds[0], modifier_bounds[0]
    )
    if np.any(overlap <= 0.0):
        raise OrcaProjectError(
            "modifier and chassis bounds do not overlap in the same coordinate system"
        )


def _object_model_path(package: dict[str, bytes]) -> str:
    candidates = sorted(
        name
        for name in package
        if name.startswith("3D/Objects/") and name.endswith(".model")
    )
    if len(candidates) != 1:
        raise OrcaProjectError(
            "template 3MF must contain exactly one object model"
        )
    return candidates[0]


def _fmt(value: float) -> str:
    text = f"{float(value):.7f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _mesh_xml(mesh: trimesh.Trimesh, object_id: int) -> str:
    vertices = "\n".join(
        f'     <vertex x="{_fmt(x)}" y="{_fmt(y)}" z="{_fmt(z)}"/>'
        for x, y, z in np.asarray(mesh.vertices, dtype=float)
    )
    triangles = "\n".join(
        f'     <triangle v1="{int(a)}" v2="{int(b)}" v3="{int(c)}"/>'
        for a, b, c in np.asarray(mesh.faces, dtype=np.int64)
    )
    return (
        f'  <object id="{object_id}" '
        f'p:UUID="0001000{object_id - 1}-81cb-4c03-9d28-80fed5dfa1dc" '
        'type="model">\n'
        "   <mesh>\n"
        "    <vertices>\n"
        f"{vertices}\n"
        "    </vertices>\n"
        "    <triangles>\n"
        f"{triangles}\n"
        "    </triangles>\n"
        "   </mesh>\n"
        "  </object>"
    )


def _object_model_xml(
    *,
    chassis: trimesh.Trimesh,
    modifier: trimesh.Trimesh,
) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        f'xmlns="{_CORE_NS}" xmlns:BambuStudio="{_BAMBU_NS}" '
        f'xmlns:p="{_PRODUCTION_NS}" requiredextensions="p">\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        " <resources>\n"
        f"{_mesh_xml(chassis, 1)}\n"
        f"{_mesh_xml(modifier, 2)}\n"
        " </resources>\n"
        "</model>\n"
    )


def _root_model_xml(
    *,
    object_path: str,
    project_name: str,
    bed_center_xy_mm: tuple[float, float],
) -> str:
    path = f"/{object_path}"
    x, y = bed_center_xy_mm
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        f'xmlns="{_CORE_NS}" xmlns:BambuStudio="{_BAMBU_NS}" '
        f'xmlns:p="{_PRODUCTION_NS}" requiredextensions="p">\n'
        ' <metadata name="Application">BambuStudio-02.06.00.51</metadata>\n'
        ' <metadata name="OrcaSlicer">2.4.2</metadata>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        f' <metadata name="Title">{_xml_text(project_name)}</metadata>\n'
        " <resources>\n"
        '  <object id="2" '
        'p:UUID="00000001-61cb-4c03-9d28-80fed5dfa1dc" type="model">\n'
        "   <components>\n"
        f'    <component p:path="{path}" objectid="1" '
        'p:UUID="00010000-b206-40ff-9872-83e8017abed1" '
        f'transform="{_IDENTITY_3MF}"/>\n'
        f'    <component p:path="{path}" objectid="2" '
        'p:UUID="00010001-b206-40ff-9872-83e8017abed1" '
        f'transform="{_IDENTITY_3MF}"/>\n'
        "   </components>\n"
        "  </object>\n"
        " </resources>\n"
        ' <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">\n'
        '  <item objectid="2" '
        'p:UUID="00000002-b1ec-4553-aec9-835e5b724bb4" '
        f'transform="1 0 0 0 1 0 0 0 1 {_fmt(x)} {_fmt(y)} 0" '
        'printable="1" auto_drop="0"/>\n'
        " </build>\n"
        "</model>\n"
    )


def _model_settings_xml(
    *,
    project_name: str,
    chassis_name: str,
    modifier_name: str,
) -> str:
    def part(
        part_id: int,
        subtype: str,
        name: str,
        *,
        extruder: bool,
    ) -> str:
        extruder_line = (
            '      <metadata key="extruder" value="1"/>\n'
            if extruder
            else ""
        )
        return (
            f'    <part id="{part_id}" subtype="{subtype}">\n'
            f'      <metadata key="name" value="{_xml_attr(name)}"/>\n'
            f'      <metadata key="matrix" value="{_IDENTITY_4X4}"/>\n'
            f'      <metadata key="source_file" value="{_xml_attr(name)}"/>\n'
            '      <metadata key="source_object_id" value="0"/>\n'
            f'      <metadata key="source_volume_id" value="{part_id - 1}"/>\n'
            '      <metadata key="source_offset_x" value="0"/>\n'
            '      <metadata key="source_offset_y" value="0"/>\n'
            '      <metadata key="source_offset_z" value="0"/>\n'
            f"{extruder_line}"
            '      <mesh_stat edges_fixed="0" degenerate_facets="0" '
            'facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
            "    </part>\n"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<config>\n"
        '  <object id="2">\n'
        f'    <metadata key="name" value="{_xml_attr(project_name)}"/>\n'
        '    <metadata key="extruder" value="1"/>\n'
        f"{part(1, 'normal_part', chassis_name, extruder=True)}"
        f"{part(2, 'support_enforcer', modifier_name, extruder=False)}"
        "  </object>\n"
        "  <plate>\n"
        '    <metadata key="plater_id" value="1"/>\n'
        f'    <metadata key="plater_name" value="{_xml_attr(project_name)}"/>\n'
        '    <metadata key="locked" value="false"/>\n'
        '    <metadata key="filament_map_mode" value="Auto For Flush"/>\n'
        '    <metadata key="gcode_file" value=""/>\n'
        "    <model_instance>\n"
        '      <metadata key="object_id" value="2"/>\n'
        '      <metadata key="instance_id" value="0"/>\n'
        '      <metadata key="identify_id" value="1"/>\n'
        "    </model_instance>\n"
        "  </plate>\n"
        "  <assemble>\n"
        "  </assemble>\n"
        "</config>\n"
    )


def _project_settings(
    raw: bytes,
    *,
    support_type: str,
    support_settings: dict[str, str],
) -> bytes:
    settings = json.loads(raw)
    settings["enable_support"] = "1"
    settings["support_type"] = support_type
    settings["support_on_build_plate_only"] = "0"
    settings["support_threshold_angle"] = "30"
    settings["curr_bed_type"] = "Textured PEI Plate"
    settings.update(support_settings)
    return json.dumps(
        settings,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")


def _normalize_support_settings(
    settings: dict[str, str | float | int],
) -> dict[str, str]:
    unknown = sorted(
        set(settings).difference(
            {
                *_SUPPORT_SETTING_RANGES,
                "tree_support_top_rate",
                *_BOOLEAN_SUPPORT_SETTINGS,
            }
        )
    )
    if unknown:
        raise ValueError(
            "unsupported OrcaSlicer support setting(s): "
            + ", ".join(unknown)
        )
    normalized: dict[str, str] = {}
    for key, value in settings.items():
        if key in _BOOLEAN_SUPPORT_SETTINGS:
            text = str(value).strip().lower()
            if text in {"1", "true"}:
                normalized[key] = "1"
            elif text in {"0", "false"}:
                normalized[key] = "0"
            else:
                raise ValueError(f"{key} must be boolean or 0/1")
            continue
        if key == "tree_support_top_rate":
            text = str(value).strip()
            numeric = float(text.removesuffix("%"))
            if not 15.0 <= numeric <= 40.0:
                raise ValueError(
                    "tree_support_top_rate must be between 15% and 40%"
                )
            normalized[key] = f"{numeric:g}%"
            continue
        numeric = float(value)
        lower, upper = _SUPPORT_SETTING_RANGES[key]
        if not lower <= numeric <= upper:
            raise ValueError(
                f"{key} must be between {lower:g} and {upper:g}"
            )
        normalized[key] = f"{numeric:g}"
    if (
        "tree_support_branch_diameter" in normalized
        and "tree_support_tip_diameter" in normalized
        and float(normalized["tree_support_branch_diameter"])
        < float(normalized["tree_support_tip_diameter"])
    ):
        raise ValueError(
            "tree support branch diameter must not be smaller than tip diameter"
        )
    return normalized


def _bounds(mesh: trimesh.Trimesh) -> list[list[float]]:
    return [
        [round(float(value), 4) for value in row]
        for row in np.asarray(mesh.bounds, dtype=float)
    ]


def _xml_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _xml_attr(value: str) -> str:
    return _xml_text(value).replace('"', "&quot;").replace("'", "&apos;")
