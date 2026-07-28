"""Audit exported STEP files with FreeCAD's exact optimal B-Rep bounds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FREECAD_RESOURCES = Path(sys.executable).resolve().parent.parent
for module_path in (
    FREECAD_RESOURCES / "lib",
    FREECAD_RESOURCES / "Mod" / "Assembly",
):
    if module_path.is_dir():
        sys.path.insert(0, str(module_path))

import FreeCAD as App
import Part


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate STEP solids and report both exact optimal and "
            "conservative FreeCAD bounds"
        )
    )
    parser.add_argument("step", nargs="+", type=Path)
    parser.add_argument(
        "--footprint-limit",
        type=float,
        help="optional maximum exact X and Y envelope in millimetres",
    )
    return parser


def bounds_payload(bounds) -> dict[str, object]:
    return {
        "envelope_mm": [
            round(float(bounds.XLength), 6),
            round(float(bounds.YLength), 6),
            round(float(bounds.ZLength), 6),
        ],
        "x_mm": [
            round(float(bounds.XMin), 6),
            round(float(bounds.XMax), 6),
        ],
        "y_mm": [
            round(float(bounds.YMin), 6),
            round(float(bounds.YMax), 6),
        ],
        "z_mm": [
            round(float(bounds.ZMin), 6),
            round(float(bounds.ZMax), 6),
        ],
    }


def main() -> int:
    argv = [
        argument
        for argument in sys.argv[1:]
        if argument not in {"--pass", "-c", "--console"}
    ]
    args = build_parser().parse_intermixed_args(argv)
    reports = []
    passed = True
    for source in args.step:
        path = source.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        shape = Part.read(str(path))
        exact = shape.optimalBoundingBox()
        valid = not shape.isNull() and shape.isValid()
        footprint_ok = (
            args.footprint_limit is None
            or (
                exact.XLength <= args.footprint_limit
                and exact.YLength <= args.footprint_limit
            )
        )
        report = {
            "file": str(path),
            "valid": valid,
            "solid_count": len(shape.Solids),
            "optimal_bounds": bounds_payload(exact),
            "conservative_bounds": bounds_payload(shape.BoundBox),
            "footprint_limit_mm": args.footprint_limit,
            "footprint_ok": footprint_ok,
        }
        reports.append(report)
        passed = passed and valid and len(shape.Solids) > 0 and footprint_ok
    print(
        json.dumps(
            {
                "passed": passed,
                "freecad_version": ".".join(App.Version()[:3]),
                "part_module": Part.__name__,
                "assembly_workbench_available": (
                    FREECAD_RESOURCES / "Mod" / "Assembly"
                ).is_dir(),
                "files": reports,
                "note": (
                    "optimal_bounds are the exact manufacturing envelope; "
                    "conservative bounds may include rounded B-spline "
                    "control polygons"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 1


# FreeCAD executes positional Python files in its embedded console namespace,
# where ``__name__`` is not guaranteed to be ``__main__``.
raise SystemExit(main())
