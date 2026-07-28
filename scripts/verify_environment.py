"""Report installed CAD stack versions and required workstation applications."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path


PACKAGES = {
    "build123d": "build123d",
    "cadquery": "cadquery",
    "ocp": "OCP",
    "pythonocc-core": "OCC",
    "numpy": "numpy",
    "scipy": "scipy",
    "trimesh": "trimesh",
    "meshio": "meshio",
    "open3d": "open3d",
}


def package_report() -> dict[str, dict[str, str | bool]]:
    result = {}
    for distribution, module_name in PACKAGES.items():
        module = importlib.import_module(module_name)
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            records = sorted(
                (Path(sys.prefix) / "conda-meta").glob(f"{distribution}-*.json")
            )
            if records:
                version = json.loads(records[-1].read_text(encoding="utf-8"))["version"]
            else:
                version = getattr(module, "__version__", "module import only")
        result[distribution] = {
            "module": module_name,
            "version": str(version),
            "imported": True,
        }
    return result


def main() -> int:
    applications = {
        "FreeCAD": Path("/Applications/FreeCAD.app").is_dir(),
        "OrcaSlicer": Path("/Applications/OrcaSlicer.app").is_dir(),
    }
    report = {
        "python": sys.version,
        "python_3_12": sys.version_info[:2] == (3, 12),
        "platform": platform.platform(),
        "packages": package_report(),
        "applications": applications,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["python_3_12"] and all(applications.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
