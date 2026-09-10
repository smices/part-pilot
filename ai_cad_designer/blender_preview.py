"""Render an isolated Blender preview from STL files in one export directory."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


PREVIEW_DIRECTORY = "blender_preview"
MANIFEST_NAME = "visual_preview.json"
DIAGNOSTIC_NAME = "diagnostic.json"
SCRIPT_NAME = "render_isometric.py"
RENDER_NAME = "isometric.png"

_SCRIPT = '''import sys
from pathlib import Path

import bpy
from mathutils import Vector


def arguments():
    values = sys.argv[sys.argv.index("--") + 1:]
    if len(values) < 2:
        raise RuntimeError("output directory and STL files are required")
    return Path(values[0]), [Path(value) for value in values[1:]]


def import_stl(path):
    try:
        bpy.ops.wm.stl_import(filepath=str(path))
    except AttributeError:
        bpy.ops.import_mesh.stl(filepath=str(path))


def main():
    output_dir, sources = arguments()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = 0.001
    for source in sources:
        bpy.ops.object.select_all(action="DESELECT")
        import_stl(source)
        for index, item in enumerate(bpy.context.selected_objects):
            if item.type != "MESH":
                continue
            item.name = (
                source.stem if index == 0 else f"{source.stem}_{index + 1}"
            )
            item.data.name = item.name
            item.scale = (0.001, 0.001, 0.001)
            bpy.context.view_layer.objects.active = item
            bpy.ops.object.transform_apply(
                location=False, rotation=False, scale=True
            )
            material = bpy.data.materials.new("PartPilot preview material")
            material.diffuse_color = (0.34, 0.60, 0.90, 1.0)
            item.data.materials.append(material)
    meshes = [item for item in scene.objects if item.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh was imported")
    bounds = [
        item.matrix_world @ Vector(corner)
        for item in meshes for corner in item.bound_box
    ]
    minimum = Vector(
        tuple(min(point[index] for point in bounds) for index in range(3))
    )
    maximum = Vector(
        tuple(max(point[index] for point in bounds) for index in range(3))
    )
    center = (minimum + maximum) / 2
    span = max((maximum - minimum).length, 0.001)
    bpy.ops.object.camera_add(
        location=center + Vector((1, -1, 0.8)).normalized() * span * 1.8
    )
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = span * 1.35
    camera.rotation_euler = (center - camera.location).to_track_quat(
        "-Z", "Y"
    ).to_euler()
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = 900
    scene.render.resolution_y = 700
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output_dir / "isometric.png")
    bpy.ops.render.render(write_still=True)


main()
'''


def resolve_blender() -> Path | None:
    """Find a local Blender executable without changing user configuration."""
    for name in ("Blender", "blender"):
        if path := shutil.which(name):
            return Path(path)
    app_binary = Path("/Applications/Blender.app/Contents/MacOS/Blender")
    return app_binary if app_binary.is_file() else None


def build_blender_command(
    blender_binary: str | Path,
    output_dir: str | Path,
    stl_paths: Iterable[str | Path],
) -> list[str]:
    """Build the fresh background process command used for rendering."""
    script = Path(output_dir) / SCRIPT_NAME
    return [
        str(blender_binary),
        "--background",
        "--factory-startup",
        "--python",
        str(script),
        "--",
        str(Path(output_dir)),
        *(str(Path(path)) for path in stl_paths),
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_diagnostic(
    path: Path,
    *,
    status: str,
    message: str,
    returncode: int | None = None,
    stdout: str = "",
    stderr: str = "",
) -> None:
    _write_json(
        path,
        {
            "status": status,
            "message": message,
            "returncode": returncode,
            "stdout": stdout[-6000:],
            "stderr": stderr[-6000:],
        },
    )


def _version(output: str) -> str | None:
    return next(
        (
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith("Blender ")
        ),
        None,
    )


def not_run_preview() -> dict[str, object]:
    """Describe the default state without creating any preview artifact."""
    return {
        "status": "not_run",
        "summary": "Blender preview was not requested.",
        "units": "millimeters",
        "sources": [],
        "render": None,
    }


def render_isometric_preview(
    stl_paths: Iterable[str | Path],
    output_dir: str | Path,
    *,
    blender_binary: str | Path | None = None,
    enabled: bool = True,
) -> dict[str, object]:
    """Write a local script, then render STL files in a fresh Blender process.

    Only files beneath ``output_dir`` are read or written.  ``blocked`` means
    Blender could not start; ``failed`` preserves a local diagnostic; and
    ``not_run`` is available to callers that leave the optional preview off.
    """
    if not enabled:
        return not_run_preview()

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    preview_dir = root / PREVIEW_DIRECTORY
    preview_dir.mkdir(exist_ok=True)
    manifest_path = preview_dir / MANIFEST_NAME
    diagnostic_path = preview_dir / DIAGNOSTIC_NAME
    script_path = preview_dir / SCRIPT_NAME
    render_path = preview_dir / RENDER_NAME
    artifacts = [_relative(root, manifest_path)]

    try:
        sources = [Path(path).expanduser().resolve() for path in stl_paths]
        if not sources:
            raise ValueError(
                "No current-run STL files were supplied for Blender preview."
            )
        for source in sources:
            if root not in source.parents or not source.is_file():
                raise ValueError(
                    "Blender preview sources must be existing files in the "
                    "current output directory."
                )
        source_records = [
            {"file_name": source.name, "sha256": _sha256(source)}
            for source in sources
        ]
    except (OSError, ValueError) as exc:
        _write_diagnostic(diagnostic_path, status="failed", message=str(exc))
        manifest = {
            "status": "failed",
            "summary": (
                "Blender preview input validation failed; diagnostics were "
                "retained."
            ),
            "sources": [],
            "units": "millimeters",
            "blender": {"version": None, "command": []},
            "render": {"file_name": RENDER_NAME, "exists": False},
            "diagnostic": _relative(root, diagnostic_path),
            "artifacts": artifacts + [_relative(root, diagnostic_path)],
        }
        _write_json(manifest_path, manifest)
        return manifest

    script_path.write_text(_SCRIPT, encoding="utf-8")
    binary = (
        Path(blender_binary).expanduser()
        if blender_binary
        else resolve_blender()
    )
    command = (
        build_blender_command(binary, preview_dir, sources) if binary else []
    )
    manifest: dict[str, object] = {
        "status": "blocked",
        "summary": "Blender preview was not run.",
        "sources": source_records,
        "units": "millimeters",
        "blender": {"version": None, "command": command},
        "render": {"file_name": RENDER_NAME, "exists": False},
        "artifacts": artifacts,
    }
    if binary is None:
        _write_diagnostic(
            diagnostic_path,
            status="blocked",
            message="Blender is not installed or not available on this machine.",
        )
        manifest.update(
            {
                "summary": "Blender preview is blocked because Blender is unavailable.",
                "diagnostic": _relative(root, diagnostic_path),
                "artifacts": artifacts + [_relative(root, diagnostic_path)],
            }
        )
    else:
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            manifest["blender"] = {
                "version": _version(output),
                "command": command,
                "returncode": completed.returncode,
            }
            if (
                completed.returncode == 0
                and render_path.is_file()
                and render_path.stat().st_size
            ):
                manifest.update(
                    {
                        "status": "passed",
                        "summary": "Rendered isolated Blender isometric preview.",
                        "render": {
                            "file_name": RENDER_NAME,
                            "path": _relative(root, render_path),
                            "exists": True,
                        },
                        "artifacts": artifacts + [_relative(root, render_path)],
                    }
                )
            else:
                _write_diagnostic(
                    diagnostic_path,
                    status="failed",
                    message="Blender exited without producing the expected PNG.",
                    returncode=completed.returncode,
                    stdout=completed.stdout or "",
                    stderr=completed.stderr or "",
                )
                manifest.update(
                    {
                        "status": "failed",
                        "summary": "Blender preview failed; diagnostics were retained.",
                        "diagnostic": _relative(root, diagnostic_path),
                        "artifacts": artifacts + [_relative(root, diagnostic_path)],
                    }
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            status = "blocked" if isinstance(exc, FileNotFoundError) else "failed"
            _write_diagnostic(
                diagnostic_path,
                status=status,
                message=f"{type(exc).__name__}: {exc}",
            )
            manifest.update(
                {
                    "status": status,
                    "summary": "Blender preview could not run; diagnostics were retained.",
                    "diagnostic": _relative(root, diagnostic_path),
                    "artifacts": artifacts + [_relative(root, diagnostic_path)],
                }
            )
    _write_json(manifest_path, manifest)
    return manifest
