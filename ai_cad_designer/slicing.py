"""Reproducible OrcaSlicer manufacturing validation."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_ORCA_BINARY = Path(
    "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
)
DEFAULT_PROFILE_ROOT = Path(
    "/Applications/OrcaSlicer.app/Contents/Resources/profiles"
)
REFERENCE_VENDOR = "BBL"
REFERENCE_MACHINE = "Bambu Lab P1P 0.4 nozzle"
REFERENCE_PROCESS = "0.20mm Standard @BBL P1P"
REFERENCE_FILAMENT = "Generic PETG @BBL P1P"


class OrcaSlicerError(RuntimeError):
    """Raised when a profile cannot be resolved or a slice cannot complete."""


def _support_removal_access_stats(
    stats: dict[str, Any],
    *,
    bed_center_xy_mm: tuple[float, float] = (0.0, 0.0),
    chassis_footprint_mm: tuple[float, float] = (132.0, 132.0),
    central_airway_radius_mm: float = 50.0,
    permanent_airway_start_z_mm: float = 29.0,
    minimum_bed_connected_interface_ratio: float = 0.98,
    maximum_side_pick_interface_moves: int = 8,
    minimum_side_pick_edge_ratio: float = 0.95,
) -> dict[str, Any]:
    """Measure whether sliced support remains extractable after printing.

    ``actual_local_bbox_xyz_mm`` is already centered on the sliced object, so
    the default origin is ``(0, 0)`` rather than the machine-bed center.
    Support cells are grouped with 26-neighbour connectivity. Interface paths
    connected to the build plate can be pulled from the open underside before
    the fan guard and hardware are installed. Small disconnected interface
    islands are limited to two percent and must remain side-pickable. A single
    exterior micro-island may instead contain at most eight interface moves,
    provided it lies within the outer five percent of the footprint.
    """

    cells = stats.get("xyz_cells", [])
    center_x, center_y = bed_center_xy_mm
    half_x = float(chassis_footprint_mm[0]) / 2.0
    half_y = float(chassis_footprint_mm[1]) / 2.0
    by_index = {
        tuple(int(value) for value in cell.get("cell_index", [])): cell
        for cell in cells
        if len(cell.get("cell_index", [])) == 3
    }
    visited: set[tuple[int, int, int]] = set()
    components: list[dict[str, Any]] = []
    index_to_component: dict[tuple[int, int, int], int] = {}
    for start in by_index:
        if start in visited:
            continue
        pending = [start]
        visited.add(start)
        indices: list[tuple[int, int, int]] = []
        while pending:
            current = pending.pop()
            indices.append(current)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        neighbor = (
                            current[0] + dx,
                            current[1] + dy,
                            current[2] + dz,
                        )
                        if neighbor in by_index and neighbor not in visited:
                            visited.add(neighbor)
                            pending.append(neighbor)
        component_cells = [by_index[index] for index in indices]
        z_min = min(
            float(cell["actual_local_bbox_xyz_mm"][2])
            for cell in component_cells
        )
        interface_moves = sum(
            int(
                cell.get("feature_move_counts", {}).get(
                    "support_interface",
                    0,
                )
            )
            for cell in component_cells
        )
        support_moves = sum(
            int(cell.get("extrusion_move_count", 0))
            for cell in component_cells
        )
        maximum_edge_ratio = max(
            max(
                abs(
                    (
                        float(cell["actual_local_bbox_xyz_mm"][0])
                        + float(cell["actual_local_bbox_xyz_mm"][3])
                    )
                    / 2.0
                    - center_x
                )
                / half_x,
                abs(
                    (
                        float(cell["actual_local_bbox_xyz_mm"][1])
                        + float(cell["actual_local_bbox_xyz_mm"][4])
                    )
                    / 2.0
                    - center_y
                )
                / half_y,
            )
            for cell in component_cells
        )
        side_pick_accessible = maximum_edge_ratio >= 0.85
        component_number = len(components)
        for index in indices:
            index_to_component[index] = component_number
        components.append(
            {
                "cell_count": len(component_cells),
                "support_move_count": support_moves,
                "support_interface_move_count": interface_moves,
                "minimum_z_mm": round(z_min, 3),
                "build_plate_connected": z_min <= 0.41,
                "maximum_footprint_edge_ratio": round(
                    maximum_edge_ratio,
                    4,
                ),
                "side_pick_accessible": side_pick_accessible,
            }
        )

    total_interface_moves = sum(
        int(
            cell.get("feature_move_counts", {}).get(
                "support_interface",
                0,
            )
        )
        for cell in cells
    )
    bed_connected_interface_moves = sum(
        int(component["support_interface_move_count"])
        for component in components
        if component["build_plate_connected"]
    )
    detached_interface_moves = (
        total_interface_moves - bed_connected_interface_moves
    )
    bed_connected_ratio = (
        bed_connected_interface_moves / total_interface_moves
        if total_interface_moves
        else 0.0
    )
    detached_ratio = (
        detached_interface_moves / total_interface_moves
        if total_interface_moves
        else 1.0
    )

    detached_interface_components = [
        component
        for component in components
        if int(component["support_interface_move_count"]) > 0
        and not component["build_plate_connected"]
    ]
    all_detached_interfaces_side_pickable = all(
        bool(component["side_pick_accessible"])
        for component in detached_interface_components
    )
    detached_interface_minimum_edge_ratio = min(
        (
            float(component["maximum_footprint_edge_ratio"])
            for component in detached_interface_components
        ),
        default=1.0,
    )
    detached_interface_micro_exception = bool(
        detached_interface_moves > 0
        and detached_interface_moves <= maximum_side_pick_interface_moves
        and len(detached_interface_components) == 1
        and all_detached_interfaces_side_pickable
        and detached_interface_minimum_edge_ratio
        >= minimum_side_pick_edge_ratio
    )
    central_airway_moves = 0
    central_airway_non_bed_connected_moves = 0
    central_airway_non_bed_component_numbers: set[int] = set()
    permanent_airway_moves = 0
    exterior_root_cells = 0
    for index, cell in by_index.items():
        bounds = [
            float(value)
            for value in cell.get("actual_local_bbox_xyz_mm", [0.0] * 6)
        ]
        x = (bounds[0] + bounds[3]) / 2.0 - center_x
        y = (bounds[1] + bounds[4]) / 2.0 - center_y
        z_mid = (bounds[2] + bounds[5]) / 2.0
        moves = int(cell.get("extrusion_move_count", 0))
        component = components[index_to_component[index]]
        if abs(x) >= half_x or abs(y) >= half_y:
            exterior_root_cells += 1
        if math.hypot(x, y) < central_airway_radius_mm:
            central_airway_moves += moves
            if not component["build_plate_connected"]:
                central_airway_non_bed_connected_moves += moves
                central_airway_non_bed_component_numbers.add(
                    index_to_component[index]
                )
            if z_mid >= permanent_airway_start_z_mm:
                permanent_airway_moves += moves

    maximum_central_non_contact_micro_moves = 5
    central_airway_non_contact_micro_path_exception = bool(
        0
        < central_airway_non_bed_connected_moves
        <= maximum_central_non_contact_micro_moves
        and permanent_airway_moves == 0
        and all(
            int(components[number]["support_interface_move_count"]) == 0
            and int(components[number]["support_move_count"])
            <= maximum_central_non_contact_micro_moves
            for number in central_airway_non_bed_component_numbers
        )
    )
    payload = {
        "passed": bool(
            total_interface_moves > 0
            and (
                (
                    bed_connected_ratio
                    >= minimum_bed_connected_interface_ratio
                    and detached_ratio
                    <= 1.0 - minimum_bed_connected_interface_ratio
                )
                or detached_interface_micro_exception
            )
            and all_detached_interfaces_side_pickable
            and (
                central_airway_non_bed_connected_moves == 0
                or central_airway_non_contact_micro_path_exception
            )
            and permanent_airway_moves == 0
        ),
        "component_count": len(components),
        "components": components,
        "total_support_interface_move_count": total_interface_moves,
        "build_plate_connected_interface_move_count": (
            bed_connected_interface_moves
        ),
        "build_plate_connected_interface_ratio": round(
            bed_connected_ratio,
            4,
        ),
        "detached_interface_move_count": detached_interface_moves,
        "detached_interface_move_ratio": round(detached_ratio, 4),
        "detached_interface_component_count": len(
            detached_interface_components
        ),
        "all_detached_interfaces_side_pickable": (
            all_detached_interfaces_side_pickable
        ),
        "side_pick_edge_ratio_threshold": 0.85,
        "maximum_detached_interface_move_ratio": round(
            1.0 - minimum_bed_connected_interface_ratio,
            4,
        ),
        "detached_interface_micro_exception": (
            detached_interface_micro_exception
        ),
        "maximum_side_pick_interface_moves": (
            maximum_side_pick_interface_moves
        ),
        "detached_interface_minimum_edge_ratio": round(
            detached_interface_minimum_edge_ratio,
            4,
        ),
        "minimum_side_pick_edge_ratio": minimum_side_pick_edge_ratio,
        "exterior_root_cell_count": exterior_root_cells,
        "central_airway_support_move_count": central_airway_moves,
        "central_airway_non_bed_connected_move_count": (
            central_airway_non_bed_connected_moves
        ),
        "central_airway_non_contact_micro_path_exception": (
            central_airway_non_contact_micro_path_exception
        ),
        "maximum_central_non_contact_micro_moves": (
            maximum_central_non_contact_micro_moves
        ),
        "permanent_airway_support_move_count": permanent_airway_moves,
        "central_airway_radius_mm": central_airway_radius_mm,
        "permanent_airway_start_z_mm": permanent_airway_start_z_mm,
        "primary_removal_direction": "-Z / open underside before assembly",
        "validation_method": (
            "26-neighbour support-cell topology from real OrcaSlicer G-code; "
            "at least 98% of interface moves must connect to the build plate, "
            "or one exterior side-pickable micro-island may contain no more "
            "than eight interface moves at footprint edge ratio >= 0.95; "
            "no support-contact component may enter the central airway; up "
            "to five non-contact pre-airway moves are treated as a slicer "
            "micro-path exception, and no support may remain in the "
            "permanent airflow section"
        ),
    }
    return payload


@dataclass(frozen=True)
class SliceResult:
    """Measured manufacturing result extracted from an OrcaSlicer 3MF."""

    part: str
    artifact: str
    printable: bool
    material: str
    layer_height_mm: float
    layers: int
    estimated_seconds: int
    filament_length_m: float
    filament_weight_g: float
    support_used: bool
    bridge_regions: int
    overhang_regions: int
    max_bridge_span_mm: float
    rotation_deg: list[float]
    support_toolpath: dict[str, Any] = field(default_factory=dict)
    slicer: str = "OrcaSlicer 2.4.2"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OrcaProfileResolver:
    """Flatten OrcaSlicer vendor profile inheritance for headless CLI use."""

    def __init__(
        self,
        profile_root: str | Path = DEFAULT_PROFILE_ROOT,
        vendor: str = REFERENCE_VENDOR,
    ) -> None:
        self.profile_root = Path(profile_root).expanduser().resolve()
        self.vendor = vendor
        manifest_path = self.profile_root / f"{vendor}.json"
        if not manifest_path.is_file():
            raise OrcaSlicerError(f"OrcaSlicer profile manifest not found: {manifest_path}")
        self.vendor_root = self.profile_root / vendor
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._paths: dict[str, Path] = {}
        for list_name in ("machine_list", "process_list", "filament_list"):
            for item in manifest.get(list_name, []):
                name = item.get("name")
                sub_path = item.get("sub_path")
                if isinstance(name, str) and isinstance(sub_path, str):
                    self._paths[name] = self.vendor_root / sub_path

    def resolve(self, profile_name: str) -> dict[str, Any]:
        """Return a parent-first merged profile with inheritance removed."""

        return self._resolve(profile_name, ())

    def _resolve(
        self,
        profile_name: str,
        stack: tuple[str, ...],
    ) -> dict[str, Any]:
        if profile_name in stack:
            chain = " -> ".join((*stack, profile_name))
            raise OrcaSlicerError(f"cyclic OrcaSlicer profile inheritance: {chain}")
        path = self._paths.get(profile_name)
        if path is None or not path.is_file():
            raise OrcaSlicerError(f"OrcaSlicer profile not found: {profile_name}")
        child = json.loads(path.read_text(encoding="utf-8"))
        parent_name = child.get("inherits")
        merged: dict[str, Any] = {}
        if isinstance(parent_name, str) and parent_name.strip():
            merged.update(self._resolve(parent_name, (*stack, profile_name)))
        merged.update(child)
        merged["inherits"] = ""
        return merged

    def write_flattened(
        self,
        profile_name: str,
        output_path: str | Path,
    ) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.resolve(profile_name), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return output


class OrcaSlicerRunner:
    """Slice exported STLs with a concrete PETG reference configuration."""

    def __init__(
        self,
        binary: str | Path = DEFAULT_ORCA_BINARY,
        profile_root: str | Path = DEFAULT_PROFILE_ROOT,
    ) -> None:
        self.binary = Path(binary).expanduser().resolve()
        if not self.binary.is_file():
            fallback = shutil.which("orca-slicer") or shutil.which("OrcaSlicer")
            if fallback:
                self.binary = Path(fallback).resolve()
        if not self.binary.is_file():
            raise OrcaSlicerError("OrcaSlicer executable is not installed")
        self.resolver = OrcaProfileResolver(profile_root)

    def prepare_profiles(
        self,
        output_dir: str | Path,
        *,
        enable_support: bool = False,
        support_threshold_angle_deg: float = 30.0,
    ) -> dict[str, Path]:
        threshold = float(support_threshold_angle_deg)
        if not 0.0 <= threshold <= 90.0:
            raise ValueError(
                "support_threshold_angle_deg must be between 0 and 90"
            )
        threshold_label = f"{threshold:g}".replace(".", "p")
        mode = (
            "support_auto"
            if enable_support and threshold == 30.0
            else (
                f"support_auto_{threshold_label}deg"
                if enable_support
                else "support_disabled"
            )
        )
        profiles_dir = Path(output_dir) / "orcaslicer_profiles" / mode
        names = {
            "machine": REFERENCE_MACHINE,
            "process": REFERENCE_PROCESS,
            "filament": REFERENCE_FILAMENT,
        }
        paths: dict[str, Path] = {}
        for kind, name in names.items():
            profile = self.resolver.resolve(name)
            if kind == "process":
                profile["curr_bed_type"] = "Textured PEI Plate"
                profile["enable_support"] = "1" if enable_support else "0"
                if enable_support:
                    profile["support_type"] = "tree(auto)"
                    profile["support_threshold_angle"] = f"{threshold:g}"
                    profile["support_on_build_plate_only"] = "0"
            path = profiles_dir / f"{kind}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(profile, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            paths[kind] = path
        filament = json.loads(paths["filament"].read_text(encoding="utf-8"))
        material = _first_value(filament.get("filament_type"), "")
        if str(material).upper() != "PETG":
            raise OrcaSlicerError(
                f"flattened filament profile is not PETG: {material!r}"
            )
        return paths

    def slice_parts(
        self,
        stl_paths: list[str | Path],
        output_dir: str | Path,
        *,
        rotations: dict[str, tuple[float, float, float]] | None = None,
        support_strategy: str = "minimal",
        analyze_support_impact: bool = True,
        support_thresholds_deg: tuple[float, ...] = (
            25.0,
            30.0,
            35.0,
            45.0,
        ),
    ) -> dict[str, Any]:
        output = Path(output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        profile_paths = self.prepare_profiles(output, enable_support=False)
        results = []
        for stl_path in stl_paths:
            stl = Path(stl_path).expanduser().resolve()
            rotation = (rotations or {}).get(stl.stem, (0.0, 0.0, 0.0))
            results.append(
                self.slice_part(
                    stl,
                    output,
                    profile_paths=profile_paths,
                    rotation=rotation,
                )
            )
        support_results: list[SliceResult] = []
        if analyze_support_impact:
            support_output = output / "support_auto_comparison"
            support_output.mkdir(parents=True, exist_ok=True)
            support_profiles = self.prepare_profiles(output, enable_support=True)
            for stl_path in stl_paths:
                stl = Path(stl_path).expanduser().resolve()
                rotation = (rotations or {}).get(
                    stl.stem,
                    (0.0, 0.0, 0.0),
                )
                support_results.append(
                    self.slice_part(
                        stl,
                        support_output,
                        profile_paths=support_profiles,
                        rotation=rotation,
                    )
                )
        support_impact = _support_impact(
            results,
            support_results,
            support_strategy=support_strategy,
        )
        threshold_sweep: dict[str, Any] = {}
        if analyze_support_impact and support_results and support_thresholds_deg:
            baseline_by_part = {item.part: item for item in results}
            support_by_part = {item.part: item for item in support_results}
            measured_parts = support_impact.get("parts", {})
            target_part = max(
                measured_parts,
                key=lambda name: (
                    float(
                        measured_parts[name].get(
                            "additional_filament_weight_g",
                            0.0,
                        )
                    ),
                    int(
                        measured_parts[name].get(
                            "additional_time_seconds",
                            0,
                        )
                    ),
                ),
                default="",
            )
            target_metrics = measured_parts.get(target_part, {})
            has_measured_support_cost = (
                bool(target_metrics.get("auto_support_required"))
                or float(
                    target_metrics.get(
                        "additional_filament_weight_g",
                        0.0,
                    )
                )
                > 0.01
                or int(
                    target_metrics.get(
                        "additional_time_seconds",
                        0,
                    )
                )
                > 5
            )
            if (
                target_part
                and target_part in baseline_by_part
                and has_measured_support_cost
            ):
                target_stl = next(
                    Path(path).expanduser().resolve()
                    for path in stl_paths
                    if Path(path).stem == target_part
                )
                threshold_sweep = self.slice_support_threshold_sweep(
                    target_stl,
                    output,
                    baseline=baseline_by_part[target_part],
                    existing_30deg=support_by_part.get(target_part),
                    rotation=(rotations or {}).get(
                        target_part,
                        (0.0, 0.0, 0.0),
                    ),
                    thresholds_deg=support_thresholds_deg,
                )
        payload = {
            "passed": all(item.printable for item in results),
            "slicer": "OrcaSlicer 2.4.2",
            "reference_profile": {
                "machine": REFERENCE_MACHINE,
                "process": REFERENCE_PROCESS,
                "filament": REFERENCE_FILAMENT,
                "purpose": (
                    "repeatable PETG manufacturability baseline; select the "
                    "actual printer profile before production"
                ),
            },
            "parts": {item.part: item.to_dict() for item in results},
            "support_analysis": support_impact,
            "support_threshold_sweep": threshold_sweep,
            "totals": {
                "estimated_seconds": sum(item.estimated_seconds for item in results),
                "filament_length_m": round(
                    sum(item.filament_length_m for item in results),
                    3,
                ),
                "filament_weight_g": round(
                    sum(item.filament_weight_g for item in results),
                    3,
                ),
                "support_used": any(item.support_used for item in results),
                "bridge_regions": sum(item.bridge_regions for item in results),
                "overhang_regions": sum(item.overhang_regions for item in results),
                "max_bridge_span_mm": max(
                    (item.max_bridge_span_mm for item in results),
                    default=0.0,
                ),
                "auto_support_generated": support_impact[
                    "auto_support_generated"
                ],
                "support_required": support_impact[
                    "support_required"
                ],
                "support_filament_weight_g": support_impact[
                    "additional_filament_weight_g"
                ],
                "support_time_seconds": support_impact[
                    "additional_time_seconds"
                ],
            },
        }
        report_path = output / "orcaslicer_report.json"
        report_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        payload["report_path"] = str(report_path)
        return payload

    def slice_support_threshold_sweep(
        self,
        stl_path: str | Path,
        output_dir: str | Path,
        *,
        baseline: SliceResult,
        existing_30deg: SliceResult | None = None,
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        thresholds_deg: tuple[float, ...] = (
            25.0,
            30.0,
            35.0,
            45.0,
        ),
    ) -> dict[str, Any]:
        """Measure how OrcaSlicer support cost changes with threshold angle."""

        stl = Path(stl_path).expanduser().resolve()
        root = Path(output_dir).expanduser().resolve()
        trials: list[tuple[float, SliceResult]] = []
        for value in sorted(set(float(item) for item in thresholds_deg)):
            if not 0.0 <= value <= 90.0:
                raise ValueError(
                    "support threshold sweep values must be between 0 and 90"
                )
            if value == 30.0 and existing_30deg is not None:
                trial = existing_30deg
            else:
                profile_paths = self.prepare_profiles(
                    root,
                    enable_support=True,
                    support_threshold_angle_deg=value,
                )
                label = f"{value:g}".replace(".", "p")
                trial_dir = root / "support_threshold_sweep" / f"{label}deg"
                trial_dir.mkdir(parents=True, exist_ok=True)
                trial = self.slice_part(
                    stl,
                    trial_dir,
                    profile_paths=profile_paths,
                    rotation=rotation,
                )
            trials.append((value, trial))

        payload = _support_threshold_sweep_report(baseline, trials)
        report_path = root / "support_threshold_sweep.json"
        report_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        payload["report_path"] = str(report_path)
        return payload

    def slice_support_enforcer_project(
        self,
        project_3mf: str | Path,
        output_dir: str | Path,
        *,
        baseline_filament_weight_g: float,
        baseline_estimated_seconds: int,
        bed_center_xy_mm: tuple[float, float] = (128.0, 128.0),
        target_interface_z_range_mm: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        """Slice an embedded manual-support project and measure its real cost."""

        project = Path(project_3mf).expanduser().resolve()
        if not project.is_file():
            raise FileNotFoundError(f"support project not found: {project}")
        output = Path(output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        log_path = output / f"{project.stem}.orcaslicer.log"
        command = [
            str(self.binary),
            "--slice",
            "0",
            "--outputdir",
            str(output),
            "--logfile",
            str(log_path),
            str(project),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        plate_gcode = output / "plate_1.gcode"
        if completed.returncode != 0 or not plate_gcode.is_file():
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise OrcaSlicerError(
                f"OrcaSlicer failed for {project.name} "
                f"(exit {completed.returncode}): {detail}"
            )
        gcode_path = output / f"{project.stem}.gcode"
        plate_gcode.replace(gcode_path)
        gcode = gcode_path.read_text(encoding="utf-8", errors="replace")
        stats = _support_toolpath_stats(
            gcode,
            {},
            fallback_center_xy_mm=bed_center_xy_mm,
        )
        removal_access = _support_removal_access_stats(stats)
        interface_cells = [
            cell
            for cell in stats.get("xyz_cells", [])
            if int(
                cell.get("feature_move_counts", {}).get(
                    "support_interface",
                    0,
                )
            )
            > 0
        ]
        interface_z_values = [
            float(value)
            for cell in interface_cells
            for value in (
                cell.get("actual_local_bbox_xyz_mm", [0.0] * 6)[2],
                cell.get("actual_local_bbox_xyz_mm", [0.0] * 6)[5],
            )
        ]
        interface_z_range = (
            [
                round(min(interface_z_values), 3),
                round(max(interface_z_values), 3),
            ]
            if interface_z_values
            else []
        )
        side_counts: dict[str, int] = {}
        target_interface_moves = 0
        center_x, center_y = (0.0, 0.0)
        for cell in interface_cells:
            bounds = cell.get("actual_local_bbox_xyz_mm", [0.0] * 6)
            x = (float(bounds[0]) + float(bounds[3])) / 2.0 - center_x
            y = (float(bounds[1]) + float(bounds[4])) / 2.0 - center_y
            side = (
                ("right" if x >= 0.0 else "left")
                if abs(x) >= abs(y)
                else ("rear" if y >= 0.0 else "front")
            )
            side_counts[side] = side_counts.get(side, 0) + int(
                cell.get("feature_move_counts", {}).get(
                    "support_interface",
                    0,
                )
            )
            if target_interface_z_range_mm is not None:
                midpoint_z = (
                    float(bounds[2]) + float(bounds[5])
                ) / 2.0
                if (
                    float(target_interface_z_range_mm[0])
                    <= midpoint_z
                    <= float(target_interface_z_range_mm[1])
                ):
                    target_interface_moves += int(
                        cell.get("feature_move_counts", {}).get(
                            "support_interface",
                            0,
                        )
                    )
        weight_match = re.search(
            r"; filament used \[g\] = ([0-9.]+)",
            gcode,
        )
        time_match = re.search(
            r"total estimated time: ([^;\n]+)",
            gcode,
        )
        layer_match = re.search(r"; total layer number: (\d+)", gcode)
        filament_weight_g = (
            float(weight_match.group(1)) if weight_match else 0.0
        )
        estimated_seconds = (
            _parse_orca_duration(time_match.group(1))
            if time_match
            else 0
        )
        feature_counts = stats.get("feature_move_counts", {})
        support_moves = int(stats.get("extrusion_move_count", 0))
        interface_moves = int(
            feature_counts.get("support_interface", 0)
        )
        support_generated = support_moves > 0 and interface_moves > 0
        target_ratio = (
            target_interface_moves / interface_moves
            if target_interface_z_range_mm is not None and interface_moves
            else 1.0
        )
        payload = {
            "passed": bool(
                support_generated
                and filament_weight_g > 0.0
                and estimated_seconds > 0
                and interface_z_range
                and target_ratio >= 0.95
                and removal_access["passed"]
            ),
            "project_3mf": str(project),
            "gcode": str(gcode_path),
            "log": str(log_path),
            "slicer": "OrcaSlicer 2.4.2",
            "support_generated": support_generated,
            "layers": int(layer_match.group(1)) if layer_match else 0,
            "filament_weight_g": round(filament_weight_g, 3),
            "estimated_seconds": int(estimated_seconds),
            "additional_filament_weight_g": round(
                max(
                    0.0,
                    filament_weight_g - float(
                        baseline_filament_weight_g
                    ),
                ),
                3,
            ),
            "additional_time_seconds": max(
                0,
                estimated_seconds - int(baseline_estimated_seconds),
            ),
            "support_extrusion_move_count": support_moves,
            "support_interface_move_count": interface_moves,
            "support_interface_cell_count": len(interface_cells),
            "support_interface_z_range_mm": interface_z_range,
            "target_interface_z_range_mm": (
                [
                    float(target_interface_z_range_mm[0]),
                    float(target_interface_z_range_mm[1]),
                ]
                if target_interface_z_range_mm is not None
                else []
            ),
            "target_interface_move_count": target_interface_moves,
            "target_interface_move_ratio": round(target_ratio, 4),
            "support_interface_side_move_counts": dict(
                sorted(side_counts.items())
            ),
            "support_removal_access": removal_access,
            "support_footprint_mm": stats.get("footprint_mm", []),
            "support_z_range_mm": stats.get("z_range_mm", []),
            "validation_method": (
                "OrcaSlicer CLI reload and real G-code parse; the enforcer "
                "must generate positive support and support-interface moves, "
                "with at least 95% of interface moves in the target Z band; "
                "support-cell connectivity also verifies bottom extraction "
                "and permanent-airway clearance"
            ),
        }
        report_path = output / f"{project.stem}.json"
        report_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        payload["report_path"] = str(report_path)
        return payload

    def slice_part(
        self,
        stl_path: str | Path,
        output_dir: str | Path,
        *,
        profile_paths: dict[str, Path],
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> SliceResult:
        stl = Path(stl_path)
        output = Path(output_dir)
        artifact = output / f"{stl.stem}.gcode.3mf"
        log_path = output / f"{stl.stem}.orcaslicer.log"
        command = [
            str(self.binary),
            "--load-settings",
            f"{profile_paths['machine']};{profile_paths['process']}",
            "--load-filaments",
            str(profile_paths["filament"]),
            "--load-defaultfila",
            "--ensure-on-bed",
            "--arrange",
            "1",
            "--orient",
            "0",
        ]
        if rotation[0]:
            command.extend(("--rotate-x", f"{rotation[0]:g}"))
        if rotation[1]:
            command.extend(("--rotate-y", f"{rotation[1]:g}"))
        if rotation[2]:
            command.extend(("--rotate", f"{rotation[2]:g}"))
        command.extend(
            (
                "--slice",
                "0",
                "--export-3mf",
                str(artifact),
                "--logfile",
                str(log_path),
                str(stl),
            )
        )
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0 or not artifact.is_file():
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise OrcaSlicerError(
                f"OrcaSlicer failed for {stl.name} "
                f"(exit {completed.returncode}): {detail}"
            )
        return parse_sliced_3mf(
            artifact,
            part=stl.stem,
            rotation=rotation,
        )


def parse_sliced_3mf(
    path: str | Path,
    *,
    part: str | None = None,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> SliceResult:
    """Extract measured slice data from an OrcaSlicer G-code 3MF."""

    artifact = Path(path)
    with zipfile.ZipFile(artifact) as archive:
        names = set(archive.namelist())
        gcode_name = next(
            (name for name in names if name.endswith("plate_1.gcode")),
            None,
        )
        config_name = next(
            (name for name in names if name.endswith("slice_info.config")),
            None,
        )
        plate_json_name = next(
            (name for name in names if name.endswith("plate_1.json")),
            None,
        )
        if not gcode_name or not config_name:
            raise OrcaSlicerError(f"not a sliced OrcaSlicer 3MF: {artifact}")
        gcode = archive.read(gcode_name).decode("utf-8", errors="replace")
        config_root = ET.fromstring(archive.read(config_name))
        plate_json = (
            json.loads(archive.read(plate_json_name))
            if plate_json_name
            else {}
        )

    metadata: dict[str, str] = {}
    for element in config_root.iter():
        key = element.attrib.get("key")
        value = element.attrib.get("value")
        if key and value is not None:
            metadata[key] = value
    filament = next(config_root.iter("filament"), None)
    material = ""
    length_m = 0.0
    weight_g = 0.0
    if filament is not None:
        material = filament.attrib.get("type", "")
        length_m = _float(filament.attrib.get("used_m"))
        weight_g = _float(filament.attrib.get("used_g"))
    if not material:
        material_match = re.search(r"; filament_type = ([^\r\n]+)", gcode)
        material = material_match.group(1).strip() if material_match else ""
    layers_match = re.search(r"; total layer number: (\d+)", gcode)
    layers = int(layers_match.group(1)) if layers_match else 0
    seconds = int(round(_float(metadata.get("prediction"))))
    support_used = metadata.get("support_used", "false").lower() == "true"
    layer_height = _float(plate_json.get("layer_height"))
    if not layer_height:
        height_match = re.search(r"; layer_height = ([0-9.]+)", gcode)
        layer_height = _float(height_match.group(1) if height_match else 0)
    bridge_regions = len(re.findall(r";\s*(?:FEATURE|TYPE):\s*Bridge", gcode))
    overhang_regions = len(
        re.findall(r";\s*(?:FEATURE|TYPE):\s*Overhang wall", gcode)
    )
    max_bridge_span = _max_feature_span(gcode, "Bridge")
    support_toolpath = _support_toolpath_stats(gcode, plate_json)
    printable = (
        material.upper() == "PETG"
        and layers > 0
        and seconds > 0
        and length_m > 0
        and weight_g > 0
        and not support_used
        and max_bridge_span <= 20.0
    )
    return SliceResult(
        part=part or artifact.stem.removesuffix(".gcode"),
        artifact=str(artifact.resolve()),
        printable=printable,
        material=material,
        layer_height_mm=layer_height,
        layers=layers,
        estimated_seconds=seconds,
        filament_length_m=round(length_m, 3),
        filament_weight_g=round(weight_g, 3),
        support_used=support_used,
        bridge_regions=bridge_regions,
        overhang_regions=overhang_regions,
        max_bridge_span_mm=round(max_bridge_span, 3),
        rotation_deg=[float(value) for value in rotation],
        support_toolpath=support_toolpath,
    )


def _support_threshold_sweep_report(
    baseline: SliceResult,
    trials: list[tuple[float, SliceResult]],
) -> dict[str, Any]:
    """Summarize support cost sensitivity without treating it as a requirement."""

    rows: list[dict[str, Any]] = []
    for threshold, trial in sorted(trials, key=lambda item: item[0]):
        envelope = trial.support_toolpath or {}
        feature_counts = envelope.get("feature_move_counts", {})
        weight_delta = max(
            0.0,
            trial.filament_weight_g - baseline.filament_weight_g,
        )
        time_delta = max(
            0,
            trial.estimated_seconds - baseline.estimated_seconds,
        )
        rows.append(
            {
                "threshold_angle_deg": float(threshold),
                "support_generated": bool(trial.support_used),
                "total_filament_weight_g": round(
                    trial.filament_weight_g,
                    3,
                ),
                "total_time_seconds": int(trial.estimated_seconds),
                "additional_filament_weight_g": round(weight_delta, 3),
                "additional_time_seconds": int(time_delta),
                "additional_filament_ratio": round(
                    weight_delta / baseline.filament_weight_g,
                    4,
                )
                if baseline.filament_weight_g
                else 0.0,
                "additional_time_ratio": round(
                    time_delta / baseline.estimated_seconds,
                    4,
                )
                if baseline.estimated_seconds
                else 0.0,
                "support_extrusion_move_count": int(
                    envelope.get("extrusion_move_count", 0)
                ),
                "support_interface_move_count": int(
                    feature_counts.get("support_interface", 0)
                ),
                "support_footprint_mm": envelope.get("footprint_mm", []),
                "support_z_range_mm": envelope.get("z_range_mm", []),
                "artifact": trial.artifact,
            }
        )

    generated = [row for row in rows if row["support_generated"]]
    first_generated = generated[0]["threshold_angle_deg"] if generated else None
    valid_trials = all(
        trial.material.upper() == "PETG"
        and trial.layers > 0
        and trial.estimated_seconds > 0
        and trial.filament_weight_g > 0
        for _, trial in trials
    )
    return {
        "passed": bool(baseline.printable and valid_trials and rows),
        "part": baseline.part,
        "method": (
            "same STL, production orientation, machine/process/PETG profile "
            "and tree(auto) support; only support_threshold_angle changes"
        ),
        "baseline": {
            "support_enabled": False,
            "filament_weight_g": baseline.filament_weight_g,
            "estimated_seconds": baseline.estimated_seconds,
            "max_bridge_span_mm": baseline.max_bridge_span_mm,
            "artifact": baseline.artifact,
        },
        "trials": rows,
        "first_tested_threshold_with_support_deg": first_generated,
        "reference_threshold_deg": 30.0,
        "decision": (
            "do not choose a threshold by support grams alone: print the "
            "bridge coupon first; after it passes keep production support "
            "disabled, and after it fails paint manual support only beneath "
            "the failed crown"
        ),
        "interpretation": (
            "OrcaSlicer generates support for slopes below the configured "
            "threshold angle, so higher thresholds can classify more of the "
            "smooth enclosure as support-eligible"
        ),
        "validation_method": (
            "headless OrcaSlicer G-code 3MF parsing for material, time, "
            "support/interface moves, footprint and Z range"
        ),
    }


def _support_impact(
    unsupported: list[SliceResult],
    supported: list[SliceResult],
    support_strategy: str = "minimal",
) -> dict[str, Any]:
    """Compare identical orientations with support disabled and automatic."""

    unsupported_by_part = {item.part: item for item in unsupported}
    comparisons: dict[str, dict[str, Any]] = {}
    for item in supported:
        baseline = unsupported_by_part[item.part]
        weight_delta = max(
            0.0,
            item.filament_weight_g - baseline.filament_weight_g,
        )
        time_delta = max(
            0,
            item.estimated_seconds - baseline.estimated_seconds,
        )
        comparisons[item.part] = {
            "auto_support_required": item.support_used,
            "additional_filament_weight_g": round(weight_delta, 3),
            "additional_time_seconds": time_delta,
            "additional_filament_ratio": round(
                weight_delta / baseline.filament_weight_g,
                4,
            )
            if baseline.filament_weight_g
            else 0.0,
            "additional_time_ratio": round(
                time_delta / baseline.estimated_seconds,
                4,
            )
            if baseline.estimated_seconds
            else 0.0,
            "support_toolpath_envelope": item.support_toolpath,
            "supported_artifact": item.artifact,
        }
    total_weight = round(
        sum(
            item["additional_filament_weight_g"]
            for item in comparisons.values()
        ),
        3,
    )
    total_time = sum(
        item["additional_time_seconds"]
        for item in comparisons.values()
    )
    auto_support_generated = any(
        item["auto_support_required"] for item in comparisons.values()
    )
    support_strategy = support_strategy if support_strategy in {"none", "minimal", "required"} else "minimal"
    support_free_baseline_passed = all(item.printable for item in unsupported)
    support_required = not support_free_baseline_passed
    supported_slice_valid = all(
        item.material.upper() == "PETG"
        and item.layers > 0
        and item.estimated_seconds > 0
        and item.filament_weight_g > 0
        and item.printable
        for item in supported
    )
    baseline_weight = sum(item.filament_weight_g for item in unsupported)
    baseline_time = sum(item.estimated_seconds for item in unsupported)
    total_weight_ratio = (
        round(total_weight / baseline_weight, 4)
        if baseline_weight
        else 0.0
    )
    total_time_ratio = (
        round(total_time / baseline_time, 4)
        if baseline_time
        else 0.0
    )
    weight_limit = max(3.0, baseline_weight * 0.05)
    time_limit = max(900, round(baseline_time * 0.10))
    if support_strategy == "none":
        strategy_passed = support_free_baseline_passed
    elif support_strategy == "required":
        strategy_passed = (
            support_free_baseline_passed
            or (supported_slice_valid and auto_support_generated)
        )
    else:
        strategy_passed = (
            support_free_baseline_passed
            or (
                supported_slice_valid
                and auto_support_generated
                and total_weight <= weight_limit
                and total_time <= time_limit
            )
        )
    return {
        "passed": strategy_passed,
        "support_strategy": support_strategy,
        "method": (
            "paired OrcaSlicer PETG slices at identical orientation: "
            "support disabled vs tree(auto), 30 degree threshold"
        ),
        "support_free_baseline_passed": support_free_baseline_passed,
        "auto_support_generated": auto_support_generated,
        "support_required": support_required,
        "additional_filament_weight_g": total_weight,
        "additional_time_seconds": total_time,
        "additional_filament_ratio": total_weight_ratio,
        "additional_time_ratio": total_time_ratio,
        "recommendation": (
            "disable automatic support; support-free slice passes and "
            "automatic support only adds material and time"
            if support_free_baseline_passed and auto_support_generated
            else (
                (
                    "automatic support required; redesign if its measured "
                    "material or time overhead exceeds the limits"
                    if auto_support_generated
                    and support_strategy == "minimal"
                    else (
                        "automatic support is required; enable support and "
                        "ignore material/time guardrails"
                        if support_strategy == "required"
                        else "support is not supported by this strategy"
                    )
                )
                if support_required
                else "automatic support is not generated"
            )
        ),
        "acceptance_limits": {
            "additional_filament_weight_g": round(weight_limit, 3),
            "additional_time_seconds": time_limit,
            "additional_filament_ratio": 0.05,
            "additional_time_ratio": 0.10,
        },
        "parts": comparisons,
    }


def _first_value(value: Any, default: Any = None) -> Any:
    if isinstance(value, list):
        return value[0] if value else default
    return default if value is None else value


def _float(value: Any) -> float:
    try:
        return float(_first_value(value, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _parse_orca_duration(value: str) -> int:
    """Parse OrcaSlicer's compact `2h 10m 2s` duration text."""

    units = {"h": 3600, "m": 60, "s": 1}
    return sum(
        int(amount) * units[unit]
        for amount, unit in re.findall(r"(\d+)\s*([hms])", value)
    )


def _max_feature_span(gcode: str, target_feature: str) -> float:
    """Measure the longest extruding XY chord in a named slicer feature."""

    x = 0.0
    y = 0.0
    feature = ""
    maximum = 0.0
    for line in gcode.splitlines():
        if line.startswith("; FEATURE:") or line.startswith("; TYPE:"):
            feature = line.split(":", 1)[1].strip()
            continue
        code = line.split(";", 1)[0].strip()
        if not code.startswith(("G0 ", "G1 ", "G2 ", "G3 ")):
            continue
        values = {
            match.group(1): float(match.group(2))
            for match in re.finditer(
                r"([XYEIJ])(-?(?:\d+(?:\.\d*)?|\.\d+))",
                code,
            )
        }
        next_x = values.get("X", x)
        next_y = values.get("Y", y)
        if (
            feature == target_feature
            and values.get("E", 0.0) > 0
            and ("X" in values or "Y" in values)
        ):
            maximum = max(
                maximum,
                ((next_x - x) ** 2 + (next_y - y) ** 2) ** 0.5,
            )
        x = next_x
        y = next_y
    return maximum


def _support_toolpath_stats(
    gcode: str,
    plate_json: dict[str, Any],
    *,
    fallback_center_xy_mm: tuple[float, float] = (0.0, 0.0),
) -> dict[str, Any]:
    """Measure the actual generated support-toolpath spatial envelope."""

    feature = ""
    x_pos = 0.0
    y_pos = 0.0
    z_pos = 0.0
    bounds = {
        "xmin": float("inf"),
        "xmax": float("-inf"),
        "ymin": float("inf"),
        "ymax": float("-inf"),
        "zmin": float("inf"),
        "zmax": float("-inf"),
    }
    extrusion_moves = 0
    feature_move_counts: dict[str, int] = {}
    support_moves: list[tuple[float, float, float, str]] = []
    z_band_size_mm = 5.0
    z_band_stats: dict[int, dict[str, Any]] = {}
    for line in gcode.splitlines():
        if line.startswith("; FEATURE:") or line.startswith("; TYPE:"):
            feature = line.split(":", 1)[1].strip()
            continue
        code = line.split(";", 1)[0].strip()
        if not code.startswith(("G0 ", "G1 ", "G2 ", "G3 ")):
            continue
        x_match = re.search(r"(?:^|\s)X(-?[0-9.]+)", code)
        y_match = re.search(r"(?:^|\s)Y(-?[0-9.]+)", code)
        z_match = re.search(r"(?:^|\s)Z(-?[0-9.]+)", code)
        e_match = re.search(r"(?:^|\s)E(-?[0-9.]+)", code)
        if x_match:
            x_pos = float(x_match.group(1))
        if y_match:
            y_pos = float(y_match.group(1))
        if z_match:
            z_pos = float(z_match.group(1))
        if (
            not feature.lower().startswith("support")
            or e_match is None
            or float(e_match.group(1)) <= 0.0
        ):
            continue
        extrusion_moves += 1
        feature_key = feature.lower().replace(" ", "_")
        feature_move_counts[feature_key] = (
            feature_move_counts.get(feature_key, 0) + 1
        )
        support_moves.append((x_pos, y_pos, z_pos, feature_key))
        bounds["xmin"] = min(bounds["xmin"], x_pos)
        bounds["xmax"] = max(bounds["xmax"], x_pos)
        bounds["ymin"] = min(bounds["ymin"], y_pos)
        bounds["ymax"] = max(bounds["ymax"], y_pos)
        bounds["zmin"] = min(bounds["zmin"], z_pos)
        bounds["zmax"] = max(bounds["zmax"], z_pos)
        band_index = int(z_pos // z_band_size_mm)
        band = z_band_stats.setdefault(
            band_index,
            {
                "extrusion_move_count": 0,
                "xmin": float("inf"),
                "xmax": float("-inf"),
                "ymin": float("inf"),
                "ymax": float("-inf"),
                "zmin": float("inf"),
                "zmax": float("-inf"),
                "feature_move_counts": {},
            },
        )
        band["extrusion_move_count"] += 1
        band["feature_move_counts"][feature_key] = (
            band["feature_move_counts"].get(feature_key, 0) + 1
        )
        band["xmin"] = min(band["xmin"], x_pos)
        band["xmax"] = max(band["xmax"], x_pos)
        band["ymin"] = min(band["ymin"], y_pos)
        band["ymax"] = max(band["ymax"], y_pos)
        band["zmin"] = min(band["zmin"], z_pos)
        band["zmax"] = max(band["zmax"], z_pos)
    if extrusion_moves == 0:
        return {}

    object_bbox = None
    bbox_objects = plate_json.get("bbox_objects", [])
    if bbox_objects and isinstance(bbox_objects[0], dict):
        candidate = bbox_objects[0].get("bbox")
        if isinstance(candidate, list) and len(candidate) == 4:
            object_bbox = [float(value) for value in candidate]
    center_x = (
        (object_bbox[0] + object_bbox[2]) / 2
        if object_bbox
        else float(fallback_center_xy_mm[0])
    )
    center_y = (
        (object_bbox[1] + object_bbox[3]) / 2
        if object_bbox
        else float(fallback_center_xy_mm[1])
    )
    xy_tile_size_mm = 20.0
    xy_tile_stats: dict[tuple[int, int], dict[str, Any]] = {}
    xyz_cell_xy_size_mm = 10.0
    xyz_cell_z_size_mm = 5.0
    xyz_cell_stats: dict[tuple[int, int, int], dict[str, Any]] = {}
    for move_x, move_y, move_z, move_feature in support_moves:
        local_x = move_x - center_x
        local_y = move_y - center_y
        tile_key = (
            math.floor(local_x / xy_tile_size_mm),
            math.floor(local_y / xy_tile_size_mm),
        )
        tile = xy_tile_stats.setdefault(
            tile_key,
            {
                "extrusion_move_count": 0,
                "xmin": float("inf"),
                "xmax": float("-inf"),
                "ymin": float("inf"),
                "ymax": float("-inf"),
                "zmin": float("inf"),
                "zmax": float("-inf"),
                "feature_move_counts": {},
            },
        )
        tile["extrusion_move_count"] += 1
        tile["feature_move_counts"][move_feature] = (
            tile["feature_move_counts"].get(move_feature, 0) + 1
        )
        tile["xmin"] = min(tile["xmin"], local_x)
        tile["xmax"] = max(tile["xmax"], local_x)
        tile["ymin"] = min(tile["ymin"], local_y)
        tile["ymax"] = max(tile["ymax"], local_y)
        tile["zmin"] = min(tile["zmin"], move_z)
        tile["zmax"] = max(tile["zmax"], move_z)
        cell_key = (
            math.floor(local_x / xyz_cell_xy_size_mm),
            math.floor(local_y / xyz_cell_xy_size_mm),
            math.floor(move_z / xyz_cell_z_size_mm),
        )
        cell = xyz_cell_stats.setdefault(
            cell_key,
            {
                "extrusion_move_count": 0,
                "xmin": float("inf"),
                "xmax": float("-inf"),
                "ymin": float("inf"),
                "ymax": float("-inf"),
                "zmin": float("inf"),
                "zmax": float("-inf"),
                "feature_move_counts": {},
            },
        )
        cell["extrusion_move_count"] += 1
        cell["feature_move_counts"][move_feature] = (
            cell["feature_move_counts"].get(move_feature, 0) + 1
        )
        cell["xmin"] = min(cell["xmin"], local_x)
        cell["xmax"] = max(cell["xmax"], local_x)
        cell["ymin"] = min(cell["ymin"], local_y)
        cell["ymax"] = max(cell["ymax"], local_y)
        cell["zmin"] = min(cell["zmin"], move_z)
        cell["zmax"] = max(cell["zmax"], move_z)
    xy_tiles = []
    for (tile_x, tile_y), tile in sorted(
        xy_tile_stats.items(),
        key=lambda item: (
            -item[1]["extrusion_move_count"],
            item[0][1],
            item[0][0],
        ),
    ):
        xy_tiles.append(
            {
                "tile_index": [tile_x, tile_y],
                "nominal_local_bbox_xy_mm": [
                    round(tile_x * xy_tile_size_mm, 3),
                    round(tile_y * xy_tile_size_mm, 3),
                    round((tile_x + 1) * xy_tile_size_mm, 3),
                    round((tile_y + 1) * xy_tile_size_mm, 3),
                ],
                "actual_local_bbox_xy_mm": [
                    round(tile["xmin"], 3),
                    round(tile["ymin"], 3),
                    round(tile["xmax"], 3),
                    round(tile["ymax"], 3),
                ],
                "actual_z_range_mm": [
                    round(tile["zmin"], 3),
                    round(tile["zmax"], 3),
                ],
                "extrusion_move_count": int(
                    tile["extrusion_move_count"]
                ),
                "move_ratio": round(
                    tile["extrusion_move_count"] / extrusion_moves,
                    4,
                ),
                "feature_move_counts": {
                    name: int(count)
                    for name, count in sorted(
                        tile["feature_move_counts"].items()
                    )
                },
            }
        )
    xyz_cells = []
    for (cell_x, cell_y, cell_z), cell in sorted(
        xyz_cell_stats.items(),
        key=lambda item: (
            -item[1]["feature_move_counts"].get(
                "support_interface",
                0,
            ),
            -item[1]["extrusion_move_count"],
            item[0][2],
            item[0][1],
            item[0][0],
        ),
    ):
        xyz_cells.append(
            {
                "cell_index": [cell_x, cell_y, cell_z],
                "nominal_local_bbox_xyz_mm": [
                    round(cell_x * xyz_cell_xy_size_mm, 3),
                    round(cell_y * xyz_cell_xy_size_mm, 3),
                    round(cell_z * xyz_cell_z_size_mm, 3),
                    round((cell_x + 1) * xyz_cell_xy_size_mm, 3),
                    round((cell_y + 1) * xyz_cell_xy_size_mm, 3),
                    round((cell_z + 1) * xyz_cell_z_size_mm, 3),
                ],
                "actual_local_bbox_xyz_mm": [
                    round(cell["xmin"], 3),
                    round(cell["ymin"], 3),
                    round(cell["zmin"], 3),
                    round(cell["xmax"], 3),
                    round(cell["ymax"], 3),
                    round(cell["zmax"], 3),
                ],
                "extrusion_move_count": int(
                    cell["extrusion_move_count"]
                ),
                "move_ratio": round(
                    cell["extrusion_move_count"] / extrusion_moves,
                    4,
                ),
                "feature_move_counts": {
                    name: int(count)
                    for name, count in sorted(
                        cell["feature_move_counts"].items()
                    )
                },
            }
        )
    support_bbox = [
        bounds["xmin"],
        bounds["ymin"],
        bounds["xmax"],
        bounds["ymax"],
    ]
    extension = (
        [
            max(0.0, object_bbox[0] - support_bbox[0]),
            max(0.0, support_bbox[2] - object_bbox[2]),
            max(0.0, object_bbox[1] - support_bbox[1]),
            max(0.0, support_bbox[3] - object_bbox[3]),
        ]
        if object_bbox
        else []
    )
    z_bands = []
    for band_index, band in sorted(z_band_stats.items()):
        band_bbox = [
            band["xmin"],
            band["ymin"],
            band["xmax"],
            band["ymax"],
        ]
        z_bands.append(
            {
                "nominal_z_range_mm": [
                    round(band_index * z_band_size_mm, 3),
                    round((band_index + 1) * z_band_size_mm, 3),
                ],
                "actual_z_range_mm": [
                    round(band["zmin"], 3),
                    round(band["zmax"], 3),
                ],
                "extrusion_move_count": int(
                    band["extrusion_move_count"]
                ),
                "move_ratio": round(
                    band["extrusion_move_count"] / extrusion_moves,
                    4,
                ),
                "feature_move_counts": {
                    name: int(count)
                    for name, count in sorted(
                        band["feature_move_counts"].items()
                    )
                },
                "footprint_mm": [
                    round(band["xmax"] - band["xmin"], 3),
                    round(band["ymax"] - band["ymin"], 3),
                ],
                "plate_bbox_xy_mm": [
                    round(value, 3) for value in band_bbox
                ],
                "local_bbox_xy_mm": [
                    round(band["xmin"] - center_x, 3),
                    round(band["ymin"] - center_y, 3),
                    round(band["xmax"] - center_x, 3),
                    round(band["ymax"] - center_y, 3),
                ],
            }
        )
    return {
        "extrusion_move_count": extrusion_moves,
        "feature_move_counts": {
            name: int(count)
            for name, count in sorted(feature_move_counts.items())
        },
        "z_range_mm": [
            round(bounds["zmin"], 3),
            round(bounds["zmax"], 3),
        ],
        "height_mm": round(bounds["zmax"] - bounds["zmin"], 3),
        "footprint_mm": [
            round(bounds["xmax"] - bounds["xmin"], 3),
            round(bounds["ymax"] - bounds["ymin"], 3),
        ],
        "plate_bbox_xy_mm": [
            round(value, 3) for value in support_bbox
        ],
        "local_bbox_xy_mm": [
            round(bounds["xmin"] - center_x, 3),
            round(bounds["ymin"] - center_y, 3),
            round(bounds["xmax"] - center_x, 3),
            round(bounds["ymax"] - center_y, 3),
        ],
        "object_bbox_xy_mm": (
            [round(value, 3) for value in object_bbox]
            if object_bbox
            else []
        ),
        "footprint_extension_l_r_f_b_mm": [
            round(value, 3) for value in extension
        ],
        "z_band_size_mm": z_band_size_mm,
        "z_bands": z_bands,
        "xy_tile_size_mm": xy_tile_size_mm,
        "xy_tiles": xy_tiles,
        "xyz_cell_size_mm": [
            xyz_cell_xy_size_mm,
            xyz_cell_xy_size_mm,
            xyz_cell_z_size_mm,
        ],
        "xyz_cells": xyz_cells,
        "method": (
            "support and support-interface positive-extrusion G0/G1/G2/G3 "
            "moves parsed into a full envelope, 5 mm height bands, "
            "20 mm local XY hotspot tiles and 10 x 10 x 5 mm XYZ cells "
            "from the generated OrcaSlicer G-code 3MF"
        ),
    }
