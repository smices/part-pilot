"""Command-line entry point for the AI CAD workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .llm import LLMPlanningError, build_provider
from .validation import validate_pythonocc_bridge
from .workflow import IndustrialDesignWorkflow


DEFAULT_SENSOR_REQUEST = "Design a portable sensor enclosure"
DEFAULT_ROBOT_REQUEST = """
我有 ESP32、18650电池、摄像头、风扇。
设计一个桌面机器人外壳。要求：不用螺丝、可拆卸、3D打印、PETG材料。
""".strip()


def _read_json_object(path: str | None, label: str) -> dict:
    if not path:
        return {}
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"{label} file not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _parameters_from_calibration(
    payload: dict,
) -> tuple[dict[str, object], dict[str, object]]:
    current = payload.get("current_values", {})
    measurements = payload.get("measurement_results", {})
    if not isinstance(current, dict) or not isinstance(measurements, dict):
        raise ValueError(
            "calibration results require current_values and "
            "measurement_results objects"
        )
    current_engineering = current.get("engineering_parameters", {})
    if not isinstance(current_engineering, dict):
        raise ValueError(
            "calibration current engineering parameters must be an object"
        )
    engineering: dict[str, object] = {}
    manufacturing: dict[str, object] = {}

    def calibrated(value: object) -> dict[str, object]:
        return {"value": value, "source": "calibration_coupon"}

    clearance = measurements.get(
        "selected_petg_clearance_per_side_mm"
    )
    if clearance is not None:
        manufacturing["tolerance_mm"] = calibrated(clearance)
    corner_radius = measurements.get("mac_corner_radius_mm")
    if corner_radius is not None:
        engineering["mac_corner_radius_mm"] = calibrated(corner_radius)
    for axis in ("x", "y"):
        delta = measurements.get(f"power_button_delta_{axis}_mm")
        if delta is None:
            continue
        key = f"power_button_{axis}_mm"
        if key not in current_engineering:
            raise ValueError(
                f"calibration current values are missing {key}"
            )
        engineering[key] = calibrated(
            float(current_engineering[key]) + float(delta)
        )
    for face in ("front", "rear"):
        for axis in ("x", "z"):
            delta = measurements.get(
                f"{face}_interface_residual_delta_{axis}_mm"
            )
            if delta is None:
                continue
            key = f"{face}_interface_delta_{axis}_mm"
            if key not in current_engineering:
                raise ValueError(
                    f"calibration current values are missing {key}"
                )
            engineering[key] = calibrated(
                float(current_engineering[key]) + float(delta)
            )
    for key in (
        "fan_mount_spacing_mm",
        "fan_mount_hole_diameter_mm",
        "ds18b20_probe_diameter_mm",
        "ds18b20_snap_interference_per_side_mm",
    ):
        value = measurements.get(key)
        if value is not None:
            engineering[key] = calibrated(value)
    return engineering, manufacturing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parametric AI industrial design workflow"
    )
    parser.add_argument(
        "workflow",
        choices=("sensor", "robot", "pcb", "design", "vision", "status"),
        help="design workflow, visual-source recognition, or provider status",
    )
    parser.add_argument("--request", help="custom Chinese or English design request")
    parser.add_argument("--pcb-input", metavar="JSON", help="measured PCB mechanical input JSON")
    parser.add_argument(
        "--print-configuration",
        metavar="JSON",
        help=(
            "confirmed printer JSON for PCB --slice: machine, nozzle_diameter_mm, process, "
            "filament, and confirmed=true"
        ),
    )
    parser.add_argument(
        "--planner",
        choices=("codex", "api", "rules"),
        default=os.getenv("AI_CAD_PLANNER", "codex"),
        help="reasoning provider; default: local authenticated Codex",
    )
    parser.add_argument("--model", help="optional Codex/API model override")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="FILE",
        help="hardware photo or schematic (PNG/JPEG/WebP/PDF); repeat up to six times",
    )
    parser.add_argument(
        "--strict-planner",
        action="store_true",
        help="fail instead of falling back to the deterministic rule planner",
    )
    parser.add_argument(
        "--output",
        default="ai_cad_designer/exports",
        help="directory for STEP, STL, proposal, and validation files",
    )
    parser.add_argument(
        "--slice",
        action="store_true",
        help="run real OrcaSlicer PETG slicing and export G-code 3MF artifacts",
    )
    parser.add_argument(
        "--blender-preview",
        action="store_true",
        help="render current-run STL files in an isolated Blender process",
    )
    parser.add_argument(
        "--engineering-parameters",
        metavar="JSON",
        help="JSON object with explicit engineering parameter values and sources",
    )
    parser.add_argument(
        "--manufacturing-parameters",
        metavar="JSON",
        help="JSON object with material, tolerance, wall and layer parameters",
    )
    parser.add_argument(
        "--calibration-results",
        metavar="JSON",
        help="completed calibration_measurement_template.json to apply",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        provider = build_provider(
            args.planner,
            model=args.model,
            working_directory=Path.cwd(),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.workflow == "status":
        payload = (
            provider.healthcheck()
            if provider is not None
            else {
                "available": True,
                "provider": "rules",
                "authenticated": False,
            }
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload["available"] else 1

    request = args.request
    if args.workflow == "sensor":
        request = request or DEFAULT_SENSOR_REQUEST
    elif args.workflow == "robot":
        request = request or DEFAULT_ROBOT_REQUEST
    elif args.workflow == "vision":
        request = request or "Identify hardware for a printable enclosure"
    elif args.workflow == "pcb":
        request = request or "Measured PCB removable enclosure"
    elif not request:
        raise SystemExit("--request is required for the design workflow")

    if args.workflow == "vision":
        if provider is None:
            raise SystemExit("vision requires --planner codex or --planner api")
        if not args.image:
            raise SystemExit("vision requires at least one --image source")
        try:
            payload = provider.analyze_hardware(args.image, request)
        except (LLMPlanningError, ValueError) as exc:
            print(
                json.dumps(
                    {"passed": False, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    workflow = IndustrialDesignWorkflow(
        Path(args.output),
        provider=provider,
        fallback_to_rules=not args.strict_planner,
    )
    try:
        engineering_parameters: dict[str, object] = {}
        manufacturing_parameters: dict[str, object] = {}
        if args.calibration_results:
            calibration_payload = _read_json_object(
                args.calibration_results,
                "calibration results",
            )
            calibrated_engineering, calibrated_manufacturing = (
                _parameters_from_calibration(calibration_payload)
            )
            engineering_parameters.update(calibrated_engineering)
            manufacturing_parameters.update(calibrated_manufacturing)
        engineering_parameters.update(
            _read_json_object(
                args.engineering_parameters,
                "engineering parameters",
            )
        )
        manufacturing_parameters.update(
            _read_json_object(
                args.manufacturing_parameters,
                "manufacturing parameters",
            )
        )
        if args.workflow == "pcb":
            result = workflow.run_pcb(
                _read_json_object(args.pcb_input, "pcb input"),
                blender_preview=args.blender_preview,
                slice_manufacturing=args.slice,
                print_configuration=_read_json_object(
                    args.print_configuration,
                    "print configuration",
                ),
            )
        else:
            result = workflow.run(
            request,
            image_paths=args.image,
            slice_manufacturing=args.slice,
            blender_preview=args.blender_preview,
            engineering_parameters=engineering_parameters or None,
            manufacturing_parameters=manufacturing_parameters or None,
            )
    except (LLMPlanningError, ValueError) as exc:
        print(
            json.dumps(
                {"passed": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    payload = result.to_dict()
    payload["pythonocc_bridge"] = validate_pythonocc_bridge()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if result.passed and payload["pythonocc_bridge"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
