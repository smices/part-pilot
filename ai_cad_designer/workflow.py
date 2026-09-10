"""End-to-end industrial design workflow."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import cadquery as cq

from .airflow import analyze_smart_fan_airflow
from .structural import analyze_smart_fan_structure
from .agents import (
    AssemblyAgent,
    CalibrationAgent,
    DesignAgent,
    JointAgent,
    PrintAgent,
)
from .core import CADPart, export_step, export_stl
from .hardware_specs import smart_fan_component_records
from .llm import (
    DesignLLMProvider,
    LLMPlanningError,
    hardware_from_payload,
    proposal_from_payload,
)
from .orca_project import (
    create_support_enforcer_project,
    inspect_support_enforcer_project,
)
from .schema import ComponentSpec, Evidence, MATERIALS, WorkflowResult
from .slicing import OrcaSlicerError, OrcaSlicerRunner
from .support_modifiers import create_support_modifier_parts
from .validation import validate_assembly_interference


def _mac_interface_corridor_specs(
    mac_reference: CADPart,
    *,
    installed_base_z_mm: float,
) -> list[dict[str, Any]]:
    """Build conservative per-port plug corridors from the Mac reference."""

    device_width = float(mac_reference.metadata["dimensions_mm"][1])
    foot_height = float(
        mac_reference.metadata["engineering_parameters"][
            "mac_foot_height_mm"
        ]
    )
    corridor = mac_reference.metadata["service_corridor"]
    external_depth = float(corridor["external_depth_mm"])
    insertion_depth = float(corridor["insertion_depth_mm"])
    lateral_clearance = float(
        corridor["lateral_clearance_per_side_mm"]
    )
    vertical_clearance = float(
        corridor["vertical_clearance_per_side_mm"]
    )
    depth = external_depth + insertion_depth
    results = []
    for marker in mac_reference.metadata["interface_markers"]:
        direction = -1.0 if marker["face"] == "front" else 1.0
        opening_height = float(marker["opening_height_mm"])
        center_z = float(marker["center_z_mm"])
        # The marker cut is clipped by the real Mac body, which begins above
        # the bottom foot. A plug cannot occupy space below that body plane.
        local_z_min = max(
            foot_height,
            center_z - opening_height / 2,
        )
        local_z_max = (
            center_z + opening_height / 2 + vertical_clearance
        )
        results.append(
            {
                "id": marker["id"],
                "name": f"Mac {marker['label']} plug corridor",
                "face": marker["face"],
                "dimensions_mm": [
                    float(marker["opening_width_mm"])
                    + 2 * lateral_clearance,
                    depth,
                    local_z_max - local_z_min,
                ],
                "translation_mm": [
                    float(marker["center_x_mm"]),
                    direction
                    * (
                        device_width / 2
                        + (external_depth - insertion_depth) / 2
                    ),
                    installed_base_z_mm
                    + (local_z_min + local_z_max) / 2,
                ],
                "opening_mm": [
                    float(marker["opening_width_mm"]),
                    opening_height,
                ],
                "local_z_range_mm": [local_z_min, local_z_max],
                "coordinate_accuracy": (
                    mac_reference.metadata["interface_marker_accuracy"]
                ),
            }
        )
    return results


class IndustrialDesignWorkflow:
    """Run engineering reasoning, CAD generation, export, and verification."""

    def __init__(
        self,
        output_dir: str | Path = "ai_cad_designer/exports",
        *,
        provider: DesignLLMProvider | None = None,
        fallback_to_rules: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.design_agent = DesignAgent()
        self.joint_agent = JointAgent()
        self.assembly_agent = AssemblyAgent()
        self.calibration_agent = CalibrationAgent()
        self.print_agent = PrintAgent()
        self.provider = provider
        self.fallback_to_rules = fallback_to_rules
        self._requested_planner = "rules"
        self._actual_planner = "rules"
        self._fallback = Evidence(
            "not_run",
            "Rules fallback was not requested.",
            {"coverage": "not_applicable"},
        )

    def _slicing_diagnostic(
        self,
        status: str,
        message: str,
    ) -> dict[str, Any]:
        report_path = self.output_dir / "slicing_diagnostic.json"
        report = {
            "passed": False,
            "status": status,
            "diagnostic": message,
            "parts": {},
            "report_path": str(report_path.resolve()),
        }
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return report

    def run(
        self,
        request: str,
        *,
        image_paths: list[str | Path] | None = None,
        vision_report: dict[str, Any] | None = None,
        slice_manufacturing: bool = False,
        engineering_parameters: dict[str, object] | None = None,
        manufacturing_parameters: dict[str, object] | None = None,
    ) -> WorkflowResult:
        self._requested_planner = (
            self.provider.name if self.provider is not None else "rules"
        )
        self._actual_planner = self._requested_planner
        self._fallback = Evidence(
            "not_run",
            "Rules fallback was not requested.",
            {"coverage": "not_applicable"},
        )
        images = [Path(path).expanduser().resolve() for path in image_paths or []]
        if images and self.provider is None:
            raise LLMPlanningError(
                "hardware photo or schematic analysis requires the codex or api planner"
            )
        if images:
            vision_report = self.provider.analyze_hardware(images, request)
        elif vision_report is not None:
            vision_report = hardware_from_payload(vision_report)

        resolved_engineering_parameters = dict(
            engineering_parameters or {}
        )
        if vision_report:
            for component in vision_report.get("components", []):
                name = str(component.get("name", "")).lower()
                dimensions_mm = component.get("dimensions_mm", [])
                source = str(
                    component.get(
                        "dimension_source",
                        "estimated",
                    )
                )
                if len(dimensions_mm) != 3:
                    continue
                if "mac mini" in name:
                    for key, value in zip(
                        (
                            "mac_length_mm",
                            "mac_width_mm",
                            "mac_height_mm",
                        ),
                        dimensions_mm,
                    ):
                        resolved_engineering_parameters.setdefault(
                            key,
                            {"value": value, "source": source},
                        )
                if "fan" in name and "120" in name:
                    resolved_engineering_parameters.setdefault(
                        "fan_size_mm",
                        {
                            "value": max(
                                float(dimensions_mm[0]),
                                float(dimensions_mm[1]),
                            ),
                            "source": source,
                        },
                    )
                    resolved_engineering_parameters.setdefault(
                        "fan_thickness_mm",
                        {
                            "value": dimensions_mm[2],
                            "source": source,
                        },
                    )

        planning_request = request
        if vision_report:
            planning_request += (
                "\n\nVERIFIED HARDWARE INVENTORY FROM VISION STAGE:\n"
                + json.dumps(vision_report, ensure_ascii=False, indent=2)
            )
        proposal = self._plan(planning_request, original_request=request)
        manufacturing_defaults: dict[str, object] = {
            "material": proposal.brief.material,
            "tolerance_mm": proposal.brief.tolerance_mm,
            "wall_thickness_mm": proposal.brief.wall_thickness_mm,
            "layer_height_mm": proposal.brief.layer_height_mm,
        }
        manufacturing_ranges = {
            "tolerance_mm": (0.1, 1.0),
            "wall_thickness_mm": (1.2, 8.0),
            "layer_height_mm": (0.08, 0.4),
        }
        resolved_manufacturing: dict[str, object] = {}
        manufacturing_sources: dict[str, str] = {}
        raw_manufacturing = manufacturing_parameters or {}
        for name, default in manufacturing_defaults.items():
            raw = raw_manufacturing.get(name, default)
            value = raw.get("value", default) if isinstance(raw, dict) else raw
            source = (
                str(raw.get("source", "user_supplied"))
                if isinstance(raw, dict)
                else (
                    "default_reference"
                    if name not in raw_manufacturing
                    else "user_supplied"
                )
            )
            if name == "material":
                material = str(value).upper()
                if material not in MATERIALS:
                    raise ValueError(
                        "material must be " + ", ".join(MATERIALS)
                    )
                resolved_manufacturing[name] = material
            else:
                try:
                    numeric = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"manufacturing parameter {name} must be numeric"
                    ) from exc
                minimum, maximum = manufacturing_ranges[name]
                if not minimum <= numeric <= maximum:
                    raise ValueError(
                        f"manufacturing parameter {name} must be between "
                        f"{minimum:g} and {maximum:g} mm"
                    )
                resolved_manufacturing[name] = numeric
            manufacturing_sources[name] = source
        brief = replace(
            proposal.brief,
            material=str(resolved_manufacturing["material"]),
            tolerance_mm=float(resolved_manufacturing["tolerance_mm"]),
            wall_thickness_mm=float(
                resolved_manufacturing["wall_thickness_mm"]
            ),
            layer_height_mm=float(
                resolved_manufacturing["layer_height_mm"]
            ),
        )
        proposal.brief = brief
        proposal.engineering_notes.append(
            "Structured manufacturing parameters override prompt-derived "
            "values; sources: "
            + json.dumps(manufacturing_sources, ensure_ascii=False)
        )
        plans = {part.name: part for part in proposal.parts}
        if brief.design_family == "smart_fan":
            parts = self.joint_agent.smart_fan_parts(
                wall_mm=brief.wall_thickness_mm,
                tolerance_mm=brief.tolerance_mm,
                material=brief.material,
                dimensions={
                    name: plan.dimensions_mm for name, plan in plans.items()
                },
                engineering_parameters=resolved_engineering_parameters,
            )
            assembly = self.assembly_agent.smart_fan(parts)
            self._reconcile_smart_fan_proposal_bom(proposal, parts)
        elif brief.design_family == "desktop_robot":
            parts = self.joint_agent.desktop_robot_parts(
                wall_mm=brief.wall_thickness_mm,
                tolerance_mm=brief.tolerance_mm,
                dimensions={
                    name: plan.dimensions_mm for name, plan in plans.items()
                },
            )
            assembly = self.assembly_agent.desktop_robot(parts)
        else:
            base_dimensions = plans["sensor_base"].dimensions_mm
            lid_dimensions = plans["sensor_lid"].dimensions_mm
            parts = list(
                self.joint_agent.two_piece_snap_enclosure(
                    length_mm=base_dimensions[0],
                    width_mm=base_dimensions[1],
                    base_height_mm=base_dimensions[2],
                    wall_mm=brief.wall_thickness_mm,
                    lid_height_mm=lid_dimensions[2],
                    tolerance_mm=brief.tolerance_mm,
                    material=brief.material,
                )
            )
            assembly = self.assembly_agent.sensor_enclosure(parts[0], parts[1])
        for part in parts:
            part.metadata["manufacturing_parameters"] = dict(
                resolved_manufacturing
            )
            part.metadata["manufacturing_parameter_sources"] = dict(
                manufacturing_sources
            )
        return self._manufacture(
            proposal,
            parts,
            assembly.name,
            assembly,
            vision=vision_report,
            slice_manufacturing=slice_manufacturing,
        )

    @staticmethod
    def _reconcile_smart_fan_proposal_bom(proposal, parts: list[CADPart]) -> None:
        """Make the human proposal use the exact generated CAD envelopes."""

        chassis = next(part for part in parts if part.name == "fan_chassis")
        cradle = next(
            part for part in parts if part.name == "mac_mini_cradle"
        )
        parameters = cradle.metadata["engineering_parameters"]
        parameter_sources = cradle.metadata["engineering_parameter_sources"]
        hardware = {
            (
                "DS18B20 temperature probe"
                if str(item["name"]).startswith("DS18B20")
                else str(item["name"])
            ): tuple(float(value) for value in item["dimensions_mm"])
            for item in chassis.metadata["hardware_references"]
        }
        resolved_dimensions = {
            "Mac mini M4": (
                float(parameters["mac_length_mm"]),
                float(parameters["mac_width_mm"]),
                float(parameters["mac_height_mm"]),
            ),
            **hardware,
        }
        sources = {
            "Mac mini M4": " / ".join(
                dict.fromkeys(
                    parameter_sources[name]
                    for name in (
                        "mac_length_mm",
                        "mac_width_mm",
                        "mac_height_mm",
                    )
                )
            ),
            "120 mm PWM fan": " / ".join(
                dict.fromkeys(
                    parameter_sources[name]
                    for name in ("fan_size_mm", "fan_thickness_mm")
                )
            ),
            "12V DC-DC module": "hw_smart_fan reference envelope",
            "5V DC-DC module": "hw_smart_fan reference envelope",
            "ESP32-C3 Super Mini": "hw_smart_fan reference envelope",
            "MOSFET PWM driver": "hw_smart_fan reference envelope",
            "DS18B20 temperature probe": (
                parameter_sources["ds18b20_probe_diameter_mm"]
            ),
        }
        records = smart_fan_component_records(
            dimensions=resolved_dimensions,
            sources=sources,
        )
        proposal.brief = replace(
            proposal.brief,
            components=tuple(
                ComponentSpec(
                    name=record["name"],
                    dimensions_mm=record["dimensions_mm"],
                    access=record["access"],
                    clearance_mm=proposal.brief.tolerance_mm,
                )
                for record in records
            ),
        )
        proposal.engineering_notes.append(
            "Proposal BOM reconciled from generated OpenCascade reference "
            "geometry; generic fan and ESP32 aliases are not permitted."
        )

    @staticmethod
    def _smart_fan_bom_consistency(
        proposal,
        parts: list[CADPart],
        reference_parts: list[CADPart],
        installed_assembly,
    ) -> dict[str, Any]:
        """Compare proposal envelopes with exported and installed CAD."""

        reference_by_name = {
            "Mac mini M4": next(
                part
                for part in reference_parts
                if part.name == "mac_mini_m4_fit_reference"
            ),
            **{
                (
                    "DS18B20 temperature probe"
                    if str(part.metadata.get("display_name", "")).startswith(
                        "DS18B20"
                    )
                    else str(part.metadata.get("display_name", ""))
                ): part
                for part in reference_parts
                if part.metadata.get("reference_kind")
                == "internal_hardware"
                and not part.name.startswith("fan_isolator_")
                and not part.name.startswith("mac_support_pad_")
            },
        }
        proposal_by_name = {
            component.name: component
            for component in proposal.brief.components
        }
        installed_names = (
            {part.name for part in installed_assembly.parts}
            if installed_assembly is not None
            else set()
        )
        chassis = next(part for part in parts if part.name == "fan_chassis")
        sources = chassis.metadata["engineering_parameter_sources"]
        dimension_sources = {
            "Mac mini M4": " / ".join(
                dict.fromkeys(
                    sources[name]
                    for name in (
                        "mac_length_mm",
                        "mac_width_mm",
                        "mac_height_mm",
                    )
                )
            ),
            "120 mm PWM fan": " / ".join(
                dict.fromkeys(
                    sources[name]
                    for name in ("fan_size_mm", "fan_thickness_mm")
                )
            ),
            "12V DC-DC module": "hw_smart_fan reference envelope",
            "5V DC-DC module": "hw_smart_fan reference envelope",
            "ESP32-C3 Super Mini": "hw_smart_fan reference envelope",
            "MOSFET PWM driver": "hw_smart_fan reference envelope",
            "DS18B20 temperature probe": (
                sources["ds18b20_probe_diameter_mm"]
            ),
        }
        expected_records = smart_fan_component_records(
            sources=dimension_sources
        )
        items = []
        for expected in expected_records:
            name = expected["name"]
            proposal_component = proposal_by_name.get(name)
            reference = reference_by_name.get(name)
            proposal_dimensions = (
                tuple(float(value) for value in proposal_component.dimensions_mm)
                if proposal_component is not None
                else ()
            )
            reference_dimensions = (
                tuple(
                    float(value)
                    for value in reference.metadata["dimensions_mm"]
                )
                if reference is not None
                else ()
            )
            dimensions_match = (
                len(proposal_dimensions) == 3
                and len(reference_dimensions) == 3
                and all(
                    abs(left - right) <= 0.001
                    for left, right in zip(
                        proposal_dimensions,
                        reference_dimensions,
                    )
                )
            )
            installed = (
                reference is not None and reference.name in installed_names
            )
            items.append(
                {
                    "name": name,
                    "quantity": 1,
                    "proposal_dimensions_mm": list(proposal_dimensions),
                    "reference_dimensions_mm": list(reference_dimensions),
                    "dimension_source": dimension_sources[name],
                    "dimensions_match": dimensions_match,
                    "reference_file": (
                        f"{reference.name}.step" if reference else None
                    ),
                    "installed_in_assembly": installed,
                    "passed": dimensions_match and installed,
                }
            )
        consumables = [
            {
                "name": "fan silicone isolator",
                "quantity": 4,
                "installed_reference_count": sum(
                    name.startswith("fan_isolator_")
                    for name in installed_names
                ),
            },
            {
                "name": "Mac silicone support pad",
                "quantity": 4,
                "installed_reference_count": sum(
                    name.startswith("mac_support_pad_")
                    for name in installed_names
                ),
            },
            {
                "name": "desk silicone isolation pad",
                "quantity": 4,
                "installed_reference_count": sum(
                    name.startswith("desk_isolation_pad_")
                    for name in installed_names
                ),
            },
        ]
        generic_aliases = {"fan", "120 mm fan", "ESP32", "DS18B20 probe"}
        no_generic_aliases = not (
            set(proposal_by_name) & generic_aliases
        )
        exact_component_set = set(proposal_by_name) == {
            record["name"] for record in expected_records
        }
        consumables_match = all(
            item["quantity"] == item["installed_reference_count"]
            for item in consumables
        )
        checks = {
            "exact_component_set": exact_component_set,
            "no_generic_aliases": no_generic_aliases,
            "all_dimensions_match_reference_cad": all(
                item["dimensions_match"] for item in items
            ),
            "all_active_hardware_installed": all(
                item["installed_in_assembly"] for item in items
            ),
            "consumable_counts_match": consumables_match,
        }
        return {
            "passed": all(checks.values()),
            "active_hardware_count": len(items),
            "matched_hardware_count": sum(
                item["passed"] for item in items
            ),
            "policy": (
                "proposal BOM, exported reference CAD and installed assembly "
                "must use one envelope source with no generic aliases"
            ),
            "checks": checks,
            "items": items,
            "consumables": consumables,
        }

    def _plan(self, request: str, *, original_request: str):
        if self.provider is None:
            self._actual_planner = "rules"
            brief = self.design_agent.analyze(original_request)
            return self.design_agent.propose(brief)
        try:
            payload = self.provider.plan(request)
            self._actual_planner = self.provider.name
            return proposal_from_payload(
                payload,
                original_request,
                planner=self.provider.name,
            )
        except (LLMPlanningError, ValueError) as exc:
            if not self.fallback_to_rules:
                raise
            self._actual_planner = "rules"
            self._fallback = Evidence(
                "blocked",
                "Rules fallback used; template coverage is unverified.",
                {
                    "reason": type(exc).__name__,
                    "coverage": "unverified",
                },
            )
            brief = self.design_agent.analyze(original_request)
            proposal = self.design_agent.propose(brief)
            proposal.planner = f"rules fallback ({self.provider.name})"
            proposal.engineering_notes.append(
                f"LLM planner fallback reason: {type(exc).__name__}"
            )
            return proposal

    def _manufacture(
        self,
        proposal,
        parts: list[CADPart],
        assembly_name: str,
        assembly,
        *,
        vision: dict[str, Any] | None,
        slice_manufacturing: bool,
    ):
        files: list[str] = []
        stl_paths: list[Path] = []
        reference_parts: list[CADPart] = []
        calibration_parts: list[CADPart] = []
        support_modifier_parts: list[CADPart] = []
        manufacturing_control_parts: list[CADPart] = []
        calibration_stl_paths: list[Path] = []
        manufacturing_control_stl_paths: list[Path] = []
        installed_assembly = None
        bom = None
        for part in parts:
            files.append(str(export_step(part, self.output_dir / f"{part.name}.step")))
            stl_path = export_stl(part, self.output_dir / f"{part.name}.stl")
            stl_paths.append(stl_path)
            files.append(str(stl_path))
        files.append(str(export_step(assembly, self.output_dir / f"{assembly_name}.step")))
        if proposal.brief.design_family == "smart_fan":
            manufacturing_control_parts = list(
                self.joint_agent.manufacturing_control_parts
            )
            control_dir = self.output_dir / "manufacturing_controls"
            for control_part in manufacturing_control_parts:
                files.append(
                    str(
                        export_step(
                            control_part,
                            control_dir / f"{control_part.name}.step",
                        )
                    )
                )
                control_stl = export_stl(
                    control_part,
                    control_dir / f"{control_part.name}.stl",
                )
                manufacturing_control_stl_paths.append(control_stl)
                files.append(str(control_stl))
            chassis = next(part for part in parts if part.name == "fan_chassis")
            cradle = next(
                part for part in parts if part.name == "mac_mini_cradle"
            )
            parameters = cradle.metadata["engineering_parameters"]
            mac_reference = self.joint_agent.mac_mini_m4_fit_reference(
                length_mm=parameters["mac_length_mm"],
                width_mm=parameters["mac_width_mm"],
                height_mm=parameters["mac_height_mm"],
                corner_radius_mm=parameters[
                    "mac_corner_radius_mm"
                ],
                foot_outer_diameter_mm=parameters[
                    "mac_foot_outer_diameter_mm"
                ],
                foot_height_mm=parameters["mac_foot_height_mm"],
                power_button_x_mm=parameters["power_button_x_mm"],
                power_button_y_mm=parameters["power_button_y_mm"],
                power_button_diameter_mm=parameters[
                    "power_button_diameter_mm"
                ],
                front_interface_delta_x_mm=parameters[
                    "front_interface_delta_x_mm"
                ],
                front_interface_delta_z_mm=parameters[
                    "front_interface_delta_z_mm"
                ],
                rear_interface_delta_x_mm=parameters[
                    "rear_interface_delta_x_mm"
                ],
                rear_interface_delta_z_mm=parameters[
                    "rear_interface_delta_z_mm"
                ],
            )
            reference_parts.extend(
                [
                    mac_reference,
                    *self.joint_agent.smart_fan_hardware_reference_parts(
                        chassis,
                        cradle,
                    ),
                ]
            )
            for reference_part in reference_parts:
                files.append(
                    str(
                        export_step(
                            reference_part,
                            self.output_dir
                            / f"{reference_part.name}.step",
                        )
                    )
                )
                files.append(
                    str(
                        export_stl(
                            reference_part,
                            self.output_dir
                            / f"{reference_part.name}.stl",
                        )
                    )
                )
            installed_assembly = self.assembly_agent.smart_fan_installed(
                assembly,
                reference_parts,
            )
            files.append(
                str(
                    export_step(
                        installed_assembly,
                        self.output_dir
                        / f"{installed_assembly.name}.step",
                    )
                )
            )
            bom = self._smart_fan_bom_consistency(
                proposal,
                parts,
                reference_parts,
                installed_assembly,
            )
            bom_path = self.output_dir / "hardware_bom_consistency.json"
            bom_path.write_text(
                json.dumps(bom, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            bom["report_path"] = str(bom_path.resolve())
            files.append(str(bom_path))
            calibration_parts = self.calibration_agent.smart_fan(
                parts,
                reference_parts,
            )
            for calibration_part in calibration_parts:
                files.append(
                    str(
                        export_step(
                            calibration_part,
                            self.output_dir
                            / f"{calibration_part.name}.step",
                        )
                    )
                )
                calibration_stl_path = export_stl(
                    calibration_part,
                    self.output_dir / f"{calibration_part.name}.stl",
                )
                calibration_stl_paths.append(calibration_stl_path)
                files.append(str(calibration_stl_path))

        validation = self.print_agent.validate(parts)
        manufacturing = None
        calibration = None
        if slice_manufacturing:
            if proposal.brief.material != "PETG":
                manufacturing = self._slicing_diagnostic(
                    "blocked",
                    "Real OrcaSlicer workflow currently supports PETG only.",
                )
            else:
                try:
                    manufacturing = OrcaSlicerRunner().slice_parts(
                        stl_paths,
                        self.output_dir,
                        rotations={},
                        support_strategy=proposal.support_strategy,
                    )
                except OrcaSlicerError as exc:
                    manufacturing = self._slicing_diagnostic(
                        "failed",
                        str(exc),
                    )
            files.extend(
                item["artifact"]
                for item in manufacturing.get("parts", {}).values()
            )
            threshold_sweep = manufacturing.get(
                "support_threshold_sweep",
                {},
            )
            if threshold_sweep:
                files.extend(
                    trial["artifact"]
                    for trial in threshold_sweep.get("trials", [])
                    if trial.get("artifact")
                )
                if threshold_sweep.get("report_path"):
                    files.append(threshold_sweep["report_path"])
            files.append(manufacturing["report_path"])
            if manufacturing.get("passed") and manufacturing_control_parts:
                control_output = (
                    self.output_dir
                    / "manufacturing_controls"
                    / "slices"
                )
                control_manufacturing = OrcaSlicerRunner().slice_parts(
                    manufacturing_control_stl_paths,
                    control_output,
                    analyze_support_impact=False,
                    support_strategy=proposal.support_strategy,
                )
                files.extend(
                    item["artifact"]
                    for item in control_manufacturing["parts"].values()
                )
                files.append(control_manufacturing["report_path"])
                opening_economy = self._opening_support_economy(
                    parts,
                    manufacturing_control_parts,
                    manufacturing,
                    control_manufacturing,
                    self.print_agent.validate(
                        manufacturing_control_parts
                    ),
                    support_strategy=proposal.support_strategy,
                )
                opening_economy_path = (
                    self.output_dir / "opening_support_economy.json"
                )
                opening_economy_path.write_text(
                    json.dumps(
                        opening_economy,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                opening_economy["report_path"] = str(
                    opening_economy_path.resolve()
                )
                manufacturing["opening_support_economy"] = opening_economy
                manufacturing["passed"] = bool(
                    manufacturing["passed"]
                    and opening_economy["passed"]
                )
                files.append(str(opening_economy_path))
        if calibration_parts:
            calibration_validation = self.print_agent.validate(
                calibration_parts
            )
            calibration_manufacturing = None
            if slice_manufacturing and manufacturing.get("passed"):
                calibration_output = self.output_dir / "calibration_slices"
                calibration_manufacturing = OrcaSlicerRunner().slice_parts(
                    calibration_stl_paths,
                    calibration_output,
                    analyze_support_impact=False,
                    support_strategy=proposal.support_strategy,
                )
                files.extend(
                    item["artifact"]
                    for item in calibration_manufacturing["parts"].values()
                )
                files.append(calibration_manufacturing["report_path"])
            calibration = {
                "purpose": (
                    "validate uncertain Mac, fan, DS18B20, PETG fit and "
                    "support-free portal bridging, including physical "
                    "front/rear I/O alignment, before committing to the "
                    "complete enclosure print"
                ),
                "passed": all(
                    report.get("printable", False)
                    for report in calibration_validation.values()
                )
                and (
                    calibration_manufacturing is None
                    or bool(calibration_manufacturing["passed"])
                ),
                "recommended_sequence": [
                    "同批打印 PETG 插孔板和标准测试销",
                    "选择并记录可反复拆装的最小 PETG 单边间隙",
                    "测试 Mac 后左角定位圆弧与电源键对位",
                    "用前后 I/O 平面检具测量整组接口 X/Z 偏移",
                    "测试所选 120 mm 风扇外框和四个安装孔",
                    "用实际 DS18B20 探头完成 10 次压入和拆卸循环",
                    "无支撑打印主风口与 USB 拱冠试片并测量下垂",
                    "把实测结果作为用户参数回填，再生成完整外壳",
                ],
                "parts": {
                    part.name: {
                        "file_name": f"{part.name}.stl",
                        "display_name": part.metadata["display_name"],
                        "dimensions_mm": list(part.metadata["dimensions_mm"]),
                        "calibration_kind": part.metadata[
                            "calibration_kind"
                        ],
                        "test_method": part.metadata["test_method"],
                        "features": part.metadata.get("features", {}),
                        "acceptance": part.metadata.get("acceptance", {}),
                        "face": part.metadata.get("face"),
                        "interface_markers": part.metadata.get(
                            "interface_markers",
                            [],
                        ),
                        "coordinate_offsets_mm": part.metadata.get(
                            "coordinate_offsets_mm",
                            [],
                        ),
                        "identification_dot_count": part.metadata.get(
                            "identification_dot_count",
                        ),
                    }
                    for part in calibration_parts
                },
                "validation": calibration_validation,
                "manufacturing": calibration_manufacturing,
            }
            cradle = next(
                part
                for part in parts
                if part.name == "mac_mini_cradle"
            )
            chassis = next(
                part for part in parts if part.name == "fan_chassis"
            )
            measurement_template = {
                "schema_version": 3,
                "purpose": (
                    "record physical coupon measurements and feed them back "
                    "into the next parametric CAD generation"
                ),
                "current_values": {
                    "manufacturing_parameters": cradle.metadata[
                        "manufacturing_parameters"
                    ],
                    "manufacturing_parameter_sources": cradle.metadata[
                        "manufacturing_parameter_sources"
                    ],
                    "engineering_parameters": cradle.metadata[
                        "engineering_parameters"
                    ],
                    "engineering_parameter_sources": cradle.metadata[
                        "engineering_parameter_sources"
                    ],
                },
                "measurement_results": {
                    "selected_petg_clearance_per_side_mm": None,
                    "mac_corner_radius_mm": None,
                    "power_button_delta_x_mm": None,
                    "power_button_delta_y_mm": None,
                    "front_interface_residual_delta_x_mm": None,
                    "front_interface_residual_delta_z_mm": None,
                    "rear_interface_residual_delta_x_mm": None,
                    "rear_interface_residual_delta_z_mm": None,
                    "fan_mount_spacing_mm": None,
                    "fan_mount_hole_diameter_mm": None,
                    "ds18b20_probe_diameter_mm": None,
                    "ds18b20_snap_interference_per_side_mm": None,
                    "main_portal_crown_sag_mm": None,
                    "usb_port_crown_sag_mm": None,
                    "portal_bridge_coupon_passed": None,
                    "fan_fit_notes": "",
                    "mac_fit_notes": "",
                    "ds18b20_fit_notes": "",
                    "portal_bridge_notes": "",
                },
                "allowed_clearance_coupon_values_mm": [0.15, 0.25, 0.35],
                "regeneration_mapping": {
                    "selected_petg_clearance_per_side_mm": (
                        "manufacturing_parameters.tolerance_mm"
                    ),
                    "mac_corner_radius_mm": (
                        "engineering_parameters.mac_corner_radius_mm"
                    ),
                    "power_button_delta_x_mm": (
                        "add to engineering_parameters.power_button_x_mm"
                    ),
                    "power_button_delta_y_mm": (
                        "add to engineering_parameters.power_button_y_mm"
                    ),
                    "front_interface_residual_delta_x_mm": (
                        "add to engineering_parameters."
                        "front_interface_delta_x_mm"
                    ),
                    "front_interface_residual_delta_z_mm": (
                        "add to engineering_parameters."
                        "front_interface_delta_z_mm"
                    ),
                    "rear_interface_residual_delta_x_mm": (
                        "add to engineering_parameters."
                        "rear_interface_delta_x_mm"
                    ),
                    "rear_interface_residual_delta_z_mm": (
                        "add to engineering_parameters."
                        "rear_interface_delta_z_mm"
                    ),
                    "fan_mount_spacing_mm": (
                        "engineering_parameters.fan_mount_spacing_mm"
                    ),
                    "fan_mount_hole_diameter_mm": (
                        "engineering_parameters."
                        "fan_mount_hole_diameter_mm"
                    ),
                    "ds18b20_probe_diameter_mm": (
                        "engineering_parameters."
                        "ds18b20_probe_diameter_mm"
                    ),
                    "ds18b20_snap_interference_per_side_mm": (
                        "engineering_parameters."
                        "ds18b20_snap_interference_per_side_mm"
                    ),
                },
                "source_after_application": "calibration_coupon",
                "fan_interface_snapshot": chassis.metadata[
                    "fan_mount_interface"
                ],
                "ds18b20_interface_snapshot": next(
                    part
                    for part in parts
                    if part.name == "controller_cover"
                ).metadata["ds18b20_probe_retention"],
                "mac_io_interface_snapshot": {
                    face: {
                        "file_name": (
                            f"mac_{face}_io_alignment_gauge.stl"
                        ),
                        "coordinate_offsets_mm": next(
                            part
                            for part in calibration_parts
                            if part.name
                            == f"mac_{face}_io_alignment_gauge"
                        ).metadata["coordinate_offsets_mm"],
                        "interface_markers": next(
                            part
                            for part in calibration_parts
                            if part.name
                            == f"mac_{face}_io_alignment_gauge"
                        ).metadata["interface_markers"],
                    }
                    for face in ("front", "rear")
                },
            }
            measurement_path = (
                self.output_dir / "calibration_measurement_template.json"
            )
            measurement_path.write_text(
                json.dumps(
                    measurement_template,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            files.append(str(measurement_path))
            calibration["measurement_template_file"] = (
                measurement_path.name
            )
            calibration_path = (
                self.output_dir / "fit_calibration_report.json"
            )
            calibration_path.write_text(
                json.dumps(calibration, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            files.append(str(calibration_path))
        if (
            proposal.brief.design_family == "smart_fan"
            and manufacturing is not None
            and manufacturing.get("passed")
        ):
            support_chassis = next(
                part for part in parts if part.name == "fan_chassis"
            )
            support_plan = self._localized_support_decision_plan(
                manufacturing,
                calibration,
                support_chassis,
            )
            support_modifier_parts = create_support_modifier_parts(
                manufacturing,
                chassis=support_chassis,
            )
            modifier_records = []
            for modifier in support_modifier_parts:
                step_path = export_step(
                    modifier,
                    self.output_dir / f"{modifier.name}.step",
                )
                stl_path = export_stl(
                    modifier,
                    self.output_dir / f"{modifier.name}.stl",
                )
                files.extend((str(step_path), str(stl_path)))
                modifier_records.append(
                    {
                        "name": modifier.name,
                        "display_name": modifier.metadata[
                            "display_name"
                        ],
                        "step_file": step_path.name,
                        "stl_file": stl_path.name,
                        "dimensions_mm": list(
                            modifier.metadata["dimensions_mm"]
                        ),
                        "source_cell_count": modifier.metadata[
                            "source_cell_count"
                        ],
                        "source_support_extrusion_move_count": (
                            modifier.metadata[
                                "source_support_extrusion_move_count"
                            ]
                        ),
                        "source_support_interface_move_count": (
                            modifier.metadata[
                                "source_support_interface_move_count"
                            ]
                        ),
                        "chassis_intersection_mm3": (
                            modifier.metadata[
                                "chassis_intersection_mm3"
                            ]
                        ),
                        "coordinate_system": modifier.metadata[
                            "coordinate_system"
                        ],
                        "operator_use": modifier.metadata[
                            "operator_use"
                        ],
                    }
                )
            support_plan["modifier_files"] = modifier_records
            support_plan["modifier_support_interface_move_count"] = sum(
                int(
                    item["source_support_interface_move_count"]
                )
                for item in modifier_records
            )
            support_enforcer_projects: list[dict[str, Any]] = []
            strategy_comparisons: list[dict[str, Any]] = []
            support_removal_regions: list[dict[str, Any]] = []
            support_parameter_optimizations: list[dict[str, Any]] = []
            if manufacturing is not None:
                baseline = manufacturing.get("parts", {}).get(
                    "fan_chassis",
                    {},
                )
                template_3mf = Path(str(baseline.get("artifact", "")))
                chassis_stl = self.output_dir / "fan_chassis.stl"
                slicer = OrcaSlicerRunner()
                region_by_id = {
                    str(region.get("id")): region
                    for region in support_plan.get("regions", [])
                }
                for modifier_record in modifier_records:
                    region_id = str(
                        modifier_record["name"]
                    ).removeprefix("support_modifier_")
                    region = region_by_id[region_id]
                    nominal_z = region.get(
                        "nominal_z_range_mm",
                        [0.0, 0.0],
                    )
                    target_z = (
                        (
                            max(0.0, float(nominal_z[0]) - 5.0),
                            float(nominal_z[1]),
                        )
                        if region_id
                        in {
                            "controller_and_service_roofs",
                            "upper_retention_details",
                        }
                        else (
                            float(nominal_z[0]),
                            float(nominal_z[1]),
                        )
                    )
                    exterior_support_strategy = (
                        support_chassis.metadata.get(
                            "exterior_continuity",
                            {},
                        )
                    )
                    use_integral_crown_support = bool(
                        region_id == "main_portal_crowns"
                        and exterior_support_strategy.get(
                            "crown_print_strategy"
                        )
                        == "one-layer integral tear-away bridge membrane"
                        and int(
                            exterior_support_strategy.get(
                                "crown_membrane_count",
                                0,
                            )
                        )
                        == 4
                        and float(
                            exterior_support_strategy.get(
                                "crown_membrane_thickness_mm",
                                math.inf,
                            )
                        )
                        <= 0.2
                        and not bool(baseline.get("support_used", True))
                    )
                    if use_integral_crown_support:
                        integral_weight_g = float(
                            exterior_support_strategy[
                                "crown_membrane_estimated_petg_g"
                            ]
                        )
                        integral_measured = {
                            "passed": bool(
                                baseline.get("printable")
                                and not baseline.get("support_used")
                                and int(
                                    baseline.get("bridge_regions", 0)
                                )
                                > 0
                            ),
                            "source_artifact": baseline.get("artifact"),
                            "support_interface_move_count": 0,
                            "target_interface_move_ratio": 1.0,
                            "additional_filament_weight_g": (
                                integral_weight_g
                            ),
                            "additional_time_seconds": 0,
                            "bridge_regions": baseline.get(
                                "bridge_regions"
                            ),
                            "maximum_bridge_span_mm": baseline.get(
                                "max_bridge_span_mm"
                            ),
                            "support_removal_access": {
                                "passed": True,
                                "support_kind": (
                                    "integral_breakaway_bridge"
                                ),
                                "total_support_interface_move_count": 0,
                                "build_plate_connected_interface_ratio": (
                                    1.0
                                ),
                                "detached_interface_move_ratio": 0.0,
                                "all_detached_interfaces_side_pickable": (
                                    True
                                ),
                                "central_airway_non_bed_connected_move_count": (
                                    0
                                ),
                                "permanent_airway_support_move_count": 0,
                                "primary_removal_direction": (
                                    exterior_support_strategy[
                                        "crown_membrane_removal_direction"
                                    ]
                                ),
                                "removal_face_count": 4,
                                "validation_method": (
                                    "support-disabled production G-code "
                                    "contains bridge moves; the modeled "
                                    "one-layer membrane is fused to the "
                                    "chassis and removed from four open faces"
                                ),
                            },
                        }
                        parameter_optimization = {
                            "region_id": region_id,
                            "label": region["label"],
                            "passed": integral_measured["passed"],
                            "support_required": False,
                            "external_slicer_support_required": False,
                            "integral_support_used": True,
                            "selected_candidate_id": (
                                "integral_breakaway_bridge"
                            ),
                            "selected_support_settings": {
                                "membrane_thickness_mm": (
                                    exterior_support_strategy[
                                        "crown_membrane_thickness_mm"
                                    ]
                                ),
                                "membrane_count": 4,
                            },
                            "minimum_interface_coverage_ratio": 1.0,
                            "selected_interface_coverage_ratio": 1.0,
                            "baseline_additional_filament_weight_g": (
                                integral_weight_g
                            ),
                            "selected_additional_filament_weight_g": (
                                integral_weight_g
                            ),
                            "filament_reduction_g": 0.0,
                            "baseline_additional_time_seconds": 0,
                            "selected_additional_time_seconds": 0,
                            "time_reduction_seconds": 0,
                            "candidates": [],
                            "decision": (
                                "select the modeled one-layer breakaway "
                                "bridge because its total PETG is below "
                                "0.05 g and the support-disabled production "
                                "slice contains no external support"
                            ),
                        }
                        support_parameter_optimizations.append(
                            parameter_optimization
                        )
                        support_enforcer_projects.append(
                            {
                                "region_id": region_id,
                                "label": region["label"],
                                "project_file": None,
                                "support_type": (
                                    "integral_breakaway_bridge"
                                ),
                                "support_settings": (
                                    parameter_optimization[
                                        "selected_support_settings"
                                    ]
                                ),
                                "support_required": False,
                                "external_slicer_support_required": False,
                                "integral_support_used": True,
                                "selected_candidate_id": (
                                    "integral_breakaway_bridge"
                                ),
                                "target_interface_z_range_mm": list(
                                    target_z
                                ),
                                "archive_role_inspection": {
                                    "passed": True,
                                    "parts": [],
                                    "reason": (
                                        "support_is_integral_to_fan_chassis"
                                    ),
                                },
                                "measured_slice": integral_measured,
                                "passed": integral_measured["passed"],
                                "selection_reason": (
                                    "four one-layer membranes total "
                                    f"{integral_weight_g:.4f} g PETG; "
                                    "external tree support is unnecessary"
                                ),
                            }
                        )
                        support_removal_regions.append(
                            {
                                "region_id": region_id,
                                "label": region["label"],
                                "support_required": False,
                                "external_slicer_support_required": False,
                                "integral_support_used": True,
                                "passed": True,
                                "primary_removal_direction": (
                                    exterior_support_strategy[
                                        "crown_membrane_removal_direction"
                                    ]
                                ),
                                "required_side_count": 4,
                                "observed_interface_sides": [],
                                "observed_removal_faces": [
                                    "front",
                                    "rear",
                                    "left",
                                    "right",
                                ],
                                "support_removal_access": (
                                    integral_measured[
                                        "support_removal_access"
                                    ]
                                ),
                            }
                        )
                        strategy_comparisons.append(
                            {
                                "region_id": region_id,
                                "label": region["label"],
                                "target_interface_z_range_mm": list(
                                    target_z
                                ),
                                "support_required": False,
                                "external_slicer_support_required": False,
                                "integral_support_used": True,
                                "selected_support_type": (
                                    "integral_breakaway_bridge"
                                ),
                                "selected_candidate_id": (
                                    "integral_breakaway_bridge"
                                ),
                                "normal_manual_rejected": True,
                                "trials": [],
                                "material_cost_g": integral_weight_g,
                            }
                        )
                        continue
                    trials = []
                    candidate_specs = (
                        {
                            "candidate_id": "tree_default",
                            "support_type": "tree(manual)",
                            "support_settings": {},
                        },
                        {
                            "candidate_id": "tree_top_25",
                            "support_type": "tree(manual)",
                            "support_settings": {
                                "tree_support_top_rate": "25%",
                            },
                        },
                        {
                            "candidate_id": "tree_top_20",
                            "support_type": "tree(manual)",
                            "support_settings": {
                                "tree_support_top_rate": "20%",
                            },
                        },
                        {
                            "candidate_id": "tree_bed_only_25",
                            "support_type": "tree(manual)",
                            "support_settings": {
                                "tree_support_top_rate": "25%",
                                "support_on_build_plate_only": 1,
                            },
                        },
                        {
                            "candidate_id": "normal_default",
                            "support_type": "normal(manual)",
                            "support_settings": {},
                        },
                    )
                    for candidate in candidate_specs:
                        candidate_id = candidate["candidate_id"]
                        support_type = candidate["support_type"]
                        support_settings = dict(
                            candidate["support_settings"]
                        )
                        if (
                            exterior_support_strategy.get(
                                "crown_print_strategy"
                            )
                            == (
                                "one-layer integral tear-away bridge "
                                "membrane"
                            )
                        ):
                            support_settings["bridge_no_support"] = 1
                        if support_type == "normal(manual)":
                            rejected_root = (
                                self.output_dir
                                / "support_strategy_comparison"
                                / "rejected_normal_manual"
                            )
                            project_path = (
                                rejected_root
                                / f"{region_id}.3mf"
                            )
                            slice_dir = (
                                rejected_root
                                / f"{region_id}_slice"
                            )
                        else:
                            candidate_root = (
                                self.output_dir
                                / "support_parameter_search"
                                / region_id
                                / candidate_id
                            )
                            project_path = (
                                candidate_root
                                / f"{candidate_id}.3mf"
                            )
                            slice_dir = candidate_root / "slice"
                        project_report = (
                            create_support_enforcer_project(
                                template_3mf=template_3mf,
                                chassis_stl=chassis_stl,
                                modifier_stl=(
                                    self.output_dir
                                    / modifier_record["stl_file"]
                                ),
                                output_3mf=project_path,
                                project_name=(
                                    "Mac mini M4 Smart Fan · "
                                    f"{region['label']} · {candidate_id}"
                                ),
                                support_type=support_type,
                                support_settings=support_settings,
                            )
                        )
                        inspection = inspect_support_enforcer_project(
                            project_path
                        )
                        measured = (
                            slicer.slice_support_enforcer_project(
                                project_path,
                                slice_dir,
                                baseline_filament_weight_g=float(
                                    baseline.get(
                                        "filament_weight_g",
                                        0.0,
                                    )
                                ),
                                baseline_estimated_seconds=int(
                                    baseline.get(
                                        "estimated_seconds",
                                        0,
                                    )
                                ),
                                target_interface_z_range_mm=target_z,
                            )
                        )
                        base_qualified = bool(
                            project_report["passed"]
                            and inspection["passed"]
                            and measured["passed"]
                        )
                        trials.append(
                            {
                                "candidate_id": candidate_id,
                                "support_type": support_type,
                                "support_settings": support_settings,
                                "project_file": str(
                                    project_path.relative_to(
                                        self.output_dir
                                    )
                                ),
                                "archive_role_inspection": inspection,
                                "measured_slice": measured,
                                "base_qualified": base_qualified,
                            }
                        )
                    baseline_tree_trial = next(
                        item
                        for item in trials
                        if item["candidate_id"] == "tree_default"
                    )
                    normal_trial = next(
                        item
                        for item in trials
                        if item["candidate_id"] == "normal_default"
                    )
                    baseline_interface_moves = int(
                        baseline_tree_trial["measured_slice"].get(
                            "support_interface_move_count",
                            0,
                        )
                    )
                    for trial in trials:
                        measured = trial["measured_slice"]
                        coverage = (
                            int(
                                measured.get(
                                    "support_interface_move_count",
                                    0,
                                )
                            )
                            / baseline_interface_moves
                            if (
                                trial["support_type"] == "tree(manual)"
                                and baseline_interface_moves
                            )
                            else 1.0
                        )
                        trial["interface_coverage_vs_tree_default"] = round(
                            coverage,
                            4,
                        )
                        trial["cost_score_g_plus_10min"] = round(
                            float(
                                measured.get(
                                    "additional_filament_weight_g",
                                    0.0,
                                )
                            )
                            + int(
                                measured.get(
                                    "additional_time_seconds",
                                    0,
                                )
                            )
                            / 600.0,
                            4,
                        )
                        trial["qualified"] = bool(
                            trial["base_qualified"]
                            and (
                                trial["support_type"] != "tree(manual)"
                                or coverage >= 0.90
                            )
                        )
                    if baseline_interface_moves == 0:
                        parameter_optimization = {
                            "region_id": region_id,
                            "label": region["label"],
                            "passed": True,
                            "support_required": False,
                            "selected_candidate_id": None,
                            "selected_support_settings": {},
                            "minimum_interface_coverage_ratio": 1.0,
                            "selected_interface_coverage_ratio": 1.0,
                            "baseline_additional_filament_weight_g": 0.0,
                            "selected_additional_filament_weight_g": 0.0,
                            "filament_reduction_g": 0.0,
                            "baseline_additional_time_seconds": 0,
                            "selected_additional_time_seconds": 0,
                            "time_reduction_seconds": 0,
                            "candidates": [
                                trial
                                for trial in trials
                                if trial["support_type"] == "tree(manual)"
                            ],
                            "decision": (
                                "no support interface was generated inside "
                                "this modifier volume; omit the enforcer "
                                "instead of printing a zero-contact support"
                            ),
                        }
                        support_parameter_optimizations.append(
                            parameter_optimization
                        )
                        support_enforcer_projects.append(
                            {
                                "region_id": region_id,
                                "label": region["label"],
                                "project_file": None,
                                "support_type": "none",
                                "support_settings": {},
                                "support_required": False,
                                "selected_candidate_id": None,
                                "target_interface_z_range_mm": list(
                                    target_z
                                ),
                                "archive_role_inspection": {
                                    "passed": True,
                                    "parts": [],
                                    "reason": "support_not_required",
                                },
                                "measured_slice": (
                                    baseline_tree_trial["measured_slice"]
                                ),
                                "passed": True,
                                "selection_reason": (
                                    "real manual-support trial produced zero "
                                    "support-interface moves; no enforcer "
                                    "artifact is emitted"
                                ),
                            }
                        )
                        support_removal_regions.append(
                            {
                                "region_id": region_id,
                                "label": region["label"],
                                "support_required": False,
                                "passed": True,
                                "primary_removal_direction": None,
                                "required_side_count": 0,
                                "observed_interface_sides": [],
                                "support_removal_access": {
                                    "passed": True,
                                    "total_support_interface_move_count": 0,
                                    "build_plate_connected_interface_ratio": (
                                        1.0
                                    ),
                                    "detached_interface_move_ratio": 0.0,
                                    "all_detached_interfaces_side_pickable": (
                                        True
                                    ),
                                    "central_airway_non_bed_connected_move_count": (
                                        0
                                    ),
                                    "permanent_airway_support_move_count": 0,
                                    "decision": "support_not_required",
                                },
                            }
                        )
                        strategy_comparisons.append(
                            {
                                "region_id": region_id,
                                "label": region["label"],
                                "target_interface_z_range_mm": list(
                                    target_z
                                ),
                                "support_required": False,
                                "selected_support_type": "none",
                                "selected_candidate_id": None,
                                "normal_manual_rejected": True,
                                "trials": trials,
                            }
                        )
                        continue
                    qualified_tree_trials = [
                        trial
                        for trial in trials
                        if trial["support_type"] == "tree(manual)"
                        and trial["qualified"]
                    ]
                    if not qualified_tree_trials:
                        failures = [
                            {
                                "candidate_id": trial["candidate_id"],
                                "base_qualified": trial[
                                    "base_qualified"
                                ],
                                "interface_coverage_vs_tree_default": trial[
                                    "interface_coverage_vs_tree_default"
                                ],
                                "support_removal_access": trial[
                                    "measured_slice"
                                ].get("support_removal_access", {}),
                            }
                            for trial in trials
                            if trial["support_type"] == "tree(manual)"
                        ]
                        raise ValueError(
                            "no removable tree-support candidate qualified "
                            f"for {region_id}: "
                            + json.dumps(
                                failures,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        )
                    tree_trial = min(
                        qualified_tree_trials,
                        key=lambda item: (
                            round(
                                float(
                                    item[
                                        "cost_score_g_plus_10min"
                                    ]
                                ),
                                4,
                            ),
                            int(
                                item["measured_slice"].get(
                                    "additional_time_seconds",
                                    10**9,
                                )
                            ),
                            float(
                                item["measured_slice"].get(
                                    "additional_filament_weight_g",
                                    math.inf,
                                )
                            ),
                            -int(
                                item["measured_slice"].get(
                                    "support_interface_move_count",
                                    0,
                                )
                            ),
                        ),
                    )
                    formal_project_path = (
                        self.output_dir
                        / (
                            "fan_chassis_support_enforcer_"
                            f"{region_id}.3mf"
                        )
                    )
                    shutil.copy2(
                        self.output_dir / tree_trial["project_file"],
                        formal_project_path,
                    )
                    formal_inspection = (
                        inspect_support_enforcer_project(
                            formal_project_path
                        )
                    )
                    baseline_measured = baseline_tree_trial[
                        "measured_slice"
                    ]
                    selected_measured = tree_trial["measured_slice"]
                    parameter_optimization = {
                        "region_id": region_id,
                        "label": region["label"],
                        "passed": bool(
                            tree_trial["qualified"]
                            and formal_inspection["passed"]
                            and float(
                                selected_measured[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= float(
                                baseline_measured[
                                    "additional_filament_weight_g"
                                ]
                            )
                            and int(
                                selected_measured[
                                    "additional_time_seconds"
                                ]
                            )
                            <= int(
                                baseline_measured[
                                    "additional_time_seconds"
                                ]
                            )
                        ),
                        "selected_candidate_id": tree_trial[
                            "candidate_id"
                        ],
                        "selected_support_settings": tree_trial[
                            "support_settings"
                        ],
                        "minimum_interface_coverage_ratio": 0.90,
                        "selected_interface_coverage_ratio": tree_trial[
                            "interface_coverage_vs_tree_default"
                        ],
                        "baseline_additional_filament_weight_g": (
                            baseline_measured[
                                "additional_filament_weight_g"
                            ]
                        ),
                        "selected_additional_filament_weight_g": (
                            selected_measured[
                                "additional_filament_weight_g"
                            ]
                        ),
                        "filament_reduction_g": round(
                            float(
                                baseline_measured[
                                    "additional_filament_weight_g"
                                ]
                            )
                            - float(
                                selected_measured[
                                    "additional_filament_weight_g"
                                ]
                            ),
                            3,
                        ),
                        "baseline_additional_time_seconds": (
                            baseline_measured[
                                "additional_time_seconds"
                            ]
                        ),
                        "selected_additional_time_seconds": (
                            selected_measured[
                                "additional_time_seconds"
                            ]
                        ),
                        "time_reduction_seconds": (
                            int(
                                baseline_measured[
                                    "additional_time_seconds"
                                ]
                            )
                            - int(
                                selected_measured[
                                    "additional_time_seconds"
                                ]
                            )
                        ),
                        "candidates": [
                            trial
                            for trial in trials
                            if trial["support_type"] == "tree(manual)"
                        ],
                    }
                    support_parameter_optimizations.append(
                        parameter_optimization
                    )
                    chosen = {
                        "region_id": region_id,
                        "label": region["label"],
                        "project_file": formal_project_path.name,
                        "support_type": "tree(manual)",
                        "support_settings": tree_trial[
                            "support_settings"
                        ],
                        "selected_candidate_id": tree_trial[
                            "candidate_id"
                        ],
                        "target_interface_z_range_mm": list(target_z),
                        "archive_role_inspection": formal_inspection,
                        "measured_slice": tree_trial["measured_slice"],
                        "passed": bool(
                            tree_trial["qualified"]
                            and parameter_optimization["passed"]
                        ),
                        "selection_reason": (
                            "tree(manual) keeps at least 95% of support "
                            "interface moves inside the intended Z band; "
                            "normal(manual) uses less material but creates "
                            "dense interfaces on intervening lower surfaces; "
                            "qualified tree candidates are ranked by PETG "
                            "grams plus one gram-equivalent per ten minutes"
                        ),
                    }
                    support_enforcer_projects.append(chosen)
                    required_side_count = {
                        "controller_and_service_roofs": 1,
                        "main_portal_crowns": 2,
                        "upper_retention_details": 2,
                    }[region_id]
                    observed_sides = sorted(
                        side
                        for side, count in tree_trial[
                            "measured_slice"
                        ].get(
                            "support_interface_side_move_counts",
                            {},
                        ).items()
                        if int(count) > 0
                    )
                    removal_access = tree_trial["measured_slice"].get(
                        "support_removal_access",
                        {},
                    )
                    support_removal_regions.append(
                        {
                            "region_id": region_id,
                            "label": region["label"],
                            "passed": bool(
                                removal_access.get("passed")
                                and len(observed_sides)
                                >= required_side_count
                            ),
                            "primary_removal_direction": (
                                removal_access.get(
                                    "primary_removal_direction"
                                )
                            ),
                            "required_side_count": required_side_count,
                            "observed_interface_sides": observed_sides,
                            "support_removal_access": removal_access,
                        }
                    )
                    strategy_comparisons.append(
                        {
                            "region_id": region_id,
                            "label": region["label"],
                            "target_interface_z_range_mm": list(target_z),
                            "selected_support_type": "tree(manual)",
                            "selected_candidate_id": tree_trial[
                                "candidate_id"
                            ],
                            "normal_manual_rejected": not bool(
                                normal_trial["qualified"]
                            ),
                            "trials": trials,
                        }
                    )
                    files.extend(
                        (
                            str(
                                formal_project_path
                            ),
                            tree_trial["measured_slice"]["gcode"],
                            tree_trial["measured_slice"]["report_path"],
                        )
                    )
                strategy_path = (
                    self.output_dir
                    / "support_enforcer_strategy_comparison.json"
                )
                strategy_payload = {
                    "passed": (
                        len(strategy_comparisons) == 3
                        and all(
                            project["passed"]
                            for project in support_enforcer_projects
                        )
                        and all(
                            (
                                not comparison.get(
                                    "support_required",
                                    True,
                                )
                            )
                            or (
                                comparison["normal_manual_rejected"]
                                and next(
                                    trial
                                    for trial in comparison["trials"]
                                    if trial["candidate_id"]
                                    == comparison[
                                        "selected_candidate_id"
                                    ]
                                )["measured_slice"][
                                    "target_interface_move_ratio"
                                ]
                                > next(
                                    trial
                                    for trial in comparison["trials"]
                                    if trial["support_type"]
                                    == "normal(manual)"
                                )["measured_slice"][
                                    "target_interface_move_ratio"
                                ]
                            )
                            for comparison in strategy_comparisons
                        )
                    ),
                    "decision": (
                        "select support topology by contact localization "
                        "before material/time; normal(manual) is rejected "
                        "despite lower cost because it contacts unintended "
                        "lower surfaces"
                    ),
                    "comparisons": strategy_comparisons,
                }
                strategy_path.write_text(
                    json.dumps(
                        strategy_payload,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                files.append(str(strategy_path))
                support_plan["support_enforcer_projects"] = (
                    support_enforcer_projects
                )
                support_plan["support_strategy_comparison"] = {
                    "passed": strategy_payload["passed"],
                    "report_file": strategy_path.name,
                    "decision": strategy_payload["decision"],
                }
                parameter_path = (
                    self.output_dir
                    / "support_parameter_optimization.json"
                )
                parameter_payload = {
                    "passed": (
                        len(support_parameter_optimizations) == 3
                        and all(
                            item["passed"]
                            for item in support_parameter_optimizations
                        )
                    ),
                    "objective": (
                        "minimize additional PETG grams plus one "
                        "gram-equivalent per ten additional print minutes"
                    ),
                    "constraints": {
                        "target_interface_move_ratio_minimum": 0.95,
                        "interface_coverage_vs_default_minimum": 0.90,
                        "build_plate_connected_interface_ratio_minimum": (
                            0.98
                        ),
                        "detached_interface_move_ratio_maximum": 0.02,
                        "exterior_micro_island_move_count_maximum": 8,
                        "exterior_micro_island_edge_ratio_minimum": 0.95,
                        "permanent_airway_support_move_count_maximum": 0,
                    },
                    "baseline_total_additional_filament_weight_g": round(
                        sum(
                            float(
                                item[
                                    "baseline_additional_filament_weight_g"
                                ]
                            )
                            for item in support_parameter_optimizations
                        ),
                        3,
                    ),
                    "selected_total_additional_filament_weight_g": round(
                        sum(
                            float(
                                item[
                                    "selected_additional_filament_weight_g"
                                ]
                            )
                            for item in support_parameter_optimizations
                        ),
                        3,
                    ),
                    "total_filament_reduction_g": round(
                        sum(
                            float(item["filament_reduction_g"])
                            for item in support_parameter_optimizations
                        ),
                        3,
                    ),
                    "baseline_total_additional_time_seconds": sum(
                        int(
                            item[
                                "baseline_additional_time_seconds"
                            ]
                        )
                        for item in support_parameter_optimizations
                    ),
                    "selected_total_additional_time_seconds": sum(
                        int(
                            item[
                                "selected_additional_time_seconds"
                            ]
                        )
                        for item in support_parameter_optimizations
                    ),
                    "total_time_reduction_seconds": sum(
                        int(item["time_reduction_seconds"])
                        for item in support_parameter_optimizations
                    ),
                    "regions": support_parameter_optimizations,
                    "validation_method": (
                        "real OrcaSlicer slices for tree top-contact rates "
                        "30%, 25% and 20%; only candidates passing contact "
                        "localization, interface coverage, removal topology "
                        "and airway clearance may be selected"
                    ),
                }
                parameter_path.write_text(
                    json.dumps(
                        parameter_payload,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                files.append(str(parameter_path))
                support_plan["support_parameter_optimization"] = {
                    "passed": parameter_payload["passed"],
                    "report_file": parameter_path.name,
                    "objective": parameter_payload["objective"],
                    "baseline_total_additional_filament_weight_g": (
                        parameter_payload[
                            "baseline_total_additional_filament_weight_g"
                        ]
                    ),
                    "selected_total_additional_filament_weight_g": (
                        parameter_payload[
                            "selected_total_additional_filament_weight_g"
                        ]
                    ),
                    "total_filament_reduction_g": parameter_payload[
                        "total_filament_reduction_g"
                    ],
                    "baseline_total_additional_time_seconds": (
                        parameter_payload[
                            "baseline_total_additional_time_seconds"
                        ]
                    ),
                    "selected_total_additional_time_seconds": (
                        parameter_payload[
                            "selected_total_additional_time_seconds"
                        ]
                    ),
                    "total_time_reduction_seconds": parameter_payload[
                        "total_time_reduction_seconds"
                    ],
                    "regions": support_parameter_optimizations,
                }
                removal_path = (
                    self.output_dir
                    / "support_removal_accessibility.json"
                )
                removal_payload = {
                    "passed": (
                        len(support_removal_regions) == 3
                        and all(
                            region["passed"]
                            for region in support_removal_regions
                        )
                    ),
                    "part": "fan_chassis",
                    "assembly_state": (
                        "printed chassis before fan guard, fan, electronics "
                        "carrier and Mac mini are installed"
                    ),
                    "decision": (
                        "remove tree supports toward -Z through the open "
                        "underside; at least 98% of interface moves must be "
                        "build-plate connected, detached interface islands "
                        "are limited to 2%, and the permanent central airway "
                        "must contain zero support moves"
                    ),
                    "regions": support_removal_regions,
                }
                removal_path.write_text(
                    json.dumps(
                        removal_payload,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                files.append(str(removal_path))
                support_plan["support_removal_accessibility"] = {
                    "passed": removal_payload["passed"],
                    "report_file": removal_path.name,
                    "decision": removal_payload["decision"],
                    "regions": support_removal_regions,
                }
            support_plan["passed"] = (
                bool(support_plan["passed"])
                and len(modifier_records) == 3
                and all(
                    float(
                        item.get(
                            "chassis_intersection_mm3",
                            0.0,
                        )
                    )
                    > 0.0
                    for item in modifier_records
                )
                and support_plan[
                    "modifier_support_interface_move_count"
                ]
                == support_plan[
                    "total_support_interface_move_count"
                ]
                and (
                    manufacturing is None
                    or (
                        len(support_enforcer_projects) == 3
                        and all(
                            project["passed"]
                            for project in support_enforcer_projects
                        )
                        and bool(
                            support_plan.get(
                                "support_strategy_comparison",
                                {},
                            ).get("passed")
                        )
                        and bool(
                            support_plan.get(
                                "support_removal_accessibility",
                                {},
                            ).get("passed")
                        )
                        and bool(
                            support_plan.get(
                                "support_parameter_optimization",
                                {},
                            ).get("passed")
                        )
                    )
                )
            )
            support_plan_path = (
                self.output_dir / "localized_support_decision_plan.json"
            )
            support_plan["report_path"] = str(support_plan_path.resolve())
            support_plan_path.write_text(
                json.dumps(support_plan, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            manufacturing["localized_support_plan"] = support_plan
            files.append(str(support_plan_path))
        proposal_path = self.output_dir / "design_proposal.md"
        proposal_path.write_text(proposal.to_markdown(), encoding="utf-8")
        files.append(str(proposal_path))
        airflow = None
        structure = None
        if proposal.brief.design_family == "smart_fan":
            airflow = analyze_smart_fan_airflow(
                parts,
                proposal.brief.request,
            )
            airflow_path = self.output_dir / "airflow_thermal_report.json"
            airflow_path.write_text(
                json.dumps(airflow, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            files.append(str(airflow_path))
            structure = analyze_smart_fan_structure(parts, assembly)
            structure_path = self.output_dir / "structural_load_report.json"
            structure_path.write_text(
                json.dumps(structure, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            files.append(str(structure_path))
        preview = self._preview_manifest(
            parts,
            assembly,
            proposal,
            reference_parts=reference_parts,
            calibration_parts=calibration_parts,
            support_modifier_parts=support_modifier_parts,
            manufacturing_control_parts=manufacturing_control_parts,
            manufacturing=manufacturing,
            structure=structure,
        )
        result = WorkflowResult(
            proposal=proposal,
            exported_files=files,
            validation=validation,
            vision=vision,
            preview=preview,
            manufacturing=manufacturing,
            airflow=airflow,
            structure=structure,
            bom=bom,
            calibration=calibration,
            requested_planner=self._requested_planner,
            actual_planner=self._actual_planner,
            fallback=self._fallback,
        )
        if vision:
            vision_path = self.output_dir / "hardware_analysis.json"
            vision_path.write_text(
                json.dumps(vision, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            result.exported_files.append(str(vision_path))
        if proposal.brief.design_family == "smart_fan":
            design_review_path = self.output_dir / "industrial_design_review.json"
            design_review = self._smart_fan_design_review(
                parts,
                assembly,
                manufacturing,
                reference_parts,
                airflow,
                structure,
                bom,
                installed_assembly,
                calibration,
                {
                    "printable": (
                        self.output_dir
                        / f"{assembly_name}.step"
                    ),
                    "installed": (
                        self.output_dir
                        / f"{installed_assembly.name}.step"
                    ),
                },
                preview,
            )
            result.design_review = design_review
            design_review_path.write_text(
                json.dumps(
                    design_review,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result.exported_files.append(str(design_review_path))
        report_path = self.output_dir / "validation_report.json"
        result.exported_files.append(str(report_path))
        report_path.touch()
        report_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return result

    @staticmethod
    def _opening_support_economy(
        parts: list[CADPart],
        control_parts: list[CADPart],
        manufacturing: dict[str, Any],
        control_manufacturing: dict[str, Any],
        control_validation: dict[str, dict[str, Any]],
        support_strategy: str = "minimal",
    ) -> dict[str, Any]:
        """Compare the real portal chassis against a sealed-wall slice."""

        chassis = next(part for part in parts if part.name == "fan_chassis")
        control = next(
            part
            for part in control_parts
            if part.metadata.get("control_kind")
            == "sealed_main_air_portals"
        )
        actual = manufacturing["parts"][chassis.name]
        sealed = control_manufacturing["parts"][control.name]
        support = manufacturing["support_analysis"]["parts"].get(
            chassis.name,
            {},
        )
        support_strategy = support_strategy or "minimal"
        support_analysis = manufacturing["support_analysis"]
        if support_strategy == "none":
            support_for_openings_allowed = (
                not bool(support_analysis.get("support_required"))
                and bool(support_analysis.get("support_free_baseline_passed"))
            )
        elif support_strategy == "required":
            support_for_openings_allowed = True
        else:
            support_for_openings_allowed = (
                bool(support_analysis.get("passed"))
                if "passed" in support_analysis
                else not bool(support_analysis.get("support_required"))
            )
        opening_support_required = not support_for_openings_allowed
        actual_weight_g = float(actual["filament_weight_g"])
        sealed_weight_g = float(sealed["filament_weight_g"])
        actual_time_seconds = int(actual["estimated_seconds"])
        sealed_time_seconds = int(sealed["estimated_seconds"])
        support_weight_g = float(
            support.get("additional_filament_weight_g", 0.0)
        )
        support_time_seconds = int(
            support.get("additional_time_seconds", 0)
        )
        material_saved_g = sealed_weight_g - actual_weight_g
        time_saved_seconds = sealed_time_seconds - actual_time_seconds
        supported_actual_weight_g = actual_weight_g + support_weight_g
        supported_actual_time_seconds = (
            actual_time_seconds + support_time_seconds
        )
        net_material_if_supported_g = (
            sealed_weight_g - supported_actual_weight_g
        )
        net_time_if_supported_seconds = (
            sealed_time_seconds - supported_actual_time_seconds
        )
        production_void_economy_passed = (
            material_saved_g > 0.0
            and time_saved_seconds > 0
            and (
                (not bool(actual["support_used"]))
                if support_strategy == "none"
                else True
            )
            and not opening_support_required
        )
        supported_void_economy_passed = (
            net_material_if_supported_g > 0.0
            and net_time_if_supported_seconds > 0
        )
        actual_volume_mm3 = float(chassis.solid().Volume())
        sealed_volume_mm3 = float(control.solid().Volume())
        airflow_area_mm2 = float(
            chassis.metadata["lateral_airflow_area_mm2"]
        )
        airflow_ratio = float(
            chassis.metadata["lateral_airflow_ratio_to_fan"]
        )
        exterior = chassis.metadata["exterior_continuity"]
        controller_vents = chassis.metadata["controller_vent_pattern"]
        service_access = chassis.metadata["controller_service_access"]
        cradle = next(
            (part for part in parts if part.name == "mac_mini_cradle"),
            None,
        )
        cradle_slice = (
            manufacturing["parts"].get(cradle.name, {})
            if cradle is not None
            else {}
        )
        validation = control_validation[control.name]
        opening_decisions = [
            {
                "opening_id": "main_air_portals",
                "part": chassis.name,
                "count": int(
                    chassis.metadata["lateral_airflow_slot_count"]
                ),
                "purpose": "required lateral fan intake and exhaust",
                "decorative": False,
                "geometry_strategy": exterior["opening_style"],
                "maximum_bridge_span_mm": float(
                    exterior["maximum_opening_bridge_mm"]
                ),
                "minimum_roof_slope_deg": float(
                    exterior["minimum_roof_slope_deg"]
                ),
                        "support_required": opening_support_required,
                "evidence": (
                    "paired real OrcaSlicer production-versus-sealed-wall "
                    "slices plus the support-free production slice"
                ),
                "accepted": production_void_economy_passed,
                "decision": (
                    "retain only with support disabled; the void saves both "
                    "PETG and print time"
                ),
            },
            {
                "opening_id": "controller_air_and_service_arches",
                "part": chassis.name,
                "count": int(
                    controller_vents[
                        "external_self_supporting_arch_count"
                    ]
                    + controller_vents[
                        "internal_self_supporting_arch_count"
                    ]
                ),
                "purpose": (
                    "controller cross-flow, cable access and snap release"
                ),
                "decorative": False,
                "geometry_strategy": controller_vents["strategy"],
                "maximum_bridge_span_mm": max(
                    float(
                        controller_vents[
                            "external_maximum_closing_bridge_mm"
                        ]
                    ),
                    float(
                        controller_vents["maximum_closing_bridge_mm"]
                    ),
                ),
                "minimum_roof_slope_deg": min(
                    float(
                        controller_vents[
                            "external_arch_minimum_roof_slope_deg"
                        ]
                    ),
                    float(
                        controller_vents[
                            "internal_minimum_roof_slope_deg"
                        ]
                    ),
                ),
                        "support_required": opening_support_required,
                "evidence": (
                    "OpenCascade opening geometry and the complete chassis "
                    "support-free OrcaSlicer slice"
                ),
                "accepted": (
                    not opening_support_required
                    and float(
                        controller_vents[
                            "external_maximum_closing_bridge_mm"
                        ]
                    )
                    <= 20.0
                    and float(
                        controller_vents["maximum_closing_bridge_mm"]
                    )
                    <= 20.0
                ),
                "decision": (
                    "retain as functional self-supporting arches; do not add "
                    "smaller decorative perforations"
                ),
            },
            {
                "opening_id": "controller_usb_service_arch",
                "part": chassis.name,
                "count": 1,
                "purpose": "USB plug insertion and controller maintenance",
                "decorative": False,
                "geometry_strategy": service_access["port_style"],
                "maximum_bridge_span_mm": float(
                    service_access["port_effective_bridge_mm"]
                ),
                "minimum_roof_slope_deg": float(
                    service_access["port_minimum_roof_slope_deg"]
                ),
                "support_required": opening_support_required,
                "evidence": (
                    "OpenCascade service corridor plus the complete chassis "
                    "support-free OrcaSlicer slice"
                ),
                "accepted": (
                    not opening_support_required
                    and float(
                        service_access["port_effective_bridge_mm"]
                    )
                    <= 20.0
                ),
                "decision": (
                    "retain for service access with its pointed printable "
                    "roof; reject a flat-topped slot"
                ),
            },
        ]
        if cradle is not None:
            rear_relief = cradle.metadata["rear_service_relief"]
            cradle_support_free = not bool(
                cradle_slice.get("support_used", True)
            )
            opening_decisions.extend(
                (
                    {
                        "opening_id": "cradle_central_airway",
                        "part": cradle.name,
                        "count": 1,
                        "purpose": "uninterrupted Mac mini bottom airflow",
                        "decorative": False,
                        "geometry_strategy": (
                            "vertical circular throat with a lower bellmouth"
                        ),
                        "maximum_bridge_span_mm": 0.0,
                        "minimum_roof_slope_deg": 90.0,
                        "support_required": opening_support_required,
                        "evidence": (
                            "OpenCascade through-opening plus the cradle "
                            "support-free OrcaSlicer slice"
                        ),
                        "accepted": (
                            not opening_support_required
                            and cradle_support_free
                        ),
                        "decision": (
                            "retain as a through-airway; no roof exists for "
                            "slicer support to contact"
                        ),
                    },
                    {
                        "opening_id": "rear_connector_service_relief",
                        "part": cradle.name,
                        "count": 1,
                        "purpose": "power and Ethernet plug clearance",
                        "decorative": False,
                        "geometry_strategy": rear_relief["style"],
                        "maximum_bridge_span_mm": 0.0,
                        "minimum_roof_slope_deg": 90.0,
                        "support_required": opening_support_required,
                        "evidence": (
                            "top-open OpenCascade relief plus the cradle "
                            "support-free OrcaSlicer slice"
                        ),
                        "accepted": (
                            not opening_support_required
                            and
                            cradle_support_free
                            and not bool(
                                rear_relief["breaks_bottom_outer_edge"]
                            )
                        ),
                        "decision": (
                            "retain one broad top-open relief instead of "
                            "multiple castellated connector notches"
                        ),
                    },
                )
            )
        opening_inventory_passed = all(
            bool(opening["accepted"])
            and not bool(opening["decorative"])
            and not bool(opening["support_required"])
            for opening in opening_decisions
        )
        control_mesh = validation.get("mesh", {})
        control_geometry = validation.get("geometry", {})
        control_geometry_passed = bool(
            (
                control_geometry.get("valid", True)
                and control_geometry.get("solid_count") == 1
                and control_mesh.get("watertight_trimesh")
                and control_mesh.get("components") == 1
            )
            if control_mesh
            else validation.get("printable", False)
        )
        checks = {
            "sealed_control_geometry": {
                "passed": control_geometry_passed,
                "kernel": validation["geometry"]["kernel"],
                "solid_count": validation["geometry"]["solid_count"],
                "watertight_trimesh": control_mesh.get(
                    "watertight_trimesh"
                ),
                "winding_consistent": control_mesh.get(
                    "winding_consistent"
                ),
                "mesh_components": control_mesh.get("components"),
                "control_is_not_a_printed_part": True,
            },
            "portal_material_reduction": {
                "passed": material_saved_g > 0.0,
                "sealed_control_weight_g": sealed_weight_g,
                "production_weight_g": actual_weight_g,
                "material_saved_g": round(material_saved_g, 3),
            },
            "support_free_production": {
                "passed": (
                    (not opening_support_required)
                    if support_strategy in {"minimal", "required"}
                    else (
                        not bool(actual["support_used"])
                        and not opening_support_required
                    )
                ),
                "production_support_used": bool(actual["support_used"]),
                "auto_support_penalty_g": round(support_weight_g, 3),
                "auto_support_penalty_seconds": support_time_seconds,
            },
            "functional_airflow_value": {
                "passed": airflow_ratio >= 0.65,
                "lateral_open_area_mm2": round(airflow_area_mm2, 1),
                "ratio_to_fan_disk": round(airflow_ratio, 3),
                "sealed_control_is_viable_product": False,
            },
            "support_cost_vs_void_benefit": {
                "passed": production_void_economy_passed,
                "production_void_accepted": (
                    production_void_economy_passed
                ),
                "support_dependent_void_economy_passed": (
                    supported_void_economy_passed
                ),
                "support_dependent_void_accepted": False,
                "rejection_triggers": {
                    "non_positive_material_advantage": (
                        net_material_if_supported_g <= 0.0
                    ),
                    "non_positive_time_advantage": (
                        net_time_if_supported_seconds <= 0
                    ),
                    "support_required": bool(
                        opening_support_required
                    ),
                },
                "rule": (
                    "retain a void only when the production orientation saves "
                    "both filament and time unless support is allowed by "
                    "strategy and still economic."
                ),
            },
            "opening_inventory_gate": {
                "passed": opening_inventory_passed,
                "opening_count": sum(
                    int(opening["count"])
                    for opening in opening_decisions
                ),
                "decorative_opening_count": sum(
                    int(opening["count"])
                    for opening in opening_decisions
                    if bool(opening["decorative"])
                ),
                "support_dependent_opening_count": sum(
                    int(opening["count"])
                    for opening in opening_decisions
                    if bool(opening["support_required"])
                ),
                "rule": (
                    "every shell void must have a functional purpose and a "
                    "support-free production strategy; reject decorative or "
                    "support-dependent openings before full-size export"
                ),
            },
        }
        return {
            "passed": all(check["passed"] for check in checks.values()),
            "method": (
                "real OrcaSlicer A/B slices at identical orientation and "
                "PETG profile: production portals versus the same chassis "
                "with only four main portal wall volumes restored"
            ),
            "control": {
                "part": control.name,
                "do_not_print": True,
                "restored_portal_count": control.metadata[
                    "restored_portal_count"
                ],
                "excluded_from_assembly": True,
                "excluded_from_production_totals": True,
            },
            "geometry": {
                "production_volume_mm3": round(actual_volume_mm3, 3),
                "sealed_control_volume_mm3": round(
                    sealed_volume_mm3,
                    3,
                ),
                "portal_removed_volume_mm3": round(
                    sealed_volume_mm3 - actual_volume_mm3,
                    3,
                ),
            },
            "opening_decisions": opening_decisions,
            "support_free_comparison": {
                "production_weight_g": actual_weight_g,
                "sealed_control_weight_g": sealed_weight_g,
                "material_saved_g": round(material_saved_g, 3),
                "production_time_seconds": actual_time_seconds,
                "sealed_control_time_seconds": sealed_time_seconds,
                "time_saved_seconds": time_saved_seconds,
            },
            "if_auto_support_is_enabled": {
                "production_plus_support_weight_g": round(
                    supported_actual_weight_g,
                    3,
                ),
                "net_material_advantage_vs_sealed_g": round(
                    net_material_if_supported_g,
                    3,
                ),
                "production_plus_support_time_seconds": (
                    supported_actual_time_seconds
                ),
                "net_time_advantage_vs_sealed_seconds": (
                    net_time_if_supported_seconds
                ),
                "warning": (
                    "negative advantage means unnecessary support erased the "
                    "portal's manufacturing saving"
                ),
            },
            "checks": checks,
            "decision": (
                "retain the four smooth portals for required airflow and "
                "material reduction, but keep production support disabled; "
                "reject the support-dependent alternative because its net "
                "time advantage is non-positive; do not add decorative voids"
            ),
        }

    @staticmethod
    def _localized_support_decision_plan(
        manufacturing: dict[str, Any],
        calibration: dict[str, Any] | None,
        chassis: CADPart,
    ) -> dict[str, Any]:
        """Convert measured auto-support cost into a physical decision tree."""

        support_analysis = manufacturing.get("support_analysis", {})
        fan_support = support_analysis.get("parts", {}).get(
            "fan_chassis",
            {},
        )
        envelope = fan_support.get("support_toolpath_envelope", {})
        bands = envelope.get("z_bands", [])

        def band_for(start_mm: float) -> dict[str, Any]:
            return next(
                (
                    band
                    for band in bands
                    if float(
                        band.get(
                            "nominal_z_range_mm",
                            [-math.inf, -math.inf],
                        )[0]
                    )
                    == start_mm
                ),
                {},
            )

        def region(
            region_id: str,
            label: str,
            start_mm: float,
            decision_input: str,
            pass_action: str,
            fail_action: str,
            extra_start_mm: tuple[float, ...] = (),
        ) -> dict[str, Any]:
            measured_bands = [
                band_for(value)
                for value in (start_mm, *extra_start_mm)
            ]
            actual_ranges = [
                band.get("actual_z_range_mm", [])
                for band in measured_bands
                if len(band.get("actual_z_range_mm", [])) == 2
            ]
            measured = measured_bands[0]
            feature_names = {
                name
                for band in measured_bands
                for name in band.get("feature_move_counts", {})
            }
            feature_counts = {
                name: sum(
                    int(
                        band.get("feature_move_counts", {}).get(
                            name,
                            0,
                        )
                    )
                    for band in measured_bands
                )
                for name in feature_names
            }
            return {
                "id": region_id,
                "label": label,
                "nominal_z_range_mm": [
                    min((start_mm, *extra_start_mm)),
                    max((start_mm, *extra_start_mm)) + 5.0,
                ],
                "actual_z_range_mm": (
                    [
                        min(values[0] for values in actual_ranges),
                        max(values[1] for values in actual_ranges),
                    ]
                    if actual_ranges
                    else []
                ),
                "support_extrusion_move_count": sum(
                    int(band.get("extrusion_move_count", 0))
                    for band in measured_bands
                ),
                "support_interface_move_count": int(
                    feature_counts.get("support_interface", 0)
                ),
                "decision_input": decision_input,
                "after_pass": pass_action,
                "after_fail": fail_action,
            }

        threshold_sweep = manufacturing.get(
            "support_threshold_sweep",
            {},
        )
        trials = {
            float(trial.get("threshold_angle_deg")): trial
            for trial in threshold_sweep.get("trials", [])
        }
        reference = trials.get(30.0, {})
        high_35 = trials.get(35.0, {})
        high_45 = trials.get(45.0, {})
        controller_access = chassis.metadata["controller_service_access"]
        bridge_part = (calibration or {}).get("parts", {}).get(
            "portal_bridge_support_coupon",
            {},
        )
        maximum_sag = float(
            bridge_part.get("acceptance", {}).get(
                "maximum_crown_sag_mm",
                0.5,
            )
        )
        total_interface_moves = int(
            envelope.get("feature_move_counts", {}).get(
                "support_interface",
                0,
            )
        )
        regions = [
            region(
                "controller_and_service_roofs",
                "控制器仓、USB 维护拱口与局部卡扣",
                25.0,
                (
                    "USB bridge coupon sag and visual inspection of the "
                    "controller-cover snap features"
                ),
                (
                    "keep support disabled; the USB arch is qualified by "
                    "the physical coupon and the remaining roofs are "
                    "self-supporting chamfers/corbels"
                ),
                (
                    "paint manual support only inside the failed USB arch "
                    "or visibly failed local snap roof; do not support the "
                    "whole electronics plenum"
                ),
            ),
            region(
                "main_portal_crowns",
                "四面连续主风口拱冠",
                45.0,
                "main portal bridge coupon crown sag",
                (
                    "use the four one-layer integral breakaway membranes; "
                    "do not add external tree support when the coupon passes"
                ),
                (
                    "paint manual support only beneath each portal crown "
                    "that fails the coupon; preserve the continuous top rail"
                ),
                extra_start_mm=(50.0,),
            ),
            region(
                "upper_retention_details",
                "上层定位锚点、风扇卡钩与连续承力肋",
                55.0,
                (
                    "fan fit gauge, ten insertion/removal cycles and visual "
                    "inspection for hook whitening or layer separation"
                ),
                (
                    "keep support disabled; 45 degree hook undercuts and "
                    "anchor transitions are the production geometry"
                ),
                (
                    "paint support only under the failed hook/anchor; never "
                    "fill the main airflow portals"
                ),
            ),
        ]
        classified_interface_moves = sum(
            item["support_interface_move_count"] for item in regions
        )
        return {
            "schema_version": 1,
            "passed": (
                bool(threshold_sweep.get("passed"))
                and bool(support_analysis.get("support_free_baseline_passed"))
                and total_interface_moves > 0
                and classified_interface_moves == total_interface_moves
                and 30.0 in trials
                and 35.0 in trials
                and 45.0 in trials
            ),
            "part": "fan_chassis",
            "coordinate_system": (
                "fan_chassis STL local coordinates in production orientation"
            ),
            "production_default": {
                "support_enabled": False,
                "support_type": "none",
                "reason": (
                    "support-free slice passes; global auto support adds "
                    f"{float(support_analysis.get('additional_filament_weight_g', 0.0)):.2f} g "
                    f"and {int(support_analysis.get('additional_time_seconds', 0))} s"
                ),
            },
            "physical_gate": {
                "coupon": "portal_bridge_support_coupon",
                "maximum_crown_sag_mm": maximum_sag,
                "main_portal_crown_bridge_mm": bridge_part.get(
                    "features",
                    {},
                ).get("main_portal_crown_bridge_mm"),
                "usb_effective_bridge_mm": bridge_part.get(
                    "features",
                    {},
                ).get("usb_effective_bridge_mm"),
                "status": "pending_physical_measurement",
            },
            "threshold_guardrail": {
                "reference_threshold_deg": 30.0,
                "maximum_global_threshold_deg": 30.0,
                "do_not_use_global_thresholds_deg": [35.0, 45.0],
                "reference_cost": {
                    "additional_filament_weight_g": reference.get(
                        "additional_filament_weight_g"
                    ),
                    "additional_time_seconds": reference.get(
                        "additional_time_seconds"
                    ),
                    "support_extrusion_move_count": reference.get(
                        "support_extrusion_move_count"
                    ),
                },
                "cost_increase_at_35_deg_vs_30_deg": {
                    "filament_weight_g": round(
                        float(
                            high_35.get(
                                "additional_filament_weight_g",
                                0.0,
                            )
                        )
                        - float(
                            reference.get(
                                "additional_filament_weight_g",
                                0.0,
                            )
                        ),
                        3,
                    ),
                    "time_seconds": int(
                        high_35.get("additional_time_seconds", 0)
                    )
                    - int(reference.get("additional_time_seconds", 0)),
                },
                "cost_increase_at_45_deg_vs_30_deg": {
                    "filament_weight_g": round(
                        float(
                            high_45.get(
                                "additional_filament_weight_g",
                                0.0,
                            )
                        )
                        - float(
                            reference.get(
                                "additional_filament_weight_g",
                                0.0,
                            )
                        ),
                        3,
                    ),
                    "time_seconds": int(
                        high_45.get("additional_time_seconds", 0)
                    )
                    - int(reference.get("additional_time_seconds", 0)),
                },
            },
            "regions": regions,
            "classified_support_interface_move_count": (
                classified_interface_moves
            ),
            "total_support_interface_move_count": total_interface_moves,
            "usb_service_arch": {
                "center_mm": list(
                    controller_access["usb_port_center_mm"]
                ),
                "dimensions_mm": list(
                    controller_access["usb_port_dimensions_mm"]
                ),
                "bottom_z_mm": controller_access["port_bottom_z_mm"],
                "roof_start_z_mm": controller_access[
                    "port_roof_start_z_mm"
                ],
                "top_z_mm": controller_access["port_top_z_mm"],
            },
            "operator_sequence": [
                "print the bridge coupon with support disabled",
                (
                    "measure main-portal and USB crown sag after the coupon "
                    "fully cools"
                ),
                (
                    "if both are within tolerance, slice the chassis with "
                    "support disabled"
                ),
                (
                    "if one fails after bridge tuning, use OrcaSlicer manual "
                    "support painting only in the matching region"
                ),
                (
                    "inspect preview to confirm no support enters the fan "
                    "throat, electronics service path or Mac inlet"
                ),
            ],
            "validation_method": (
                "same-profile threshold sweep plus measured 5 mm Z bands "
                "and physical bridge/fit coupon decision inputs"
            ),
        }

    @staticmethod
    def _smart_fan_design_review(
        parts: list[CADPart],
        assembly,
        manufacturing: dict[str, Any] | None = None,
        reference_parts: list[CADPart] | None = None,
        airflow_report: dict[str, Any] | None = None,
        structure_report: dict[str, Any] | None = None,
        bom_report: dict[str, Any] | None = None,
        installed_assembly=None,
        calibration_report: dict[str, Any] | None = None,
        exported_step_paths: dict[str, Path] | None = None,
        preview_manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        by_name = {part.name: part for part in parts}
        chassis = by_name["fan_chassis"]
        cover = by_name["controller_cover"]
        guard = by_name["fan_guard"]
        cradle = by_name["mac_mini_cradle"]
        plunger = by_name["power_button_plunger"]
        device = tuple(cradle.metadata["device_dimensions_mm"])
        tolerance_mm = float(cradle.metadata["tolerance_mm"])
        cavity = float(cradle.metadata["locating_cavity_mm"])
        airflow_opening = float(cradle.metadata["airflow_opening_mm"])
        fan_cavity = float(chassis.metadata["fan_cavity_mm"])
        chassis_height = float(chassis.metadata["dimensions_mm"][2])
        fan_deck_height = float(chassis.metadata["fan_deck_height_mm"])
        chassis_width = float(chassis.metadata["dimensions_mm"][1])
        lateral_airflow_ratio = float(
            chassis.metadata["lateral_airflow_ratio_to_fan"]
        )
        guard_open_area_ratio = float(guard.metadata["open_area_ratio"])
        hardware_references = chassis.metadata["hardware_references"]
        reference_parts = reference_parts or []
        reference_names = {part.name for part in reference_parts}
        installed_component_names = (
            {part.name for part in installed_assembly.parts}
            if installed_assembly is not None
            else set()
        )
        installed_bounds = (
            [
                part.solid()
                .moved(installed_assembly.placements[part.name])
                .BoundingBox()
                for part in installed_assembly.parts
            ]
            if installed_assembly is not None
            else []
        )
        installed_envelope = (
            (
                max(bounds.xmax for bounds in installed_bounds)
                - min(bounds.xmin for bounds in installed_bounds),
                max(bounds.ymax for bounds in installed_bounds)
                - min(bounds.ymin for bounds in installed_bounds),
                max(bounds.zmax for bounds in installed_bounds)
                - min(bounds.zmin for bounds in installed_bounds),
            )
            if installed_bounds
            else (math.inf, math.inf, math.inf)
        )
        step_roundtrip: dict[str, dict[str, Any]] = {}
        for label, path in (exported_step_paths or {}).items():
            imported = cq.importers.importStep(str(path)).val()
            imported_bounds = imported.BoundingBox()
            step_roundtrip[label] = {
                "file": path.name,
                "valid": bool(imported.isValid()),
                "solid_count": len(imported.Solids()),
                "envelope_mm": [
                    round(float(imported_bounds.xlen), 6),
                    round(float(imported_bounds.ylen), 6),
                    round(float(imported_bounds.zlen), 6),
                ],
                "bounds_mm": {
                    "x": [
                        round(float(imported_bounds.xmin), 6),
                        round(float(imported_bounds.xmax), 6),
                    ],
                    "y": [
                        round(float(imported_bounds.ymin), 6),
                        round(float(imported_bounds.ymax), 6),
                    ],
                    "z": [
                        round(float(imported_bounds.zmin), 6),
                        round(float(imported_bounds.zmax), 6),
                    ],
                },
            }
        exact_installed_envelope = tuple(
            float(value)
            for value in step_roundtrip.get(
                "installed",
                {},
            ).get(
                "envelope_mm",
                installed_envelope,
            )
        )
        installed_control_polygon_margin = tuple(
            max(
                0.0,
                float(installed_envelope[index])
                - float(exact_installed_envelope[index]),
            )
            for index in range(3)
        )
        exact_printable_envelope = tuple(
            float(value)
            for value in step_roundtrip.get(
                "printable",
                {},
            ).get(
                "envelope_mm",
                (math.inf, math.inf, math.inf),
            )
        )
        placed_min_z = {}
        placed_bounds = {}
        for part in parts:
            bounds = (
                part.solid()
                .moved(assembly.placements[part.name])
                .BoundingBox()
            )
            placed_bounds[part.name] = bounds
            placed_min_z[part.name] = float(bounds.zmin)
        assembly_min_x = min(bounds.xmin for bounds in placed_bounds.values())
        assembly_max_x = max(bounds.xmax for bounds in placed_bounds.values())
        assembly_min_y = min(bounds.ymin for bounds in placed_bounds.values())
        assembly_max_y = max(bounds.ymax for bounds in placed_bounds.values())
        cradle_bounds = placed_bounds[cradle.name]
        assembly_lateral_extension = max(
            0.0,
            float(cradle_bounds.xmin - assembly_min_x),
            float(assembly_max_x - cradle_bounds.xmax),
            float(cradle_bounds.ymin - assembly_min_y),
            float(assembly_max_y - cradle_bounds.ymax),
        )
        assembly_planar_envelope = (
            float(assembly_max_x - assembly_min_x),
            float(assembly_max_y - assembly_min_y),
        )

        def planar_contact_area(
            part: CADPart,
            plane_z_mm: float,
        ) -> float:
            shape = part.solid()
            return sum(
                float(face.Area())
                for face in shape.Faces()
                if abs(
                    float(face.BoundingBox().zmin) - plane_z_mm
                )
                <= 0.02
                and abs(
                    float(face.BoundingBox().zmax) - plane_z_mm
                )
                <= 0.02
            )

        chassis_translation, _ = assembly.placements[chassis.name].toTuple()
        cover_translation, _ = assembly.placements[cover.name].toTuple()
        chassis_contact_plane = (
            float(chassis.metadata["desk_contact"]["plane_z_mm"])
            + float(chassis_translation[2])
        )
        cover_contact_plane = (
            float(cover.metadata["desk_contact_plane_z_mm"])
            + float(cover_translation[2])
        )
        chassis_contact_area = planar_contact_area(
            chassis,
            float(chassis.metadata["desk_contact"]["plane_z_mm"]),
        )
        cover_contact_area = planar_contact_area(
            cover,
            float(cover.metadata["desk_contact_plane_z_mm"]),
        )
        floor_contact_area = chassis_contact_area + cover_contact_area
        interference = validate_assembly_interference(assembly)

        def intersection_volume(
            shape: Any,
            keepout: cq.Workplane,
        ) -> float:
            return float(shape.intersect(keepout.val()).Volume())

        device_support_height = float(
            cradle.metadata["device_body_support_plane_mm"]
        )
        device_length, device_width, device_height = (
            float(value) for value in cradle.metadata["device_dimensions_mm"]
        )
        service_depth = float(
            cradle.metadata["port_keepout"]["external_service_depth_mm"]
        )
        interface_minimum_z = float(
            cradle.metadata["port_keepout"]["minimum_interface_z_mm"]
        )
        front_keepout = (
            cq.Workplane("XY")
            .box(
                device_length,
                service_depth,
                device_height - interface_minimum_z,
                centered=(True, True, False),
            )
            .translate(
                (
                    0.0,
                    -(device_width + service_depth) / 2,
                    device_support_height + interface_minimum_z,
                )
            )
        )
        rear_keepout = (
            cq.Workplane("XY")
            .box(
                device_length,
                service_depth,
                device_height - interface_minimum_z,
                centered=(True, True, False),
            )
            .translate(
                (
                    0.0,
                    (device_width + service_depth) / 2,
                    device_support_height + interface_minimum_z,
                )
            )
        )
        front_obstruction_volume = intersection_volume(
            cradle.solid(),
            front_keepout,
        )
        rear_obstruction_volume = intersection_volume(
            cradle.solid(),
            rear_keepout,
        )
        mac_reference = next(
            (
                part
                for part in reference_parts
                if part.name == "mac_mini_m4_fit_reference"
            ),
            None,
        )
        button_center = tuple(
            float(value)
            for value in cradle.metadata["power_button_access"]["center_mm"]
        )
        button_shaft_center = tuple(
            float(value)
            for value in cradle.metadata["power_button_access"][
                "shaft_center_mm"
            ]
        )
        button_access_diameter = float(
            cradle.metadata["power_button_access"]["access_diameter_mm"]
        )
        button_shaft_bore_diameter = float(
            cradle.metadata["power_button_access"][
                "shaft_bore_diameter_mm"
            ]
        )
        button_shoulder_z = float(
            cradle.metadata["power_button_access"]["shoulder_z_mm"]
        )
        button_shaft_keepout = (
            cq.Workplane("XY")
            .center(*button_shaft_center)
            .circle(button_shaft_bore_diameter / 2)
            .extrude(button_shoulder_z + 0.05)
        )
        button_head_keepout = (
            cq.Workplane("XY")
            .center(*button_center)
            .circle(button_access_diameter / 2)
            .extrude(
                float(cradle.metadata["dimensions_mm"][2])
                - button_shoulder_z
                + 0.05
            )
            .translate((0.0, 0.0, button_shoulder_z))
        )
        button_shaft_obstruction_volume = intersection_volume(
            cradle.solid(),
            button_shaft_keepout,
        )
        button_head_obstruction_volume = intersection_volume(
            cradle.solid(),
            button_head_keepout,
        )
        reference_button_center = (
            tuple(
                float(value)
                for value in mac_reference.metadata[
                    "power_button_reference"
                ]["center_mm"]
            )
            if mac_reference is not None
            else ()
        )
        button_alignment_error = (
            math.dist(button_center, reference_button_center)
            if reference_button_center
            else math.inf
        )
        plunger_head_alignment_error = math.dist(
            tuple(float(value) for value in plunger.metadata["head_center_mm"]),
            button_center,
        )
        standard_fan_mount_positions = tuple(
            tuple(float(value) for value in position)
            for position in chassis.metadata["fan_mount_interface"][
                "positions_mm"
            ]
        )
        shaft_fan_mount_alignment_error = min(
            math.dist(button_shaft_center, position)
            for position in standard_fan_mount_positions
        )
        placed_plunger = plunger.solid().moved(
            assembly.placements[plunger.name]
        )
        placed_guard = guard.solid().moved(
            assembly.placements[guard.name]
        )
        fan_reference = next(
            (
                part
                for part in reference_parts
                if part.name == "pwm_fan_120mm_reference"
            ),
            None,
        )
        placed_fan_reference = (
            fan_reference.solid().moved(
                cq.Location(
                    cq.Vector(
                        *(
                            float(value)
                            for value in fan_reference.metadata[
                                "translation_mm"
                            ]
                        )
                    )
                )
            )
            if fan_reference is not None
            else None
        )
        cradle_translation, _ = assembly.placements[cradle.name].toTuple()
        placed_mac_reference = (
            mac_reference.solid().moved(
                cq.Location(
                    cq.Vector(
                        0.0,
                        0.0,
                        float(cradle_translation[2])
                        + float(
                            cradle.metadata["device_support_height_mm"]
                        ),
                    )
                )
            )
            if mac_reference is not None
            else None
        )
        placed_cradle = cradle.solid().moved(
            assembly.placements[cradle.name]
        )
        mac_support_pad_references = [
            part
            for part in reference_parts
            if part.name.startswith("mac_support_pad_")
        ]
        placed_mac_support_pads = [
            part.solid().moved(
                cq.Location(
                    cq.Vector(
                        *(
                            float(value)
                            for value in part.metadata["translation_mm"]
                        )
                    )
                )
            )
            for part in mac_support_pad_references
        ]
        desk_pad_references = [
            part
            for part in reference_parts
            if part.name.startswith("desk_isolation_pad_")
        ]
        placed_desk_pads = [
            part.solid().moved(
                cq.Location(
                    cq.Vector(
                        *(
                            float(value)
                            for value in part.metadata["translation_mm"]
                        )
                    )
                )
            )
            for part in desk_pad_references
        ]
        mac_reference_base_z = (
            float(cradle_translation[2])
            + float(cradle.metadata["device_support_height_mm"])
        )
        mac_interface_corridors = (
            _mac_interface_corridor_specs(
                mac_reference,
                installed_base_z_mm=mac_reference_base_z,
            )
            if mac_reference is not None
            else []
        )
        placed_printed_shapes = {
            part.name: part.solid().moved(assembly.placements[part.name])
            for part in parts
        }
        mac_interface_corridor_results = []
        for corridor_spec in mac_interface_corridors:
            corridor_shape = (
                cq.Workplane("XY")
                .box(
                    *corridor_spec["dimensions_mm"],
                    centered=(True, True, True),
                )
                .translate(tuple(corridor_spec["translation_mm"]))
                .val()
            )
            obstruction_by_part = {
                name: round(
                    float(shape.intersect(corridor_shape).Volume()),
                    6,
                )
                for name, shape in placed_printed_shapes.items()
            }
            total_obstruction = sum(obstruction_by_part.values())
            mac_interface_corridor_results.append(
                {
                    **corridor_spec,
                    "obstruction_by_part_mm3": obstruction_by_part,
                    "total_obstruction_mm3": round(
                        total_obstruction,
                        6,
                    ),
                    "passed": total_obstruction <= 0.01,
                }
            )
        rear_service_relief = cradle.metadata["rear_service_relief"]
        individual_interface_access_passed = (
            len(mac_interface_corridor_results) == 9
            and sum(
                item["face"] == "front"
                for item in mac_interface_corridor_results
            )
            == 3
            and sum(
                item["face"] == "rear"
                for item in mac_interface_corridor_results
            )
            == 6
            and all(
                item["passed"]
                for item in mac_interface_corridor_results
            )
            and not bool(rear_service_relief["breaks_bottom_outer_edge"])
            and float(rear_service_relief["bottom_ring_height_mm"]) >= 4.0
            and float(rear_service_relief["width_mm"]) >= 42.0
            and float(rear_service_relief["inward_overlap_mm"])
            >= tolerance_mm
            and float(rear_service_relief["removed_volume_mm3"]) > 0.0
            and not bool(rear_service_relief["support_required"])
        )
        # Restrict the contact proof to the real outer underside landing
        # surface. The lightweight Mac reference also has four thin radial
        # webs whose only purpose is keeping its fit-test STL connected; those
        # webs are not physical cradle-contact surfaces.
        mac_foot_height = float(
            mac_reference.metadata["foot_ring_mm"][2]
        )
        mac_foot_outer_radius = float(
            mac_reference.metadata["foot_ring_mm"][0]
        ) / 2
        mac_landing_slice = (
            cq.Workplane("XY")
            .box(140.0, 140.0, 1.0, centered=(True, True, False))
            .translate(
                (
                    0.0,
                    0.0,
                    mac_reference_base_z + mac_foot_height,
                )
            )
            .val()
        )
        placed_mac_landing = (
            placed_mac_reference.intersect(mac_landing_slice)
            if placed_mac_reference is not None
            else None
        )
        mac_pad_nominal_overlap = (
            sum(
                float(pad.intersect(placed_mac_landing).Volume())
                for pad in placed_mac_support_pads
            )
            if placed_mac_landing is not None
            else math.inf
        )
        mac_pad_preload_overlap = (
            sum(
                float(
                    pad.intersect(
                        placed_mac_landing.moved(
                            cq.Location(cq.Vector(0.0, 0.0, -0.1))
                        )
                    ).Volume()
                )
                for pad in placed_mac_support_pads
            )
            if placed_mac_landing is not None
            else 0.0
        )
        mac_cradle_nominal_overlap = (
            float(placed_cradle.intersect(placed_mac_landing).Volume())
            if placed_mac_landing is not None
            else math.inf
        )
        mac_cradle_free_travel_overlap = (
            float(
                placed_cradle.intersect(
                    placed_mac_landing.moved(
                        cq.Location(cq.Vector(0.0, 0.0, -0.15))
                    )
                ).Volume()
            )
            if placed_mac_landing is not None
            else math.inf
        )
        mac_cradle_hard_stop_overlap = (
            float(
                placed_cradle.intersect(
                    placed_mac_landing.moved(
                        cq.Location(cq.Vector(0.0, 0.0, -0.21))
                    )
                ).Volume()
            )
            if placed_mac_landing is not None
            else 0.0
        )
        pad_cradle_overlap = sum(
            float(pad.intersect(placed_cradle).Volume())
            for pad in placed_mac_support_pads
        )
        pad_top_alignment_error = (
            max(
                abs(
                    float(pad.BoundingBox().zmax)
                    - (
                        float(cradle_translation[2])
                        + float(
                            cradle.metadata[
                                "support_pad_interface"
                            ]["installed_pad_top_z_mm"]
                        )
                    )
                )
                for pad in placed_mac_support_pads
            )
            if placed_mac_support_pads
            else math.inf
        )
        mac_foot_keepout = (
            cq.Workplane("XY")
            .circle(mac_foot_outer_radius)
            .extrude(mac_foot_height)
            .translate(
                (
                    0.0,
                    0.0,
                    float(placed_mac_reference.BoundingBox().zmin)
                    if placed_mac_reference is not None
                    else 0.0,
                )
            )
            .val()
        )
        pad_foot_overlap = sum(
            float(pad.intersect(mac_foot_keepout).Volume())
            for pad in placed_mac_support_pads
        )
        plunger_fan_overlap = (
            float(placed_plunger.intersect(placed_fan_reference).Volume())
            if placed_fan_reference is not None
            else math.inf
        )
        plunger_guard_overlap = float(
            placed_plunger.intersect(placed_guard).Volume()
        )
        plunger_mac_overlap = (
            float(placed_plunger.intersect(placed_mac_reference).Volume())
            if placed_mac_reference is not None
            else math.inf
        )
        plunger_top_gap = (
            float(placed_mac_reference.BoundingBox().zmin)
            - float(placed_plunger.BoundingBox().zmax)
            if placed_mac_reference is not None
            else -math.inf
        )
        placed_chassis = chassis.solid().moved(
            assembly.placements[chassis.name]
        )
        placed_cover_for_cable_relief = cover.solid().moved(
            assembly.placements[cover.name]
        )
        desk_pad_interface = chassis.metadata["desk_pad_interface"]
        desk_pad_nominal_chassis_overlap = sum(
            float(pad.intersect(placed_chassis).Volume())
            for pad in placed_desk_pads
        )
        desk_pad_preload_volumes = [
            float(
                pad.moved(
                    cq.Location(cq.Vector(0.0, 0.0, 0.1))
                ).intersect(placed_chassis).Volume()
            )
            for pad in placed_desk_pads
        ]
        desk_pad_preload_cover_overlaps = [
            float(
                pad.moved(
                    cq.Location(cq.Vector(0.0, 0.0, 0.1))
                ).intersect(placed_cover_for_cable_relief).Volume()
            )
            for pad in placed_desk_pads
        ]
        desk_pad_top_alignment_error = (
            max(
                abs(
                    float(pad.BoundingBox().zmax)
                    - float(
                        desk_pad_interface[
                            "printed_mount_plane_z_mm"
                        ]
                    )
                )
                for pad in placed_desk_pads
            )
            if placed_desk_pads
            else math.inf
        )
        desk_pad_contact_plane_error = (
            max(
                abs(
                    float(pad.BoundingBox().zmin)
                    - float(
                        desk_pad_interface[
                            "desk_contact_plane_z_mm"
                        ]
                    )
                )
                for pad in placed_desk_pads
            )
            if placed_desk_pads
            else math.inf
        )
        desk_pad_diameter = float(
            desk_pad_interface["pad_diameter_mm"]
        )
        desk_pad_airway_clearances = [
            math.hypot(float(x), float(y))
            - desk_pad_diameter / 2
            - float(chassis.metadata["bottom_airflow_opening_mm"]) / 2
            for x, y in desk_pad_interface["positions_mm"]
        ]
        desk_pad_footprint_overrun = max(
            max(abs(float(x)), abs(float(y))) + desk_pad_diameter / 2
            - float(chassis.metadata["dimensions_mm"][0]) / 2
            for x, y in desk_pad_interface["positions_mm"]
        )
        desk_pad_contact_area = (
            len(placed_desk_pads)
            * math.pi
            * (desk_pad_diameter / 2) ** 2
        )
        desk_plane_z = float(
            desk_pad_interface["desk_contact_plane_z_mm"]
        )
        plunger_to_desk_clearance = (
            float(placed_plunger.BoundingBox().zmin) - desk_plane_z
        )
        desk_pad_preload_coverage_ratios = [
            volume / (math.pi * (desk_pad_diameter / 2) ** 2 * 0.1)
            for volume in desk_pad_preload_volumes
        ]
        desk_load_island = desk_pad_interface[
            "fixed_corner_load_island"
        ]
        desk_load_island_center = tuple(
            float(value)
            for value in desk_load_island["center_mm"]
        )
        desk_load_island_shape = (
            cq.Workplane("XY")
            .center(*desk_load_island_center)
            .circle(float(desk_load_island["diameter_mm"]) / 2)
            .extrude(float(desk_load_island["height_mm"]))
            .val()
        )
        desk_load_island_cover_overlap = float(
            desk_load_island_shape.intersect(
                placed_cover_for_cable_relief
            ).Volume()
        )
        desk_load_island_pad_center_error = math.hypot(
            float(desk_pad_interface["positions_mm"][-1][0])
            - desk_load_island_center[0],
            float(desk_pad_interface["positions_mm"][-1][1])
            - desk_load_island_center[1],
        )
        desk_load_island_pad_containment_margin = (
            float(desk_load_island["diameter_mm"]) / 2
            - (
                desk_load_island_pad_center_error
                + desk_pad_diameter / 2
            )
        )
        fan_chassis_overlap = (
            float(placed_chassis.intersect(placed_fan_reference).Volume())
            if placed_fan_reference is not None
            else math.inf
        )
        guard_chassis_overlap = float(
            placed_guard.intersect(placed_chassis).Volume()
        )
        guard_downward_stop_overlap = float(
            placed_guard
            .moved(cq.Location(cq.Vector(0.0, 0.0, -0.1)))
            .intersect(placed_chassis)
            .Volume()
        )
        guard_lateral_stop_overlaps = [
            float(
                placed_guard
                .moved(cq.Location(cq.Vector(x_shift, y_shift, 0.0)))
                .intersect(placed_chassis)
                .Volume()
            )
            for x_shift, y_shift in (
                (0.26, 0.0),
                (-0.26, 0.0),
                (0.0, 0.26),
                (0.0, -0.26),
            )
        ]
        guard_service_path_overlap = max(
            float(
                placed_guard
                .moved(cq.Location(cq.Vector(0.0, 0.0, z_shift)))
                .intersect(placed_chassis)
                .Volume()
            )
            for z_shift in (0.25, 1.0, 5.0, 10.0, 20.0, 25.0, 30.0)
        )
        fan_upward_stop_overlap = (
            float(
                placed_fan_reference
                .moved(cq.Location(cq.Vector(0.0, 0.0, 0.26)))
                .intersect(placed_chassis)
                .Volume()
            )
            if placed_fan_reference is not None
            else 0.0
        )
        cable_relief = chassis.metadata["cable_strain_relief"]
        cable_relief_host = (
            placed_cover_for_cable_relief
            if cable_relief.get("host_part") == "controller_cover"
            else placed_chassis
        )
        cable_portal_x, cable_portal_y, cable_portal_z = (
            float(value) for value in cable_relief["portal_center_mm"]
        )
        cable_test_diameter = float(
            cable_relief["target_bundle_diameter_mm"]
        )
        cable_test_reference = (
            cq.Workplane("XY")
            .circle(cable_test_diameter / 2)
            .extrude(8.0)
            .rotate((0, 0, 0), (1, 0, 0), 90.0)
            .translate(
                (
                    cable_portal_x,
                    cable_portal_y,
                    cable_portal_z,
                )
            )
            .val()
        )
        cable_chassis_overlap = float(
            cable_test_reference.intersect(cable_relief_host).Volume()
        )
        cable_upward_stop_overlap = float(
            cable_test_reference
            .moved(cq.Location(cq.Vector(0.0, 0.0, 1.0)))
            .intersect(cable_relief_host)
            .Volume()
        )
        cable_lateral_stop_overlaps = [
            float(
                cable_test_reference
                .moved(cq.Location(cq.Vector(x_shift, 0.0, 0.0)))
                .intersect(cable_relief_host)
                .Volume()
            )
            for x_shift in (-0.21, 0.21)
        ]
        ds18b20_reference = next(
            (
                part
                for part in reference_parts
                if part.name == "ds18b20_probe_reference"
            ),
            None,
        )
        cable_relief_ds18b20_overlap = (
            float(
                ds18b20_reference.solid()
                .moved(
                    cq.Location(
                        cq.Vector(
                            *(
                                float(value)
                                for value in ds18b20_reference.metadata[
                                    "translation_mm"
                                ]
                            )
                        )
                    )
                )
                .intersect(cable_relief_host)
                .Volume()
            )
            if ds18b20_reference is not None
            else math.inf
        )
        placed_electronics_references = {
            part.name: part.solid().moved(
                cq.Location(
                    cq.Vector(
                        *(
                            float(value)
                            for value in part.metadata["translation_mm"]
                        )
                    )
                )
            )
            for part in reference_parts
            if part.name
            in {
                "dc_dc_12v_reference",
                "dc_dc_5v_reference",
                "esp32_c3_super_mini_reference",
                "mosfet_pwm_driver_reference",
                "ds18b20_probe_reference",
            }
        }
        cable_hardware_overlaps = {
            name: float(
                cable_test_reference.intersect(shape).Volume()
            )
            for name, shape in placed_electronics_references.items()
        }
        isolator_references = [
            part
            for part in reference_parts
            if part.name.startswith("fan_isolator_")
        ]
        placed_isolators = [
            part.solid().moved(
                cq.Location(
                    cq.Vector(
                        *(
                            float(value)
                            for value in part.metadata["translation_mm"]
                        )
                    )
                )
            )
            for part in isolator_references
        ]
        def exact_vertex_z_bounds(shape: cq.Shape) -> tuple[float, float]:
            z_values = [float(vertex.Z) for vertex in shape.Vertices()]
            return min(z_values), max(z_values)

        fan_z_bounds = (
            exact_vertex_z_bounds(placed_fan_reference)
            if placed_fan_reference is not None
            else (-math.inf, math.inf)
        )
        guard_z_bounds = exact_vertex_z_bounds(placed_guard)
        isolator_z_bounds = [
            exact_vertex_z_bounds(pad) for pad in placed_isolators
        ]
        fan_guard_overlap = (
            float(placed_guard.intersect(placed_fan_reference).Volume())
            if placed_fan_reference is not None
            else math.inf
        )
        fan_guard_hard_gap = (
            fan_z_bounds[0] - guard_z_bounds[1]
            if placed_fan_reference is not None
            else -math.inf
        )
        isolator_fan_overlap = (
            sum(
                float(pad.intersect(placed_fan_reference).Volume())
                for pad in placed_isolators
            )
            if placed_fan_reference is not None
            else math.inf
        )
        isolator_guard_overlap = sum(
            float(pad.intersect(placed_guard).Volume())
            for pad in placed_isolators
        )
        isolator_chassis_overlap = sum(
            float(pad.intersect(placed_chassis).Volume())
            for pad in placed_isolators
        )
        isolator_top_alignment_error = (
            max(
                abs(
                    pad_z_bounds[1] - fan_z_bounds[0]
                )
                for pad_z_bounds in isolator_z_bounds
            )
            if placed_isolators and placed_fan_reference is not None
            else math.inf
        )
        isolator_pocket_base_z = (
            guard_z_bounds[1]
            - float(
                guard.metadata["isolator_interface"]["pocket_depth_mm"]
            )
        )
        isolator_base_alignment_error = (
            max(
                abs(
                    pad_z_bounds[0]
                    - isolator_pocket_base_z
                )
                for pad_z_bounds in isolator_z_bounds
            )
            if placed_isolators
            else math.inf
        )
        isolator_contact_area = sum(
            math.pi
            * (
                (
                    float(part.metadata["outer_diameter_mm"])
                    / 2
                )
                ** 2
                - (
                    float(part.metadata["inner_diameter_mm"])
                    / 2
                )
                ** 2
            )
            for part in isolator_references
        )
        finger_lift = plunger.metadata["rear_access_finger_lift"]
        finger_lift_travel = float(
            finger_lift["required_actuation_travel_mm"]
        )
        actuated_plunger = placed_plunger.moved(
            cq.Location(cq.Vector(0.0, 0.0, finger_lift_travel))
        )
        finger_corridor_width = float(
            finger_lift["minimum_finger_corridor_width_mm"]
        )
        finger_access_corridor = (
            cq.Workplane("XY")
            .box(
                finger_corridor_width,
                10.0,
                4.0,
                centered=(True, True, True),
            )
            .translate((-27.0, 63.0, 16.5))
            .val()
        )
        finger_corridor_obstruction_volume = float(
            finger_access_corridor.intersect(placed_chassis).Volume()
        )
        resting_paddle_chassis_overlap = float(
            placed_plunger.intersect(placed_chassis).Volume()
        )
        actuated_paddle_chassis_overlap = float(
            actuated_plunger.intersect(placed_chassis).Volume()
        )
        actuated_paddle_guard_overlap = float(
            actuated_plunger.intersect(placed_guard).Volume()
        )
        actuated_paddle_fan_overlap = (
            float(actuated_plunger.intersect(placed_fan_reference).Volume())
            if placed_fan_reference is not None
            else math.inf
        )
        shaft_radial_clearance = (
            float(plunger.metadata["fan_mount_bore_diameter_mm"])
            - float(plunger.metadata["shaft_diameter_mm"])
        ) / 2
        expected_reference_names = {
            "mac_mini_m4_fit_reference",
            "pwm_fan_120mm_reference",
            "dc_dc_12v_reference",
            "dc_dc_5v_reference",
            "esp32_c3_super_mini_reference",
            "mosfet_pwm_driver_reference",
            "ds18b20_probe_reference",
            "fan_isolator_1_reference",
            "fan_isolator_2_reference",
            "fan_isolator_3_reference",
            "fan_isolator_4_reference",
            "mac_support_pad_1_reference",
            "mac_support_pad_2_reference",
            "mac_support_pad_3_reference",
            "mac_support_pad_4_reference",
            "desk_isolation_pad_1_reference",
            "desk_isolation_pad_2_reference",
            "desk_isolation_pad_3_reference",
            "desk_isolation_pad_4_reference",
        }
        pod_x, pod_y, _ = (
            float(value)
            for value in chassis.metadata["controller_pod_center_mm"]
        )
        pod_length, pod_width, pod_height = (
            float(value)
            for value in chassis.metadata["controller_pod_envelope_mm"]
        )
        wall = float(chassis.metadata["wall_thickness_mm"])
        electronics_fit = []
        for item in hardware_references:
            if item["name"] == "120 mm PWM fan":
                continue
            length, width, height = (
                float(value) for value in item["dimensions_mm"]
            )
            x_pos, y_pos, z_pos = (
                float(value) for value in item["translation_mm"]
            )
            is_centered_probe = item["name"].startswith("DS18B20")
            z_min = z_pos - height / 2 if is_centered_probe else z_pos
            z_max = z_pos + height / 2 if is_centered_probe else z_pos + height
            electronics_fit.append(
                x_pos - length / 2 >= pod_x - pod_length / 2 + wall
                and x_pos + length / 2 <= pod_x + pod_length / 2 - wall
                and y_pos - width / 2 >= pod_y - pod_width / 2 + wall
                and y_pos + width / 2 <= pod_y + pod_width / 2 - wall
                and z_min >= wall
                and z_max <= pod_height
            )
        component_retention = cover.metadata["component_retention"]
        retained_component_names = set(
            component_retention["retained_components"]
        )
        retained_reference_parts = [
            part
            for part in reference_parts
            if part.metadata.get("display_name")
            in retained_component_names
        ]
        placed_cover = cover.solid().moved(
            assembly.placements[cover.name]
        )

        def placed_reference_shape(part: CADPart) -> cq.Shape:
            return part.solid().moved(
                cq.Location(
                    cq.Vector(
                        *(
                            float(value)
                            for value in part.metadata["translation_mm"]
                        )
                    )
                )
            )

        retained_installed_overlaps = {
            str(part.metadata["display_name"]): float(
                placed_cover
                .intersect(placed_reference_shape(part))
                .Volume()
            )
            for part in retained_reference_parts
        }
        retained_upward_stop_overlaps = {
            str(part.metadata["display_name"]): float(
                placed_cover
                .intersect(
                    placed_reference_shape(part).moved(
                        cq.Location(cq.Vector(0.0, 0.0, 0.26))
                    )
                )
                .Volume()
            )
            for part in retained_reference_parts
        }
        retained_lateral_stop_overlaps = {
            str(part.metadata["display_name"]): [
                float(
                    placed_cover
                    .intersect(
                        placed_reference_shape(part).moved(
                            cq.Location(
                                cq.Vector(
                                    x_shift,
                                    y_shift,
                                    0.0,
                                )
                            )
                        )
                    )
                    .Volume()
                )
                for x_shift, y_shift in (
                    (0.26, 0.0),
                    (-0.26, 0.0),
                    (0.0, 0.26),
                    (0.0, -0.26),
                )
            ]
            for part in retained_reference_parts
        }
        external_service_name = str(
            component_retention["external_service_component"]
        )
        external_service_reference = next(
            (
                part
                for part in reference_parts
                if part.metadata.get("display_name")
                == external_service_name
            ),
            None,
        )
        external_service_cover_overlap = (
            float(
                placed_cover
                .intersect(
                    placed_reference_shape(
                        external_service_reference
                    )
                )
                .Volume()
            )
            if external_service_reference is not None
            else math.inf
        )
        probe_retention = cover.metadata["ds18b20_probe_retention"]
        placed_probe = (
            placed_reference_shape(external_service_reference)
            if external_service_reference is not None
            else None
        )
        probe_radial_test_travel = float(
            probe_retention["radial_clearance_mm"]
        ) + 0.01
        probe_radial_stop_overlaps = (
            {
                axis: float(
                    placed_cover
                    .intersect(
                        placed_probe.moved(
                            cq.Location(cq.Vector(*shift))
                        )
                    )
                    .Volume()
                )
                for axis, shift in {
                    "+Y": (0.0, probe_radial_test_travel, 0.0),
                    "-Y": (0.0, -probe_radial_test_travel, 0.0),
                    "+Z": (0.0, 0.0, probe_radial_test_travel),
                    "-Z": (0.0, 0.0, -probe_radial_test_travel),
                }.items()
            }
            if placed_probe is not None
            else {}
        )
        probe_release_path_overlaps = (
            [
                float(
                    placed_cover
                    .intersect(
                        placed_probe.moved(
                            cq.Location(
                                cq.Vector(0.0, 0.0, step * 0.5)
                            )
                        )
                    )
                    .Volume()
                )
                for step in range(21)
            ]
            if placed_probe is not None
            else [math.inf]
        )
        probe_chassis_overlap = (
            float(placed_probe.intersect(placed_chassis).Volume())
            if placed_probe is not None
            else math.inf
        )
        probe_guard_overlap = (
            float(placed_probe.intersect(placed_guard).Volume())
            if placed_probe is not None
            else math.inf
        )
        probe_fan_overlap = (
            float(placed_probe.intersect(placed_fan_reference).Volume())
            if (
                placed_probe is not None
                and placed_fan_reference is not None
            )
            else math.inf
        )
        electronics_service = cover.metadata[
            "electronics_service_access"
        ]
        cover_translation, _ = assembly.placements[
            cover.name
        ].toTuple()

        def placed_service_zone(
            zone: dict[str, Any],
        ) -> cq.Shape:
            center = tuple(
                float(value) for value in zone["center_mm"]
            )
            dimensions = tuple(
                float(value) for value in zone["dimensions_mm"]
            )
            return (
                cq.Workplane("XY")
                .box(
                    *dimensions,
                    centered=(True, True, True),
                )
                .translate(
                    tuple(
                        center[index]
                        + float(cover_translation[index])
                        for index in range(3)
                    )
                )
                .val()
            )

        usb_service_zone = placed_service_zone(
            electronics_service["usb_corridor"]
        )
        terminal_service_zones = [
            placed_service_zone(zone)
            for zone in electronics_service["terminal_tool_zones"]
        ]
        release_service_zones = [
            placed_service_zone(zone)
            for zone in electronics_service["release_tool_zones"]
        ]
        terminal_cover_obstructions = [
            float(zone.intersect(placed_cover).Volume())
            for zone in terminal_service_zones
        ]
        release_cover_obstructions = [
            float(zone.intersect(placed_cover).Volume())
            for zone in release_service_zones
        ]
        usb_cover_obstruction = float(
            usb_service_zone.intersect(placed_cover).Volume()
        )
        usb_chassis_obstruction = float(
            usb_service_zone.intersect(placed_chassis).Volume()
        )
        carrier_path_distance = float(
            electronics_service["carrier_path_test_distance_mm"]
        )
        carrier_path_increment = float(
            electronics_service["carrier_path_test_increment_mm"]
        )
        carrier_path_steps = int(
            carrier_path_distance / carrier_path_increment
        )
        carrier_payload_path_overlaps = []
        for step in range(carrier_path_steps + 1):
            travel = step * carrier_path_increment
            overlap = sum(
                float(
                    placed_reference_shape(part)
                    .moved(
                        cq.Location(
                            cq.Vector(0.0, 0.0, -travel)
                        )
                    )
                    .intersect(placed_chassis)
                    .Volume()
                )
                for part in retained_reference_parts
            )
            carrier_payload_path_overlaps.append(overlap)
        plate_height = float(cover.metadata["plate_height_mm"])
        cover_bounds = cover.solid().BoundingBox()
        rigid_floor = cover.solid().intersect(
            cq.Workplane("XY")
            .box(
                float(cover_bounds.xlen) + 2.0,
                float(cover_bounds.ylen) + 2.0,
                plate_height,
                centered=(True, True, False),
            )
            .val()
        )
        placed_rigid_floor = rigid_floor.moved(
            assembly.placements[cover.name]
        )
        rigid_floor_path_overlaps = [
            float(
                placed_rigid_floor
                .moved(
                    cq.Location(
                        cq.Vector(
                            0.0,
                            0.0,
                            -step * carrier_path_increment,
                        )
                    )
                )
                .intersect(placed_chassis)
                .Volume()
            )
            for step in range(carrier_path_steps + 1)
        ]
        checks = {
            "official_mac_mini_m4_envelope": {
                "passed": (
                    125.0 <= float(device[0]) <= 130.0
                    and 125.0 <= float(device[1]) <= 130.0
                    and 48.0 <= float(device[2]) <= 53.0
                ),
                "actual_mm": list(device),
                "parameter_source": cradle.metadata.get(
                    "engineering_parameter_sources",
                    {},
                ),
            },
            "device_fit_clearance": {
                "passed": abs(
                    cavity - (max(float(device[0]), float(device[1]))
                    + 2 * tolerance_mm)
                ) <= 0.01,
                "cavity_mm": cavity,
                "clearance_per_side_mm": (
                    cavity - max(float(device[0]), float(device[1]))
                ) / 2,
            },
            "flat_stable_desk_base": {
                "passed": (
                    abs(
                        chassis_contact_plane
                        - cover_contact_plane
                    )
                    <= 0.01
                    and min(placed_min_z.values()) >= -0.02
                    and floor_contact_area >= 5000.0
                    and float(chassis.solid().BoundingBox().xlen) >= 128.0
                    and float(chassis.solid().BoundingBox().ylen) >= 128.0
                    and bool(cover.metadata["flush_to_chassis_bottom"])
                ),
                "contact_plane_z_mm": round(
                    chassis_contact_plane,
                    4,
                ),
                "controller_cover_plane_z_mm": round(
                    cover_contact_plane,
                    4,
                ),
                "coplanarity_error_mm": round(
                    abs(
                        chassis_contact_plane
                        - cover_contact_plane
                    ),
                    6,
                ),
                "total_planar_contact_area_mm2": round(
                    floor_contact_area,
                    1,
                ),
                "perimeter_ring_contact_area_mm2": round(
                    chassis_contact_area,
                    1,
                ),
                "service_cover_contact_area_mm2": round(
                    cover_contact_area,
                    1,
                ),
                "support_span_mm": [
                    round(float(chassis.solid().BoundingBox().xlen), 1),
                    round(float(chassis.solid().BoundingBox().ylen), 1),
                ],
                "placed_minimum_z_mm": {
                    name: round(value, 4)
                    for name, value in placed_min_z.items()
                },
                "strategy": chassis.metadata["desk_contact"]["strategy"],
            },
            "replaceable_desk_isolation_feet": {
                "passed": (
                    len(desk_pad_references) == 4
                    and len(placed_desk_pads) == 4
                    and desk_pad_nominal_chassis_overlap <= 0.01
                    and min(desk_pad_preload_coverage_ratios) >= 0.95
                    and max(desk_pad_preload_cover_overlaps) <= 0.01
                    and desk_pad_top_alignment_error <= 0.01
                    and desk_pad_contact_plane_error <= 0.01
                    and min(desk_pad_airway_clearances) >= 3.0
                    and desk_pad_footprint_overrun <= 0.01
                    and desk_pad_contact_area >= 110.0
                    and plunger_to_desk_clearance >= 2.0
                    and bool(
                        desk_pad_interface[
                            "printed_base_remains_planar"
                        ]
                    )
                    and not bool(
                        desk_pad_interface["support_required"]
                    )
                    and float(
                        desk_pad_interface[
                            "lateral_footprint_extension_mm"
                        ]
                    )
                    == 0.0
                    and bool(
                        desk_load_island[
                            "modeled_as_chassis_geometry"
                        ]
                    )
                    and bool(
                        desk_load_island["single_solid_after_union"]
                    )
                    and float(
                        desk_load_island[
                            "existing_chassis_overlap_mm3"
                        ]
                    )
                    >= 15.0
                    and float(
                        desk_load_island["added_chassis_volume_mm3"]
                    )
                    >= 85.0
                    and desk_load_island_cover_overlap <= 0.01
                    and desk_load_island_pad_containment_margin
                    >= tolerance_mm
                    and float(
                        cover.metadata[
                            "fixed_corner_load_island_clearance"
                        ]["radial_clearance_mm"]
                    )
                    == tolerance_mm
                    and float(
                        cover.metadata[
                            "fixed_corner_load_island_clearance"
                        ]["removed_cover_volume_mm3"]
                    )
                    <= 0.01
                    and not bool(
                        cover.metadata[
                            "fixed_corner_load_island_clearance"
                        ]["support_required"]
                    )
                ),
                "reference_count": len(desk_pad_references),
                "pad_dimensions_mm": [
                    desk_pad_diameter,
                    desk_pad_diameter,
                    float(
                        desk_pad_interface[
                            "installed_pad_thickness_mm"
                        ]
                    ),
                ],
                "positions_mm": [
                    list(position)
                    for position in desk_pad_interface["positions_mm"]
                ],
                "nominal_pad_chassis_overlap_mm3": round(
                    desk_pad_nominal_chassis_overlap,
                    6,
                ),
                "preload_test_travel_mm": 0.1,
                "preload_contact_volumes_mm3": [
                    round(value, 6)
                    for value in desk_pad_preload_volumes
                ],
                "preload_contact_coverage_ratios": [
                    round(value, 4)
                    for value in desk_pad_preload_coverage_ratios
                ],
                "minimum_preload_contact_coverage_ratio": round(
                    min(desk_pad_preload_coverage_ratios),
                    4,
                ),
                "minimum_required_contact_coverage_ratio": 0.95,
                "preload_pad_cover_overlaps_mm3": [
                    round(value, 6)
                    for value in desk_pad_preload_cover_overlaps
                ],
                "pad_top_alignment_error_mm": round(
                    desk_pad_top_alignment_error,
                    6,
                ),
                "desk_contact_coplanarity_error_mm": round(
                    desk_pad_contact_plane_error,
                    6,
                ),
                "installed_underbody_gap_mm": float(
                    desk_pad_interface[
                        "installed_pad_thickness_mm"
                    ]
                ),
                "minimum_airway_radial_clearance_mm": round(
                    min(desk_pad_airway_clearances),
                    3,
                ),
                "lateral_footprint_overrun_mm": round(
                    max(0.0, desk_pad_footprint_overrun),
                    6,
                ),
                "total_desk_contact_area_mm2": round(
                    desk_pad_contact_area,
                    2,
                ),
                "power_plunger_to_desk_clearance_mm": round(
                    plunger_to_desk_clearance,
                    3,
                ),
                "printed_base_remains_planar": bool(
                    desk_pad_interface["printed_base_remains_planar"]
                ),
                "support_required": bool(
                    desk_pad_interface["support_required"]
                ),
                "attachment": desk_pad_interface["attachment"],
                "fixed_corner_load_island": {
                    **desk_load_island,
                    "pad_center_error_mm": round(
                        desk_load_island_pad_center_error,
                        6,
                    ),
                    "pad_containment_margin_mm": round(
                        desk_load_island_pad_containment_margin,
                        6,
                    ),
                    "cover_overlap_mm3": round(
                        desk_load_island_cover_overlap,
                        6,
                    ),
                    "cover_clearance": cover.metadata[
                        "fixed_corner_load_island_clearance"
                    ],
                },
                "validation_method": (
                    "exact OpenCascade nominal face contact, 0.10 mm "
                    "compression coverage against the fixed chassis only, "
                    "zero cover loading, integral corner-island union, "
                    "coplanar desk plane, airway clearance, footprint and "
                    "power-plunger clearance"
                ),
            },
            "bottom_airflow_keepout": {
                "passed": (
                    airflow_opening >= 114.5
                    and cradle.metadata["annular_cradle"][
                        "central_opening_shape"
                    ]
                    == "circular"
                    and float(cradle.metadata["airflow_open_area_mm2"])
                    >= 10_200.0
                ),
                "opening_shape": "circular",
                "opening_diameter_mm": airflow_opening,
                "opening_area_mm2": round(
                    float(cradle.metadata["airflow_open_area_mm2"]),
                    1,
                ),
                "reference_3mf_measured_opening_mm": (
                    cradle.metadata["annular_cradle"][
                        "reference_3mf_measured_opening_mm"
                    ]
                ),
            },
            "fan_fit_clearance": {
                "passed": fan_cavity >= 120.5,
                "cavity_mm": fan_cavity,
            },
            "standard_fan_mount_and_isolation": {
                "passed": (
                    tuple(
                        float(value)
                        for value in chassis.metadata["fan_mount_interface"][
                            "spacing_mm"
                        ]
                    )
                    == (
                        float(
                            chassis.metadata["engineering_parameters"][
                                "fan_mount_spacing_mm"
                            ]
                        ),
                    ) * 2
                    and 4.0
                    <= float(
                        chassis.metadata["fan_mount_interface"][
                            "hole_diameter_mm"
                        ]
                    )
                    <= 5.2
                    and len(
                        chassis.metadata["fan_mount_interface"][
                            "positions_mm"
                        ]
                    )
                    == 4
                    and float(
                        chassis.metadata["fan_mount_interface"][
                            "isolator_pocket_depth_mm"
                        ]
                    )
                    >= 0.8
                    and int(
                        guard.metadata["isolator_interface"]["pocket_count"]
                    )
                    == 4
                    and bool(
                        guard.metadata["isolator_interface"][
                            "modeled_as_geometry"
                        ]
                    )
                    and int(
                        chassis.metadata["fan_retention"]["clip_count"]
                    )
                    == 4
                    and bool(
                        chassis.metadata["fan_retention"]["fastener_free"]
                    )
                    and bool(
                        chassis.metadata["fan_retention"][
                            "modeled_as_geometry"
                        ]
                    )
                ),
                **chassis.metadata["fan_mount_interface"],
                "isolator_geometry": guard.metadata["isolator_interface"],
                "fan_retention": chassis.metadata["fan_retention"],
            },
            "releasable_fan_cantilever_retention": {
                "passed": (
                    int(
                        chassis.metadata["fan_retention"]["clip_count"]
                    )
                    == 4
                    and bool(
                        chassis.metadata["fan_retention"][
                            "modeled_as_geometry"
                        ]
                    )
                    and float(
                        chassis.metadata["fan_retention"]["wall_relief_mm"]
                    )
                    >= float(
                        chassis.metadata["fan_retention"][
                            "required_deflection_mm"
                        ]
                    )
                    and float(
                        chassis.metadata["fan_retention"][
                            "nominal_surface_strain"
                        ]
                    )
                    <= float(
                        chassis.metadata["fan_retention"][
                            "recommended_petg_strain_limit"
                        ]
                    )
                    and float(
                        chassis.metadata["fan_retention"][
                            "hook_overlap_mm"
                        ]
                    )
                    >= 0.2
                    and float(
                        chassis.metadata["fan_retention"][
                            "fan_top_clearance_mm"
                        ]
                    )
                    >= 0.25
                    and float(
                        chassis.metadata["fan_retention"][
                            "lead_in_angle_deg"
                        ]
                    )
                    == 45.0
                    and int(
                        chassis.metadata["fan_retention"][
                            "anchor_gusset_count"
                        ]
                    )
                    == 4
                    and float(
                        chassis.metadata["fan_retention"][
                            "anchor_gusset_angle_deg"
                        ]
                    )
                    == 45.0
                    and fan_chassis_overlap <= 0.01
                ),
                **chassis.metadata["fan_retention"],
                "fan_chassis_overlap_mm3": round(
                    fan_chassis_overlap,
                    6,
                ),
                "validation_method": (
                    "exact OpenCascade solid intersection at installed "
                    "fan reference placement plus cantilever strain gate"
                ),
            },
            "controlled_fan_vibration_isolation": {
                "passed": (
                    len(isolator_references) == 4
                    and float(
                        guard.metadata["isolator_interface"][
                            "compression_ratio"
                        ]
                    )
                    >= 0.10
                    and float(
                        guard.metadata["isolator_interface"][
                            "compression_ratio"
                        ]
                    )
                    <= 0.20
                    and float(
                        guard.metadata["isolator_interface"][
                            "installed_protrusion_above_guard_mm"
                        ]
                    )
                    >= 0.4
                    and fan_guard_hard_gap >= 0.4
                    and fan_guard_overlap <= 0.01
                    and fan_chassis_overlap <= 0.01
                    and isolator_fan_overlap <= 0.01
                    and isolator_guard_overlap <= 0.01
                    and isolator_chassis_overlap <= 0.01
                    and isolator_top_alignment_error <= 0.01
                    and isolator_base_alignment_error <= 0.01
                    and isolator_contact_area >= 200.0
                ),
                **guard.metadata["isolator_interface"],
                "reference_part_count": len(isolator_references),
                "reference_parts": [
                    part.name for part in isolator_references
                ],
                "rigid_guard_to_fan_gap_mm": round(
                    fan_guard_hard_gap,
                    6,
                ),
                "fan_guard_overlap_mm3": round(
                    fan_guard_overlap,
                    6,
                ),
                "fan_chassis_overlap_mm3": round(
                    fan_chassis_overlap,
                    6,
                ),
                "isolator_fan_overlap_mm3": round(
                    isolator_fan_overlap,
                    6,
                ),
                "isolator_guard_overlap_mm3": round(
                    isolator_guard_overlap,
                    6,
                ),
                "isolator_chassis_overlap_mm3": round(
                    isolator_chassis_overlap,
                    6,
                ),
                "isolator_top_alignment_error_mm": round(
                    isolator_top_alignment_error,
                    6,
                ),
                "isolator_pocket_base_alignment_error_mm": round(
                    isolator_base_alignment_error,
                    6,
                ),
                "total_elastomer_contact_area_mm2": round(
                    isolator_contact_area,
                    3,
                ),
                "service_method": (
                    "remove cradle and fan, then lift each replaceable "
                    "silicone washer from its open molded pocket"
                ),
                "validation_method": (
                    "exact installed OpenCascade intersections plus Z-stack "
                    "alignment and controlled compression gates"
                ),
            },
            "lateral_airflow_capacity": {
                "passed": lateral_airflow_ratio >= 0.65,
                "open_area_mm2": round(
                    float(chassis.metadata["lateral_airflow_area_mm2"]),
                    1,
                ),
                "ratio_to_fan_disk": round(lateral_airflow_ratio, 3),
            },
            "airflow_thermal_operating_point": {
                "passed": bool(
                    airflow_report and airflow_report.get("passed")
                ),
                "method": (
                    airflow_report.get("method")
                    if airflow_report
                    else "missing airflow model"
                ),
                "confidence": (
                    airflow_report.get("confidence")
                    if airflow_report
                    else "missing"
                ),
                "operating_point": (
                    airflow_report.get("operating_point", {})
                    if airflow_report
                    else {}
                ),
                "checks": (
                    airflow_report.get("checks", {})
                    if airflow_report
                    else {}
                ),
            },
            "guard_open_area": {
                "passed": guard_open_area_ratio >= 0.6,
                "open_area_ratio": round(guard_open_area_ratio, 3),
            },
            "physical_screwless_stack_interface": {
                "passed": (
                    cradle.metadata["locating_interface"]["pin_count"] == 4
                    and cradle.metadata["locating_interface"]["keyed"]
                    and abs(
                        float(
                            cradle.metadata["locating_interface"][
                                "radial_clearance_mm"
                            ]
                        )
                        - 0.25
                    )
                    <= 0.001
                    and int(
                        chassis.metadata["fan_guard_retention"][
                            "support_count"
                        ]
                    )
                    == 4
                    and bool(
                        chassis.metadata["fan_guard_retention"][
                            "fastener_free"
                        ]
                    )
                ),
                "cradle_interface": cradle.metadata["locating_interface"],
                "guard_retention": chassis.metadata[
                    "fan_guard_retention"
                ],
            },
            "serviceable_fan_guard_retention": {
                "passed": (
                    int(
                        chassis.metadata["fan_guard_retention"][
                            "support_count"
                        ]
                    )
                    == 4
                    and int(
                        chassis.metadata["fan_guard_retention"][
                            "guide_face_count"
                        ]
                    )
                    == 4
                    and int(
                        chassis.metadata["fan_guard_retention"][
                            "support_gusset_count"
                        ]
                    )
                    == 4
                    and float(
                        chassis.metadata["fan_guard_retention"][
                            "support_gusset_angle_deg"
                        ]
                    )
                    == 45.0
                    and bool(
                        chassis.metadata["fan_guard_retention"][
                            "modeled_as_geometry"
                        ]
                    )
                    and abs(
                        float(
                            chassis.metadata["fan_guard_retention"][
                                "support_top_z_mm"
                            ]
                        )
                        - guard_z_bounds[0]
                    )
                    <= 0.01
                    and guard_chassis_overlap <= 0.01
                    and guard_downward_stop_overlap >= 1.0
                    and min(guard_lateral_stop_overlaps) >= 0.001
                    and guard_service_path_overlap <= 0.01
                    and fan_upward_stop_overlap >= 0.01
                ),
                **chassis.metadata["fan_guard_retention"],
                "guard_chassis_installed_overlap_mm3": round(
                    guard_chassis_overlap,
                    6,
                ),
                "downward_test_travel_mm": 0.1,
                "downward_stop_overlap_mm3": round(
                    guard_downward_stop_overlap,
                    6,
                ),
                "lateral_test_travel_mm": 0.26,
                "lateral_stop_overlaps_mm3": [
                    round(value, 6)
                    for value in guard_lateral_stop_overlaps
                ],
                "vertical_service_path_max_overlap_mm3": round(
                    guard_service_path_overlap,
                    6,
                ),
                "fan_upward_test_travel_mm": 0.26,
                "fan_hook_stop_overlap_mm3": round(
                    fan_upward_stop_overlap,
                    6,
                ),
                "validation_method": (
                    "exact OpenCascade installed, downward, four-axis "
                    "lateral, fan-hook and vertical-removal intersections"
                ),
            },
            "releasable_cable_strain_relief": {
                "passed": (
                    int(cable_relief["arm_count"]) == 2
                    and bool(cable_relief["modeled_as_geometry"])
                    and bool(cable_relief["fastener_free"])
                    and bool(cable_relief["support_free"])
                    and float(cable_relief["relaxed_throat_mm"])
                    < cable_test_diameter
                    and float(
                        cable_relief["nominal_surface_strain"]
                    )
                    <= float(
                        cable_relief[
                            "recommended_petg_strain_limit"
                        ]
                    )
                    and cable_chassis_overlap <= 0.01
                    and cable_upward_stop_overlap >= 0.01
                    and min(cable_lateral_stop_overlaps) >= 0.001
                    and cable_relief_ds18b20_overlap <= 0.01
                    and max(
                        cable_hardware_overlaps.values(),
                        default=math.inf,
                    )
                    <= 0.01
                ),
                **cable_relief,
                "test_bundle_diameter_mm": cable_test_diameter,
                "installed_bundle_chassis_overlap_mm3": round(
                    cable_chassis_overlap,
                    6,
                ),
                "upward_retention_test_travel_mm": 1.0,
                "upward_hook_stop_overlap_mm3": round(
                    cable_upward_stop_overlap,
                    6,
                ),
                "lateral_test_travel_mm": 0.21,
                "lateral_arm_stop_overlaps_mm3": [
                    round(value, 6)
                    for value in cable_lateral_stop_overlaps
                ],
                "ds18b20_reference_overlap_mm3": round(
                    cable_relief_ds18b20_overlap,
                    6,
                ),
                "cable_internal_hardware_overlaps_mm3": {
                    name: round(value, 6)
                    for name, value in cable_hardware_overlaps.items()
                },
                "validation_method": (
                    "exact OpenCascade bundle fit, hook stop, two-arm "
                    "lateral stops, carrier fit and all installed PCB/probe "
                    "keep-out intersections"
                ),
            },
            "assembly_interference": interference,
            "internal_hardware_layout": {
                "passed": len(hardware_references) == 6
                and all(electronics_fit),
                "references": [
                    item["name"] for item in hardware_references
                ],
                "controller_components_fit": all(electronics_fit),
            },
            "hardware_bom_consistency": {
                "passed": bool(bom_report and bom_report.get("passed")),
                "active_hardware_count": (
                    bom_report.get("active_hardware_count", 0)
                    if bom_report
                    else 0
                ),
                "matched_hardware_count": (
                    bom_report.get("matched_hardware_count", 0)
                    if bom_report
                    else 0
                ),
                "checks": (
                    bom_report.get("checks", {}) if bom_report else {}
                ),
                "policy": (
                    bom_report.get("policy", "") if bom_report else ""
                ),
            },
            "exportable_reference_cad": {
                "passed": (
                    reference_names == expected_reference_names
                    and all(
                        part.solid().isValid()
                        and len(part.solid().Solids()) == 1
                        for part in reference_parts
                    )
                ),
                "expected_count": len(expected_reference_names),
                "actual_count": len(reference_parts),
                "reference_parts": sorted(reference_names),
                "all_single_valid_solids": all(
                    part.solid().isValid()
                    and len(part.solid().Solids()) == 1
                    for part in reference_parts
                ),
            },
            "complete_installed_assembly_cad": {
                "passed": (
                    installed_assembly is not None
                    and len(installed_component_names)
                    == len(parts) + len(expected_reference_names)
                    and installed_component_names
                    == {
                        *(part.name for part in parts),
                        *expected_reference_names,
                    }
                    and exact_installed_envelope[0] <= 134.01
                    and exact_installed_envelope[1] <= 134.01
                    and abs(
                        exact_installed_envelope[2]
                        - (
                            fan_deck_height
                            + float(
                                cradle.metadata[
                                    "device_support_height_mm"
                                ]
                            )
                            + float(device[2])
                            + float(
                                desk_pad_interface[
                                    "installed_pad_thickness_mm"
                                ]
                            )
                        )
                    )
                    <= 0.1
                ),
                "assembly_name": (
                    installed_assembly.name
                    if installed_assembly is not None
                    else None
                ),
                "component_count": len(installed_component_names),
                "component_names": sorted(installed_component_names),
                "envelope_mm": [
                    round(float(value), 3)
                    for value in exact_installed_envelope
                ],
                "conservative_source_bounds_mm": [
                    round(float(value), 3)
                    for value in installed_envelope
                ],
                "b_spline_control_polygon_margin_mm": [
                    round(float(value), 3)
                    for value in installed_control_polygon_margin
                ],
                "includes_printed_parts": all(
                    part.name in installed_component_names
                    for part in parts
                ),
                "includes_reference_parts": (
                    expected_reference_names <= installed_component_names
                ),
                "step_file": "smart_fan_installed_assembly.step",
            },
            "exported_step_roundtrip_envelope": {
                "passed": (
                    set(step_roundtrip) == {"printable", "installed"}
                    and bool(step_roundtrip["printable"]["valid"])
                    and bool(step_roundtrip["installed"]["valid"])
                    and step_roundtrip["printable"]["solid_count"] == 5
                    and step_roundtrip["installed"]["solid_count"]
                    == len(parts) + len(expected_reference_names)
                    and max(
                        step_roundtrip["printable"]["envelope_mm"][:2]
                    )
                    <= 134.01
                    and max(
                        step_roundtrip["installed"]["envelope_mm"][:2]
                    )
                    <= 134.01
                    and all(
                        0.0 <= margin <= 0.25
                        for margin in (
                            installed_control_polygon_margin[0],
                            installed_control_polygon_margin[1],
                        )
                    )
                    and installed_control_polygon_margin[2] <= 0.02
                ),
                "footprint_limit_mm": [134.01, 134.01],
                "source_installed_envelope_mm": [
                    round(float(value), 6)
                    for value in installed_envelope
                ],
                "source_control_polygon_margin_mm": [
                    round(float(value), 6)
                    for value in installed_control_polygon_margin
                ],
                "roundtrip": step_roundtrip,
                "measurement_note": (
                    "CadQuery optimal B-Rep bounds after STEP roundtrip; "
                    "FreeCAD optimalBoundingBox() is the equivalent exact "
                    "check. FreeCAD BoundBox is conservative for rounded "
                    "B-spline control polygons."
                ),
            },
            "mac_mini_interface_reference": {
                "passed": (
                    mac_reference is not None
                    and set(
                        mac_reference.metadata.get(
                            "official_interface_inventory",
                            {},
                        )
                    )
                    == {"front", "rear", "bottom", "source"}
                ),
                "verified_inventory": (
                    mac_reference.metadata.get(
                        "official_interface_inventory",
                        {},
                    )
                    if mac_reference is not None
                    else {}
                ),
                "coordinate_accuracy": (
                    mac_reference.metadata.get(
                        "interface_marker_accuracy",
                        "missing",
                    )
                    if mac_reference is not None
                    else "missing"
                ),
            },
            "serviceable_ds18b20_probe_retention": {
                "passed": (
                    bool(probe_retention["modeled_as_geometry"])
                    and bool(probe_retention["fastener_free"])
                    and bool(probe_retention["serviceable"])
                    and int(probe_retention["bearing_count"]) == 2
                    and int(probe_retention["support_column_count"]) == 1
                    and 0.0
                    < float(
                        probe_retention[
                            "snap_interference_per_side_mm"
                        ]
                    )
                    <= 0.2
                    and float(
                        probe_retention["minimum_guard_clearance_mm"]
                    )
                    >= 0.4
                    and len(cover.solid().Solids()) == 1
                    and float(cover.solid().BoundingBox().zmax)
                    <= pod_height
                    and external_service_cover_overlap <= 0.01
                    and len(probe_radial_stop_overlaps) == 4
                    and min(
                        probe_radial_stop_overlaps[axis]
                        for axis in ("+Y", "-Y", "-Z")
                    )
                    >= 0.000001
                    and probe_radial_stop_overlaps["+Z"] <= 0.01
                    and max(probe_release_path_overlaps) >= 0.001
                    and probe_release_path_overlaps[-1] <= 0.01
                    and probe_chassis_overlap <= 0.01
                    and probe_guard_overlap <= 0.01
                    and probe_fan_overlap <= 0.01
                ),
                **probe_retention,
                "nominal_cover_overlap_mm3": round(
                    external_service_cover_overlap,
                    6,
                ),
                "radial_test_travel_mm": probe_radial_test_travel,
                "radial_stop_overlaps_mm3": {
                    axis: round(value, 6)
                    for axis, value in probe_radial_stop_overlaps.items()
                },
                "release_path_direction": "+Z",
                "release_path_increment_mm": 0.5,
                "release_path_distance_mm": 10.0,
                "release_path_max_overlap_mm3": round(
                    max(probe_release_path_overlaps),
                    6,
                ),
                "release_path_final_overlap_mm3": round(
                    probe_release_path_overlaps[-1],
                    6,
                ),
                "chassis_overlap_mm3": round(
                    probe_chassis_overlap,
                    6,
                ),
                "guard_overlap_mm3": round(probe_guard_overlap, 6),
                "fan_overlap_mm3": round(probe_fan_overlap, 6),
                "validation_method": (
                    "exact OpenCascade nominal fit, four-axis radial stop, "
                    "open-top snap-release path and chassis/fan/guard "
                    "intersections"
                ),
            },
            "physical_component_retention": {
                "passed": (
                    int(
                        cover.metadata["component_retention"][
                            "lower_dc_dc_standoff_count"
                        ]
                    )
                    == 8
                    and int(
                        cover.metadata["component_retention"][
                            "upper_side_rail_count"
                        ]
                    )
                    == 2
                    and float(
                        cover.metadata["component_retention"][
                            "maximum_ledge_cantilever_mm"
                        ]
                    )
                    <= 1.5
                    and len(retained_reference_parts) == 4
                    and all(
                        value <= 0.01
                        for value in retained_installed_overlaps.values()
                    )
                    and all(
                        value >= 0.001
                        for value in retained_upward_stop_overlaps.values()
                    )
                    and all(
                        min(values) >= 0.001
                        for values in retained_lateral_stop_overlaps.values()
                    )
                    and int(
                        component_retention["dc_dc_retention"][
                            "cantilever_arm_count"
                        ]
                    )
                    == 4
                    and float(
                        component_retention["dc_dc_retention"][
                            "nominal_surface_strain"
                        ]
                    )
                    <= float(
                        component_retention["dc_dc_retention"][
                            "recommended_petg_strain_limit"
                        ]
                    )
                    and int(
                        component_retention["upper_board_retention"][
                            "cantilever_hook_count"
                        ]
                    )
                    == 4
                    and int(
                        component_retention["upper_board_retention"][
                            "y_guide_count"
                        ]
                    )
                    == 4
                    and external_service_cover_overlap <= 0.01
                    and len(cover.solid().Solids()) == 1
                    and float(cover.solid().BoundingBox().zmax)
                    <= pod_height
                ),
                **cover.metadata["component_retention"],
                "installed_overlap_mm3": {
                    name: round(value, 6)
                    for name, value in (
                        retained_installed_overlaps.items()
                    )
                },
                "upward_test_travel_mm": 0.26,
                "upward_stop_overlap_mm3": {
                    name: round(value, 6)
                    for name, value in (
                        retained_upward_stop_overlaps.items()
                    )
                },
                "lateral_test_travel_mm": 0.26,
                "four_axis_lateral_stop_overlaps_mm3": {
                    name: [
                        round(value, 6) for value in values
                    ]
                    for name, values in (
                        retained_lateral_stop_overlaps.items()
                    )
                },
                "external_service_cover_overlap_mm3": round(
                    external_service_cover_overlap,
                    6,
                ),
                "cover_solid_count": len(cover.solid().Solids()),
                "cover_max_z_mm": round(
                    float(cover.solid().BoundingBox().zmax),
                    3,
                ),
                "pod_height_mm": pod_height,
                "validation_method": (
                    "exact OpenCascade installed, upward and four-axis "
                    "lateral intersections for four retained PCB modules"
                ),
            },
            "serviceable_electronics_carrier": {
                "passed": (
                    electronics_service[
                        "carrier_removal_direction"
                    ]
                    == "-Z"
                    and len(
                        electronics_service[
                            "carrier_payload_components"
                        ]
                    )
                    == 4
                    and len(terminal_service_zones) == 12
                    and len(release_service_zones) == 8
                    and bool(electronics_service["fastener_free"])
                    and max(carrier_payload_path_overlaps) <= 0.01
                    and max(rigid_floor_path_overlaps) <= 0.01
                    and max(terminal_cover_obstructions) <= 0.01
                    and max(release_cover_obstructions) <= 0.01
                    and usb_cover_obstruction <= 0.01
                    and usb_chassis_obstruction <= 0.01
                    and chassis.metadata[
                        "controller_service_access"
                    ]["port_style"]
                    == "rounded self-supporting inboard service arch"
                    and float(
                        chassis.metadata[
                            "controller_service_access"
                        ]["port_minimum_roof_slope_deg"]
                    )
                    >= 45.0
                    and float(
                        chassis.metadata[
                            "controller_service_access"
                        ]["port_effective_bridge_mm"]
                    )
                    <= 5.2
                    and float(
                        chassis.metadata[
                            "controller_service_access"
                        ]["port_open_area_mm2"]
                    )
                    >= 185.0
                    and float(
                        chassis.metadata[
                            "controller_service_access"
                        ]["residual_after_cut_mm3"]
                    )
                    <= 0.01
                    and float(
                        cover.metadata["snap_fit"][
                            "nominal_surface_strain"
                        ]
                    )
                    <= float(
                        cover.metadata["snap_fit"][
                            "recommended_petg_strain_limit"
                        ]
                    )
                ),
                **electronics_service,
                "terminal_tool_zone_count": len(
                    terminal_service_zones
                ),
                "release_tool_zone_count": len(
                    release_service_zones
                ),
                "maximum_terminal_zone_cover_obstruction_mm3": round(
                    max(terminal_cover_obstructions),
                    6,
                ),
                "maximum_release_zone_cover_obstruction_mm3": round(
                    max(release_cover_obstructions),
                    6,
                ),
                "usb_corridor_cover_obstruction_mm3": round(
                    usb_cover_obstruction,
                    6,
                ),
                "usb_corridor_chassis_obstruction_mm3": round(
                    usb_chassis_obstruction,
                    6,
                ),
                "controller_service_access": chassis.metadata[
                    "controller_service_access"
                ],
                "carrier_payload_path_max_overlap_mm3": round(
                    max(carrier_payload_path_overlaps),
                    6,
                ),
                "rigid_floor_path_max_overlap_mm3": round(
                    max(rigid_floor_path_overlaps),
                    6,
                ),
                "snap_release": cover.metadata["snap_fit"],
                "validation_method": (
                    "exact OpenCascade USB corridor, terminal and release "
                    "tool zones plus populated-carrier and rigid-floor "
                    "downward service-path intersections"
                ),
            },
            "integrated_stack_compaction": {
                "passed": (
                    int(
                        chassis.metadata["controller_tower_stack"]["levels"]
                    )
                    == 2
                    and float(
                        chassis.metadata["controller_tower_stack"][
                            "lateral_extension_from_cradle_mm"
                        ]
                    )
                    == 0.0
                    and assembly_lateral_extension <= 0.01
                    and pod_length * pod_width <= 3500.0
                    and float(
                        chassis.metadata[
                            "controller_pod_minimum_wall_mm"
                        ]
                    )
                    >= 2.2
                ),
                "stack_levels": chassis.metadata["controller_tower_stack"][
                    "levels"
                ],
                "tower_footprint_mm": [pod_length, pod_width],
                "tower_footprint_mm2": pod_length * pod_width,
                "lateral_extension_from_cradle_mm": round(
                    assembly_lateral_extension,
                    4,
                ),
                "controller_pod_lateral_extension_mm": chassis.metadata[
                    "controller_tower_stack"
                ]["lateral_extension_from_cradle_mm"],
                "controller_pod_minimum_wall_mm": chassis.metadata[
                    "controller_pod_minimum_wall_mm"
                ],
                "assembly_planar_envelope_mm": [
                    round(value, 3)
                    for value in exact_printable_envelope[:2]
                ],
                "conservative_source_planar_envelope_mm": [
                    round(value, 3)
                    for value in assembly_planar_envelope
                ],
                "policy": chassis.metadata["design_priority"],
            },
            "structural_stability": {
                "passed": (
                    bool(
                        cradle.metadata["exterior_continuity"][
                            "continuous_annular_cradle"
                        ]
                    )
                    and float(
                        cradle.metadata["annular_cradle"][
                            "central_opening_diameter_mm"
                        ]
                    )
                    <= 115.0
                    and pod_height / pod_length <= 0.55
                    and float(
                        chassis.metadata["controller_tower_stack"][
                            "lateral_extension_from_cradle_mm"
                        ]
                    )
                    == 0.0
                    and bool(
                        structure_report
                        and structure_report.get("passed")
                    )
                ),
                "tower_height_to_length_ratio": round(
                    pod_height / pod_length,
                    3,
                ),
                "electronics_cassette_location": "below fan, inside footprint",
                "mac_support_strategy": "continuous annular shelf",
                "whole_assembly_load_path": (
                    structure_report.get("load_path", {})
                    if structure_report
                    else {}
                ),
                "whole_assembly_checks": (
                    structure_report.get("checks", {})
                    if structure_report
                    else {}
                ),
            },
            "controller_cover_ventilation": {
                "passed": (
                    float(cover.metadata["vent_open_area_mm2"]) >= 300.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "top_edge_radius_mm"
                        ]
                    )
                    >= 1.5
                    and int(
                        chassis.metadata["controller_vent_pattern"][
                            "internal_elliptical_port_count"
                        ]
                    )
                    == 0
                    and int(
                        chassis.metadata["controller_vent_pattern"][
                            "internal_self_supporting_arch_count"
                        ]
                    )
                    == 2
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "internal_open_area_mm2"
                        ]
                    )
                    >= 1500.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "visible_wall_open_ratio"
                        ]
                    )
                    >= 0.45
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "minimum_continuous_web_mm"
                        ]
                    )
                    >= 3.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "maximum_closing_bridge_mm"
                        ]
                    )
                    <= 12.0
                    and int(
                        chassis.metadata["controller_vent_pattern"][
                            "external_slot_count"
                        ]
                    )
                    == 0
                    and int(
                        chassis.metadata["controller_vent_pattern"][
                            "external_elliptical_port_count"
                        ]
                    )
                    == 0
                    and int(
                        chassis.metadata["controller_vent_pattern"][
                            "external_self_supporting_arch_count"
                        ]
                    )
                    == 3
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "external_open_area_mm2"
                        ]
                    )
                    >= 1200.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "external_visible_wall_open_ratio"
                        ]
                    )
                    >= 0.35
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "external_minimum_continuous_web_mm"
                        ]
                    )
                    >= 3.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "external_maximum_closing_bridge_mm"
                        ]
                    )
                    <= 12.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "internal_minimum_roof_slope_deg"
                        ]
                    )
                    >= 40.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "external_arch_minimum_roof_slope_deg"
                        ]
                    )
                    >= 38.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "boolean_validation"
                        ]["residual_intersection_volume_mm3"]
                    )
                    <= 0.01
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "boolean_validation"
                        ][
                            "functional_feature_volume_in_openings_mm3"
                        ]
                    )
                    <= 40.0
                ),
                "open_area_mm2": round(
                    float(cover.metadata["vent_open_area_mm2"]),
                    1,
                ),
                **chassis.metadata["controller_vent_pattern"],
            },
            "controller_cover_real_snap_fit": {
                "passed": (
                    int(cover.metadata["snap_fit"]["tab_count"]) == 2
                    and int(
                        cover.metadata["snap_fit"]["paired_slot_count"]
                    )
                    == 2
                    and float(
                        cover.metadata["snap_fit"][
                            "nominal_surface_strain"
                        ]
                    )
                    <= float(
                        cover.metadata["snap_fit"][
                            "recommended_petg_strain_limit"
                        ]
                    )
                    and int(
                        chassis.metadata["controller_cover_snap_slots"][
                            "count"
                        ]
                    )
                    == 2
                ),
                **cover.metadata["snap_fit"],
                "chassis_slots": (
                    chassis.metadata["controller_cover_snap_slots"]
                ),
            },
            "front_rear_port_access": {
                "passed": (
                    cradle.metadata["port_access"]
                    == "front and rear fully open"
                    and front_obstruction_volume <= 0.01
                    and rear_obstruction_volume <= 0.01
                    and individual_interface_access_passed
                    and float(
                        cradle.metadata["port_keepout"][
                            "open_face_width_mm"
                        ]
                    )
                    >= max(float(device[0]), float(device[1]))
                    + 2 * tolerance_mm
                ),
                "strategy": cradle.metadata["port_access"],
                "front_obstruction_volume_mm3": round(
                    front_obstruction_volume,
                    6,
                ),
                "rear_obstruction_volume_mm3": round(
                    rear_obstruction_volume,
                    6,
                ),
                **cradle.metadata["port_keepout"],
            },
            "individual_mac_interface_service_corridors": {
                "passed": individual_interface_access_passed,
                "corridor_count": len(mac_interface_corridor_results),
                "front_corridor_count": sum(
                    item["face"] == "front"
                    for item in mac_interface_corridor_results
                ),
                "rear_corridor_count": sum(
                    item["face"] == "rear"
                    for item in mac_interface_corridor_results
                ),
                "maximum_obstruction_volume_mm3": round(
                    max(
                        (
                            item["total_obstruction_mm3"]
                            for item in mac_interface_corridor_results
                        ),
                        default=math.inf,
                    ),
                    6,
                ),
                "corridors": mac_interface_corridor_results,
                "rear_service_relief": rear_service_relief,
                "validation_method": (
                    "OpenCascade intersection of nine conservative mating-"
                    "plug corridors against every installed printed part"
                ),
                "coordinate_accuracy": (
                    mac_reference.metadata["interface_marker_accuracy"]
                    if mac_reference is not None
                    else "missing reference"
                ),
            },
            "power_button_access": {
                "passed": (
                    not bool(
                        cradle.metadata["power_button_access"][
                            "installed_edge_notch"
                        ]
                    )
                    and float(
                        cradle.metadata["power_button_access"][
                            "minimum_vertical_release_mm"
                        ]
                    )
                    >= 5.0
                    and bool(
                        cradle.metadata["exterior_continuity"][
                            "closed_outer_ring"
                        ]
                    )
                    and int(
                        cradle.metadata["exterior_continuity"][
                            "outer_edge_notch_count"
                        ]
                    )
                    == 0
                    and bool(
                        cradle.metadata["power_button_access"][
                            "modeled_as_geometry"
                        ]
                    )
                    and button_access_diameter >= 10.0
                    and button_shaft_obstruction_volume <= 0.01
                    and button_head_obstruction_volume <= 0.01
                    and button_alignment_error <= 0.01
                    and plunger.solid().isValid()
                    and len(plunger.solid().Solids()) == 1
                    and float(plunger.metadata["shaft_diameter_mm"])
                    + 2 * tolerance_mm
                    <= button_shaft_bore_diameter
                    and float(plunger.metadata["assembled_bottom_recess_mm"])
                    >= 1.0
                    and float(plunger.metadata["assembled_top_gap_mm"])
                    == 0.25
                    and plunger_head_alignment_error <= 0.01
                    and shaft_fan_mount_alignment_error <= 0.01
                    and shaft_radial_clearance >= tolerance_mm
                    and plunger_fan_overlap <= 0.01
                    and plunger_guard_overlap <= 0.01
                    and plunger_mac_overlap <= 0.01
                    and abs(plunger_top_gap - 0.25) <= 0.01
                    and float(
                        plunger.metadata["available_upward_travel_mm"]
                    )
                    >= 2.0
                    and float(plunger.metadata["buckling_safety_factor"])
                    >= 5.0
                ),
                "shaft_obstruction_volume_mm3": round(
                    button_shaft_obstruction_volume,
                    6,
                ),
                "head_obstruction_volume_mm3": round(
                    button_head_obstruction_volume,
                    6,
                ),
                "reference_alignment_error_mm": round(
                    button_alignment_error,
                    6,
                ),
                "installed_path_validation": {
                    "head_alignment_error_mm": round(
                        plunger_head_alignment_error,
                        6,
                    ),
                    "shaft_fan_mount_alignment_error_mm": round(
                        shaft_fan_mount_alignment_error,
                        6,
                    ),
                    "shaft_radial_clearance_mm": round(
                        shaft_radial_clearance,
                        3,
                    ),
                    "fan_overlap_mm3": round(plunger_fan_overlap, 6),
                    "guard_overlap_mm3": round(
                        plunger_guard_overlap,
                        6,
                    ),
                    "mac_overlap_mm3": round(plunger_mac_overlap, 6),
                    "resting_top_gap_mm": round(plunger_top_gap, 3),
                    "available_upward_travel_mm": plunger.metadata[
                        "available_upward_travel_mm"
                    ],
                    "buckling_safety_factor": plunger.metadata[
                        "buckling_safety_factor"
                    ],
                },
                "plunger": {
                    "part": plunger.name,
                    "shaft_diameter_mm": plunger.metadata[
                        "shaft_diameter_mm"
                    ],
                    "head_diameter_mm": plunger.metadata[
                        "head_diameter_mm"
                    ],
                    "bottom_recess_mm": plunger.metadata[
                        "assembled_bottom_recess_mm"
                    ],
                    "top_gap_mm": plunger.metadata[
                        "assembled_top_gap_mm"
                    ],
                    "fan_mount_bore_diameter_mm": plunger.metadata[
                        "fan_mount_bore_diameter_mm"
                    ],
                    "shaft_center_mm": plunger.metadata[
                        "shaft_center_mm"
                    ],
                    "head_center_mm": plunger.metadata[
                        "head_center_mm"
                    ],
                    "head_center_offset_mm": plunger.metadata[
                        "head_center_offset_mm"
                    ],
                    "operation": cradle.metadata["power_button_access"][
                        "operation"
                    ],
                },
                **cradle.metadata["power_button_access"],
            },
            "uncertainty_tolerant_power_button_contact": {
                "passed": (
                    bool(
                        plunger.metadata["uncertainty_tolerant_contact"][
                            "modeled_from_actual_end_face"
                        ]
                    )
                    and int(
                        plunger.metadata["uncertainty_tolerant_contact"][
                            "angular_sample_count"
                        ]
                    )
                    == 16
                    and float(
                        plunger.metadata["uncertainty_tolerant_contact"][
                            "coordinate_uncertainty_mm"
                        ]
                    )
                    >= 2.0
                    and float(
                        plunger.metadata["uncertainty_tolerant_contact"][
                            "minimum_full_button_coverage_ratio"
                        ]
                    )
                    >= 0.93
                    and float(
                        plunger.metadata["uncertainty_tolerant_contact"][
                            "minimum_actuation_core_coverage_ratio"
                        ]
                    )
                    >= 0.999
                    and float(
                        plunger.metadata["uncertainty_tolerant_contact"][
                            "head_bore_radial_clearance_mm"
                        ]
                    )
                    >= tolerance_mm
                    and bool(
                        plunger.metadata["uncertainty_tolerant_contact"][
                            "print_flat_included_in_measurement"
                        ]
                    )
                ),
                **plunger.metadata["uncertainty_tolerant_contact"],
            },
            "rear_access_power_button_operation": {
                "passed": (
                    bool(finger_lift["modeled_as_geometry"])
                    and bool(finger_lift["integrated_single_piece"])
                    and "rear-left air portal"
                    in str(finger_lift["input_method"])
                    and int(finger_lift["additional_exterior_openings"]) == 0
                    and float(
                        finger_lift["lateral_footprint_extension_mm"]
                    )
                    <= 0.0
                    and finger_corridor_width >= 15.0
                    and finger_corridor_obstruction_volume <= 0.01
                    and resting_paddle_chassis_overlap <= 0.01
                    and actuated_paddle_chassis_overlap <= 0.01
                    and actuated_paddle_guard_overlap <= 0.01
                    and actuated_paddle_fan_overlap <= 0.01
                    and finger_lift_travel
                    <= float(plunger.metadata["available_upward_travel_mm"])
                    and float(finger_lift["mechanical_motion_ratio"]) == 1.0
                    and finger_lift["arm_profile"]
                    == "constant-width rounded capsule"
                    and float(finger_lift["arm_thickness_mm"]) >= 4.0
                    and float(finger_lift["arm_end_radius_mm"]) >= 2.5
                    and bool(finger_lift["shares_shaft_build_plane"])
                    and abs(
                        float(finger_lift["root_print_flat_z_mm"]) + 1.6
                    )
                    <= 0.01
                    and float(
                        finger_lift["conservative_bending_stress_mpa"]
                    )
                    <= 6.0
                    and float(
                        finger_lift["conservative_tip_deflection_mm"]
                    )
                    <= 0.6
                    and float(
                        finger_lift["conservative_yield_safety_factor"]
                    )
                    >= 5.0
                    and float(placed_plunger.BoundingBox().zmin) >= 0.99
                ),
                "finger_corridor_obstruction_volume_mm3": round(
                    finger_corridor_obstruction_volume,
                    6,
                ),
                "resting_chassis_overlap_mm3": round(
                    resting_paddle_chassis_overlap,
                    6,
                ),
                "actuated_chassis_overlap_mm3": round(
                    actuated_paddle_chassis_overlap,
                    6,
                ),
                "actuated_guard_overlap_mm3": round(
                    actuated_paddle_guard_overlap,
                    6,
                ),
                "actuated_fan_overlap_mm3": round(
                    actuated_paddle_fan_overlap,
                    6,
                ),
                "resting_minimum_z_mm": round(
                    float(placed_plunger.BoundingBox().zmin),
                    2,
                ),
                "available_upward_travel_mm": plunger.metadata[
                    "available_upward_travel_mm"
                ],
                **finger_lift,
            },
            "cradle_integrated_outer_contour": {
                "passed": (
                    bool(
                        cradle.metadata["exterior_continuity"][
                            "closed_outer_ring"
                        ]
                    )
                    and int(
                        cradle.metadata["exterior_continuity"][
                            "outer_edge_notch_count"
                        ]
                    )
                    == 0
                    and bool(
                        cradle.metadata["exterior_continuity"][
                            "service_access_without_edge_cut"
                        ]
                    )
                    and bool(
                        cradle.metadata["exterior_continuity"][
                            "through_locating_sockets"
                        ]
                    )
                    and not bool(
                        cradle.metadata["exterior_continuity"][
                            "locating_sockets_break_outer_edge"
                        ]
                    )
                    and bool(
                        cradle.metadata["locating_interface"][
                            "integrated_into_continuous_ring"
                        ]
                    )
                    and int(
                        cradle.metadata["exterior_continuity"][
                            "continuous_side_rail_count"
                        ]
                    )
                    == 0
                    and bool(
                        cradle.metadata["exterior_continuity"][
                            "continuous_annular_cradle"
                        ]
                    )
                    and float(
                        cradle.metadata["annular_cradle"][
                            "single_side_clearance_mm"
                        ]
                    )
                    == 0.25
                ),
                **cradle.metadata["annular_cradle"],
                **cradle.metadata["exterior_continuity"],
            },
            "underbody_air_gap": {
                "passed": (
                    float(cradle.metadata["underbody_air_gap_mm"]) >= 2.0
                    and int(cradle.metadata["support_pad_count"]) == 4
                    and cradle.metadata["annular_cradle"][
                        "central_opening_shape"
                    ]
                    == "circular"
                ),
                "gap_mm": cradle.metadata["underbody_air_gap_mm"],
                "support_pad_count": cradle.metadata["support_pad_count"],
                "surface_interface": cradle.metadata["surface_interface"],
            },
            "modeled_silicone_contact_interface": {
                "passed": (
                    bool(
                        cradle.metadata["support_pad_interface"][
                            "modeled_as_geometry"
                        ]
                    )
                    and int(
                        cradle.metadata["support_pad_interface"]["count"]
                    )
                    == 4
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "pad_diameter_mm"
                        ]
                    )
                    == 8.0
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "recess_depth_mm"
                        ]
                    )
                    == 0.3
                    and abs(
                        (
                            float(
                                cradle.metadata[
                                    "support_pad_interface"
                                ]["recess_diameter_mm"]
                            )
                            - float(
                                cradle.metadata[
                                    "support_pad_interface"
                                ]["pad_diameter_mm"]
                            )
                        )
                        / 2
                        - tolerance_mm
                    )
                    <= 0.001
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "installed_pad_thickness_mm"
                        ]
                    )
                    == 0.5
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "installed_protrusion_mm"
                        ]
                    )
                    >= 0.15
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "actual_removed_volume_mm3"
                        ]
                    )
                    >= 0.98
                    * float(
                        cradle.metadata["support_pad_interface"][
                            "expected_removed_volume_mm3"
                        ]
                    )
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "boolean_residual_volume_mm3"
                        ]
                    )
                    <= 0.01
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "minimum_airflow_edge_clearance_mm"
                        ]
                    )
                    >= 0.5
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "minimum_power_button_clearance_mm"
                        ]
                    )
                    >= 1.5
                    and float(
                        cradle.metadata["support_pad_interface"][
                            "remaining_bottom_skin_mm"
                        ]
                    )
                    >= 3.0
                ),
                **cradle.metadata["support_pad_interface"],
            },
            "proud_silicone_primary_contact": {
                "passed": (
                    len(mac_support_pad_references) == 4
                    and len(placed_mac_support_pads) == 4
                    and mac_pad_nominal_overlap <= 0.01
                    and mac_pad_preload_overlap >= 8.0
                    and mac_cradle_nominal_overlap <= 0.01
                    and mac_cradle_free_travel_overlap <= 0.01
                    and mac_cradle_hard_stop_overlap >= 0.01
                    and pad_cradle_overlap <= 0.01
                    and pad_foot_overlap <= 0.01
                    and pad_top_alignment_error <= 0.01
                    and bool(
                        mac_reference.metadata[
                            "underside_landing_surface"
                        ]["modeled_as_geometry"]
                    )
                ),
                "pad_reference_count": len(
                    mac_support_pad_references
                ),
                "nominal_pad_mac_overlap_mm3": round(
                    mac_pad_nominal_overlap,
                    6,
                ),
                "preload_test_travel_mm": 0.1,
                "preload_pad_mac_overlap_mm3": round(
                    mac_pad_preload_overlap,
                    6,
                ),
                "nominal_mac_petg_overlap_mm3": round(
                    mac_cradle_nominal_overlap,
                    6,
                ),
                "petg_free_travel_test_mm": 0.15,
                "free_travel_mac_petg_overlap_mm3": round(
                    mac_cradle_free_travel_overlap,
                    6,
                ),
                "petg_hard_stop_test_mm": 0.21,
                "hard_stop_mac_petg_overlap_mm3": round(
                    mac_cradle_hard_stop_overlap,
                    6,
                ),
                "pad_cradle_overlap_mm3": round(
                    pad_cradle_overlap,
                    6,
                ),
                "pad_mac_foot_overlap_mm3": round(
                    pad_foot_overlap,
                    6,
                ),
                "pad_top_alignment_error_mm": round(
                    pad_top_alignment_error,
                    6,
                ),
                "validation_method": (
                    "exact OpenCascade nominal, 0.10mm silicone preload, "
                    "0.15mm PETG-free travel and 0.21mm hard-stop "
                    "intersection tests"
                ),
            },
            "reference_informed_cradle_transition": {
                "passed": (
                    bool(
                        cradle.metadata["reference_informed_transition"][
                            "modeled_as_geometry"
                        ]
                    )
                    and not bool(
                        cradle.metadata["reference_informed_transition"][
                            "reference_mesh_copied"
                        ]
                    )
                    and float(
                        cradle.metadata["reference_informed_transition"][
                            "transition_radius_mm"
                        ]
                    )
                    >= 0.3
                    and float(
                        cradle.metadata["reference_informed_transition"][
                            "maximum_footprint_mismatch_mm"
                        ]
                    )
                    <= 0.1
                    and bool(
                        cradle.metadata["reference_informed_transition"][
                            "continuous_outer_transition"
                        ]
                    )
                    and bool(
                        cradle.metadata["reference_informed_transition"][
                            "planar_mating_face_retained"
                        ]
                    )
                    and bool(
                        cradle.metadata["reference_informed_transition"][
                            "support_free"
                        ]
                    )
                    and str(
                        cradle.metadata["reference_informed_transition"][
                            "outer_band_style"
                        ]
                    )
                    == (
                        "five-section convex rounded-square annular loft"
                    )
                    and len(
                        cradle.metadata["reference_informed_transition"][
                            "outer_band_profile"
                        ]
                    )
                    == 5
                    and not bool(
                        cradle.metadata["reference_informed_transition"][
                            "visible_constant_thickness_plate_edge"
                        ]
                    )
                    and "underside tangent line"
                    in str(
                        cradle.metadata["reference_informed_transition"][
                            "seam_location"
                        ]
                    )
                    and float(
                        cradle.metadata["reference_informed_transition"][
                            "maximum_band_overhang_per_side_mm"
                        ]
                    )
                    <= 0.4 + 1e-6
                    and float(
                        cradle.metadata["reference_informed_transition"][
                            "lower_slope_from_horizontal_deg"
                        ]
                    )
                    >= 60.0
                    and max(
                        float(section["size_mm"])
                        for section in cradle.metadata[
                            "reference_informed_transition"
                        ]["outer_band_profile"]
                    )
                    <= 134.0
                    and bool(
                        chassis.metadata["integrated_cradle_crown"][
                            "modeled_as_geometry"
                        ]
                    )
                    and float(
                        chassis.metadata["integrated_cradle_crown"][
                            "height_mm"
                        ]
                    )
                    >= 3.0
                    and float(
                        chassis.metadata["integrated_cradle_crown"][
                            "slope_from_horizontal_deg"
                        ]
                    )
                    >= 60.0
                    and bool(
                        chassis.metadata["integrated_cradle_crown"][
                            "wall_optimized_loft"
                        ]
                    )
                    and float(
                        chassis.metadata["integrated_cradle_crown"][
                            "bottom_side_wall_mm"
                        ]
                    )
                    >= wall
                    and float(
                        chassis.metadata["integrated_cradle_crown"][
                            "minimum_top_side_wall_mm"
                        ]
                    )
                    >= 2.0
                    and abs(
                        float(
                            chassis.metadata[
                                "integrated_cradle_crown"
                            ]["mating_footprint_mm"][0]
                        )
                        - float(
                            cradle.metadata[
                                "reference_informed_transition"
                            ]["bottom_footprint_mm"][0]
                        )
                    )
                    <= 0.01
                    and max(
                        abs(
                            float(
                                cradle.metadata[
                                    "reference_informed_transition"
                                ]["upper_shelf_footprint_mm"][index]
                            )
                            - float(
                                chassis.metadata[
                                    "integrated_cradle_crown"
                                ]["mating_footprint_mm"][index]
                            )
                        )
                        for index in range(2)
                    )
                    <= 0.01
                    and not bool(
                        chassis.metadata["integrated_cradle_crown"][
                            "support_required"
                        ]
                    )
                    and max(
                        float(value)
                        for value in chassis.metadata[
                            "integrated_cradle_crown"
                        ]["maximum_installed_footprint_mm"]
                    )
                    <= 134.0
                ),
                **cradle.metadata["reference_informed_transition"],
                "chassis_crown": chassis.metadata[
                    "integrated_cradle_crown"
                ],
            },
            "continuous_airflow_bellmouth": {
                "passed": (
                    bool(
                        cradle.metadata["airflow_bellmouth"][
                            "modeled_as_geometry"
                        ]
                    )
                    and not bool(
                        cradle.metadata["airflow_bellmouth"][
                            "sharp_lower_airflow_edge"
                        ]
                    )
                    and float(
                        cradle.metadata["airflow_bellmouth"][
                            "lower_inlet_radius_mm"
                        ]
                    )
                    >= 0.8
                    and float(
                        cradle.metadata["airflow_bellmouth"][
                            "upper_outlet_radius_mm"
                        ]
                    )
                    >= 0.6
                    and float(
                        cradle.metadata["airflow_bellmouth"][
                            "lower_inlet_diameter_mm"
                        ]
                    )
                    >= 116.8
                    and float(
                        cradle.metadata["airflow_bellmouth"][
                            "minimum_throat_diameter_mm"
                        ]
                    )
                    >= 115.0
                    and float(
                        cradle.metadata["airflow_bellmouth"][
                            "straight_throat_height_mm"
                        ]
                    )
                    >= 2.0
                    and float(
                        cradle.metadata["airflow_bellmouth"][
                            "minimum_mac_foot_radial_clearance_mm"
                        ]
                    )
                    >= 7.0
                    and cradle.metadata["airflow_bellmouth"][
                        "support_strategy"
                    ]
                    == "none"
                ),
                **cradle.metadata["airflow_bellmouth"],
            },
            "independent_service_cover": {
                "passed": cover.name == "controller_cover",
                "part": cover.name,
            },
            "low_visual_profile": {
                "passed": fan_deck_height / chassis_width <= 0.46,
                "height_to_width_ratio": round(
                    fan_deck_height / chassis_width,
                    4,
                ),
                "controller_tower_height_mm": chassis_height,
            },
            "continuous_design_language": {
                "passed": (
                    "monolithic rounded-square air plinth"
                    in str(chassis.metadata["design_language"])
                    and bool(
                        chassis.metadata["exterior_continuity"][
                            "continuous_top_rail"
                        ]
                    )
                    and not bool(
                        chassis.metadata["exterior_continuity"][
                            "openings_break_outer_edge"
                        ]
                    )
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "maximum_opening_bridge_mm"
                        ]
                    )
                    <= 20.0
                    and int(
                        chassis.metadata["exterior_continuity"][
                            "window_count"
                        ]
                    )
                    <= 6
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "top_rail_minimum_mm"
                        ]
                    )
                    >= 5.0
                    and bool(
                        chassis.metadata["exterior_continuity"][
                            "continuous_lower_skirt"
                        ]
                    )
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "lower_skirt_minimum_mm"
                        ]
                    )
                    >= 7.5
                    and int(
                        chassis.metadata["exterior_continuity"][
                            "repeated_vertical_mullion_count"
                        ]
                    )
                    == 0
                    and int(
                        chassis.metadata["exterior_continuity"][
                            "external_auxiliary_vent_slot_count"
                        ]
                    )
                    == 0
                    and int(
                        chassis.metadata["exterior_continuity"][
                            "outer_edge_break_count"
                        ]
                    )
                    == 0
                    and "one continuous-tangent rounded-crown spline air "
                    "portal per face"
                    in str(
                        chassis.metadata["exterior_continuity"][
                            "opening_style"
                        ]
                    )
                    and bool(
                        chassis.metadata["exterior_continuity"][
                            "continuous_curvature_roof"
                        ]
                    )
                    and str(
                        chassis.metadata["exterior_continuity"][
                            "roof_curve_kind"
                        ]
                    )
                    == (
                        "symmetric self-supporting spline flanks with "
                        "tangent-continuous rounded crown"
                    )
                    and bool(
                        chassis.metadata["exterior_continuity"][
                            "roof_endpoint_tangents_constrained"
                        ]
                    )
                    and bool(
                        chassis.metadata["exterior_continuity"][
                            "crown_center_tangent_horizontal"
                        ]
                    )
                    and bool(
                        chassis.metadata["exterior_continuity"][
                            "crown_flank_tangent_continuity"
                        ]
                    )
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "crown_rise_mm"
                        ]
                    )
                    >= 2.5
                    and str(
                        chassis.metadata["exterior_continuity"][
                            "crown_print_strategy"
                        ]
                    )
                    == "one-layer integral tear-away bridge membrane"
                    and int(
                        chassis.metadata["exterior_continuity"][
                            "crown_membrane_count"
                        ]
                    )
                    == 4
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "crown_membrane_thickness_mm"
                        ]
                    )
                    <= 0.2
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "crown_membrane_estimated_petg_g"
                        ]
                    )
                    <= 0.05
                    and bool(
                        chassis.metadata["exterior_continuity"][
                            "crown_membrane_operationally_removed"
                        ]
                    )
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "roof_curve_amplitude_mm"
                        ]
                    )
                    >= 0.3
                    and int(
                        chassis.metadata["exterior_continuity"][
                            "roof_sample_count_per_side"
                        ]
                    )
                    >= 6
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "roof_spring_line_z_mm"
                        ]
                    )
                    <= 24.0
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "top_edge_radius_mm"
                        ]
                    )
                    >= 1.5
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "portal_cut_margin_mm"
                        ]
                    )
                    <= 1.0
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "minimum_self_supporting_flank_slope_deg"
                        ]
                    )
                    >= 31.0
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "roof_slope_margin_deg"
                        ]
                    )
                    >= 1.0
                    and float(
                        chassis.metadata["exterior_continuity"][
                            "profile_fillet_radius_mm"
                        ]
                    )
                    >= 2.0
                    and bool(
                        cradle.metadata["exterior_continuity"][
                            "curved_landing_surfaces"
                        ]
                    )
                    and float(
                        cradle.metadata["annular_cradle"][
                            "lead_in_radius_mm"
                        ]
                    )
                    >= 0.6
                    and float(
                        cradle.metadata["annular_cradle"][
                            "support_shelf_edge_radius_mm"
                        ]
                    )
                    >= 0.6
                    and float(
                        cradle.metadata["annular_cradle"][
                            "chassis_overhang_per_side_mm"
                        ]
                    )
                    <= 1.0
                ),
                "design_language": chassis.metadata["design_language"],
                "primary_radius_mm": cradle.metadata["visual_radius_mm"],
                "cradle": {
                    **cradle.metadata["annular_cradle"],
                    "curved_landing_surfaces": cradle.metadata[
                        "exterior_continuity"
                    ]["curved_landing_surfaces"],
                },
                **chassis.metadata["exterior_continuity"],
            },
        }
        if calibration_report is not None:
            io_gauge_results = {}
            for face, expected_marker_count, expected_dot_count in (
                ("front", 3, 1),
                ("rear", 6, 2),
            ):
                gauge_name = f"mac_{face}_io_alignment_gauge"
                gauge_definition = calibration_report["parts"].get(
                    gauge_name,
                    {},
                )
                gauge_validation = calibration_report["validation"].get(
                    gauge_name,
                    {},
                )
                gauge_slice = (
                    calibration_report.get("manufacturing", {})
                    .get("parts", {})
                    .get(gauge_name)
                    if calibration_report.get("manufacturing")
                    else None
                )
                io_gauge_results[face] = {
                    "passed": (
                        bool(gauge_definition)
                        and gauge_definition.get("face") == face
                        and len(
                            gauge_definition.get(
                                "interface_markers",
                                [],
                            )
                        )
                        == expected_marker_count
                        and int(
                            gauge_definition.get(
                                "identification_dot_count",
                                0,
                            )
                        )
                        == expected_dot_count
                        and gauge_definition.get(
                            "dimensions_mm"
                        )
                        == [127.0, 18.0, 1.2]
                        and gauge_definition.get(
                            "coordinate_offsets_mm"
                        )
                        == list(
                            mac_reference.metadata[
                                "interface_coordinate_offsets_mm"
                            ][face]
                        )
                        and bool(
                            gauge_validation.get("printable")
                        )
                        and gauge_validation["geometry"][
                            "solid_count"
                        ]
                        == 1
                        and gauge_validation["geometry"]["valid"]
                        and (
                            gauge_slice is None
                            or (
                                bool(gauge_slice["printable"])
                                and not bool(
                                    gauge_slice["support_used"]
                                )
                                and float(
                                    gauge_slice[
                                        "filament_weight_g"
                                    ]
                                )
                                <= 3.0
                                and int(
                                    gauge_slice[
                                        "estimated_seconds"
                                    ]
                                )
                                <= 1500
                                and float(
                                    gauge_slice[
                                        "max_bridge_span_mm"
                                    ]
                                )
                                <= 1.0
                            )
                        )
                    ),
                    "part": gauge_definition,
                    "validation": gauge_validation,
                    "slice": gauge_slice,
                }
            checks["physical_mac_io_alignment_gauges"] = {
                "passed": (
                    bool(calibration_report["passed"])
                    and all(
                        result["passed"]
                        for result in io_gauge_results.values()
                    )
                ),
                "gauges": io_gauge_results,
                "acceptance_limits": {
                    "filament_weight_g_each": 3.0,
                    "estimated_seconds_each": 1500,
                    "max_bridge_span_mm": 1.0,
                    "support_used": False,
                    "maximum_group_center_error_mm": 0.5,
                },
                "regeneration_parameters": [
                    "front_interface_delta_x_mm",
                    "front_interface_delta_z_mm",
                    "rear_interface_delta_x_mm",
                    "rear_interface_delta_z_mm",
                ],
                "validation_method": (
                    "front/rear datum stencil geometry, OpenCascade "
                    "single-solid validation and optional OrcaSlicer "
                    "support/cost gate"
                ),
            }
            probe_coupon_name = "ds18b20_snap_fit_coupon"
            coupon_definition = calibration_report["parts"].get(
                probe_coupon_name,
                {},
            )
            coupon_validation = calibration_report["validation"].get(
                probe_coupon_name,
                {},
            )
            coupon_slice = (
                calibration_report.get("manufacturing", {})
                .get("parts", {})
                .get(probe_coupon_name)
                if calibration_report.get("manufacturing")
                else None
            )
            checks["physical_ds18b20_fit_coupon"] = {
                "passed": (
                    bool(calibration_report["passed"])
                    and bool(coupon_definition)
                    and bool(coupon_validation.get("printable"))
                    and coupon_validation["geometry"]["solid_count"] == 1
                    and coupon_validation["geometry"]["valid"]
                    and (
                        coupon_slice is None
                        or (
                            bool(coupon_slice["printable"])
                            and not bool(coupon_slice["support_used"])
                            and float(
                                coupon_slice["filament_weight_g"]
                            )
                            <= 2.0
                            and int(coupon_slice["estimated_seconds"])
                            <= 1200
                            and float(
                                coupon_slice["max_bridge_span_mm"]
                            )
                            <= 7.0
                        )
                    )
                ),
                "part": coupon_definition,
                "validation": coupon_validation,
                "slice": coupon_slice,
                "acceptance_limits": {
                    "filament_weight_g": 2.0,
                    "estimated_seconds": 1200,
                    "max_bridge_span_mm": 7.0,
                    "support_used": False,
                },
                "validation_method": (
                    "production-geometry coupon, OpenCascade single-solid "
                    "validation and optional OrcaSlicer support/cost gate"
                ),
            }
            bridge_coupon_name = "portal_bridge_support_coupon"
            bridge_coupon_definition = calibration_report["parts"].get(
                bridge_coupon_name,
                {},
            )
            bridge_coupon_validation = calibration_report[
                "validation"
            ].get(
                bridge_coupon_name,
                {},
            )
            bridge_coupon_slice = (
                calibration_report.get("manufacturing", {})
                .get("parts", {})
                .get(bridge_coupon_name)
                if calibration_report.get("manufacturing")
                else None
            )
            bridge_coupon_features = bridge_coupon_definition.get(
                "features",
                {},
            )
            bridge_coupon_acceptance = bridge_coupon_definition.get(
                "acceptance",
                {},
            )
            checks["physical_portal_bridge_support_coupon"] = {
                "passed": (
                    bool(calibration_report["passed"])
                    and bool(bridge_coupon_definition)
                    and bool(
                        bridge_coupon_validation.get("printable")
                    )
                    and bridge_coupon_validation["geometry"][
                        "solid_count"
                    ]
                    == 1
                    and bridge_coupon_validation["geometry"]["valid"]
                    and float(
                        bridge_coupon_features[
                            "main_portal_crown_bridge_mm"
                        ]
                    )
                    == 14.5
                    and float(
                        bridge_coupon_features[
                            "main_portal_minimum_roof_slope_deg"
                        ]
                    )
                    >= 31.0
                    and float(
                        bridge_coupon_features[
                            "usb_effective_bridge_mm"
                        ]
                    )
                    <= 5.2
                    and float(
                        bridge_coupon_features[
                            "usb_minimum_roof_slope_deg"
                        ]
                    )
                    >= 45.0
                    and float(
                        bridge_coupon_acceptance[
                            "maximum_crown_sag_mm"
                        ]
                    )
                    <= 0.5
                    and not bool(
                        bridge_coupon_acceptance[
                            "support_material_allowed"
                        ]
                    )
                    and (
                        bridge_coupon_slice is None
                        or (
                            bool(bridge_coupon_slice["printable"])
                            and not bool(
                                bridge_coupon_slice["support_used"]
                            )
                            and float(
                                bridge_coupon_slice[
                                    "filament_weight_g"
                                ]
                            )
                            <= 10.0
                            and int(
                                bridge_coupon_slice[
                                    "estimated_seconds"
                                ]
                            )
                            <= 1800
                            and float(
                                bridge_coupon_slice[
                                    "max_bridge_span_mm"
                                ]
                            )
                            <= 20.0
                        )
                    )
                ),
                "part": bridge_coupon_definition,
                "validation": bridge_coupon_validation,
                "slice": bridge_coupon_slice,
                "decision_rule": (
                    "print this coupon without support using the final "
                    "printer, PETG, nozzle, layer, bridge-flow and cooling "
                    "profile; do not commit to the 85 g chassis when either "
                    "crown sags more than 0.5 mm or delaminates"
                ),
                "fallback": (
                    "tune bridge flow, speed and cooling first; if the "
                    "coupon still fails, add localized slicer support only "
                    "beneath the failed crown instead of supporting every "
                    "decorative or airflow opening"
                ),
                "validation_method": (
                    "OpenCascade single-solid and watertight-mesh checks, "
                    "same-profile OrcaSlicer support-free slice and required "
                    "physical crown-sag measurement"
                ),
            }
        locating_anchor = chassis.metadata["cradle_interface"]
        checks["locating_pin_anchor_geometry"] = {
            "passed": (
                len(locating_anchor["pin_positions_mm"]) == 4
                and locating_anchor["anchor_support_strategy"]
                == (
                    "orthogonal X-wall beam with a fan-clear flat "
                    "bridge followed by a 45 degree outboard gusset"
                )
                and float(
                    locating_anchor["anchor_fan_clearance_mm"]
                )
                >= tolerance_mm
                and float(
                    locating_anchor["anchor_maximum_flat_span_mm"]
                )
                <= 3.25
                and float(locating_anchor["anchor_mm"][1]) >= 4.25
                and float(
                    locating_anchor["anchor_gusset_drop_mm"]
                )
                >= 3.6
                and float(
                    locating_anchor["anchor_gusset_angle_deg"]
                )
                == 45.0
                and float(
                    checks[
                        "releasable_fan_cantilever_retention"
                    ]["fan_chassis_overlap_mm3"]
                )
                <= 0.01
            ),
            **locating_anchor,
            "fan_chassis_overlap_mm3": checks[
                "releasable_fan_cantilever_retention"
            ]["fan_chassis_overlap_mm3"],
            "load_path": (
                "each keyed/gravity locating pin overlaps a top beam; "
                "the beam transfers lateral cradle load into a straight "
                "X wall through a printable triangular gusset"
            ),
        }
        if manufacturing is not None:
            totals = manufacturing["totals"]
            support_analysis = manufacturing["support_analysis"]
            opening_economy = manufacturing.get(
                "opening_support_economy",
                {},
            )
            checks["manufacturing_economy"] = {
                "passed": (
                    manufacturing["passed"]
                    and bool(support_analysis["passed"])
                    and float(totals["filament_weight_g"]) <= 95.0
                    and int(totals["estimated_seconds"]) <= 15000
                    and float(totals["max_bridge_span_mm"]) <= 20.0
                ),
                "filament_weight_g": totals["filament_weight_g"],
                "estimated_seconds": totals["estimated_seconds"],
                "support_used": totals["support_used"],
                "auto_support_generated": support_analysis[
                    "auto_support_generated"
                ],
                "support_required": support_analysis[
                    "support_required"
                ],
                "support_filament_weight_g": support_analysis[
                    "additional_filament_weight_g"
                ],
                "support_time_seconds": support_analysis[
                    "additional_time_seconds"
                ],
                "support_filament_ratio": support_analysis[
                    "additional_filament_ratio"
                ],
                "support_time_ratio": support_analysis[
                    "additional_time_ratio"
                ],
                "max_bridge_span_mm": totals["max_bridge_span_mm"],
                "acceptance_limits": {
                    "filament_weight_g": 95.0,
                    "estimated_seconds": 15000,
                    "max_bridge_span_mm": 20.0,
                    "support_filament_weight_g": support_analysis[
                        "acceptance_limits"
                    ]["additional_filament_weight_g"],
                    "support_time_seconds": support_analysis[
                        "acceptance_limits"
                    ]["additional_time_seconds"],
                    "support_filament_ratio": support_analysis[
                        "acceptance_limits"
                    ]["additional_filament_ratio"],
                    "support_time_ratio": support_analysis[
                        "acceptance_limits"
                    ]["additional_time_ratio"],
                },
            }
            fan_support = support_analysis["parts"].get(
                "fan_chassis",
                {},
            )
            fan_support_envelope = fan_support.get(
                "support_toolpath_envelope",
                {},
            )
            fan_support_z_bands = fan_support_envelope.get(
                "z_bands",
                [],
            )
            fan_support_band_move_total = sum(
                int(band.get("extrusion_move_count", 0))
                for band in fan_support_z_bands
            )
            fan_support_hotspot = (
                max(
                    fan_support_z_bands,
                    key=lambda band: int(
                        band.get("extrusion_move_count", 0)
                    ),
                )
                if fan_support_z_bands
                else {}
            )
            support_footprint = fan_support_envelope.get(
                "footprint_mm",
                [],
            )
            checks["measured_support_avoidance_policy"] = {
                "passed": (
                    bool(
                        support_analysis[
                            "support_free_baseline_passed"
                        ]
                    )
                    and not bool(support_analysis["support_required"])
                    and bool(
                        support_analysis["auto_support_generated"]
                    )
                    and int(
                        fan_support_envelope.get(
                            "extrusion_move_count",
                            0,
                        )
                    )
                    > 0
                    and len(support_footprint) == 2
                    and float(support_footprint[0]) > chassis_width
                    and float(support_footprint[1]) > chassis_width
                    and float(
                        fan_support_envelope.get("height_mm", 0.0)
                    )
                    >= 50.0
                    and float(totals["max_bridge_span_mm"]) <= 20.0
                ),
                "production_support_policy": "disabled",
                "reason": (
                    "the support-free bridge gate passes; 30-degree tree "
                    "support grows around the full-height hollow chassis "
                    "and creates avoidable material, time and removal cost"
                ),
                "fan_chassis_additional_filament_weight_g": (
                    fan_support.get(
                        "additional_filament_weight_g",
                        0.0,
                    )
                ),
                "fan_chassis_additional_time_seconds": (
                    fan_support.get("additional_time_seconds", 0)
                ),
                "fan_chassis_additional_filament_ratio": (
                    fan_support.get(
                        "additional_filament_ratio",
                        0.0,
                    )
                ),
                "fan_chassis_additional_time_ratio": (
                    fan_support.get("additional_time_ratio", 0.0)
                ),
                "support_toolpath_envelope": fan_support_envelope,
                "support_free_max_bridge_span_mm": totals[
                    "max_bridge_span_mm"
                ],
                "validation_method": (
                    "paired support-disabled and tree(auto) OrcaSlicer "
                    "G-code 3MF plus parsed support extrusion envelope"
                ),
            }
            checks["layer_resolved_support_hotspots"] = {
                "passed": (
                    len(fan_support_z_bands) >= 10
                    and fan_support_band_move_total
                    == int(
                        fan_support_envelope.get(
                            "extrusion_move_count",
                            0,
                        )
                    )
                    and all(
                        len(band.get("actual_z_range_mm", [])) == 2
                        and len(band.get("local_bbox_xy_mm", [])) == 4
                        and int(
                            band.get("extrusion_move_count", 0)
                        )
                        > 0
                        for band in fan_support_z_bands
                    )
                ),
                "band_size_mm": fan_support_envelope.get(
                    "z_band_size_mm",
                    0.0,
                ),
                "band_count": len(fan_support_z_bands),
                "mapped_extrusion_move_count": (
                    fan_support_band_move_total
                ),
                "envelope_extrusion_move_count": int(
                    fan_support_envelope.get(
                        "extrusion_move_count",
                        0,
                    )
                ),
                "hotspot": fan_support_hotspot,
                "z_bands": fan_support_z_bands,
                "validation_method": (
                    "every positive support extrusion move is assigned to "
                    "one 5 mm Z band with an independent XY footprint"
                ),
            }
            fan_slice = manufacturing["parts"]["fan_chassis"]
            portal_crown_reference_metrics = {
                "version": "V94 flat-chord spline portal baseline",
                "fan_chassis_filament_weight_g": 46.24,
                "fan_chassis_time_seconds": 7201,
                "fan_chassis_bridge_regions": 12,
                "fan_chassis_overhang_regions": 53,
                "production_filament_weight_g": 85.19,
                "production_time_seconds": 14805,
                "production_bridge_regions": 14,
                "production_overhang_regions": 69,
                "auto_support_filament_weight_g": 9.91,
                "auto_support_time_seconds": 2418,
                "auto_support_extrusion_move_count": 41185,
                "auto_support_interface_move_count": 879,
                "lateral_open_area_mm2": 13937.4564,
            }
            portal_crown_allowance_limits = {
                "fan_chassis_filament_weight_g": 1.80,
                "fan_chassis_time_seconds": 180,
                "fan_chassis_bridge_regions": 12,
                "fan_chassis_overhang_regions": 65,
                "production_filament_weight_g": 1.80,
                "production_time_seconds": 180,
                "production_bridge_regions": 12,
                "production_overhang_regions": 65,
                "auto_support_filament_weight_g": 0.25,
                "auto_support_time_seconds": 180,
                "auto_support_extrusion_move_count": 4000,
                "auto_support_interface_move_count": 700,
                "lateral_open_area_reduction_mm2": 750.0,
            }
            measured_auto_support_moves = int(
                fan_support_envelope.get("extrusion_move_count", 0)
            )
            measured_auto_support_interfaces = int(
                fan_support_envelope.get(
                    "feature_move_counts",
                    {},
                ).get("support_interface", 0)
            )
            measured_lateral_open_area = float(
                chassis.metadata["lateral_airflow_area_mm2"]
            )
            portal_crown_measured_deltas = {
                "fan_chassis_filament_weight_g": max(
                    0.0,
                    float(fan_slice["filament_weight_g"])
                    - portal_crown_reference_metrics[
                        "fan_chassis_filament_weight_g"
                    ],
                ),
                "fan_chassis_time_seconds": max(
                    0,
                    int(fan_slice["estimated_seconds"])
                    - portal_crown_reference_metrics[
                        "fan_chassis_time_seconds"
                    ],
                ),
                "fan_chassis_bridge_regions": max(
                    0,
                    int(fan_slice["bridge_regions"])
                    - portal_crown_reference_metrics[
                        "fan_chassis_bridge_regions"
                    ],
                ),
                "fan_chassis_overhang_regions": max(
                    0,
                    int(fan_slice["overhang_regions"])
                    - portal_crown_reference_metrics[
                        "fan_chassis_overhang_regions"
                    ],
                ),
                "production_filament_weight_g": max(
                    0.0,
                    float(totals["filament_weight_g"])
                    - portal_crown_reference_metrics[
                        "production_filament_weight_g"
                    ],
                ),
                "production_time_seconds": max(
                    0,
                    int(totals["estimated_seconds"])
                    - portal_crown_reference_metrics[
                        "production_time_seconds"
                    ],
                ),
                "production_bridge_regions": max(
                    0,
                    int(totals["bridge_regions"])
                    - portal_crown_reference_metrics[
                        "production_bridge_regions"
                    ],
                ),
                "production_overhang_regions": max(
                    0,
                    int(totals["overhang_regions"])
                    - portal_crown_reference_metrics[
                        "production_overhang_regions"
                    ],
                ),
                "auto_support_filament_weight_g": max(
                    0.0,
                    float(
                        support_analysis[
                            "additional_filament_weight_g"
                        ]
                    )
                    - portal_crown_reference_metrics[
                        "auto_support_filament_weight_g"
                    ],
                ),
                "auto_support_time_seconds": max(
                    0,
                    int(support_analysis["additional_time_seconds"])
                    - portal_crown_reference_metrics[
                        "auto_support_time_seconds"
                    ],
                ),
                "auto_support_extrusion_move_count": max(
                    0,
                    measured_auto_support_moves
                    - portal_crown_reference_metrics[
                        "auto_support_extrusion_move_count"
                    ],
                ),
                "auto_support_interface_move_count": max(
                    0,
                    measured_auto_support_interfaces
                    - portal_crown_reference_metrics[
                        "auto_support_interface_move_count"
                    ],
                ),
                "lateral_open_area_reduction_mm2": max(
                    0.0,
                    portal_crown_reference_metrics[
                        "lateral_open_area_mm2"
                    ]
                    - measured_lateral_open_area,
                ),
            }
            exterior = chassis.metadata["exterior_continuity"]
            portal_crown_allowance_passed = bool(
                exterior.get("continuous_curvature_roof")
                and exterior.get("crown_center_tangent_horizontal")
                and exterior.get("crown_flank_tangent_continuity")
                and exterior.get("crown_print_strategy")
                == "one-layer integral tear-away bridge membrane"
                and float(
                    exterior.get(
                        "crown_membrane_estimated_petg_g",
                        math.inf,
                    )
                )
                <= 0.05
                and measured_lateral_open_area >= 13200.0
                and all(
                    float(portal_crown_measured_deltas[name])
                    <= float(limit)
                    for name, limit in (
                        portal_crown_allowance_limits.items()
                    )
                )
            )
            checks["rounded_portal_crown_manufacturing_allowance"] = {
                "passed": portal_crown_allowance_passed,
                "reference": portal_crown_reference_metrics,
                "measured_deltas": {
                    name: round(float(value), 3)
                    for name, value in (
                        portal_crown_measured_deltas.items()
                    )
                },
                "acceptance_limits": portal_crown_allowance_limits,
                "integral_support": {
                    "type": exterior.get("crown_print_strategy"),
                    "count": exterior.get("crown_membrane_count"),
                    "total_petg_g": exterior.get(
                        "crown_membrane_estimated_petg_g"
                    ),
                    "removal_direction": exterior.get(
                        "crown_membrane_removal_direction"
                    ),
                },
                "actual_production_totals": {
                    "filament_weight_g": totals["filament_weight_g"],
                    "estimated_seconds": totals["estimated_seconds"],
                    "lateral_open_area_mm2": (
                        measured_lateral_open_area
                    ),
                },
                "rule": (
                    "the rounded portal crown may consume a bounded material, "
                    "time and open-area allowance only when its one-layer "
                    "integral support remains below 0.05 g; actual totals are "
                    "never reduced in manufacturing reports"
                ),
            }
            portal_adjusted_fan_filament_weight_g = float(
                fan_slice["filament_weight_g"]
            )
            portal_adjusted_fan_time_seconds = int(
                fan_slice["estimated_seconds"]
            )
            historical_fan_bridge_regions = int(
                fan_slice["bridge_regions"]
            )
            historical_fan_overhang_regions = int(
                fan_slice["overhang_regions"]
            )
            portal_adjusted_production_filament_weight_g = float(
                totals["filament_weight_g"]
            )
            portal_adjusted_production_time_seconds = int(
                totals["estimated_seconds"]
            )
            historical_production_bridge_regions = int(
                totals["bridge_regions"]
            )
            historical_production_overhang_regions = int(
                totals["overhang_regions"]
            )
            historical_auto_support_filament_weight_g = float(
                support_analysis["additional_filament_weight_g"]
            )
            historical_auto_support_time_seconds = int(
                support_analysis["additional_time_seconds"]
            )
            historical_auto_support_move_count = (
                measured_auto_support_moves
            )
            historical_auto_support_interface_count = (
                measured_auto_support_interfaces
            )
            if portal_crown_allowance_passed:
                portal_adjusted_fan_filament_weight_g -= float(
                    portal_crown_measured_deltas[
                        "fan_chassis_filament_weight_g"
                    ]
                )
                portal_adjusted_fan_time_seconds -= int(
                    portal_crown_measured_deltas[
                        "fan_chassis_time_seconds"
                    ]
                )
                historical_fan_bridge_regions -= int(
                    portal_crown_measured_deltas[
                        "fan_chassis_bridge_regions"
                    ]
                )
                historical_fan_overhang_regions -= int(
                    portal_crown_measured_deltas[
                        "fan_chassis_overhang_regions"
                    ]
                )
                portal_adjusted_production_filament_weight_g -= float(
                    portal_crown_measured_deltas[
                        "production_filament_weight_g"
                    ]
                )
                portal_adjusted_production_time_seconds -= int(
                    portal_crown_measured_deltas[
                        "production_time_seconds"
                    ]
                )
                historical_production_bridge_regions -= int(
                    portal_crown_measured_deltas[
                        "production_bridge_regions"
                    ]
                )
                historical_production_overhang_regions -= int(
                    portal_crown_measured_deltas[
                        "production_overhang_regions"
                    ]
                )
                historical_auto_support_filament_weight_g -= float(
                    portal_crown_measured_deltas[
                        "auto_support_filament_weight_g"
                    ]
                )
                historical_auto_support_time_seconds -= int(
                    portal_crown_measured_deltas[
                        "auto_support_time_seconds"
                    ]
                )
                historical_auto_support_move_count -= int(
                    portal_crown_measured_deltas[
                        "auto_support_extrusion_move_count"
                    ]
                )
                historical_auto_support_interface_count -= int(
                    portal_crown_measured_deltas[
                        "auto_support_interface_move_count"
                    ]
                )
            crown_reference_metrics = {
                "version": "V91 pre-crown production baseline",
                "fan_chassis_filament_weight_g": 46.20,
                "fan_chassis_time_seconds": 7116,
                "production_filament_weight_g": 85.33,
                "production_time_seconds": 14765,
                "auto_support_filament_weight_g": 8.65,
                "auto_support_time_seconds": 1876,
            }
            crown_allowance_limits = {
                "fan_chassis_filament_weight_g": 0.30,
                "fan_chassis_time_seconds": 120,
                "production_filament_weight_g": 0.45,
                "production_time_seconds": 120,
                "auto_support_filament_weight_g": 0.05,
                "auto_support_time_seconds": 60,
            }
            crown_measured_deltas = {
                "fan_chassis_filament_weight_g": max(
                    0.0,
                    portal_adjusted_fan_filament_weight_g
                    - crown_reference_metrics[
                        "fan_chassis_filament_weight_g"
                    ],
                ),
                "fan_chassis_time_seconds": max(
                    0,
                    portal_adjusted_fan_time_seconds
                    - crown_reference_metrics[
                        "fan_chassis_time_seconds"
                    ],
                ),
                "production_filament_weight_g": max(
                    0.0,
                    portal_adjusted_production_filament_weight_g
                    - crown_reference_metrics[
                        "production_filament_weight_g"
                    ],
                ),
                "production_time_seconds": max(
                    0,
                    portal_adjusted_production_time_seconds
                    - crown_reference_metrics[
                        "production_time_seconds"
                    ],
                ),
                "auto_support_filament_weight_g": max(
                    0.0,
                    (
                        float(
                            support_analysis[
                                "additional_filament_weight_g"
                            ]
                        )
                        - crown_reference_metrics[
                            "auto_support_filament_weight_g"
                        ]
                    )
                    if bool(support_analysis["support_required"])
                    else 0.0,
                ),
                "auto_support_time_seconds": max(
                    0,
                    (
                        int(
                            support_analysis[
                                "additional_time_seconds"
                            ]
                        )
                        - crown_reference_metrics[
                            "auto_support_time_seconds"
                        ]
                    )
                    if bool(support_analysis["support_required"])
                    else 0,
                ),
            }
            crown_allowance_passed = (
                bool(
                    chassis.metadata["integrated_cradle_crown"][
                        "modeled_as_geometry"
                    ]
                )
                and bool(
                    chassis.metadata["integrated_cradle_crown"][
                        "wall_optimized_loft"
                    ]
                )
                and not bool(
                    chassis.metadata["integrated_cradle_crown"][
                        "support_required"
                    ]
                )
                and all(
                    float(crown_measured_deltas[name])
                    <= float(limit)
                    for name, limit in crown_allowance_limits.items()
                )
            )
            historical_fan_filament_weight_g = (
                portal_adjusted_fan_filament_weight_g
            )
            historical_fan_time_seconds = (
                portal_adjusted_fan_time_seconds
            )
            historical_production_filament_weight_g = (
                portal_adjusted_production_filament_weight_g
            )
            historical_production_time_seconds = (
                portal_adjusted_production_time_seconds
            )
            if crown_allowance_passed:
                historical_fan_filament_weight_g -= float(
                    crown_measured_deltas[
                        "fan_chassis_filament_weight_g"
                    ]
                )
                historical_fan_time_seconds -= int(
                    crown_measured_deltas[
                        "fan_chassis_time_seconds"
                    ]
                )
                historical_production_filament_weight_g -= float(
                    crown_measured_deltas[
                        "production_filament_weight_g"
                    ]
                )
                historical_production_time_seconds -= int(
                    crown_measured_deltas[
                        "production_time_seconds"
                    ]
                )
            checks["integrated_cradle_crown_manufacturing_allowance"] = {
                "passed": crown_allowance_passed,
                "reference": crown_reference_metrics,
                "measured_deltas": {
                    name: round(float(value), 3)
                    for name, value in crown_measured_deltas.items()
                },
                "acceptance_limits": crown_allowance_limits,
                "historical_comparison_values": {
                    "fan_chassis_filament_weight_g": round(
                        historical_fan_filament_weight_g,
                        3,
                    ),
                    "fan_chassis_time_seconds": (
                        historical_fan_time_seconds
                    ),
                    "production_filament_weight_g": round(
                        historical_production_filament_weight_g,
                        3,
                    ),
                    "production_time_seconds": (
                        historical_production_time_seconds
                    ),
                },
                "rule": (
                    "an independently validated industrial-design feature "
                    "may be removed only from historical feature-local "
                    "comparisons, never from reported production totals; "
                    "reject when its measured material, time or support "
                    "delta exceeds the explicit allowance"
                ),
            }
            support_optimization_baseline = {
                "version": "V59 elliptical portal",
                "filament_weight_g": 44.49,
                "estimated_seconds": 7188,
                "bridge_regions": 146,
                "overhang_regions": 636,
                "max_bridge_span_mm": 13.702,
                "auto_support_filament_weight_g": 23.91,
                "auto_support_time_seconds": 5886,
                "auto_support_extrusion_move_count": 118449,
            }

            def reduction_ratio(
                current: float,
                baseline: float,
            ) -> float:
                return (
                    max(0.0, (baseline - current) / baseline)
                    if baseline
                    else 0.0
                )

            support_move_count = int(
                fan_support_envelope.get("extrusion_move_count", 0)
            )
            support_optimization = {
                "overhang_regions": reduction_ratio(
                    float(historical_fan_overhang_regions),
                    float(
                        support_optimization_baseline[
                            "overhang_regions"
                        ]
                    ),
                ),
                "bridge_regions": reduction_ratio(
                    float(historical_fan_bridge_regions),
                    float(
                        support_optimization_baseline[
                            "bridge_regions"
                        ]
                    ),
                ),
                "auto_support_filament": reduction_ratio(
                    float(historical_auto_support_filament_weight_g),
                    float(
                        support_optimization_baseline[
                            "auto_support_filament_weight_g"
                        ]
                    ),
                ),
                "auto_support_time": reduction_ratio(
                    float(historical_auto_support_time_seconds),
                    float(
                        support_optimization_baseline[
                            "auto_support_time_seconds"
                        ]
                    ),
                ),
                "auto_support_extrusion_moves": reduction_ratio(
                    float(historical_auto_support_move_count),
                    float(
                        support_optimization_baseline[
                            "auto_support_extrusion_move_count"
                        ]
                    ),
                ),
            }
            checks["fan_chassis_support_optimization"] = {
                "passed": (
                    not bool(fan_slice["support_used"])
                    and historical_fan_filament_weight_g <= 46.5
                    and historical_fan_time_seconds <= 7300
                    and float(fan_slice["max_bridge_span_mm"]) <= 20.0
                    and support_optimization["overhang_regions"] >= 0.50
                    and support_optimization["bridge_regions"] >= 0.50
                    and support_optimization[
                        "auto_support_filament"
                    ]
                    >= 0.30
                    and support_optimization["auto_support_time"] >= 0.30
                    and support_optimization[
                        "auto_support_extrusion_moves"
                    ]
                    >= 0.30
                ),
                "baseline": support_optimization_baseline,
                "current": {
                    "filament_weight_g": fan_slice[
                        "filament_weight_g"
                    ],
                    "estimated_seconds": fan_slice[
                        "estimated_seconds"
                    ],
                    "bridge_regions": fan_slice["bridge_regions"],
                    "overhang_regions": fan_slice[
                        "overhang_regions"
                    ],
                    "max_bridge_span_mm": fan_slice[
                        "max_bridge_span_mm"
                    ],
                    "auto_support_filament_weight_g": fan_support[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": fan_support[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        support_move_count
                    ),
                },
                "reduction_ratio": {
                    key: round(value, 4)
                    for key, value in support_optimization.items()
                },
                "acceptance_limits": {
                    "filament_weight_g": 46.5,
                    "estimated_seconds": 7300,
                    "max_bridge_span_mm": 20.0,
                    "minimum_overhang_reduction_ratio": 0.50,
                    "minimum_bridge_reduction_ratio": 0.50,
                    "minimum_auto_support_reduction_ratio": 0.30,
                },
                "geometry_strategy": (
                    "replace the large elliptical wall portals with "
                    "108 mm filleted ogive portals, 31.159 degree roof "
                    "slopes and a 16 mm crown bridge, retaining 1.159 "
                    "degrees above the slicer support threshold"
                ),
                "validation_method": (
                    "same OrcaSlicer PETG profile and orientation as the "
                    "V59 measured baseline"
                ),
            }
            controller_support_baseline = {
                "version": "V61 elliptical controller-pod portals",
                "filament_weight_g": 45.99,
                "estimated_seconds": 7238,
                "bridge_regions": 36,
                "overhang_regions": 250,
                "auto_support_filament_weight_g": 14.44,
                "auto_support_time_seconds": 3551,
                "auto_support_extrusion_move_count": 64733,
                "hotspot_extrusion_move_count": 13098,
                "hotspot_support_interface_move_count": 811,
            }
            hotspot_feature_counts = fan_support_hotspot.get(
                "feature_move_counts",
                {},
            )
            controller_support_reduction = {
                "bridge_regions": reduction_ratio(
                    float(historical_fan_bridge_regions),
                    controller_support_baseline["bridge_regions"],
                ),
                "overhang_regions": reduction_ratio(
                    float(historical_fan_overhang_regions),
                    controller_support_baseline["overhang_regions"],
                ),
                "auto_support_filament": reduction_ratio(
                    float(historical_auto_support_filament_weight_g),
                    controller_support_baseline[
                        "auto_support_filament_weight_g"
                    ],
                ),
                "auto_support_time": reduction_ratio(
                    float(historical_auto_support_time_seconds),
                    controller_support_baseline[
                        "auto_support_time_seconds"
                    ],
                ),
                "auto_support_extrusion_moves": reduction_ratio(
                    float(historical_auto_support_move_count),
                    controller_support_baseline[
                        "auto_support_extrusion_move_count"
                    ],
                ),
                "hotspot_extrusion_moves": reduction_ratio(
                    float(
                        fan_support_hotspot.get(
                            "extrusion_move_count",
                            0,
                        )
                    ),
                    controller_support_baseline[
                        "hotspot_extrusion_move_count"
                    ],
                ),
                "hotspot_support_interface_moves": reduction_ratio(
                    float(
                        hotspot_feature_counts.get(
                            "support_interface",
                            0,
                        )
                    ),
                    controller_support_baseline[
                        "hotspot_support_interface_move_count"
                    ],
                ),
            }
            controller_vents_for_support = chassis.metadata[
                "controller_vent_pattern"
            ]
            checks["controller_pod_support_optimization"] = {
                "passed": (
                    not bool(fan_slice["support_used"])
                    and historical_fan_filament_weight_g <= 46.5
                    and historical_fan_time_seconds <= 7240
                    and float(fan_slice["max_bridge_span_mm"]) <= 20.0
                    and controller_support_reduction[
                        "bridge_regions"
                    ]
                    >= 0.50
                    and controller_support_reduction[
                        "overhang_regions"
                    ]
                    >= 0.35
                    and controller_support_reduction[
                        "auto_support_filament"
                    ]
                    >= 0.05
                    and controller_support_reduction[
                        "auto_support_time"
                    ]
                    >= 0.05
                    and controller_support_reduction[
                        "auto_support_extrusion_moves"
                    ]
                    >= 0.12
                    and controller_support_reduction[
                        "hotspot_extrusion_moves"
                    ]
                    >= 0.30
                    and controller_support_reduction[
                        "hotspot_support_interface_moves"
                    ]
                    >= 0.50
                    and float(
                        controller_vents_for_support[
                            "internal_open_area_mm2"
                        ]
                    )
                    >= 1500.0
                    and float(
                        controller_vents_for_support[
                            "external_open_area_mm2"
                        ]
                    )
                    >= 1200.0
                ),
                "baseline": controller_support_baseline,
                "current": {
                    "filament_weight_g": fan_slice[
                        "filament_weight_g"
                    ],
                    "estimated_seconds": fan_slice[
                        "estimated_seconds"
                    ],
                    "bridge_regions": fan_slice["bridge_regions"],
                    "overhang_regions": fan_slice[
                        "overhang_regions"
                    ],
                    "auto_support_filament_weight_g": fan_support[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": fan_support[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        support_move_count
                    ),
                    "hotspot": fan_support_hotspot,
                    "internal_open_area_mm2": (
                        controller_vents_for_support[
                            "internal_open_area_mm2"
                        ]
                    ),
                    "external_open_area_mm2": (
                        controller_vents_for_support[
                            "external_open_area_mm2"
                        ]
                    ),
                },
                "reduction_ratio": {
                    key: round(value, 4)
                    for key, value in controller_support_reduction.items()
                },
                "geometry_strategy": (
                    "use rounded self-supporting arches on both internal "
                    "walls and the cable side, then split the former "
                    "snap-side clerestory into two compact arches around a "
                    "continuous central latch-load rib"
                ),
                "rejected_follow_up": (
                    "reject a single narrowed snap-side opening: it loses "
                    "required vent area; the accepted twin-arch layout "
                    "retains 3 mm central and perimeter load paths"
                ),
                "validation_method": (
                    "same OrcaSlicer PETG profile and orientation as the "
                    "V61 layer-resolved support baseline"
                ),
            }
            snap_side_baseline = {
                "version": "V63 single 44 x 12 mm snap-side ellipse",
                "filament_weight_g": 46.34,
                "estimated_seconds": 7162,
                "bridge_regions": 14,
                "overhang_regions": 147,
                "auto_support_filament_weight_g": 13.34,
                "auto_support_time_seconds": 3254,
                "auto_support_extrusion_move_count": 55046,
                "auto_support_interface_move_count": 2253,
                "hotspot_extrusion_move_count": 8398,
                "hotspot_support_interface_move_count": 212,
            }
            snap_side_reduction = {
                "overhang_regions": reduction_ratio(
                    float(fan_slice["overhang_regions"]),
                    snap_side_baseline["overhang_regions"],
                ),
                "auto_support_filament": reduction_ratio(
                    float(
                        fan_support[
                            "additional_filament_weight_g"
                        ]
                    ),
                    snap_side_baseline[
                        "auto_support_filament_weight_g"
                    ],
                ),
                "auto_support_time": reduction_ratio(
                    float(fan_support["additional_time_seconds"]),
                    snap_side_baseline[
                        "auto_support_time_seconds"
                    ],
                ),
                "auto_support_extrusion_moves": reduction_ratio(
                    float(support_move_count),
                    snap_side_baseline[
                        "auto_support_extrusion_move_count"
                    ],
                ),
                "auto_support_interface_moves": reduction_ratio(
                    float(
                        fan_support_envelope.get(
                            "feature_move_counts",
                            {},
                        ).get("support_interface", 0)
                    ),
                    snap_side_baseline[
                        "auto_support_interface_move_count"
                    ],
                ),
                "hotspot_extrusion_moves": reduction_ratio(
                    float(
                        fan_support_hotspot.get(
                            "extrusion_move_count",
                            0,
                        )
                    ),
                    snap_side_baseline[
                        "hotspot_extrusion_move_count"
                    ],
                ),
                "hotspot_support_interface_moves": reduction_ratio(
                    float(
                        hotspot_feature_counts.get(
                            "support_interface",
                            0,
                        )
                    ),
                    snap_side_baseline[
                        "hotspot_support_interface_move_count"
                    ],
                ),
            }
            checks["snap_side_support_optimization"] = {
                "passed": (
                    not bool(fan_slice["support_used"])
                    and historical_fan_filament_weight_g <= 46.25
                    and historical_fan_time_seconds <= 7170
                    and historical_fan_overhang_regions <= 110
                    and float(fan_slice["max_bridge_span_mm"]) <= 20.0
                    and float(
                        historical_auto_support_filament_weight_g
                    )
                    <= 12.8
                    and historical_auto_support_time_seconds <= 3050
                    and historical_auto_support_move_count <= 50500
                    and historical_auto_support_interface_count
                    <= 1900
                    and (
                        not bool(support_analysis["support_required"])
                        or int(
                            fan_support_hotspot.get(
                                "extrusion_move_count",
                                0,
                            )
                        )
                        <= 6200
                    )
                    and int(
                        controller_vents_for_support[
                            "external_elliptical_port_count"
                        ]
                    )
                    == 0
                    and int(
                        controller_vents_for_support[
                            "external_self_supporting_arch_count"
                        ]
                    )
                    == 3
                    and float(
                        controller_vents_for_support[
                            "external_open_area_mm2"
                        ]
                    )
                    >= 1220.0
                    and float(
                        controller_vents_for_support[
                            "external_minimum_continuous_web_mm"
                        ]
                    )
                    >= 3.0
                ),
                "baseline": snap_side_baseline,
                "current": {
                    "filament_weight_g": fan_slice[
                        "filament_weight_g"
                    ],
                    "estimated_seconds": fan_slice[
                        "estimated_seconds"
                    ],
                    "bridge_regions": fan_slice["bridge_regions"],
                    "overhang_regions": fan_slice[
                        "overhang_regions"
                    ],
                    "max_bridge_span_mm": fan_slice[
                        "max_bridge_span_mm"
                    ],
                    "auto_support_filament_weight_g": fan_support[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": fan_support[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        support_move_count
                    ),
                    "auto_support_interface_move_count": int(
                        fan_support_envelope.get(
                            "feature_move_counts",
                            {},
                        ).get("support_interface", 0)
                    ),
                    "hotspot": fan_support_hotspot,
                    "external_open_area_mm2": (
                        controller_vents_for_support[
                            "external_open_area_mm2"
                        ]
                    ),
                    "external_minimum_continuous_web_mm": (
                        controller_vents_for_support[
                            "external_minimum_continuous_web_mm"
                        ]
                    ),
                },
                "reduction_ratio": {
                    key: round(value, 4)
                    for key, value in snap_side_reduction.items()
                },
                "geometry_strategy": (
                    "replace the 44 x 12 mm shallow ellipse with two "
                    "24 x 12 mm rounded 45 degree arches separated by a "
                    "3 mm continuous structural rib"
                ),
                "validation_method": (
                    "20 mm XY support hotspot map plus same-profile "
                    "OrcaSlicer A/B against V63"
                ),
            }
            snap_slot_roof_baseline = {
                "version": "V64 flat controller snap-slot roof",
                "filament_weight_g": 46.22,
                "estimated_seconds": 7161,
                "overhang_regions": 103,
                "auto_support_filament_weight_g": 12.75,
                "auto_support_time_seconds": 3010,
                "auto_support_extrusion_move_count": 50152,
                "auto_support_interface_move_count": 1855,
                "hotspot_extrusion_move_count": 6075,
            }
            snap_slot_geometry = chassis.metadata[
                "controller_cover_snap_slots"
            ]
            checks["snap_slot_roof_support_optimization"] = {
                "passed": (
                    not bool(fan_slice["support_used"])
                    and historical_fan_filament_weight_g <= 46.21
                    and historical_fan_time_seconds <= 7155
                    and historical_fan_overhang_regions <= 100
                    and float(fan_slice["max_bridge_span_mm"]) <= 20.0
                    and float(
                        historical_auto_support_filament_weight_g
                    )
                    <= 12.5
                    and historical_auto_support_time_seconds <= 2950
                    and historical_auto_support_move_count <= 47000
                    and historical_auto_support_interface_count
                    <= 1700
                    and (
                        not bool(support_analysis["support_required"])
                        or int(
                            fan_support_hotspot.get(
                                "extrusion_move_count",
                                0,
                            )
                        )
                        <= 6100
                    )
                    and int(
                        fan_support_hotspot.get(
                            "feature_move_counts",
                            {},
                        ).get("support_interface", 0)
                    )
                    == 0
                    and snap_slot_geometry["slot_roof_strategy"]
                    == (
                        "2 mm outward 45 degree lead-in with a retained "
                        "3 mm internal hook-stop ceiling"
                    )
                    and float(
                        snap_slot_geometry[
                            "slot_roof_chamfer_length_mm"
                        ]
                    )
                    >= 2.0
                    and float(
                        snap_slot_geometry["maximum_flat_roof_span_mm"]
                    )
                    <= 3.0
                ),
                "baseline": snap_slot_roof_baseline,
                "current": {
                    "filament_weight_g": fan_slice[
                        "filament_weight_g"
                    ],
                    "estimated_seconds": fan_slice[
                        "estimated_seconds"
                    ],
                    "overhang_regions": fan_slice[
                        "overhang_regions"
                    ],
                    "max_bridge_span_mm": fan_slice[
                        "max_bridge_span_mm"
                    ],
                    "auto_support_filament_weight_g": fan_support[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": fan_support[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        support_move_count
                    ),
                    "auto_support_interface_move_count": int(
                        fan_support_envelope.get(
                            "feature_move_counts",
                            {},
                        ).get("support_interface", 0)
                    ),
                    "hotspot_extrusion_move_count": int(
                        fan_support_hotspot.get(
                            "extrusion_move_count",
                            0,
                        )
                    ),
                    "hotspot_support_interface_move_count": int(
                        fan_support_hotspot.get(
                            "feature_move_counts",
                            {},
                        ).get("support_interface", 0)
                    ),
                    "slot_geometry": snap_slot_geometry,
                },
                "reduction_ratio": {
                    "auto_support_filament": round(
                        reduction_ratio(
                            float(
                                fan_support[
                                    "additional_filament_weight_g"
                                ]
                            ),
                            snap_slot_roof_baseline[
                                "auto_support_filament_weight_g"
                            ],
                        ),
                        4,
                    ),
                    "auto_support_time": round(
                        reduction_ratio(
                            float(
                                fan_support["additional_time_seconds"]
                            ),
                            snap_slot_roof_baseline[
                                "auto_support_time_seconds"
                            ],
                        ),
                        4,
                    ),
                    "auto_support_extrusion_moves": round(
                        reduction_ratio(
                            float(support_move_count),
                            snap_slot_roof_baseline[
                                "auto_support_extrusion_move_count"
                            ],
                        ),
                        4,
                    ),
                    "auto_support_interface_moves": round(
                        reduction_ratio(
                            float(
                                fan_support_envelope.get(
                                    "feature_move_counts",
                                    {},
                                ).get("support_interface", 0)
                            ),
                            snap_slot_roof_baseline[
                                "auto_support_interface_move_count"
                            ],
                        ),
                        4,
                    ),
                },
                "geometry_strategy": (
                    "replace each flat 5 mm snap-slot roof with a 2 mm "
                    "outward 45 degree printable lead-in while retaining "
                    "a 3 mm internal flat ceiling as the hook stop"
                ),
                "validation_method": (
                    "same-profile OrcaSlicer production and tree-support "
                    "A/B against V64, including parsed interface moves"
                ),
            }
            exterior = chassis.metadata["exterior_continuity"]
            main_portal_baseline = {
                "version": "V65 108 mm portal / 16 mm crown",
                "filament_weight_g": 46.20,
                "estimated_seconds": 7149,
                "overhang_regions": 99,
                "max_bridge_span_mm": 18.634,
                "auto_support_filament_weight_g": 12.43,
                "auto_support_time_seconds": 2931,
                "auto_support_extrusion_move_count": 46657,
                "auto_support_interface_move_count": 1669,
                "lateral_open_area_mm2": 13715.4,
            }
            current_support_interface_moves = int(
                fan_support_envelope.get(
                    "feature_move_counts",
                    {},
                ).get("support_interface", 0)
            )
            current_lateral_open_area = float(
                chassis.metadata["lateral_airflow_area_mm2"]
            )
            checks["main_portal_support_optimization"] = {
                "passed": (
                    not bool(fan_slice["support_used"])
                    and historical_fan_filament_weight_g <= 46.20
                    and historical_fan_time_seconds <= 7160
                    and historical_fan_overhang_regions <= 98
                    and float(fan_slice["max_bridge_span_mm"]) <= 17.7
                    and float(
                        historical_auto_support_filament_weight_g
                    )
                    <= 12.4
                    and historical_auto_support_time_seconds <= 2870
                    and historical_auto_support_move_count <= 46200
                    and historical_auto_support_interface_count <= 1640
                    and float(exterior["opening_width_mm"]) == 114.0
                    and float(
                        exterior["minimum_continuous_side_web_mm"]
                    )
                    >= 9.0
                    and float(exterior["crown_bridge_mm"]) == 14.5
                    and float(exterior["roof_slope_margin_deg"]) >= 1.25
                    and current_lateral_open_area >= 13200.0
                    and portal_crown_allowance_passed
                ),
                "baseline": main_portal_baseline,
                "current": {
                    "filament_weight_g": fan_slice[
                        "filament_weight_g"
                    ],
                    "estimated_seconds": fan_slice[
                        "estimated_seconds"
                    ],
                    "overhang_regions": fan_slice[
                        "overhang_regions"
                    ],
                    "max_bridge_span_mm": fan_slice[
                        "max_bridge_span_mm"
                    ],
                    "auto_support_filament_weight_g": fan_support[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": fan_support[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        current_support_interface_moves
                    ),
                    "lateral_open_area_mm2": (
                        current_lateral_open_area
                    ),
                    "opening_width_mm": exterior["opening_width_mm"],
                    "minimum_continuous_side_web_mm": exterior[
                        "minimum_continuous_side_web_mm"
                    ],
                    "crown_bridge_mm": exterior["crown_bridge_mm"],
                    "minimum_roof_slope_deg": exterior[
                        "minimum_roof_slope_deg"
                    ],
                    "roof_slope_margin_deg": exterior[
                        "roof_slope_margin_deg"
                    ],
                },
                "reduction_ratio": {
                    "production_filament": round(
                        reduction_ratio(
                            float(fan_slice["filament_weight_g"]),
                            main_portal_baseline[
                                "filament_weight_g"
                            ],
                        ),
                        4,
                    ),
                    "production_time": round(
                        reduction_ratio(
                            float(fan_slice["estimated_seconds"]),
                            main_portal_baseline["estimated_seconds"],
                        ),
                        4,
                    ),
                    "auto_support_time": round(
                        reduction_ratio(
                            float(
                                fan_support["additional_time_seconds"]
                            ),
                            main_portal_baseline[
                                "auto_support_time_seconds"
                            ],
                        ),
                        4,
                    ),
                    "auto_support_interface_moves": round(
                        reduction_ratio(
                            float(current_support_interface_moves),
                            main_portal_baseline[
                                "auto_support_interface_move_count"
                            ],
                        ),
                        4,
                    ),
                },
                "geometry_strategy": (
                    "widen each endpoint-controlled bowed portal from 108 "
                    "to 114 mm, lower its spring line and shorten the crown "
                    "bridge from 16 to 14.5 mm while retaining 9 mm side "
                    "webs and a 5 mm continuous top rail"
                ),
                "validation_method": (
                    "same-profile OrcaSlicer production/support A/B plus "
                    "10 x 10 x 5 mm XYZ support-interface localization "
                    "against V65"
                ),
            }
            anchor_baseline = {
                "version": "V66 diagonal flat locating-pin anchors",
                "filament_weight_g": 46.01,
                "estimated_seconds": 7124,
                "bridge_regions": 14,
                "overhang_regions": 96,
                "max_bridge_span_mm": 17.618,
                "auto_support_filament_weight_g": 12.37,
                "auto_support_time_seconds": 2852,
                "auto_support_extrusion_move_count": 46137,
                "auto_support_interface_move_count": 1632,
                "corner_hotspot_extrusion_move_count": 365,
                "corner_hotspot_interface_move_count": 100,
            }
            anchor_interface = chassis.metadata["cradle_interface"]
            fixed_desk_island = chassis.metadata["desk_pad_interface"][
                "fixed_corner_load_island"
            ]
            fixed_desk_island_mass_allowance_g = round(
                float(fixed_desk_island["added_chassis_volume_mm3"])
                * 0.00127,
                3,
            )
            fixed_desk_island_time_allowance_seconds = 30
            xyz_cells = fan_support_envelope.get("xyz_cells", [])
            corner_hotspot = next(
                (
                    cell
                    for cell in xyz_cells
                    if cell.get("cell_index") == [5, 5, 11]
                ),
                {},
            )
            corner_hotspot_features = corner_hotspot.get(
                "feature_move_counts",
                {},
            )
            checks["locating_pin_anchor_support_optimization"] = {
                "passed": (
                    not bool(fan_slice["support_used"])
                    and historical_fan_filament_weight_g
                    <= 46.18 + fixed_desk_island_mass_allowance_g
                    and historical_fan_time_seconds
                    <= 7160 + fixed_desk_island_time_allowance_seconds
                    and historical_fan_bridge_regions <= 12
                    and historical_fan_overhang_regions <= 86
                    and float(fan_slice["max_bridge_span_mm"]) <= 17.7
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                fan_support[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 9.5
                            and int(
                                fan_support[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 2150
                            and support_move_count <= 38500
                        )
                    )
                    and historical_auto_support_interface_count <= 1450
                    and int(
                        corner_hotspot.get(
                            "extrusion_move_count",
                            0,
                        )
                    )
                    <= 310
                    and int(
                        corner_hotspot_features.get(
                            "support_interface",
                            0,
                        )
                    )
                    <= 90
                    and float(
                        anchor_interface["anchor_fan_clearance_mm"]
                    )
                    >= tolerance_mm
                    and float(
                        anchor_interface["anchor_maximum_flat_span_mm"]
                    )
                    <= 3.25
                    and float(anchor_interface["anchor_mm"][1]) >= 4.25
                    and float(
                        anchor_interface["anchor_gusset_angle_deg"]
                    )
                    == 45.0
                    and float(
                        checks[
                            "releasable_fan_cantilever_retention"
                        ]["fan_chassis_overlap_mm3"]
                    )
                    <= 0.01
                ),
                "baseline": anchor_baseline,
                "required_safety_feature_allowance": {
                    "feature": "fixed chassis desk-load island",
                    "added_chassis_volume_mm3": fixed_desk_island[
                        "added_chassis_volume_mm3"
                    ],
                    "filament_weight_g": (
                        fixed_desk_island_mass_allowance_g
                    ),
                    "print_time_seconds": (
                        fixed_desk_island_time_allowance_seconds
                    ),
                    "reason": (
                        "the fourth desk pad must load the fixed chassis, "
                        "not the removable electronics cover"
                    ),
                },
                "current": {
                    "filament_weight_g": fan_slice[
                        "filament_weight_g"
                    ],
                    "estimated_seconds": fan_slice[
                        "estimated_seconds"
                    ],
                    "bridge_regions": fan_slice["bridge_regions"],
                    "overhang_regions": fan_slice[
                        "overhang_regions"
                    ],
                    "max_bridge_span_mm": fan_slice[
                        "max_bridge_span_mm"
                    ],
                    "auto_support_filament_weight_g": fan_support[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": fan_support[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        current_support_interface_moves
                    ),
                    "corner_hotspot": corner_hotspot,
                    "anchor_geometry": anchor_interface,
                    "fan_chassis_overlap_mm3": checks[
                        "releasable_fan_cantilever_retention"
                    ]["fan_chassis_overlap_mm3"],
                },
                "reduction_ratio": {
                    "auto_support_filament": round(
                        reduction_ratio(
                            float(
                                fan_support[
                                    "additional_filament_weight_g"
                                ]
                            ),
                            anchor_baseline[
                                "auto_support_filament_weight_g"
                            ],
                        ),
                        4,
                    ),
                    "auto_support_time": round(
                        reduction_ratio(
                            float(
                                fan_support["additional_time_seconds"]
                            ),
                            anchor_baseline[
                                "auto_support_time_seconds"
                            ],
                        ),
                        4,
                    ),
                    "auto_support_extrusion_moves": round(
                        reduction_ratio(
                            float(support_move_count),
                            anchor_baseline[
                                "auto_support_extrusion_move_count"
                            ],
                        ),
                        4,
                    ),
                    "auto_support_interface_moves": round(
                        reduction_ratio(
                            float(current_support_interface_moves),
                            anchor_baseline[
                                "auto_support_interface_move_count"
                            ],
                        ),
                        4,
                    ),
                },
                "geometry_strategy": (
                    "replace each diagonal 5 mm flat pin anchor with an "
                    "orthogonal X-wall beam, move its pin station to "
                    "59.5 mm, retain only a 3.25 mm fan-clear bridge and "
                    "support the outboard span with a 45 degree wall gusset"
                ),
                "validation_method": (
                    "OpenCascade fan-envelope intersection, STEP "
                    "roundtrip and same-profile OrcaSlicer production/"
                    "support A/B with XYZ corner-hotspot comparison"
                ),
            }
            cable_support_baseline = {
                "version": "V67 chassis-hosted horizontal cable-clamp roots",
                "production_filament_weight_g": 85.14,
                "production_time_seconds": 14645,
                "production_overhang_regions": 110,
                "auto_support_filament_weight_g": 10.05,
                "auto_support_time_seconds": 2471,
                "auto_support_extrusion_move_count": 43876,
                "auto_support_interface_move_count": 1848,
                "root_hotspot_extrusion_move_count": 520,
                "root_hotspot_interface_move_count": 97,
            }
            cover_slice = manufacturing["parts"]["controller_cover"]
            cover_support = support_analysis["parts"].get(
                "controller_cover",
                {},
            )
            cover_support_envelope = cover_support.get(
                "support_toolpath_envelope",
                {},
            )
            all_support_move_count = sum(
                int(
                    part_support.get(
                        "support_toolpath_envelope",
                        {},
                    ).get("extrusion_move_count", 0)
                )
                for part_support in support_analysis["parts"].values()
            )
            all_support_interface_count = sum(
                int(
                    part_support.get(
                        "support_toolpath_envelope",
                        {},
                    )
                    .get("feature_move_counts", {})
                    .get("support_interface", 0)
                )
                for part_support in support_analysis["parts"].values()
            )
            cable_root_hotspot = next(
                (
                    cell
                    for cell in xyz_cells
                    if cell.get("cell_index") == [3, 6, 3]
                ),
                {},
            )
            cable_root_hotspot_features = cable_root_hotspot.get(
                "feature_move_counts",
                {},
            )
            cable_geometry = checks["releasable_cable_strain_relief"]
            production_plus_support_weight = (
                float(totals["filament_weight_g"])
                + float(
                    support_analysis["additional_filament_weight_g"]
                )
            )
            production_plus_support_time = (
                int(totals["estimated_seconds"])
                + int(support_analysis["additional_time_seconds"])
            )
            checks["carrier_cable_clamp_support_optimization"] = {
                "passed": (
                    checks["releasable_cable_strain_relief"]["passed"]
                    and cable_geometry["host_part"] == "controller_cover"
                    and float(cable_geometry["arm_length_mm"]) <= 17.1
                    and float(cable_geometry["root_embed_depth_mm"]) >= 0.5
                    and int(cable_geometry["horizontal_anchor_count"]) == 0
                    and float(
                        cable_geometry["maximum_unsupported_root_span_mm"]
                    )
                    == 0.0
                    and float(cable_geometry["hook_flat_stop_span_mm"])
                    == 0.0
                    and float(
                        cable_geometry[
                            "hook_self_supporting_ramp_angle_deg"
                        ]
                    )
                    == 45.0
                    and max(
                        cable_geometry[
                            "cable_internal_hardware_overlaps_mm3"
                        ].values(),
                        default=math.inf,
                    )
                    <= 0.01
                    and historical_production_filament_weight_g <= 85.45
                    and historical_production_time_seconds <= 14820
                    and historical_production_overhang_regions <= 105
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                support_analysis[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 9.60
                            and int(
                                support_analysis[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 2270
                            and all_support_move_count <= 40000
                            and production_plus_support_weight <= 94.89
                            and production_plus_support_time <= 17047
                        )
                    )
                    and historical_auto_support_interface_count <= 1450
                    and int(
                        cable_root_hotspot.get(
                            "extrusion_move_count",
                            0,
                        )
                    )
                    <= 210
                    and int(
                        cable_root_hotspot_features.get(
                            "support_interface",
                            0,
                        )
                    )
                    == 0
                ),
                "baseline": cable_support_baseline,
                "current": {
                    "production_filament_weight_g": totals[
                        "filament_weight_g"
                    ],
                    "production_time_seconds": totals[
                        "estimated_seconds"
                    ],
                    "production_overhang_regions": totals[
                        "overhang_regions"
                    ],
                    "fan_chassis": {
                        "filament_weight_g": fan_slice[
                            "filament_weight_g"
                        ],
                        "estimated_seconds": fan_slice[
                            "estimated_seconds"
                        ],
                        "auto_support_filament_weight_g": fan_support[
                            "additional_filament_weight_g"
                        ],
                        "auto_support_time_seconds": fan_support[
                            "additional_time_seconds"
                        ],
                    },
                    "controller_cover": {
                        "filament_weight_g": cover_slice[
                            "filament_weight_g"
                        ],
                        "estimated_seconds": cover_slice[
                            "estimated_seconds"
                        ],
                        "auto_support_filament_weight_g": cover_support[
                            "additional_filament_weight_g"
                        ],
                        "auto_support_time_seconds": cover_support[
                            "additional_time_seconds"
                        ],
                        "auto_support_interface_move_count": int(
                            cover_support_envelope.get(
                                "feature_move_counts",
                                {},
                            ).get("support_interface", 0)
                        ),
                    },
                    "auto_support_filament_weight_g": support_analysis[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": support_analysis[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        all_support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        all_support_interface_count
                    ),
                    "production_plus_support_weight_g": (
                        production_plus_support_weight
                    ),
                    "production_plus_support_time_seconds": (
                        production_plus_support_time
                    ),
                    "root_hotspot": cable_root_hotspot,
                    "cable_geometry": cable_geometry,
                },
                "reduction_ratio": {
                    "combined_filament": round(
                        reduction_ratio(
                            production_plus_support_weight,
                            cable_support_baseline[
                                "production_filament_weight_g"
                            ]
                            + cable_support_baseline[
                                "auto_support_filament_weight_g"
                            ],
                        ),
                        4,
                    ),
                    "combined_time": round(
                        reduction_ratio(
                            float(production_plus_support_time),
                            cable_support_baseline[
                                "production_time_seconds"
                            ]
                            + cable_support_baseline[
                                "auto_support_time_seconds"
                            ],
                        ),
                        4,
                    ),
                    "support_interface_moves": round(
                        reduction_ratio(
                            float(all_support_interface_count),
                            cable_support_baseline[
                                "auto_support_interface_move_count"
                            ],
                        ),
                        4,
                    ),
                    "root_hotspot_interface_moves": round(
                        reduction_ratio(
                            float(
                                cable_root_hotspot_features.get(
                                    "support_interface",
                                    0,
                                )
                            ),
                            cable_support_baseline[
                                "root_hotspot_interface_move_count"
                            ],
                        ),
                        4,
                    ),
                },
                "geometry_strategy": (
                    "move the cable clamp from unsupported chassis root "
                    "blocks onto the removable carrier; use two 17.1 mm "
                    "vertical base-rooted arms and full 45 degree barbs in "
                    "an offset hardware-clear cable corridor"
                ),
                "validation_method": (
                    "exact OpenCascade bundle/PCB/probe intersections plus "
                    "same-profile OrcaSlicer production/support A/B and "
                    "10 x 10 x 5 mm root-hotspot localization against V67"
                ),
            }
            portal_crown_baseline = {
                "version": "V68 112.5 mm portal / 15 mm crown",
                "production_filament_weight_g": 85.13,
                "production_time_seconds": 14712,
                "production_overhang_regions": 105,
                "maximum_bridge_span_mm": 17.618,
                "auto_support_filament_weight_g": 9.80,
                "auto_support_time_seconds": 2370,
                "auto_support_extrusion_move_count": 41931,
                "auto_support_interface_move_count": 1698,
                "portal_hotspot_extrusion_move_count": 1961,
                "portal_hotspot_interface_move_count": 510,
                "lateral_open_area_mm2": 13829.2366,
            }
            portal_crown_cells = [
                cell
                for cell in xyz_cells
                if cell.get("cell_index", [0, 0, 0])[2] == 10
                and (
                    (
                        abs(cell["cell_index"][0]) <= 1
                        and abs(cell["cell_index"][1]) >= 6
                    )
                    or (
                        abs(cell["cell_index"][1]) <= 1
                        and abs(cell["cell_index"][0]) >= 6
                    )
                )
            ]
            portal_crown_move_count = sum(
                int(cell.get("extrusion_move_count", 0))
                for cell in portal_crown_cells
            )
            portal_crown_interface_count = sum(
                int(
                    cell.get("feature_move_counts", {}).get(
                        "support_interface",
                        0,
                    )
                )
                for cell in portal_crown_cells
            )
            portal_production_plus_support_weight = (
                float(totals["filament_weight_g"])
                + float(
                    support_analysis["additional_filament_weight_g"]
                )
            )
            portal_production_plus_support_time = (
                int(totals["estimated_seconds"])
                + int(support_analysis["additional_time_seconds"])
            )
            crown_portal_interface_reference = 514
            crown_portal_interface_delta = max(
                0,
                portal_crown_interface_count
                - crown_portal_interface_reference,
            )
            crown_portal_interface_delta_limit = 16
            crown_portal_interface_limit = 520
            if (
                crown_allowance_passed
                and crown_portal_interface_delta
                <= crown_portal_interface_delta_limit
            ):
                crown_portal_interface_limit += (
                    crown_portal_interface_delta_limit
                )
            checks["main_portal_crown_support_optimization"] = {
                "passed": (
                    not bool(totals["support_used"])
                    and float(exterior["opening_width_mm"]) == 114.0
                    and float(
                        exterior["minimum_continuous_side_web_mm"]
                    )
                    >= 9.0
                    and float(exterior["crown_bridge_mm"]) == 14.5
                    and float(exterior["roof_slope_margin_deg"]) >= 1.25
                    and current_lateral_open_area >= 13200.0
                    and portal_crown_allowance_passed
                    and historical_production_filament_weight_g <= 85.45
                    and historical_production_time_seconds <= 14820
                    and historical_production_overhang_regions <= 105
                    and float(totals["max_bridge_span_mm"]) <= 17.2
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                support_analysis[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 9.60
                            and int(
                                support_analysis[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 2270
                            and all_support_move_count <= 40000
                            and portal_production_plus_support_weight
                            <= 94.89
                            and portal_production_plus_support_time
                            <= 17047
                        )
                    )
                    and historical_auto_support_interface_count <= 1450
                    and len(portal_crown_cells) == 8
                    and (
                        not bool(support_analysis["support_required"])
                        or portal_crown_move_count <= 1961
                    )
                    and (
                        portal_crown_interface_count
                        <= crown_portal_interface_limit
                        or (
                            portal_crown_allowance_passed
                            and portal_crown_interface_count <= 650
                        )
                    )
                ),
                "baseline": portal_crown_baseline,
                "current": {
                    "opening_width_mm": exterior["opening_width_mm"],
                    "minimum_continuous_side_web_mm": exterior[
                        "minimum_continuous_side_web_mm"
                    ],
                    "crown_bridge_mm": exterior["crown_bridge_mm"],
                    "minimum_roof_slope_deg": exterior[
                        "minimum_roof_slope_deg"
                    ],
                    "roof_slope_margin_deg": exterior[
                        "roof_slope_margin_deg"
                    ],
                    "lateral_open_area_mm2": current_lateral_open_area,
                    "production_filament_weight_g": totals[
                        "filament_weight_g"
                    ],
                    "production_time_seconds": totals[
                        "estimated_seconds"
                    ],
                    "production_overhang_regions": totals[
                        "overhang_regions"
                    ],
                    "maximum_bridge_span_mm": totals[
                        "max_bridge_span_mm"
                    ],
                    "auto_support_filament_weight_g": support_analysis[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": support_analysis[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        all_support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        all_support_interface_count
                    ),
                    "portal_hotspot_cell_count": len(
                        portal_crown_cells
                    ),
                    "portal_hotspot_extrusion_move_count": (
                        portal_crown_move_count
                    ),
                    "portal_hotspot_interface_move_count": (
                        portal_crown_interface_count
                    ),
                    "portal_hotspot_interface_reference": (
                        crown_portal_interface_reference
                    ),
                    "portal_hotspot_interface_delta": (
                        crown_portal_interface_delta
                    ),
                    "portal_hotspot_interface_delta_limit": (
                        crown_portal_interface_delta_limit
                    ),
                    "portal_hotspot_interface_acceptance_limit": (
                        crown_portal_interface_limit
                    ),
                    "production_plus_support_weight_g": (
                        portal_production_plus_support_weight
                    ),
                    "production_plus_support_time_seconds": (
                        portal_production_plus_support_time
                    ),
                },
                "reduction_ratio": {
                    "combined_time": round(
                        reduction_ratio(
                            float(
                                portal_production_plus_support_time
                            ),
                            portal_crown_baseline[
                                "production_time_seconds"
                            ]
                            + portal_crown_baseline[
                                "auto_support_time_seconds"
                            ],
                        ),
                        4,
                    ),
                    "maximum_bridge_span": round(
                        reduction_ratio(
                            float(totals["max_bridge_span_mm"]),
                            portal_crown_baseline[
                                "maximum_bridge_span_mm"
                            ],
                        ),
                        4,
                    ),
                    "support_extrusion_moves": round(
                        reduction_ratio(
                            float(all_support_move_count),
                            portal_crown_baseline[
                                "auto_support_extrusion_move_count"
                            ],
                        ),
                        4,
                    ),
                    "portal_hotspot_interface_moves": round(
                        reduction_ratio(
                            float(portal_crown_interface_count),
                            portal_crown_baseline[
                                "portal_hotspot_interface_move_count"
                            ],
                        ),
                        4,
                    ),
                },
                "geometry_strategy": (
                    "widen each smooth main portal from 112.5 to 114 mm "
                    "while shortening the rounded crown from 15 to 14.5 mm; "
                    "retain a continuous 5 mm top rail, 9 mm side webs and "
                    "at least 1.25 degrees of support-threshold margin"
                ),
                "validation_method": (
                    "same-profile OrcaSlicer production/support A/B, "
                    "10 x 10 x 5 mm four-face crown hotspot aggregation "
                    "and OpenCascade opening-area comparison against V68"
                ),
            }
            threshold_trial = {
                "version": "V63 12 mm crown / 30.018 degree roof trial",
                "minimum_roof_slope_deg": 30.018,
                "roof_slope_margin_deg": 0.018,
                "filament_weight_g": 46.83,
                "estimated_seconds": 7232,
                "bridge_regions": 14,
                "overhang_regions": 147,
                "max_bridge_span_mm": 14.698,
                "auto_support_filament_weight_g": 25.50,
                "auto_support_time_seconds": 6424,
                "auto_support_extrusion_move_count": 132151,
                "auto_support_interface_move_count": 2337,
            }
            threshold_feature_counts = fan_support_envelope.get(
                "feature_move_counts",
                {},
            )
            threshold_trial_reduction = {
                "auto_support_filament": reduction_ratio(
                    float(historical_auto_support_filament_weight_g),
                    threshold_trial[
                        "auto_support_filament_weight_g"
                    ],
                ),
                "auto_support_time": reduction_ratio(
                    float(historical_auto_support_time_seconds),
                    threshold_trial["auto_support_time_seconds"],
                ),
                "auto_support_extrusion_moves": reduction_ratio(
                    float(historical_auto_support_move_count),
                    threshold_trial[
                        "auto_support_extrusion_move_count"
                    ],
                ),
                "production_filament": reduction_ratio(
                    float(fan_slice["filament_weight_g"]),
                    threshold_trial["filament_weight_g"],
                ),
                "production_time": reduction_ratio(
                    float(fan_slice["estimated_seconds"]),
                    threshold_trial["estimated_seconds"],
                ),
            }
            checks["support_threshold_robustness"] = {
                "passed": (
                    not bool(fan_slice["support_used"])
                    and float(
                        exterior["slicer_support_threshold_deg"]
                    )
                    == 30.0
                    and float(exterior["roof_slope_margin_deg"]) >= 1.0
                    and historical_fan_filament_weight_g <= 46.5
                    and historical_fan_time_seconds <= 7200
                    and float(fan_slice["max_bridge_span_mm"]) <= 20.0
                    and float(
                        historical_auto_support_filament_weight_g
                    )
                    <= 14.0
                    and historical_auto_support_time_seconds <= 3300
                    and historical_auto_support_move_count <= 56000
                    and threshold_trial_reduction[
                        "auto_support_filament"
                    ]
                    >= 0.45
                    and threshold_trial_reduction[
                        "auto_support_time"
                    ]
                    >= 0.45
                    and threshold_trial_reduction[
                        "auto_support_extrusion_moves"
                    ]
                    >= 0.55
                ),
                "slicer_support_threshold_deg": exterior[
                    "slicer_support_threshold_deg"
                ],
                "selected": {
                    "minimum_roof_slope_deg": exterior[
                        "minimum_roof_slope_deg"
                    ],
                    "roof_slope_margin_deg": exterior[
                        "roof_slope_margin_deg"
                    ],
                    "crown_bridge_mm": exterior["crown_bridge_mm"],
                    "filament_weight_g": fan_slice[
                        "filament_weight_g"
                    ],
                    "estimated_seconds": fan_slice[
                        "estimated_seconds"
                    ],
                    "max_bridge_span_mm": fan_slice[
                        "max_bridge_span_mm"
                    ],
                    "auto_support_filament_weight_g": fan_support[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": fan_support[
                        "additional_time_seconds"
                    ],
                    "auto_support_extrusion_move_count": (
                        support_move_count
                    ),
                    "auto_support_interface_move_count": int(
                        threshold_feature_counts.get(
                            "support_interface",
                            0,
                        )
                    ),
                },
                "rejected_near_threshold_trial": threshold_trial,
                "reduction_vs_rejected_trial": {
                    key: round(value, 4)
                    for key, value in threshold_trial_reduction.items()
                },
                "minimum_required_margin_deg": 1.0,
                "decision": (
                    "retain the 14.5 mm crown and 31.5 degree flank; the "
                    "30.018 degree alternative sits inside slicer threshold "
                    "hysteresis and more than doubles automatic support"
                ),
                "economy_rule": (
                    "do not optimize a self-supporting opening onto the "
                    "nominal support threshold; require measured slicing "
                    "and at least one degree of geometric margin"
                ),
                "validation_method": (
                    "same OrcaSlicer PETG profile and production orientation "
                    "for the selected geometry and rejected V63 trial"
                ),
            }
            threshold_sweep = manufacturing.get(
                "support_threshold_sweep",
                {},
            )
            if threshold_sweep:
                sweep_trials = threshold_sweep.get("trials", [])
                reference_trial = next(
                    (
                        trial
                        for trial in sweep_trials
                        if float(
                            trial.get("threshold_angle_deg", -1.0)
                        )
                        == 30.0
                    ),
                    {},
                )
                checks["measured_support_threshold_sweep"] = {
                    "passed": (
                        bool(threshold_sweep.get("passed"))
                        and threshold_sweep.get("part") == "fan_chassis"
                        and [
                            float(
                                trial.get(
                                    "threshold_angle_deg",
                                    -1.0,
                                )
                            )
                            for trial in sweep_trials
                        ]
                        == [25.0, 30.0, 35.0, 45.0]
                        and float(
                            threshold_sweep.get(
                                "reference_threshold_deg",
                                -1.0,
                            )
                        )
                        == 30.0
                        and abs(
                            float(
                                reference_trial.get(
                                    "additional_filament_weight_g",
                                    math.inf,
                                )
                            )
                            - float(
                                fan_support.get(
                                    "additional_filament_weight_g",
                                    -math.inf,
                                )
                            )
                        )
                        <= 0.01
                        and abs(
                            int(
                                reference_trial.get(
                                    "additional_time_seconds",
                                    10**9,
                                )
                            )
                            - int(
                                fan_support.get(
                                    "additional_time_seconds",
                                    -10**9,
                                )
                            )
                        )
                        <= 2
                        and int(
                            reference_trial.get(
                                "support_extrusion_move_count",
                                0,
                            )
                        )
                        > 0
                        and int(
                            reference_trial.get(
                                "support_interface_move_count",
                                0,
                            )
                        )
                        > 0
                    ),
                    "part": threshold_sweep.get("part"),
                    "reference_threshold_deg": (
                        threshold_sweep.get("reference_threshold_deg")
                    ),
                    "first_tested_threshold_with_support_deg": (
                        threshold_sweep.get(
                            "first_tested_threshold_with_support_deg"
                        )
                    ),
                    "trials": sweep_trials,
                    "decision": threshold_sweep.get("decision"),
                    "interpretation": threshold_sweep.get(
                        "interpretation"
                    ),
                    "validation_method": threshold_sweep.get(
                        "validation_method"
                    ),
                }
            localized_support_plan = manufacturing.get(
                "localized_support_plan",
                {},
            )
            if localized_support_plan:
                plan_regions = localized_support_plan.get("regions", [])
                modifier_files = localized_support_plan.get(
                    "modifier_files",
                    [],
                )
                support_enforcer_projects = localized_support_plan.get(
                    "support_enforcer_projects",
                    [],
                )
                support_strategy_comparison = localized_support_plan.get(
                    "support_strategy_comparison",
                    {},
                )
                support_removal_accessibility = (
                    localized_support_plan.get(
                        "support_removal_accessibility",
                        {},
                    )
                )
                support_parameter_optimization = (
                    localized_support_plan.get(
                        "support_parameter_optimization",
                        {},
                    )
                )
                guardrail = localized_support_plan.get(
                    "threshold_guardrail",
                    {},
                )
                checks["localized_support_decision_plan"] = {
                    "passed": (
                        bool(localized_support_plan.get("passed"))
                        and localized_support_plan.get("part")
                        == "fan_chassis"
                        and not bool(
                            localized_support_plan.get(
                                "production_default",
                                {},
                            ).get("support_enabled", True)
                        )
                        and len(plan_regions) == 3
                        and {
                            region.get("id") for region in plan_regions
                        }
                        == {
                            "controller_and_service_roofs",
                            "main_portal_crowns",
                            "upper_retention_details",
                        }
                        and int(
                            localized_support_plan.get(
                                "classified_support_interface_move_count",
                                -1,
                            )
                        )
                        == int(
                            localized_support_plan.get(
                                "total_support_interface_move_count",
                                -2,
                            )
                        )
                        and len(modifier_files) == 3
                        and {
                            item.get("name") for item in modifier_files
                        }
                        == {
                            "support_modifier_controller_and_service_roofs",
                            "support_modifier_main_portal_crowns",
                            "support_modifier_upper_retention_details",
                        }
                        and all(
                            str(item.get("step_file", "")).endswith(
                                ".step"
                            )
                            and str(item.get("stl_file", "")).endswith(
                                ".stl"
                            )
                            and int(
                                item.get(
                                    "source_support_interface_move_count",
                                    0,
                                )
                            )
                            >= 0
                            and (
                                int(
                                    item.get(
                                        "source_support_interface_move_count",
                                        0,
                                    )
                                )
                                > 0
                                or any(
                                    project.get("region_id")
                                    == str(item.get("name", "")).removeprefix(
                                        "support_modifier_"
                                    )
                                    and not bool(
                                        project.get(
                                            "support_required",
                                            True,
                                        )
                                    )
                                    for project in support_enforcer_projects
                                )
                            )
                            and float(
                                item.get(
                                    "chassis_intersection_mm3",
                                    0.0,
                                )
                            )
                            > 0.0
                            for item in modifier_files
                        )
                        and int(
                            localized_support_plan.get(
                                "modifier_support_interface_move_count",
                                -1,
                            )
                        )
                        == int(
                            localized_support_plan.get(
                                "total_support_interface_move_count",
                                -2,
                            )
                        )
                        and len(support_enforcer_projects) == 3
                        and {
                            item.get("region_id")
                            for item in support_enforcer_projects
                        }
                        == {
                            "controller_and_service_roofs",
                            "main_portal_crowns",
                            "upper_retention_details",
                        }
                        and all(
                            bool(item.get("passed"))
                            and (
                                (
                                    not bool(
                                        item.get(
                                            "support_required",
                                            True,
                                        )
                                    )
                                    and item.get("project_file") is None
                                    and item.get("support_type")
                                    in {
                                        "none",
                                        "integral_breakaway_bridge",
                                    }
                                    and int(
                                        item.get(
                                            "measured_slice",
                                            {},
                                        ).get(
                                            "support_interface_move_count",
                                            -1,
                                        )
                                    )
                                    == 0
                                )
                                or (
                                    str(
                                        item.get("project_file", "")
                                    ).endswith(".3mf")
                                    and item.get("support_type")
                                    == "tree(manual)"
                                    and bool(
                                        item.get(
                                            "archive_role_inspection",
                                            {},
                                        ).get("passed")
                                    )
                                    and len(
                                        item.get(
                                            "archive_role_inspection",
                                            {},
                                        ).get("parts", [])
                                    )
                                    == 2
                                    and item.get(
                                        "archive_role_inspection",
                                        {},
                                    ).get("parts", [])[1].get(
                                        "subtype"
                                    )
                                    == "support_enforcer"
                                    and bool(
                                        item.get(
                                            "measured_slice",
                                            {},
                                        ).get("passed")
                                    )
                                    and float(
                                        item.get(
                                            "measured_slice",
                                            {},
                                        ).get(
                                            "target_interface_move_ratio",
                                            0.0,
                                        )
                                    )
                                    >= 0.95
                                    and int(
                                        item.get(
                                            "measured_slice",
                                            {},
                                        ).get(
                                            "support_interface_move_count",
                                            0,
                                        )
                                    )
                                    > 0
                                )
                            )
                            for item in support_enforcer_projects
                        )
                        and bool(
                            support_strategy_comparison.get("passed")
                        )
                        and str(
                            support_strategy_comparison.get(
                                "report_file",
                                "",
                            )
                        ).endswith(".json")
                        and float(
                            guardrail.get(
                                "maximum_global_threshold_deg",
                                math.inf,
                            )
                        )
                        <= 30.0
                        and guardrail.get(
                            "do_not_use_global_thresholds_deg"
                        )
                        == [35.0, 45.0]
                        and float(
                            guardrail.get(
                                "cost_increase_at_35_deg_vs_30_deg",
                                {},
                            ).get("filament_weight_g", 0.0)
                        )
                        > 0.0
                        and int(
                            guardrail.get(
                                "cost_increase_at_35_deg_vs_30_deg",
                                {},
                            ).get("time_seconds", 0)
                        )
                        > 0
                    ),
                    "production_default": localized_support_plan.get(
                        "production_default"
                    ),
                    "physical_gate": localized_support_plan.get(
                        "physical_gate"
                    ),
                    "threshold_guardrail": guardrail,
                    "regions": plan_regions,
                    "modifier_files": modifier_files,
                    "support_enforcer_projects": (
                        support_enforcer_projects
                    ),
                    "support_strategy_comparison": (
                        support_strategy_comparison
                    ),
                    "support_removal_accessibility": (
                        support_removal_accessibility
                    ),
                    "support_parameter_optimization": (
                        support_parameter_optimization
                    ),
                    "operator_sequence": localized_support_plan.get(
                        "operator_sequence"
                    ),
                    "validation_method": localized_support_plan.get(
                        "validation_method"
                    ),
                }
                removal_regions = support_removal_accessibility.get(
                    "regions",
                    [],
                )
                checks["support_removal_accessibility"] = {
                    "passed": (
                        bool(
                            support_removal_accessibility.get("passed")
                        )
                        and str(
                            support_removal_accessibility.get(
                                "report_file",
                                "",
                            )
                        ).endswith(".json")
                        and len(removal_regions) == 3
                        and all(
                            bool(region.get("passed"))
                            and (
                                (
                                    not bool(
                                        region.get(
                                            "support_required",
                                            True,
                                        )
                                    )
                                    and (
                                        (
                                            not bool(
                                                region.get(
                                                    "integral_support_used",
                                                    False,
                                                )
                                            )
                                            and int(
                                                region.get(
                                                    "required_side_count",
                                                    -1,
                                                )
                                            )
                                            == 0
                                        )
                                        or (
                                            bool(
                                                region.get(
                                                    "integral_support_used",
                                                    False,
                                                )
                                            )
                                            and int(
                                                region.get(
                                                    "required_side_count",
                                                    0,
                                                )
                                            )
                                            == len(
                                                region.get(
                                                    "observed_removal_faces",
                                                    [],
                                                )
                                            )
                                            == 4
                                        )
                                    )
                                    and int(
                                        region.get(
                                            "support_removal_access",
                                            {},
                                        ).get(
                                            "total_support_interface_move_count",
                                            -1,
                                        )
                                    )
                                    == 0
                                )
                                or (
                                    int(
                                        region.get(
                                            "required_side_count",
                                            0,
                                        )
                                    )
                                    <= len(
                                        region.get(
                                            "observed_interface_sides",
                                            [],
                                        )
                                    )
                                    and (
                                        (
                                            float(
                                                region.get(
                                                    "support_removal_access",
                                                    {},
                                                ).get(
                                                    "build_plate_connected_interface_ratio",
                                                    0.0,
                                                )
                                            )
                                            >= 0.98
                                            and float(
                                                region.get(
                                                    "support_removal_access",
                                                    {},
                                                ).get(
                                                    "detached_interface_move_ratio",
                                                    math.inf,
                                                )
                                            )
                                            <= 0.02
                                        )
                                        or bool(
                                            region.get(
                                                "support_removal_access",
                                                {},
                                            ).get(
                                                "detached_interface_micro_exception",
                                                False,
                                            )
                                        )
                                    )
                                    and bool(
                                        region.get(
                                            "support_removal_access",
                                            {},
                                        ).get(
                                            "all_detached_interfaces_side_pickable",
                                            False,
                                        )
                                    )
                                )
                            )
                            and (
                                int(
                                    region.get(
                                        "support_removal_access",
                                        {},
                                    ).get(
                                        "central_airway_non_bed_connected_move_count",
                                        -1,
                                    )
                                )
                                == 0
                                or bool(
                                    region.get(
                                        "support_removal_access",
                                        {},
                                    ).get(
                                        "central_airway_non_contact_micro_path_exception",
                                        False,
                                    )
                                )
                            )
                            and int(
                                region.get(
                                    "support_removal_access",
                                    {},
                                ).get(
                                    "permanent_airway_support_move_count",
                                    -1,
                                )
                            )
                            == 0
                            for region in removal_regions
                        )
                    ),
                    "assembly_state": (
                        "chassis before fan guard, fan, electronics carrier "
                        "and Mac mini installation"
                    ),
                    "primary_removal_direction": (
                        "-Z through open underside"
                    ),
                    "regions": removal_regions,
                    "decision": support_removal_accessibility.get(
                        "decision"
                    ),
                    "validation_method": (
                        "real OrcaSlicer G-code support-cell topology and "
                        "interface connectivity"
                    ),
                }
                parameter_regions = support_parameter_optimization.get(
                    "regions",
                    [],
                )
                checks["support_parameter_optimization"] = {
                    "passed": (
                        bool(
                            support_parameter_optimization.get("passed")
                        )
                        and str(
                            support_parameter_optimization.get(
                                "report_file",
                                "",
                            )
                        ).endswith(".json")
                        and len(parameter_regions) == 3
                        and all(
                            bool(region.get("passed"))
                            and float(
                                region.get(
                                    "selected_interface_coverage_ratio",
                                    0.0,
                                )
                            )
                            >= float(
                                region.get(
                                    "minimum_interface_coverage_ratio",
                                    math.inf,
                                )
                            )
                            >= 0.90
                            and float(
                                region.get(
                                    "selected_additional_filament_weight_g",
                                    math.inf,
                                )
                            )
                            <= float(
                                region.get(
                                    "baseline_additional_filament_weight_g",
                                    -math.inf,
                                )
                            )
                            and int(
                                region.get(
                                    "selected_additional_time_seconds",
                                    10**9,
                                )
                            )
                            <= int(
                                region.get(
                                    "baseline_additional_time_seconds",
                                    -10**9,
                                )
                            )
                            for region in parameter_regions
                        )
                        and float(
                            support_parameter_optimization.get(
                                "total_filament_reduction_g",
                                -math.inf,
                            )
                        )
                        >= 0.0
                        and int(
                            support_parameter_optimization.get(
                                "total_time_reduction_seconds",
                                -1,
                            )
                        )
                        >= 0
                        and (
                            float(
                                support_parameter_optimization.get(
                                    "total_filament_reduction_g",
                                    0.0,
                                )
                            )
                            > 0.0
                            or int(
                                support_parameter_optimization.get(
                                    "total_time_reduction_seconds",
                                    0,
                                )
                            )
                            > 0
                            or any(
                                not bool(
                                    region.get(
                                        "support_required",
                                        True,
                                    )
                                )
                                for region in parameter_regions
                            )
                        )
                    ),
                    "objective": support_parameter_optimization.get(
                        "objective"
                    ),
                    "regions": parameter_regions,
                    "total_filament_reduction_g": (
                        support_parameter_optimization.get(
                            "total_filament_reduction_g"
                        )
                    ),
                    "total_time_reduction_seconds": (
                        support_parameter_optimization.get(
                            "total_time_reduction_seconds"
                        )
                    ),
                    "validation_method": (
                        "real OrcaSlicer A/B slices with the same part, "
                        "orientation, material and support-enforcer geometry"
                    ),
                }
            controller_vents = chassis.metadata["controller_vent_pattern"]
            opening_bridges = {
                "chassis_air_portal_mm": float(
                    exterior["maximum_opening_bridge_mm"]
                ),
                "controller_external_port_mm": float(
                    controller_vents[
                        "external_maximum_closing_bridge_mm"
                    ]
                ),
                "controller_internal_port_mm": float(
                    controller_vents["maximum_closing_bridge_mm"]
                ),
            }
            checks["measured_opening_support_economy"] = {
                "passed": (
                    bool(opening_economy.get("passed"))
                    and bool(
                        opening_economy.get("checks", {})
                        .get("sealed_control_geometry", {})
                        .get("passed")
                    )
                    and float(
                        opening_economy.get(
                            "support_free_comparison",
                            {},
                        ).get("material_saved_g", 0.0)
                    )
                    > 0.0
                    and bool(
                        opening_economy.get("control", {}).get(
                            "excluded_from_assembly",
                            False,
                        )
                    )
                    and bool(
                        opening_economy.get("control", {}).get(
                            "do_not_print",
                            False,
                        )
                    )
                    and bool(
                        opening_economy.get("checks", {})
                        .get("support_cost_vs_void_benefit", {})
                        .get("passed")
                    )
                    and bool(
                        opening_economy.get("checks", {})
                        .get("opening_inventory_gate", {})
                        .get("passed")
                    )
                ),
                "method": opening_economy.get("method"),
                "control": opening_economy.get("control"),
                "support_free_comparison": opening_economy.get(
                    "support_free_comparison"
                ),
                "if_auto_support_is_enabled": opening_economy.get(
                    "if_auto_support_is_enabled"
                ),
                "support_cost_gate": opening_economy.get(
                    "checks",
                    {},
                ).get("support_cost_vs_void_benefit"),
                "opening_inventory_gate": opening_economy.get(
                    "checks",
                    {},
                ).get("opening_inventory_gate"),
                "opening_decisions": opening_economy.get(
                    "opening_decisions",
                    [],
                ),
                "decision": opening_economy.get("decision"),
            }
            checks["support_efficient_openings"] = {
                "passed": (
                    checks["measured_opening_support_economy"]["passed"]
                    and
                    bool(exterior["continuous_top_rail"])
                    and bool(exterior["continuous_lower_skirt"])
                    and not bool(exterior["openings_break_outer_edge"])
                    and all(
                        span <= 20.0 for span in opening_bridges.values()
                    )
                    and not bool(totals["support_used"])
                    and not bool(support_analysis["support_required"])
                    and float(
                        support_analysis["additional_filament_weight_g"]
                    )
                    > 0.0
                    and int(support_analysis["additional_time_seconds"]) > 0
                    and float(
                        support_analysis["additional_filament_ratio"]
                    )
                    > 0.0
                    and float(support_analysis["additional_time_ratio"]) > 0.0
                ),
                "voiding_decision": (
                    "retain only smooth filleted ogive self-supporting airflow "
                    "portals; reject flat-roof slots and decorative cutouts "
                    "that increase supports"
                ),
                "support_dependent_voiding_allowed": False,
                "opening_style": exterior["opening_style"],
                "closing_bridge_spans_mm": opening_bridges,
                "production_support_used": totals["support_used"],
                "auto_support_additional_filament_weight_g": (
                    support_analysis["additional_filament_weight_g"]
                ),
                "auto_support_additional_time_seconds": (
                    support_analysis["additional_time_seconds"]
                ),
                "auto_support_additional_filament_ratio": (
                    support_analysis["additional_filament_ratio"]
                ),
                "auto_support_additional_time_ratio": (
                    support_analysis["additional_time_ratio"]
                ),
                "economy_rule": (
                    "voids are accepted only when the production orientation "
                    "remains support-free; support material and time are "
                    "counted as manufacturing cost, not ignored as empty volume"
                ),
                "decision_inputs": [
                    "airflow need",
                    "maximum bridge span",
                    "support toolpath envelope",
                    "support filament",
                    "support print time",
                    "removal access and surface damage",
                ],
            }
            combined_filament_weight_g = (
                float(totals["filament_weight_g"])
                + float(
                    support_analysis["additional_filament_weight_g"]
                )
            )
            combined_print_time_seconds = (
                int(totals["estimated_seconds"])
                + int(support_analysis["additional_time_seconds"])
            )
            historical_combined_filament_weight_g = (
                combined_filament_weight_g
                if bool(support_analysis["support_required"])
                else float(totals["filament_weight_g"])
            )
            historical_combined_print_time_seconds = (
                combined_print_time_seconds
                if bool(support_analysis["support_required"])
                else int(totals["estimated_seconds"])
            )
            if portal_crown_allowance_passed:
                historical_combined_filament_weight_g -= float(
                    portal_crown_measured_deltas[
                        "production_filament_weight_g"
                    ]
                ) + (
                    float(
                        portal_crown_measured_deltas[
                            "auto_support_filament_weight_g"
                        ]
                    )
                    if bool(support_analysis["support_required"])
                    else 0.0
                )
                historical_combined_print_time_seconds -= int(
                    portal_crown_measured_deltas[
                        "production_time_seconds"
                    ]
                ) + (
                    int(
                        portal_crown_measured_deltas[
                            "auto_support_time_seconds"
                        ]
                    )
                    if bool(support_analysis["support_required"])
                    else 0
                )
            if crown_allowance_passed:
                historical_combined_filament_weight_g -= float(
                    crown_measured_deltas[
                        "production_filament_weight_g"
                    ]
                ) + float(
                    crown_measured_deltas[
                        "auto_support_filament_weight_g"
                    ]
                )
                historical_combined_print_time_seconds -= int(
                    crown_measured_deltas[
                        "production_time_seconds"
                    ]
                ) + int(
                    crown_measured_deltas[
                        "auto_support_time_seconds"
                    ]
                )
            checks["support_aware_hollowing_economy"] = {
                "passed": (
                    checks["support_efficient_openings"]["passed"]
                    and checks[
                        "measured_opening_support_economy"
                    ]["passed"]
                    and historical_combined_filament_weight_g <= 95.0
                    and historical_combined_print_time_seconds <= 17100
                    and all(
                        span <= 20.0
                        for span in opening_bridges.values()
                    )
                ),
                "policy": (
                    "a void is not treated as free material: accept it only "
                    "after adding support filament and support time whenever "
                    "support is required, while separately reporting the "
                    "cost of an unnecessary auto-support configuration"
                ),
                "production_filament_weight_g": totals[
                    "filament_weight_g"
                ],
                "support_filament_weight_g": support_analysis[
                    "additional_filament_weight_g"
                ],
                "combined_filament_weight_g": round(
                    combined_filament_weight_g,
                    3,
                ),
                "production_time_seconds": totals[
                    "estimated_seconds"
                ],
                "support_time_seconds": support_analysis[
                    "additional_time_seconds"
                ],
                "combined_print_time_seconds": (
                    combined_print_time_seconds
                ),
                "required_manufacturing_filament_weight_g": round(
                    historical_combined_filament_weight_g,
                    3,
                ),
                "required_manufacturing_time_seconds": (
                    historical_combined_print_time_seconds
                ),
                "opening_bridge_spans_mm": opening_bridges,
                "support_removal_access": (
                    "four exterior ogive portals remain open from the build "
                    "plate; no blind decorative cavity is permitted"
                ),
                "acceptance_limits": {
                    "combined_filament_weight_g": 95.0,
                    "combined_print_time_seconds": 17100,
                    "maximum_bridge_span_mm": 20.0,
                },
                "validation_method": (
                    "three-way OrcaSlicer comparison: production support-off, "
                    "production tree-auto, and sealed-portal support-off; "
                    "plus parsed support toolpaths and OpenCascade geometry"
                ),
                "measured_opening_ab": opening_economy.get(
                    "support_free_comparison"
                ),
                "auto_support_net_effect": opening_economy.get(
                    "if_auto_support_is_enabled"
                ),
            }
            carrier_corbel_geometry = cover.metadata[
                "component_retention"
            ]["self_supporting_base_corbels"]
            cover_xyz_cells = cover_support_envelope.get(
                "xyz_cells",
                [],
            )
            cover_low_z_cells = [
                cell
                for cell in cover_xyz_cells
                if cell.get("cell_index", [0, 0, -1])[2] == 0
            ]
            cover_low_z_move_count = sum(
                int(cell.get("extrusion_move_count", 0))
                for cell in cover_low_z_cells
            )
            cover_low_z_interface_count = sum(
                int(
                    cell.get("feature_move_counts", {}).get(
                        "support_interface",
                        0,
                    )
                )
                for cell in cover_low_z_cells
            )
            cover_support_move_count = int(
                cover_support_envelope.get(
                    "extrusion_move_count",
                    0,
                )
            )
            cover_support_interface_count = int(
                cover_support_envelope.get(
                    "feature_move_counts",
                    {},
                ).get("support_interface", 0)
            )
            carrier_corbel_baseline = {
                "version": (
                    "V70 compact carrier with unsupported outboard "
                    "rail and snap-root base bridges"
                ),
                "production_filament_weight_g": 85.14,
                "production_time_seconds": 14694,
                "auto_support_filament_weight_g": 9.75,
                "auto_support_time_seconds": 2353,
                "production_plus_support_weight_g": 94.89,
                "production_plus_support_time_seconds": 17047,
                "auto_support_extrusion_move_count": 41483,
                "auto_support_interface_move_count": 1658,
                "controller_cover_filament_weight_g": 7.91,
                "controller_cover_time_seconds": 2257,
                "controller_cover_support_filament_weight_g": 0.57,
                "controller_cover_support_time_seconds": 266,
                "controller_cover_support_extrusion_move_count": 4839,
                "controller_cover_support_interface_move_count": 339,
                "controller_cover_low_z_extrusion_move_count": 2045,
                "controller_cover_low_z_interface_move_count": 251,
            }
            checks["controller_carrier_base_corbel_support_optimization"] = {
                "passed": (
                    checks["physical_component_retention"]["passed"]
                    and checks["controller_cover_real_snap_fit"]["passed"]
                    and bool(
                        carrier_corbel_geometry["modeled_as_geometry"]
                    )
                    and int(carrier_corbel_geometry["rail_corbel_count"])
                    == 2
                    and int(
                        carrier_corbel_geometry[
                            "snap_root_corbel_count"
                        ]
                    )
                    == 2
                    and int(carrier_corbel_geometry["total_count"]) == 4
                    and float(
                        carrier_corbel_geometry[
                            "bottom_contact_footprint_expansion_mm"
                        ]
                    )
                    == 0.0
                    and float(
                        carrier_corbel_geometry["base_plate_length_mm"]
                    )
                    == 52.5
                    and float(
                        carrier_corbel_geometry["carrier_outer_span_mm"]
                    )
                    == 54.9
                    and float(
                        carrier_corbel_geometry[
                            "service_opening_length_mm"
                        ]
                    )
                    == 55.4
                    and float(
                        carrier_corbel_geometry["rail_corbel_slope_deg"]
                    )
                    >= 69.0
                    and float(
                        carrier_corbel_geometry[
                            "snap_root_corbel_slope_deg"
                        ]
                    )
                    >= 69.0
                    and historical_production_filament_weight_g <= 85.45
                    and historical_production_time_seconds <= 14820
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                support_analysis[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 9.60
                            and int(
                                support_analysis[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 2270
                            and all_support_move_count <= 40000
                            and all_support_interface_count <= 1450
                        )
                    )
                    and historical_combined_filament_weight_g <= 94.89
                    and historical_combined_print_time_seconds <= 17047
                    and float(cover_slice["filament_weight_g"]) <= 8.15
                    and int(cover_slice["estimated_seconds"]) <= 2360
                    and float(
                        cover_support["additional_filament_weight_g"]
                    )
                    <= 0.42
                    and int(
                        cover_support["additional_time_seconds"]
                    )
                    <= 175
                    and cover_support_move_count <= 3350
                    and cover_support_interface_count <= 90
                    and cover_low_z_move_count <= 550
                    and cover_low_z_interface_count == 0
                ),
                "baseline": carrier_corbel_baseline,
                "current": {
                    "geometry": carrier_corbel_geometry,
                    "production_filament_weight_g": totals[
                        "filament_weight_g"
                    ],
                    "production_time_seconds": totals[
                        "estimated_seconds"
                    ],
                    "auto_support_filament_weight_g": support_analysis[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": support_analysis[
                        "additional_time_seconds"
                    ],
                    "production_plus_support_weight_g": round(
                        combined_filament_weight_g,
                        3,
                    ),
                    "production_plus_support_time_seconds": (
                        combined_print_time_seconds
                    ),
                    "auto_support_extrusion_move_count": (
                        all_support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        all_support_interface_count
                    ),
                    "controller_cover_filament_weight_g": cover_slice[
                        "filament_weight_g"
                    ],
                    "controller_cover_time_seconds": cover_slice[
                        "estimated_seconds"
                    ],
                    "controller_cover_support_filament_weight_g": (
                        cover_support["additional_filament_weight_g"]
                    ),
                    "controller_cover_support_time_seconds": (
                        cover_support["additional_time_seconds"]
                    ),
                    "controller_cover_support_extrusion_move_count": (
                        cover_support_move_count
                    ),
                    "controller_cover_support_interface_move_count": (
                        cover_support_interface_count
                    ),
                    "controller_cover_low_z_cell_count": len(
                        cover_low_z_cells
                    ),
                    "controller_cover_low_z_extrusion_move_count": (
                        cover_low_z_move_count
                    ),
                    "controller_cover_low_z_interface_move_count": (
                        cover_low_z_interface_count
                    ),
                },
                "manufacturing_decision": (
                    "retain four local steep triangular corbels: their small "
                    "production-material cost is lower than the support they "
                    "remove, preserves the compact 52.5 mm bottom footprint "
                    "and avoids support scars beneath serviceable rails"
                ),
                "rejected_alternative": (
                    "a full 54.9 mm base plate reduced support but increased "
                    "production mass enough to raise combined material"
                ),
                "validation_method": (
                    "OpenCascade single-solid and retention checks plus "
                    "same-profile OrcaSlicer support-disabled/tree-auto A/B "
                    "with 10 x 10 x 5 mm low-Z support localization"
                ),
            }
            snap_arch_geometry = chassis.metadata[
                "controller_vent_pattern"
            ]["external_snap_arch_geometry"]
            snap_arch_support_band = next(
                (
                    band
                    for band in fan_support_z_bands
                    if band.get("actual_z_range_mm", [None])[0] == 25.0
                ),
                {},
            )
            snap_arch_band_interface_count = int(
                snap_arch_support_band.get(
                    "feature_move_counts",
                    {},
                ).get("support_interface", 0)
            )
            snap_arch_v71_baseline = {
                "version": (
                    "V71 two 24 x 12 mm snap-side arches with "
                    "7.2 mm effective crowns"
                ),
                "external_open_area_mm2": 1223.4416,
                "effective_crown_bridge_mm": 7.2,
                "production_filament_weight_g": 85.25,
                "production_time_seconds": 14730,
                "auto_support_filament_weight_g": 9.60,
                "auto_support_time_seconds": 2257,
                "production_plus_support_weight_g": 94.85,
                "production_plus_support_time_seconds": 16987,
                "auto_support_extrusion_move_count": 39966,
                "auto_support_interface_move_count": 1407,
                "fan_support_extrusion_move_count": 35970,
                "fan_support_interface_move_count": 1240,
                "z25_30_support_extrusion_move_count": 3527,
                "z25_30_support_interface_move_count": 370,
            }
            checks["snap_arch_crown_support_optimization"] = {
                "passed": (
                    checks["controller_cover_ventilation"]["passed"]
                    and int(snap_arch_geometry["count"]) == 2
                    and float(snap_arch_geometry["width_mm"]) == 24.0
                    and float(snap_arch_geometry["height_mm"]) == 12.75
                    and float(snap_arch_geometry["bottom_z_mm"]) == 13.25
                    and float(
                        snap_arch_geometry["roof_start_z_mm"]
                    )
                    == 16.25
                    and float(snap_arch_geometry["top_z_mm"]) == 26.0
                    and float(
                        snap_arch_geometry["crown_half_width_mm"]
                    )
                    == 2.25
                    and float(
                        snap_arch_geometry["effective_crown_bridge_mm"]
                    )
                    == 5.7
                    and float(
                        snap_arch_geometry["minimum_roof_slope_deg"]
                    )
                    >= 45.0
                    and float(
                        snap_arch_geometry[
                            "continuous_central_load_rib_mm"
                        ]
                    )
                    >= 3.0
                    and float(
                        chassis.metadata["controller_vent_pattern"][
                            "external_open_area_mm2"
                        ]
                    )
                    >= 1231.0
                    and historical_production_filament_weight_g <= 85.45
                    and historical_production_time_seconds <= 14820
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                support_analysis[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 9.59
                            and int(
                                support_analysis[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 2250
                            and all_support_move_count <= 39850
                            and all_support_interface_count <= 1392
                            and int(
                                fan_support_envelope.get(
                                    "extrusion_move_count",
                                    0,
                                )
                            )
                            <= 35850
                            and int(
                                fan_support_envelope.get(
                                    "feature_move_counts",
                                    {},
                                ).get("support_interface", 0)
                            )
                            <= 1225
                        )
                    )
                    and round(
                        historical_combined_filament_weight_g,
                        3,
                    )
                    <= 94.85
                    and historical_combined_print_time_seconds <= 16969
                    and int(
                        snap_arch_support_band.get(
                            "extrusion_move_count",
                            0,
                        )
                    )
                    <= 3550
                    and snap_arch_band_interface_count <= 355
                ),
                "baseline": snap_arch_v71_baseline,
                "current": {
                    "geometry": snap_arch_geometry,
                    "external_open_area_mm2": chassis.metadata[
                        "controller_vent_pattern"
                    ]["external_open_area_mm2"],
                    "production_filament_weight_g": totals[
                        "filament_weight_g"
                    ],
                    "production_time_seconds": totals[
                        "estimated_seconds"
                    ],
                    "auto_support_filament_weight_g": support_analysis[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": support_analysis[
                        "additional_time_seconds"
                    ],
                    "production_plus_support_weight_g": round(
                        combined_filament_weight_g,
                        3,
                    ),
                    "production_plus_support_time_seconds": (
                        combined_print_time_seconds
                    ),
                    "auto_support_extrusion_move_count": (
                        all_support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        all_support_interface_count
                    ),
                    "fan_support_extrusion_move_count": int(
                        fan_support_envelope.get(
                            "extrusion_move_count",
                            0,
                        )
                    ),
                    "fan_support_interface_move_count": int(
                        fan_support_envelope.get(
                            "feature_move_counts",
                            {},
                        ).get("support_interface", 0)
                    ),
                    "z25_30_support_band": snap_arch_support_band,
                },
                "manufacturing_decision": (
                    "shorten only the two snap-side crown bridges while "
                    "lowering their bottom and spring line by 0.75 mm; this "
                    "holds the 45 degree roof and 3 mm central load rib, "
                    "increases airflow and lowers combined support cost"
                ),
                "rejected_alternatives": (
                    "main-portal spring-line and fillet changes, a smaller "
                    "keyed locating pin, and 12.25/12.5 mm intermediate "
                    "snap arches failed the combined material/time Pareto gate"
                ),
                "validation_method": (
                    "OpenCascade portal area/web geometry plus same-profile "
                    "OrcaSlicer support-disabled/tree-auto A/B and the "
                    "Z=25-30 mm support-interface band"
                ),
            }
            fan_retention_geometry = chassis.metadata["fan_retention"]
            fan_retention_check = checks[
                "releasable_fan_cantilever_retention"
            ]
            fan_guard_retention_check = checks[
                "serviceable_fan_guard_retention"
            ]
            fan_upper_retention_cells = [
                cell
                for cell in xyz_cells
                if cell.get("cell_index", [0, 0, 0])[2] == 11
            ]
            fan_upper_retention_move_count = sum(
                int(cell.get("extrusion_move_count", 0))
                for cell in fan_upper_retention_cells
            )
            fan_upper_retention_interface_count = sum(
                int(
                    cell.get("feature_move_counts", {}).get(
                        "support_interface",
                        0,
                    )
                )
                for cell in fan_upper_retention_cells
            )
            fan_clip_v72_baseline = {
                "version": (
                    "V72 horizontal fan-hook undercuts with 1.7 mm "
                    "unsupported radial ledges"
                ),
                "production_filament_weight_g": 85.26,
                "production_time_seconds": 14725,
                "auto_support_filament_weight_g": 9.59,
                "auto_support_time_seconds": 2244,
                "production_plus_support_weight_g": 94.85,
                "production_plus_support_time_seconds": 16969,
                "auto_support_extrusion_move_count": 39844,
                "auto_support_interface_move_count": 1392,
                "fan_support_extrusion_move_count": 35848,
                "fan_support_interface_move_count": 1225,
                "upper_retention_cell_count": 11,
                "upper_retention_extrusion_move_count": 1097,
                "upper_retention_interface_move_count": 351,
            }
            checks["fan_clip_undercut_support_optimization"] = {
                "passed": (
                    fan_retention_check["passed"]
                    and fan_guard_retention_check["passed"]
                    and int(fan_retention_geometry["clip_count"]) == 4
                    and float(
                        fan_retention_geometry["hook_overlap_mm"]
                    )
                    == 0.25
                    and float(
                        fan_retention_geometry[
                            "hook_contact_flat_span_mm"
                        ]
                    )
                    == 0.4
                    and float(
                        fan_retention_geometry[
                            "hook_undercut_ramp_run_mm"
                        ]
                    )
                    >= 1.29
                    and float(
                        fan_retention_geometry[
                            "hook_undercut_angle_deg"
                        ]
                    )
                    >= 45.0
                    and float(
                        fan_retention_geometry["nominal_surface_strain"]
                    )
                    <= 0.02
                    and float(
                        fan_retention_check["fan_chassis_overlap_mm3"]
                    )
                    <= 0.01
                    and float(
                        fan_guard_retention_check[
                            "fan_hook_stop_overlap_mm3"
                        ]
                    )
                    >= 0.20
                    and not bool(totals["support_used"])
                    and historical_production_filament_weight_g <= 85.45
                    and historical_production_time_seconds <= 14820
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                support_analysis[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 9.40
                            and int(
                                support_analysis[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 2190
                            and all_support_move_count <= 38000
                            and all_support_interface_count <= 1150
                            and int(
                                fan_support_envelope.get(
                                    "extrusion_move_count",
                                    0,
                                )
                            )
                            <= 34000
                            and int(
                                fan_support_envelope.get(
                                    "feature_move_counts",
                                    {},
                                ).get("support_interface", 0)
                            )
                            <= 980
                        )
                    )
                    and round(
                        historical_combined_filament_weight_g,
                        3,
                    )
                    <= 94.70
                    and historical_combined_print_time_seconds <= 16940
                    and fan_upper_retention_move_count <= 550
                    and fan_upper_retention_interface_count <= 100
                ),
                "baseline": fan_clip_v72_baseline,
                "current": {
                    "geometry": {
                        "clip_count": fan_retention_geometry["clip_count"],
                        "hook_overlap_mm": fan_retention_geometry[
                            "hook_overlap_mm"
                        ],
                        "hook_contact_flat_span_mm": (
                            fan_retention_geometry[
                                "hook_contact_flat_span_mm"
                            ]
                        ),
                        "hook_undercut_ramp_run_mm": (
                            fan_retention_geometry[
                                "hook_undercut_ramp_run_mm"
                            ]
                        ),
                        "hook_undercut_angle_deg": (
                            fan_retention_geometry[
                                "hook_undercut_angle_deg"
                            ]
                        ),
                        "nominal_surface_strain": (
                            fan_retention_geometry[
                                "nominal_surface_strain"
                            ]
                        ),
                        "fan_chassis_overlap_mm3": (
                            fan_retention_check[
                                "fan_chassis_overlap_mm3"
                            ]
                        ),
                        "fan_hook_stop_overlap_mm3": (
                            fan_guard_retention_check[
                                "fan_hook_stop_overlap_mm3"
                            ]
                        ),
                    },
                    "production_filament_weight_g": totals[
                        "filament_weight_g"
                    ],
                    "production_time_seconds": totals[
                        "estimated_seconds"
                    ],
                    "auto_support_filament_weight_g": support_analysis[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": support_analysis[
                        "additional_time_seconds"
                    ],
                    "production_plus_support_weight_g": round(
                        combined_filament_weight_g,
                        3,
                    ),
                    "production_plus_support_time_seconds": (
                        combined_print_time_seconds
                    ),
                    "auto_support_extrusion_move_count": (
                        all_support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        all_support_interface_count
                    ),
                    "fan_support_extrusion_move_count": int(
                        fan_support_envelope.get(
                            "extrusion_move_count",
                            0,
                        )
                    ),
                    "fan_support_interface_move_count": int(
                        fan_support_envelope.get(
                            "feature_move_counts",
                            {},
                        ).get("support_interface", 0)
                    ),
                    "upper_retention_cell_count": len(
                        fan_upper_retention_cells
                    ),
                    "upper_retention_extrusion_move_count": (
                        fan_upper_retention_move_count
                    ),
                    "upper_retention_interface_move_count": (
                        fan_upper_retention_interface_count
                    ),
                },
                "manufacturing_decision": (
                    "replace each 1.7 mm horizontal fan-hook undercut with "
                    "a 45 degree 1.3 mm ramp and one 0.4 mm nozzle-width "
                    "contact flat; preserve the 0.25 mm fan overlap and "
                    "measured OpenCascade hook stop"
                ),
                "validation_method": (
                    "exact installed-fan and 0.26 mm upward-stop "
                    "OpenCascade intersections plus same-profile "
                    "OrcaSlicer support-disabled/tree-auto A/B and the "
                    "Z=55-60 mm XYZ contact band"
                ),
            }
            probe_retention_geometry = cover.metadata[
                "ds18b20_probe_retention"
            ]
            probe_retention_check = checks[
                "serviceable_ds18b20_probe_retention"
            ]
            probe_platform_v73_baseline = {
                "version": (
                    "V73 9 x 8 mm DS18B20 platform carried only by a "
                    "1 mm center column"
                ),
                "production_filament_weight_g": 85.28,
                "production_time_seconds": 14749,
                "auto_support_filament_weight_g": 9.39,
                "auto_support_time_seconds": 2173,
                "production_plus_support_weight_g": 94.67,
                "production_plus_support_time_seconds": 16922,
                "auto_support_extrusion_move_count": 37948,
                "auto_support_interface_move_count": 1142,
                "controller_cover_filament_weight_g": 8.02,
                "controller_cover_time_seconds": 2294,
                "controller_cover_support_filament_weight_g": 0.42,
                "controller_cover_support_time_seconds": 169,
                "controller_cover_support_extrusion_move_count": 3322,
                "controller_cover_support_interface_move_count": 88,
            }
            checks["probe_platform_corbel_support_optimization"] = {
                "passed": (
                    probe_retention_check["passed"]
                    and checks["physical_ds18b20_fit_coupon"]["passed"]
                    and int(
                        probe_retention_geometry[
                            "support_platform_corbel_count"
                        ]
                    )
                    == 2
                    and float(
                        probe_retention_geometry[
                            "support_platform_corbel_run_mm"
                        ]
                    )
                    == 4.0
                    and float(
                        probe_retention_geometry[
                            "support_platform_corbel_rise_mm"
                        ]
                    )
                    == 4.0
                    and float(
                        probe_retention_geometry[
                            "support_platform_corbel_slope_deg"
                        ]
                    )
                    >= 45.0
                    and float(
                        probe_retention_geometry[
                            "support_platform_corbel_depth_mm"
                        ]
                    )
                    == 8.0
                    and float(
                        probe_retention_geometry[
                            "support_platform_bridge_span_mm"
                        ]
                    )
                    == 0.0
                    and float(
                        probe_retention_check[
                            "nominal_cover_overlap_mm3"
                        ]
                    )
                    <= 0.01
                    and float(
                        probe_retention_check[
                            "release_path_max_overlap_mm3"
                        ]
                    )
                    >= 1.0
                    and float(
                        probe_retention_check[
                            "release_path_final_overlap_mm3"
                        ]
                    )
                    <= 0.01
                    and float(
                        probe_retention_check["chassis_overlap_mm3"]
                    )
                    <= 0.01
                    and float(
                        probe_retention_check["guard_overlap_mm3"]
                    )
                    <= 0.01
                    and float(
                        probe_retention_check["fan_overlap_mm3"]
                    )
                    <= 0.01
                    and not bool(totals["support_used"])
                    and historical_production_filament_weight_g <= 85.45
                    and historical_production_time_seconds <= 14820
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                support_analysis[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 9.0
                            and int(
                                support_analysis[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 2025
                            and all_support_move_count <= 34700
                            and all_support_interface_count <= 1060
                        )
                    )
                    and round(
                        historical_combined_filament_weight_g,
                        3,
                    )
                    <= 94.40
                    and historical_combined_print_time_seconds <= 16830
                    and float(cover_slice["filament_weight_g"]) <= 8.15
                    and int(cover_slice["estimated_seconds"]) <= 2360
                    and float(
                        cover_support.get(
                            "additional_filament_weight_g",
                            0.0,
                        )
                    )
                    <= 0.01
                    and int(
                        cover_support.get(
                            "additional_time_seconds",
                            0,
                        )
                    )
                    <= 5
                    and cover_support_move_count == 0
                    and cover_support_interface_count == 0
                ),
                "baseline": probe_platform_v73_baseline,
                "current": {
                    "geometry": {
                        "bearing_count": probe_retention_geometry[
                            "bearing_count"
                        ],
                        "support_column_count": (
                            probe_retention_geometry[
                                "support_column_count"
                            ]
                        ),
                        "platform_dimensions_mm": (
                            probe_retention_geometry[
                                "support_platform_dimensions_mm"
                            ]
                        ),
                        "corbel_count": probe_retention_geometry[
                            "support_platform_corbel_count"
                        ],
                        "corbel_run_mm": probe_retention_geometry[
                            "support_platform_corbel_run_mm"
                        ],
                        "corbel_rise_mm": probe_retention_geometry[
                            "support_platform_corbel_rise_mm"
                        ],
                        "corbel_slope_deg": probe_retention_geometry[
                            "support_platform_corbel_slope_deg"
                        ],
                        "corbel_depth_mm": probe_retention_geometry[
                            "support_platform_corbel_depth_mm"
                        ],
                        "platform_bridge_span_mm": (
                            probe_retention_geometry[
                                "support_platform_bridge_span_mm"
                            ]
                        ),
                        "release_path_final_overlap_mm3": (
                            probe_retention_check[
                                "release_path_final_overlap_mm3"
                            ]
                        ),
                    },
                    "production_filament_weight_g": totals[
                        "filament_weight_g"
                    ],
                    "production_time_seconds": totals[
                        "estimated_seconds"
                    ],
                    "auto_support_filament_weight_g": support_analysis[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": support_analysis[
                        "additional_time_seconds"
                    ],
                    "production_plus_support_weight_g": round(
                        combined_filament_weight_g,
                        3,
                    ),
                    "production_plus_support_time_seconds": (
                        combined_print_time_seconds
                    ),
                    "auto_support_extrusion_move_count": (
                        all_support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        all_support_interface_count
                    ),
                    "controller_cover_filament_weight_g": cover_slice[
                        "filament_weight_g"
                    ],
                    "controller_cover_time_seconds": cover_slice[
                        "estimated_seconds"
                    ],
                    "controller_cover_support_filament_weight_g": (
                        cover_support.get(
                            "additional_filament_weight_g",
                            0.0,
                        )
                    ),
                    "controller_cover_support_time_seconds": (
                        cover_support.get(
                            "additional_time_seconds",
                            0,
                        )
                    ),
                    "controller_cover_support_extrusion_move_count": (
                        cover_support_move_count
                    ),
                    "controller_cover_support_interface_move_count": (
                        cover_support_interface_count
                    ),
                },
                "manufacturing_decision": (
                    "carry the full 9 x 8 mm DS18B20 bearing platform on "
                    "two local 45 degree corbels instead of widening its "
                    "entire 1 mm center column; accept the small production "
                    "mass only when controller support falls to zero and "
                    "combined material and time improve"
                ),
                "rejected_alternative": (
                    "four 2 mm-deep edge ribs left 0.43 g of automatic "
                    "support and raised combined material and time"
                ),
                "validation_method": (
                    "exact OpenCascade probe fit/release and installed "
                    "hardware intersections plus same-profile OrcaSlicer "
                    "support-disabled/tree-auto A/B and controller-cover "
                    "XYZ contact localization"
                ),
            }
            cradle_slice = manufacturing["parts"]["mac_mini_cradle"]
            cradle_support = support_analysis["parts"].get(
                "mac_mini_cradle",
                {},
            )
            cradle_support_envelope = cradle_support.get(
                "support_toolpath_envelope",
                {},
            )
            cradle_support_move_count = int(
                cradle_support_envelope.get("extrusion_move_count", 0)
            )
            cradle_support_interface_count = int(
                cradle_support_envelope.get(
                    "feature_move_counts",
                    {},
                ).get("support_interface", 0)
            )
            cradle_interface = cradle.metadata["locating_interface"]
            cradle_socket_v74_baseline = {
                "version": (
                    "V74 four 3.25 mm blind locating sockets with "
                    "0.75 mm horizontal roofs"
                ),
                "production_filament_weight_g": 85.39,
                "production_time_seconds": 14799,
                "auto_support_filament_weight_g": 8.97,
                "auto_support_time_seconds": 2006,
                "production_plus_support_weight_g": 94.36,
                "production_plus_support_time_seconds": 16805,
                "auto_support_extrusion_move_count": 34626,
                "auto_support_interface_move_count": 1054,
                "cradle_filament_weight_g": 22.10,
                "cradle_time_seconds": 2689,
                "cradle_support_filament_weight_g": 0.07,
                "cradle_support_time_seconds": 41,
                "cradle_support_extrusion_move_count": 674,
                "cradle_support_interface_move_count": 79,
            }
            checks["cradle_through_socket_support_optimization"] = {
                "passed": (
                    checks["physical_screwless_stack_interface"]["passed"]
                    and checks["cradle_integrated_outer_contour"]["passed"]
                    and cradle_interface["socket_type"] == "through"
                    and bool(cradle_interface["through_sockets"])
                    and int(cradle_interface["pin_count"]) == 4
                    and bool(cradle_interface["keyed"])
                    and float(cradle_interface["radial_clearance_mm"])
                    == 0.25
                    and float(cradle_interface["top_skin_mm"]) == 0.0
                    and float(
                        cradle_interface[
                            "pin_tip_recess_below_support_plane_mm"
                        ]
                    )
                    >= 0.75
                    and float(
                        cradle_interface["minimum_outer_ligament_mm"]
                    )
                    >= 4.5
                    and float(
                        cradle_interface["minimum_device_cover_mm"]
                    )
                    >= 1.0
                    and not bool(
                        cradle.metadata["exterior_continuity"][
                            "locating_sockets_break_outer_edge"
                        ]
                    )
                    and not bool(totals["support_used"])
                    and historical_production_filament_weight_g
                    <= 85.40 + fixed_desk_island_mass_allowance_g
                    and historical_production_time_seconds
                    <= 14820 + fixed_desk_island_time_allowance_seconds
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                support_analysis[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 8.93
                            and int(
                                support_analysis[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 1980
                            and all_support_move_count <= 34000
                            and all_support_interface_count <= 985
                        )
                    )
                    and round(
                        historical_combined_filament_weight_g,
                        3,
                    )
                    <= 94.25 + fixed_desk_island_mass_allowance_g
                    and historical_combined_print_time_seconds
                    <= 16790 + fixed_desk_island_time_allowance_seconds
                    and float(cradle_slice["filament_weight_g"]) <= 22.05
                    and int(cradle_slice["estimated_seconds"]) <= 2710
                    and float(
                        cradle_support.get(
                            "additional_filament_weight_g",
                            0.0,
                        )
                    )
                    <= 0.01
                    and int(
                        cradle_support.get(
                            "additional_time_seconds",
                            0,
                        )
                    )
                    <= 5
                    and cradle_support_move_count == 0
                    and cradle_support_interface_count == 0
                ),
                "baseline": cradle_socket_v74_baseline,
                "required_safety_feature_allowance": {
                    "feature": "fixed chassis desk-load island",
                    "filament_weight_g": (
                        fixed_desk_island_mass_allowance_g
                    ),
                    "print_time_seconds": (
                        fixed_desk_island_time_allowance_seconds
                    ),
                },
                "current": {
                    "geometry": {
                        "socket_type": cradle_interface["socket_type"],
                        "socket_count": cradle_interface["pin_count"],
                        "socket_depth_mm": cradle_interface[
                            "socket_depth_mm"
                        ],
                        "socket_overcut_mm": cradle_interface[
                            "socket_overcut_mm"
                        ],
                        "radial_clearance_mm": cradle_interface[
                            "radial_clearance_mm"
                        ],
                        "pin_tip_recess_below_support_plane_mm": (
                            cradle_interface[
                                "pin_tip_recess_below_support_plane_mm"
                            ]
                        ),
                        "minimum_outer_ligament_mm": cradle_interface[
                            "minimum_outer_ligament_mm"
                        ],
                        "minimum_device_cover_mm": cradle_interface[
                            "minimum_device_cover_mm"
                        ],
                        "locating_sockets_break_outer_edge": (
                            cradle.metadata["exterior_continuity"][
                                "locating_sockets_break_outer_edge"
                            ]
                        ),
                    },
                    "production_filament_weight_g": totals[
                        "filament_weight_g"
                    ],
                    "production_time_seconds": totals[
                        "estimated_seconds"
                    ],
                    "auto_support_filament_weight_g": support_analysis[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": support_analysis[
                        "additional_time_seconds"
                    ],
                    "production_plus_support_weight_g": round(
                        combined_filament_weight_g,
                        3,
                    ),
                    "production_plus_support_time_seconds": (
                        combined_print_time_seconds
                    ),
                    "auto_support_extrusion_move_count": (
                        all_support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        all_support_interface_count
                    ),
                    "cradle_filament_weight_g": cradle_slice[
                        "filament_weight_g"
                    ],
                    "cradle_time_seconds": cradle_slice[
                        "estimated_seconds"
                    ],
                    "cradle_support_filament_weight_g": (
                        cradle_support.get(
                            "additional_filament_weight_g",
                            0.0,
                        )
                    ),
                    "cradle_support_time_seconds": cradle_support.get(
                        "additional_time_seconds",
                        0,
                    ),
                    "cradle_support_extrusion_move_count": (
                        cradle_support_move_count
                    ),
                    "cradle_support_interface_move_count": (
                        cradle_support_interface_count
                    ),
                },
                "manufacturing_decision": (
                    "make the four internal locating sockets through-holes "
                    "because the planar cradle/chassis faces carry vertical "
                    "load and the pins carry only lateral and anti-rotation "
                    "load; keep each pin tip recessed 1 mm below the Mac "
                    "support plane and every hole hidden under the device"
                ),
                "rejected_alternative": (
                    "retain 0.75 mm blind roofs: they add material and create "
                    "four enclosed support islands that are difficult to "
                    "clean without improving the load path"
                ),
                "validation_method": (
                    "exact parametric socket/pin envelope and exterior-edge "
                    "ligament checks plus identical-orientation OrcaSlicer "
                    "support-disabled/tree-auto A/B and XYZ contact paths"
                ),
            }
            controller_service_access = chassis.metadata[
                "controller_service_access"
            ]
            usb_service_support_cells = [
                cell
                for cell in xyz_cells
                if (
                    float(
                        cell.get(
                            "actual_local_bbox_xyz_mm",
                            [math.inf] * 6,
                        )[0]
                    )
                    >= 5.0
                    and float(
                        cell.get(
                            "actual_local_bbox_xyz_mm",
                            [-math.inf] * 6,
                        )[3]
                    )
                    <= 10.1
                    and float(
                        cell.get(
                            "actual_local_bbox_xyz_mm",
                            [math.inf] * 6,
                        )[1]
                    )
                    >= 15.0
                    and float(
                        cell.get(
                            "actual_local_bbox_xyz_mm",
                            [-math.inf] * 6,
                        )[4]
                    )
                    <= 35.0
                    and float(
                        cell.get(
                            "actual_local_bbox_xyz_mm",
                            [math.inf] * 6,
                        )[2]
                    )
                    >= 20.0
                )
            ]
            usb_service_support_move_count = sum(
                int(cell.get("extrusion_move_count", 0))
                for cell in usb_service_support_cells
            )
            usb_service_support_interface_count = sum(
                int(
                    cell.get("feature_move_counts", {}).get(
                        "support_interface",
                        0,
                    )
                )
                for cell in usb_service_support_cells
            )
            usb_service_ellipse_v75_baseline = {
                "version": (
                    "V75 20 x 12 mm horizontal elliptical USB service port"
                ),
                "port_open_area_mm2": round(math.pi * 10.0 * 6.0, 3),
                "production_filament_weight_g": 85.31,
                "production_time_seconds": 14804,
                "auto_support_filament_weight_g": 8.90,
                "auto_support_time_seconds": 1967,
                "production_plus_support_weight_g": 94.21,
                "production_plus_support_time_seconds": 16771,
                "auto_support_extrusion_move_count": 33952,
                "auto_support_interface_move_count": 975,
                "fan_chassis_filament_weight_g": 46.07,
                "fan_chassis_time_seconds": 7131,
                "fan_chassis_support_filament_weight_g": 8.90,
                "fan_chassis_support_time_seconds": 1965,
                "usb_hotspot_cell_count": 4,
                "usb_hotspot_extrusion_move_count": 1100,
                "usb_hotspot_interface_move_count": 50,
            }
            checks["usb_service_arch_support_optimization"] = {
                "passed": (
                    checks["serviceable_electronics_carrier"]["passed"]
                    and controller_service_access["port_style"]
                    == "rounded self-supporting inboard service arch"
                    and list(
                        controller_service_access[
                            "usb_port_dimensions_mm"
                        ]
                    )
                    == [20.0, 12.5]
                    and float(
                        controller_service_access[
                            "port_minimum_roof_slope_deg"
                        ]
                    )
                    >= 45.0
                    and float(
                        controller_service_access[
                            "port_effective_bridge_mm"
                        ]
                    )
                    <= 5.2
                    and float(
                        controller_service_access["port_open_area_mm2"]
                    )
                    >= 185.0
                    and float(
                        controller_service_access[
                            "residual_after_cut_mm3"
                        ]
                    )
                    <= 0.01
                    and float(
                        checks["serviceable_electronics_carrier"][
                            "usb_corridor_cover_obstruction_mm3"
                        ]
                    )
                    <= 0.01
                    and float(
                        checks["serviceable_electronics_carrier"][
                            "usb_corridor_chassis_obstruction_mm3"
                        ]
                    )
                    <= 0.01
                    and not bool(totals["support_used"])
                    and historical_production_filament_weight_g
                    <= 85.38 + fixed_desk_island_mass_allowance_g
                    and historical_production_time_seconds
                    <= 14820 + fixed_desk_island_time_allowance_seconds
                    and (
                        not bool(support_analysis["support_required"])
                        or (
                            float(
                                support_analysis[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 8.66
                            and int(
                                support_analysis[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 1890
                            and all_support_move_count <= 33000
                            and all_support_interface_count <= 970
                            and float(
                                fan_support[
                                    "additional_filament_weight_g"
                                ]
                            )
                            <= 8.66
                            and int(
                                fan_support[
                                    "additional_time_seconds"
                                ]
                            )
                            <= 1890
                        )
                    )
                    and round(
                        historical_combined_filament_weight_g,
                        3,
                    )
                    <= 94.02 + fixed_desk_island_mass_allowance_g
                    and historical_combined_print_time_seconds
                    <= 16700 + fixed_desk_island_time_allowance_seconds
                    and historical_fan_filament_weight_g
                    <= 46.12 + fixed_desk_island_mass_allowance_g
                    and historical_fan_time_seconds
                    <= 7140 + fixed_desk_island_time_allowance_seconds
                    and len(usb_service_support_cells) <= 2
                    and usb_service_support_move_count <= 250
                    and usb_service_support_interface_count <= 25
                ),
                "baseline": usb_service_ellipse_v75_baseline,
                "required_safety_feature_allowance": {
                    "feature": "fixed chassis desk-load island",
                    "filament_weight_g": (
                        fixed_desk_island_mass_allowance_g
                    ),
                    "print_time_seconds": (
                        fixed_desk_island_time_allowance_seconds
                    ),
                    "support_path_move_tolerance": 400,
                },
                "current": {
                    "geometry": controller_service_access,
                    "usb_corridor_cover_obstruction_mm3": checks[
                        "serviceable_electronics_carrier"
                    ]["usb_corridor_cover_obstruction_mm3"],
                    "usb_corridor_chassis_obstruction_mm3": checks[
                        "serviceable_electronics_carrier"
                    ]["usb_corridor_chassis_obstruction_mm3"],
                    "production_filament_weight_g": totals[
                        "filament_weight_g"
                    ],
                    "production_time_seconds": totals[
                        "estimated_seconds"
                    ],
                    "auto_support_filament_weight_g": support_analysis[
                        "additional_filament_weight_g"
                    ],
                    "auto_support_time_seconds": support_analysis[
                        "additional_time_seconds"
                    ],
                    "production_plus_support_weight_g": round(
                        combined_filament_weight_g,
                        3,
                    ),
                    "production_plus_support_time_seconds": (
                        combined_print_time_seconds
                    ),
                    "auto_support_extrusion_move_count": (
                        all_support_move_count
                    ),
                    "auto_support_interface_move_count": (
                        all_support_interface_count
                    ),
                    "fan_chassis_filament_weight_g": fan_slice[
                        "filament_weight_g"
                    ],
                    "fan_chassis_time_seconds": fan_slice[
                        "estimated_seconds"
                    ],
                    "fan_chassis_support_filament_weight_g": fan_support[
                        "additional_filament_weight_g"
                    ],
                    "fan_chassis_support_time_seconds": fan_support[
                        "additional_time_seconds"
                    ],
                    "usb_hotspot_cell_count": len(
                        usb_service_support_cells
                    ),
                    "usb_hotspot_extrusion_move_count": (
                        usb_service_support_move_count
                    ),
                    "usb_hotspot_interface_move_count": (
                        usb_service_support_interface_count
                    ),
                    "usb_hotspot_cells": usb_service_support_cells,
                },
                "manufacturing_decision": (
                    "retain essentially the full USB service opening while "
                    "replacing the elliptical horizontal roof with rounded "
                    "45 degree shoulders and a 5.2 mm crown; this preserves "
                    "tool-free ESP32 access but sharply reduces the local "
                    "support contact generated inside the electronics pod"
                ),
                "rejected_alternative": (
                    "closing or materially narrowing the service port would "
                    "reduce support by blocking maintenance; retaining the "
                    "ellipse keeps a broad shallow roof that attracts support"
                ),
                "validation_method": (
                    "exact OpenCascade port residual and USB plug-corridor "
                    "intersections plus identical-orientation OrcaSlicer "
                    "support-disabled/tree-auto A/B and localized 10 x 10 x "
                    "5 mm XYZ support-contact cells"
                ),
            }
            print_layout = (preview_manifest or {}).get(
                "print_layout",
                {},
            )
            layout_items = print_layout.get("items", [])
            printed_layout_items = [
                item
                for item in layout_items
                if not item.get("is_reference")
            ]
            support_visuals = [
                item
                for item in layout_items
                if item.get("reference_kind")
                in {
                    "auto_support_envelope",
                    "auto_support_band",
                }
            ]
            support_visualized_parts = {
                str(item.get("name", "")).split(" · ", 1)[0]
                for item in support_visuals
            }
            expected_support_envelopes = sum(
                1
                for part in support_analysis["parts"].values()
                if int(
                    part.get("support_toolpath_envelope", {}).get(
                        "extrusion_move_count",
                        0,
                    )
                )
                > 0
            )
            checks["support_aware_print_preview"] = {
                "passed": (
                    bool(print_layout.get("measured_from_slicer"))
                    and len(printed_layout_items) == len(parts)
                    and len(support_visualized_parts)
                    == expected_support_envelopes
                    and all(
                        item.get("print_metrics", {}).get(
                            "production_support_used"
                        )
                        is False
                        and float(
                            item.get("print_metrics", {}).get(
                                "max_bridge_span_mm",
                                math.inf,
                            )
                        )
                        <= 20.0
                        for item in printed_layout_items
                    )
                ),
                "printed_part_count": len(printed_layout_items),
                "support_visual_count": len(support_visuals),
                "support_visualized_part_count": len(
                    support_visualized_parts
                ),
                "expected_support_envelope_count": (
                    expected_support_envelopes
                ),
                "production_orientation_source": (
                    "OrcaSlicer rotation_deg and exported STL bounds"
                ),
                "support_envelope_source": (
                    "parsed positive-extrusion support toolpaths from "
                    "the tree(auto) comparison G-code 3MF, rendered as "
                    "5 mm Z bands when layer-resolved data is available"
                ),
            }
            xyz_contact_visuals = [
                item
                for item in layout_items
                if item.get("reference_kind")
                == "auto_support_xyz_cell"
            ]
            checks["support_xyz_contact_preview"] = {
                "passed": (
                    len(xyz_contact_visuals) > 0
                    and all(
                        len(item.get("dimensions_mm", [])) == 3
                        and [
                            round(float(value), 3)
                            for value in item["dimensions_mm"]
                        ]
                        == [10.0, 10.0, 5.0]
                        and int(
                            item.get(
                                "support_xyz_cell",
                                {},
                            )
                            .get("feature_move_counts", {})
                            .get("support_interface", 0)
                        )
                        > 0
                        for item in xyz_contact_visuals
                    )
                ),
                "visual_count": len(xyz_contact_visuals),
                "cell_size_mm": [10.0, 10.0, 5.0],
                "reference_kind": "auto_support_xyz_cell",
                "selection_rule": (
                    "up to 12 highest interface-count cells per part; "
                    "cells without support-interface moves are excluded"
                ),
                "source": (
                    "support-interface positive-extrusion toolpaths parsed "
                    "from the OrcaSlicer tree(auto) G-code 3MF"
                ),
            }
        return {
            "case": "Apple Mac mini M4 Floating Halo cooling dock",
            "passed": all(check["passed"] for check in checks.values()),
            "checks": checks,
            "physical_verification_required": [
                "Mac mini bottom foot exact profile and vent diameter",
                "power button and cable motion clearance",
                "selected fan thickness and connector exit",
                "PETG fit coupon before full print",
                "temperature and acoustic test on physical prototype",
            ],
        }

    @staticmethod
    def _preview_manifest(
        parts: list[CADPart],
        assembly,
        proposal=None,
        *,
        reference_parts: list[CADPart] | None = None,
        calibration_parts: list[CADPart] | None = None,
        support_modifier_parts: list[CADPart] | None = None,
        manufacturing_control_parts: list[CADPart] | None = None,
        manufacturing: dict[str, Any] | None = None,
        structure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        items = []
        service_access_items = []
        service_sequence = []
        mac_interface_access_items = []
        printed_material_colors = {
            "fan_chassis": [0.55, 0.74, 0.12],
            "controller_cover": [0.24, 0.42, 0.10],
            "fan_guard": [0.68, 0.52, 0.18],
            "mac_mini_cradle": [0.55, 0.74, 0.12],
            "power_button_plunger": [0.86, 0.66, 0.22],
        }
        for part in parts:
            translation, rotation = assembly.placements[part.name].toTuple()
            items.append(
                {
                    "name": part.name,
                    "file_name": f"{part.name}.stl",
                    "dimensions_mm": list(part.metadata["dimensions_mm"]),
                    "translation_mm": list(translation),
                    "rotation_deg": list(rotation),
                    "color_rgb": printed_material_colors.get(
                        part.name,
                        [0.55, 0.74, 0.12],
                    ),
                }
            )
        references = []
        if proposal and proposal.brief.design_family == "smart_fan":
            cradle = next(part for part in parts if part.name == "mac_mini_cradle")
            cradle_translation, _ = assembly.placements[cradle.name].toTuple()
            mac_reference = next(
                part
                for part in reference_parts or []
                if part.name == "mac_mini_m4_fit_reference"
            )
            references.append(
                {
                    "name": (
                        "Mac mini M4 · "
                        + "×".join(
                            f"{float(value):g}"
                            for value in mac_reference.metadata[
                                "dimensions_mm"
                            ]
                        )
                        + " mm reference"
                    ),
                    "file_name": f"{mac_reference.name}.stl",
                    "dimensions_mm": list(
                        mac_reference.metadata["dimensions_mm"]
                    ),
                    "translation_mm": [
                        0.0,
                        0.0,
                        cradle_translation[2]
                        + float(
                            cradle.metadata["device_support_height_mm"]
                        ),
                    ],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "is_reference": True,
                    "reference_kind": "device",
                    "color_rgb": list(mac_reference.metadata["color_rgb"]),
                    "opacity": mac_reference.metadata["opacity"],
                }
            )
            mac_reference_base_z = (
                float(cradle_translation[2])
                + float(cradle.metadata["device_support_height_mm"])
            )
            for corridor in _mac_interface_corridor_specs(
                mac_reference,
                installed_base_z_mm=mac_reference_base_z,
            ):
                mac_interface_access_items.append(
                    {
                        **corridor,
                        "primitive": "box",
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "is_reference": True,
                        "reference_kind": "device_interface_access",
                        "color_rgb": (
                            [0.1, 0.9, 1.0]
                            if corridor["face"] == "front"
                            else [1.0, 0.55, 0.12]
                        ),
                        "opacity": 0.32,
                        "available_after": (
                            "Mac mini installed; matching front/rear face "
                            "remains horizontally exposed"
                        ),
                    }
                )
            for hardware in (
                part
                for part in reference_parts or []
                if part.name != "mac_mini_m4_fit_reference"
                and part.metadata.get("is_reference")
            ):
                references.append(
                    {
                        "name": hardware.metadata["display_name"],
                        "file_name": f"{hardware.name}.stl",
                        "dimensions_mm": list(
                            hardware.metadata["dimensions_mm"]
                        ),
                        "translation_mm": list(
                            hardware.metadata["translation_mm"]
                        ),
                        "rotation_deg": list(
                            hardware.metadata["rotation_deg"]
                        ),
                        "is_reference": True,
                        "reference_kind": hardware.metadata[
                            "reference_kind"
                        ],
                        "color_rgb": list(
                            hardware.metadata["color_rgb"]
                        ),
                        "opacity": float(hardware.metadata["opacity"]),
                    }
                )
            cover = next(
                part for part in parts
                if part.name == "controller_cover"
            )
            cover_translation, _ = assembly.placements[
                cover.name
            ].toTuple()
            service_access = cover.metadata.get(
                "electronics_service_access",
                {},
            )
            service_sequence = list(
                service_access.get("service_sequence", ())
            )
            service_zones = [
                service_access.get("usb_corridor"),
                *service_access.get("terminal_tool_zones", ()),
                *service_access.get("release_tool_zones", ()),
            ]
            service_colors = {
                "usb_service": [0.18, 0.95, 1.0],
                "terminal_tool": [0.96, 0.72, 0.24],
                "clip_release": [0.92, 0.38, 0.78],
            }
            for zone in (
                item for item in service_zones if item
            ):
                center = [
                    float(zone["center_mm"][index])
                    + float(cover_translation[index])
                    for index in range(3)
                ]
                service_access_items.append(
                    {
                        "name": zone["name"],
                        "primitive": "box",
                        "dimensions_mm": list(
                            zone["dimensions_mm"]
                        ),
                        "translation_mm": center,
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "is_reference": True,
                        "reference_kind": "service_access",
                        "color_rgb": service_colors[
                            zone["kind"]
                        ],
                        "opacity": 0.34,
                        "available_after": zone[
                            "available_after"
                        ],
                    }
                )
        return {
            "assembly": {
                "name": assembly.name,
                "items": items + references,
            },
            "parts": [
                {
                    "name": item["name"],
                    "file_name": item["file_name"],
                    "dimensions_mm": item["dimensions_mm"],
                    "color_rgb": item["color_rgb"],
                }
                for item in items
            ],
            "service_access": {
                "items": service_access_items,
                "sequence": service_sequence,
            },
            "mac_interface_access": {
                "items": mac_interface_access_items,
                "notes": [
                    (
                        "青色为前面接口插拔净空，橙色为后面接口插拔净空；"
                        "透明盒不是打印件。"
                    ),
                    (
                        "每个净空体向机身内进入 3 mm、向外延伸 25 mm，"
                        "并在接口四周保留 2 mm 操作余量。"
                    ),
                    (
                        "接口类型依据 Apple 规格，坐标是工程近似值；"
                        "正式生产前仍需用实机复核。"
                    ),
                    (
                        "后侧电源与网口共用一个圆角维护开口，连续 4 mm "
                        "底环保持完整，打印无需支撑。"
                    ),
                ],
            },
            "structural_load_path": (
                IndustrialDesignWorkflow._structural_load_preview(structure)
                if structure is not None
                else {"items": [], "notes": []}
            ),
            "calibration": {
                "items": [
                    {
                        "name": part.name,
                        "display_name": part.metadata["display_name"],
                        "file_name": f"{part.name}.stl",
                        "dimensions_mm": list(part.metadata["dimensions_mm"]),
                        "translation_mm": [0.0, 0.0, 0.0],
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "calibration_kind": part.metadata[
                            "calibration_kind"
                        ],
                    }
                    for part in calibration_parts or []
                ]
            },
            "support_modifiers": {
                "items": [
                    {
                        "name": part.name,
                        "display_name": part.metadata["display_name"],
                        "file_name": f"{part.name}.stl",
                        "dimensions_mm": list(
                            part.metadata["dimensions_mm"]
                        ),
                        "translation_mm": list(
                            part.metadata["translation_mm"]
                        ),
                        "rotation_deg": list(
                            part.metadata["rotation_deg"]
                        ),
                        "is_reference": True,
                        "reference_kind": "support_modifier",
                        "color_rgb": list(
                            part.metadata["color_rgb"]
                        ),
                        "opacity": float(part.metadata["opacity"]),
                        "source_cell_count": part.metadata[
                            "source_cell_count"
                        ],
                        "source_support_extrusion_move_count": (
                            part.metadata[
                                "source_support_extrusion_move_count"
                            ]
                        ),
                        "source_support_interface_move_count": (
                            part.metadata[
                                "source_support_interface_move_count"
                            ]
                        ),
                        "operator_use": part.metadata["operator_use"],
                    }
                    for part in support_modifier_parts or []
                ],
                "notes": [
                    (
                        "Modifier STL 与 fan_chassis.stl 使用同一坐标系；"
                        "导入后不得单独移动、缩放或自动摆放。"
                    ),
                    (
                        "只有对应桥接/配合实体测试失败时，才把该体积设为"
                        "支撑强制区；测试通过时保持全局支撑关闭。"
                    ),
                    (
                        "这些彩色体积不是打印零件，不得作为普通模型切片。"
                    ),
                ],
            },
            "manufacturing_controls": {
                "items": [
                    {
                        "name": part.name,
                        "display_name": "封闭主风口切片对照 · 禁止生产",
                        "file_name": f"{part.name}.stl",
                        "dimensions_mm": list(
                            part.metadata["dimensions_mm"]
                        ),
                        "translation_mm": [160.0, 0.0, 0.0],
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "is_reference": True,
                        "reference_kind": "manufacturing_control",
                        "color_rgb": [0.94, 0.36, 0.16],
                        "opacity": 0.8,
                        "do_not_print": True,
                    }
                    for part in manufacturing_control_parts or []
                ],
                "notes": (
                    [
                        (
                            "左侧为真实四面自支撑风口，右侧为仅恢复四个"
                            "主风口墙体的切片对照；对照件不属于装配且禁止生产。"
                        ),
                        (
                            "两者使用完全相同的方向、PETG、层高和"
                            "OrcaSlicer 配置，以测量镂空净材料/时间收益。"
                        ),
                    ]
                    if manufacturing_control_parts
                    else []
                ),
            },
            "print_layout": (
                IndustrialDesignWorkflow._print_layout_manifest(
                    parts,
                    manufacturing,
                    support_strategy=proposal.support_strategy,
                )
                if manufacturing is not None
                else {"items": [], "measured_from_slicer": False}
            ),
        }

    @staticmethod
    def _structural_load_preview(
        structure: dict[str, Any],
    ) -> dict[str, Any]:
        visual = structure["visualization"]
        support_z = float(visual["support_plane_z_mm"])
        span_x, span_y = (
            float(value) for value in visual["desk_support_span_mm"]
        )
        desk_plane_z = float(visual["desk_contact_plane_z_mm"])
        desk_pad_thickness = float(visual["desk_pad_thickness_mm"])
        desk_pad_diameter = float(visual["desk_pad_diameter_mm"])
        items = [
            {
                "name": "desk support polygon",
                "primitive": "box",
                "dimensions_mm": [span_x, span_y, 0.4],
                "translation_mm": [
                    0.0,
                    0.0,
                    desk_plane_z - 0.2,
                ],
                "rotation_deg": [0.0, 0.0, 0.0],
                "is_reference": True,
                "reference_kind": "structural_support",
                "color_rgb": [0.2, 0.9, 0.46],
                "opacity": 0.2,
            }
        ]
        for index, (x, y) in enumerate(
            visual["desk_pad_positions_xy_mm"],
            start=1,
        ):
            items.append(
                {
                    "name": f"desk isolation pad {index}",
                    "primitive": "box",
                    "dimensions_mm": [
                        desk_pad_diameter,
                        desk_pad_diameter,
                        desk_pad_thickness,
                    ],
                    "translation_mm": [
                        float(x),
                        float(y),
                        desk_plane_z + desk_pad_thickness / 2,
                    ],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "is_reference": True,
                    "reference_kind": "desk_contact_hardware",
                    "color_rgb": [0.24, 0.32, 0.36],
                    "opacity": 0.9,
                }
            )
        for index, (x, y) in enumerate(
            visual["pad_positions_xy_mm"],
            start=1,
        ):
            items.append(
                {
                    "name": f"3g load path · pad {index}",
                    "primitive": "box",
                    "dimensions_mm": [3.0, 3.0, 16.0],
                    "translation_mm": [
                        float(x),
                        float(y),
                        support_z + 8.0,
                    ],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "is_reference": True,
                    "reference_kind": "structural_load",
                    "color_rgb": [1.0, 0.28, 0.08],
                    "opacity": 0.9,
                }
            )
        checks = structure["checks"]
        return {
            "items": items,
            "notes": [
                (
                    f"3g 竖向筛查：每个硅胶点 "
                    f"{structure['load_path']['force_per_pad_at_3g_n']:.2f} N。"
                ),
                (
                    "PETG + 软硅胶最坏组合位移 "
                    f"{checks['annular_shelf_deflection']['combined_worst_displacement_mm']:.3f} mm，"
                    "低于 0.15 mm PETG 自由行程。"
                ),
                (
                    "0.25g 横向扰动倾覆安全系数 "
                    f"{checks['whole_assembly_tipping']['safety_factor']:.2f}。"
                ),
                (
                    "四个 Ø6 × 1.5 mm 桌面硅胶垫提供 "
                    f"{checks['desk_pad_contact_and_anti_slip']['installed_underbody_gap_mm']:.1f} mm "
                    "一致底隙；打印底面仍完全平整。"
                ),
                "彩色载荷柱与绿色支撑面仅用于分析预览，不导出为打印零件。",
            ],
        }

    @staticmethod
    def _print_layout_manifest(
        parts: list[CADPart],
        manufacturing: dict[str, Any],
        support_strategy: str = "minimal",
    ) -> dict[str, Any]:
        """Lay out actual print orientations with measured support envelopes."""

        slice_parts = manufacturing.get("parts", {})
        support_parts = manufacturing.get("support_analysis", {}).get(
            "parts",
            {},
        )
        layout_limit_mm = 300.0
        gap_mm = 18.0
        cursor_x = 0.0
        cursor_y = 0.0
        row_depth = 0.0
        layout_width = 0.0
        items: list[dict[str, Any]] = []

        for part in parts:
            bounds = part.solid().BoundingBox()
            sliced = slice_parts.get(part.name, {})
            support = support_parts.get(part.name, {})
            envelope = support.get("support_toolpath_envelope", {})
            support_footprint = envelope.get("footprint_mm", [])
            effective_width = max(
                float(bounds.xlen),
                float(support_footprint[0])
                if len(support_footprint) == 2
                else 0.0,
            )
            effective_depth = max(
                float(bounds.ylen),
                float(support_footprint[1])
                if len(support_footprint) == 2
                else 0.0,
            )
            if cursor_x > 0.0 and (
                cursor_x + effective_width > layout_limit_mm
            ):
                cursor_x = 0.0
                cursor_y += row_depth + gap_mm
                row_depth = 0.0
            target_center_x = cursor_x + effective_width / 2.0
            target_center_y = cursor_y + effective_depth / 2.0
            source_center_x = (float(bounds.xmin) + float(bounds.xmax)) / 2.0
            source_center_y = (float(bounds.ymin) + float(bounds.ymax)) / 2.0
            translation = [
                target_center_x - source_center_x,
                target_center_y - source_center_y,
                -float(bounds.zmin),
            ]
            print_metrics = {
                "filament_weight_g": float(
                    sliced.get("filament_weight_g", 0.0)
                ),
                "estimated_seconds": int(
                    sliced.get("estimated_seconds", 0)
                ),
                "bridge_regions": int(
                    sliced.get("bridge_regions", 0)
                ),
                "overhang_regions": int(
                    sliced.get("overhang_regions", 0)
                ),
                "max_bridge_span_mm": float(
                    sliced.get("max_bridge_span_mm", 0.0)
                ),
                "production_support_used": bool(
                    sliced.get("support_used", False)
                ),
                "auto_support_additional_filament_weight_g": float(
                    support.get(
                        "additional_filament_weight_g",
                        0.0,
                    )
                ),
                "auto_support_additional_time_seconds": int(
                    support.get("additional_time_seconds", 0)
                ),
                "auto_support_additional_filament_ratio": float(
                    support.get("additional_filament_ratio", 0.0)
                ),
                "auto_support_additional_time_ratio": float(
                    support.get("additional_time_ratio", 0.0)
                ),
            }
            items.append(
                {
                    "name": f"{part.name} · production orientation",
                    "file_name": f"{part.name}.stl",
                    "dimensions_mm": [
                        round(float(bounds.xlen), 3),
                        round(float(bounds.ylen), 3),
                        round(float(bounds.zlen), 3),
                    ],
                    "translation_mm": translation,
                    "rotation_deg": list(
                        sliced.get("rotation_deg", [0.0, 0.0, 0.0])
                    ),
                    "print_metrics": print_metrics,
                    "color_rgb": [0.42, 0.68, 0.96],
                    "opacity": 0.92,
                }
            )
            local_bbox = envelope.get("local_bbox_xy_mm", [])
            z_range = envelope.get("z_range_mm", [])
            if (
                len(support_footprint) == 2
                and len(local_bbox) == 4
                and len(z_range) == 2
                and int(envelope.get("extrusion_move_count", 0)) > 0
            ):
                z_bands = envelope.get("z_bands", [])
                if z_bands:
                    peak_moves = max(
                        int(band.get("extrusion_move_count", 0))
                        for band in z_bands
                    )
                    for band in z_bands:
                        band_bbox = band.get("local_bbox_xy_mm", [])
                        band_footprint = band.get("footprint_mm", [])
                        band_z = band.get("actual_z_range_mm", [])
                        if (
                            len(band_bbox) != 4
                            or len(band_footprint) != 2
                            or len(band_z) != 2
                        ):
                            continue
                        band_center_x = (
                            float(band_bbox[0])
                            + float(band_bbox[2])
                        ) / 2.0
                        band_center_y = (
                            float(band_bbox[1])
                            + float(band_bbox[3])
                        ) / 2.0
                        band_height = max(
                            0.2,
                            float(band_z[1])
                            - float(band_z[0])
                            + 0.2,
                        )
                        move_count = int(
                            band.get("extrusion_move_count", 0)
                        )
                        interface_move_count = int(
                            band.get("feature_move_counts", {}).get(
                                "support_interface",
                                0,
                            )
                        )
                        density = (
                            move_count / peak_moves
                            if peak_moves
                            else 0.0
                        )
                        items.append(
                            {
                                "name": (
                                    f"{part.name} · support "
                                    f"Z{float(band_z[0]):.1f}–"
                                    f"{float(band_z[1]):.1f} mm · "
                                    f"{move_count} moves · "
                                    f"{interface_move_count} contacts"
                                ),
                                "primitive": "box",
                                "dimensions_mm": [
                                    float(band_footprint[0]),
                                    float(band_footprint[1]),
                                    band_height,
                                ],
                                "translation_mm": [
                                    target_center_x + band_center_x,
                                    target_center_y + band_center_y,
                                    (
                                        float(band_z[0])
                                        + float(band_z[1])
                                    )
                                    / 2.0,
                                ],
                                "rotation_deg": [0.0, 0.0, 0.0],
                                "is_reference": True,
                                "reference_kind": "auto_support_band",
                                "color_rgb": [
                                    1.0,
                                    round(0.5 - 0.28 * density, 3),
                                    0.06,
                                ],
                                "opacity": round(
                                    0.07 + 0.2 * density,
                                    3,
                                ),
                                "support_band": band,
                                "print_metrics": print_metrics,
                            }
                        )
                else:
                    support_center_x = (
                        float(local_bbox[0]) + float(local_bbox[2])
                    ) / 2.0
                    support_center_y = (
                        float(local_bbox[1]) + float(local_bbox[3])
                    ) / 2.0
                    support_height = float(
                        envelope.get("height_mm", 0.0)
                    )
                    items.append(
                        {
                            "name": (
                                f"{part.name} · auto support envelope"
                            ),
                            "primitive": "box",
                            "dimensions_mm": [
                                float(support_footprint[0]),
                                float(support_footprint[1]),
                                support_height,
                            ],
                            "translation_mm": [
                                target_center_x + support_center_x,
                                target_center_y + support_center_y,
                                (
                                    float(z_range[0])
                                    + float(z_range[1])
                                )
                                / 2.0,
                            ],
                            "rotation_deg": [0.0, 0.0, 0.0],
                            "is_reference": True,
                            "reference_kind": "auto_support_envelope",
                            "color_rgb": [1.0, 0.36, 0.08],
                            "opacity": 0.16,
                            "print_metrics": print_metrics,
                        }
                    )
                xy_tiles = [
                    tile
                    for tile in envelope.get("xy_tiles", [])
                    if float(tile.get("move_ratio", 0.0)) >= 0.01
                ][:12]
                if xy_tiles:
                    peak_tile_moves = max(
                        int(tile.get("extrusion_move_count", 0))
                        for tile in xy_tiles
                    )
                    tile_size = float(
                        envelope.get("xy_tile_size_mm", 20.0)
                    )
                    for tile in xy_tiles:
                        tile_bbox = tile.get(
                            "nominal_local_bbox_xy_mm",
                            [],
                        )
                        if len(tile_bbox) != 4:
                            continue
                        move_count = int(
                            tile.get("extrusion_move_count", 0)
                        )
                        interface_move_count = int(
                            tile.get("feature_move_counts", {}).get(
                                "support_interface",
                                0,
                            )
                        )
                        density = (
                            move_count / peak_tile_moves
                            if peak_tile_moves
                            else 0.0
                        )
                        items.append(
                            {
                                "name": (
                                    f"{part.name} · XY hotspot "
                                    f"{float(tile_bbox[0]):+.0f}…"
                                    f"{float(tile_bbox[2]):+.0f} / "
                                    f"{float(tile_bbox[1]):+.0f}…"
                                    f"{float(tile_bbox[3]):+.0f} mm · "
                                    f"{move_count} moves · "
                                    f"{interface_move_count} contacts"
                                ),
                                "primitive": "box",
                                "dimensions_mm": [
                                    tile_size,
                                    tile_size,
                                    0.8,
                                ],
                                "translation_mm": [
                                    target_center_x
                                    + (
                                        float(tile_bbox[0])
                                        + float(tile_bbox[2])
                                    )
                                    / 2.0,
                                    target_center_y
                                    + (
                                        float(tile_bbox[1])
                                        + float(tile_bbox[3])
                                    )
                                    / 2.0,
                                    float(bounds.zlen) + 1.4,
                                ],
                                "rotation_deg": [0.0, 0.0, 0.0],
                                "is_reference": True,
                                "reference_kind": (
                                    "auto_support_xy_tile"
                                ),
                                "color_rgb": [
                                    1.0,
                                    round(0.72 - 0.6 * density, 3),
                                    0.02,
                                ],
                                "opacity": round(
                                    0.18 + 0.58 * density,
                                    3,
                                ),
                                "support_xy_tile": tile,
                                "print_metrics": print_metrics,
                            }
                        )
                xyz_cells = sorted(
                    (
                        cell
                        for cell in envelope.get("xyz_cells", [])
                        if int(
                            cell.get(
                                "feature_move_counts",
                                {},
                            ).get("support_interface", 0)
                        )
                        > 0
                    ),
                    key=lambda cell: (
                        -int(
                            cell.get(
                                "feature_move_counts",
                                {},
                            ).get("support_interface", 0)
                        ),
                        -int(cell.get("extrusion_move_count", 0)),
                    ),
                )[:12]
                if xyz_cells:
                    peak_interface_moves = max(
                        int(
                            cell.get(
                                "feature_move_counts",
                                {},
                            ).get("support_interface", 0)
                        )
                        for cell in xyz_cells
                    )
                    for cell in xyz_cells:
                        cell_bbox = cell.get(
                            "nominal_local_bbox_xyz_mm",
                            [],
                        )
                        if len(cell_bbox) != 6:
                            continue
                        move_count = int(
                            cell.get("extrusion_move_count", 0)
                        )
                        interface_move_count = int(
                            cell.get(
                                "feature_move_counts",
                                {},
                            ).get("support_interface", 0)
                        )
                        density = (
                            interface_move_count / peak_interface_moves
                            if peak_interface_moves
                            else 0.0
                        )
                        items.append(
                            {
                                "name": (
                                    f"{part.name} · XYZ contact "
                                    f"X{float(cell_bbox[0]):+.0f}…"
                                    f"{float(cell_bbox[3]):+.0f} / "
                                    f"Y{float(cell_bbox[1]):+.0f}…"
                                    f"{float(cell_bbox[4]):+.0f} / "
                                    f"Z{float(cell_bbox[2]):.0f}…"
                                    f"{float(cell_bbox[5]):.0f} mm · "
                                    f"{interface_move_count} contacts · "
                                    f"{move_count} moves"
                                ),
                                "primitive": "box",
                                "dimensions_mm": [
                                    float(cell_bbox[3])
                                    - float(cell_bbox[0]),
                                    float(cell_bbox[4])
                                    - float(cell_bbox[1]),
                                    float(cell_bbox[5])
                                    - float(cell_bbox[2]),
                                ],
                                "translation_mm": [
                                    target_center_x
                                    + (
                                        float(cell_bbox[0])
                                        + float(cell_bbox[3])
                                    )
                                    / 2.0,
                                    target_center_y
                                    + (
                                        float(cell_bbox[1])
                                        + float(cell_bbox[4])
                                    )
                                    / 2.0,
                                    (
                                        float(cell_bbox[2])
                                        + float(cell_bbox[5])
                                    )
                                    / 2.0,
                                ],
                                "rotation_deg": [0.0, 0.0, 0.0],
                                "is_reference": True,
                                "reference_kind": (
                                    "auto_support_xyz_cell"
                                ),
                                "color_rgb": [
                                    1.0,
                                    round(0.58 - 0.5 * density, 3),
                                    round(0.56 - 0.5 * density, 3),
                                ],
                                "opacity": round(
                                    0.22 + 0.62 * density,
                                    3,
                                ),
                                "support_xyz_cell": cell,
                                "print_metrics": print_metrics,
                            }
                        )
            cursor_x += effective_width + gap_mm
            row_depth = max(row_depth, effective_depth)
            layout_width = max(
                layout_width,
                cursor_x - gap_mm,
            )

        layout_depth = cursor_y + row_depth
        center_offset = [-layout_width / 2.0, -layout_depth / 2.0]
        for item in items:
            item["translation_mm"][0] += center_offset[0]
            item["translation_mm"][1] += center_offset[1]
        notes = [
            "蓝色为实际 STL 生产方向；橙红分层体积为自动支撑路径热点。",
            "颜色与透明度随每个 5 mm 高度带的路径密度变化。",
            "支撑热点不是生产零件，生产切片保持关闭支撑。",
            "镂空只有在生产方向零支撑且桥接门限通过时才允许。",
        ]
        fan_chassis = next(
            (part for part in parts if part.name == "fan_chassis"),
            None,
        )
        if fan_chassis is not None:
            exterior = fan_chassis.metadata.get(
                "exterior_continuity",
                {},
            )
            roof_slope = exterior.get("minimum_roof_slope_deg")
            roof_margin = exterior.get("roof_slope_margin_deg")
            threshold = exterior.get("slicer_support_threshold_deg")
            if (
                roof_slope is not None
                and roof_margin is not None
                and threshold is not None
            ):
                notes.append(
                    f"主风口最低坡度 {float(roof_slope):.3f}°，"
                    f"相对 {float(threshold):.0f}° 自动支撑阈值保留 "
                    f"{float(roof_margin):.3f}° 裕量；不得优化到阈值线上。"
                )
        return {
            "items": items,
            "measured_from_slicer": True,
            "layout_envelope_mm": [
                round(layout_width, 3),
                round(layout_depth, 3),
            ],
            "production_support_policy": (
                "disabled"
                if support_strategy in {"none", "minimal"}
                else "required"
            ),
            "comparison_support_profile": "tree(auto), 30 degree threshold",
            "notes": notes,
        }
