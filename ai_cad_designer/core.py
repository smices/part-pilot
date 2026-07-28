"""Core parametric CAD primitives, assemblies, joints, and exporters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import cadquery as cq


@dataclass
class CADPart:
    name: str
    shape: cq.Workplane
    metadata: dict[str, Any] = field(default_factory=dict)

    def solid(self) -> cq.Shape:
        value = self.shape.val()
        if not isinstance(value, cq.Shape):
            raise TypeError(f"{self.name} does not contain a CadQuery shape")
        return value


@dataclass
class CADAssembly:
    name: str
    assembly: cq.Assembly
    parts: list[CADPart]
    placements: dict[str, cq.Location]


@dataclass(frozen=True)
class JointPair:
    joint_type: str
    male: CADPart
    female: CADPart
    tolerance_mm: float


def _positive(value: float, name: str) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def create_part(
    name: str,
    dimensions_mm: tuple[float, float, float],
    *,
    wall_thickness_mm: float | None = None,
    open_top: bool = False,
    material: str = "PETG",
) -> CADPart:
    """Create a solid box or an open-top enclosure shell at the XY origin."""
    length, width, height = (
        _positive(value, label)
        for value, label in zip(dimensions_mm, ("length", "width", "height"), strict=True)
    )
    shape = cq.Workplane("XY").box(length, width, height, centered=(True, True, False))
    if open_top:
        if wall_thickness_mm is None:
            raise ValueError("wall_thickness_mm is required for an open-top part")
        wall = _positive(wall_thickness_mm, "wall_thickness_mm")
        if 2 * wall >= min(length, width) or wall >= height:
            raise ValueError("wall thickness leaves no usable enclosure cavity")
        cavity = (
            cq.Workplane("XY")
            .box(
                length - 2 * wall,
                width - 2 * wall,
                height - wall,
                centered=(True, True, False),
            )
            .translate((0, 0, wall))
        )
        shape = shape.cut(cavity)

    return CADPart(
        name=name,
        shape=shape,
        metadata={
            "dimensions_mm": (length, width, height),
            "wall_thickness_mm": wall_thickness_mm,
            "open_top": open_top,
            "material": material,
        },
    )


def create_assembly(
    name: str,
    parts: Iterable[CADPart | tuple[CADPart, cq.Location]],
) -> CADAssembly:
    """Create a named CadQuery assembly from parts and optional placements."""
    assembly = cq.Assembly(name=name)
    normalized: list[CADPart] = []
    placements: dict[str, cq.Location] = {}
    for item in parts:
        if isinstance(item, tuple):
            part, location = item
        else:
            part, location = item, cq.Location()
        assembly.add(part.shape, name=part.name, loc=location)
        normalized.append(part)
        placements[part.name] = location
    if not normalized:
        raise ValueError("an assembly requires at least one part")
    return CADAssembly(
        name=name,
        assembly=assembly,
        parts=normalized,
        placements=placements,
    )


def generate_joint(
    joint_type: str,
    *,
    width_mm: float = 10.0,
    length_mm: float = 12.0,
    height_mm: float = 3.0,
    tolerance_mm: float = 0.25,
    material: str = "PETG",
) -> JointPair:
    """Generate a printable male/female reference pair for a supported joint."""
    joint = joint_type.strip().lower().replace("-", "_").replace(" ", "_")
    width = _positive(width_mm, "width_mm")
    length = _positive(length_mm, "length_mm")
    height = _positive(height_mm, "height_mm")
    tolerance = _positive(tolerance_mm, "tolerance_mm")

    if joint in {"snap", "snap_fit"}:
        beam = cq.Workplane("XY").box(length, width, height, centered=(False, True, False))
        hook = (
            cq.Workplane("XY")
            .box(height, width, height * 1.6, centered=(False, True, False))
            .translate((length - height, 0, height))
        )
        male_shape = beam.union(hook)
        female_shape = cq.Workplane("XY").box(
            length + 2 * tolerance,
            width + 2 * tolerance,
            height * 2.7 + tolerance,
            centered=(False, True, False),
        )
    elif joint in {"dovetail", "sliding_rail"}:
        profile = (
            cq.Workplane("YZ")
            .polyline(
                [
                    (-width / 2, 0),
                    (width / 2, 0),
                    (width * 0.35, height),
                    (-width * 0.35, height),
                ]
            )
            .close()
        )
        male_shape = profile.extrude(length)
        female_shape = (
            cq.Workplane("YZ")
            .polyline(
                [
                    (-width / 2 - tolerance, 0),
                    (width / 2 + tolerance, 0),
                    (width * 0.35 + tolerance, height + tolerance),
                    (-width * 0.35 - tolerance, height + tolerance),
                ]
            )
            .close()
            .extrude(length)
        )
    elif joint in {"mortise_tenon", "mortise", "tenon"}:
        male_shape = cq.Workplane("XY").box(
            length, width, height, centered=(False, True, False)
        )
        female_shape = cq.Workplane("XY").box(
            length + 2 * tolerance,
            width + 2 * tolerance,
            height + tolerance,
            centered=(False, True, False),
        )
    elif joint == "magnet":
        diameter = width
        male_shape = cq.Workplane("XY").circle(diameter / 2).extrude(height)
        female_shape = (
            cq.Workplane("XY").circle(diameter / 2 + tolerance).extrude(height + tolerance)
        )
    else:
        raise ValueError(
            "joint_type must be snap_fit, dovetail, mortise_tenon, sliding_rail, or magnet"
        )

    metadata = {
        "joint_type": joint,
        "tolerance_mm": tolerance,
        "material": material,
        "wall_thickness_mm": min(height, 2.5),
    }
    return JointPair(
        joint_type=joint,
        male=CADPart(f"{joint}_male", male_shape, dict(metadata)),
        female=CADPart(f"{joint}_female_clearance", female_shape, dict(metadata)),
        tolerance_mm=tolerance,
    )


def _ensure_parent(path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def export_step(part: CADPart | CADAssembly, path: str | Path) -> Path:
    """Export a part or assembly to STEP."""
    target = _ensure_parent(path)
    if target.suffix.lower() not in {".step", ".stp"}:
        raise ValueError("STEP export path must end in .step or .stp")
    if isinstance(part, CADAssembly):
        part.assembly.save(str(target), exportType="STEP")
    else:
        # CadQuery exporters may adjust/normalize the source workplane in-place.
        # Export against an explicit copy so production I/O is non-destructive.
        source = part.shape.val().copy()
        cq.exporters.export(
            cq.Workplane(obj=source),
            str(target),
            exportType="STEP",
        )
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"STEP export failed: {target}")
    return target


def export_stl(
    part: CADPart,
    path: str | Path,
    *,
    linear_tolerance_mm: float = 0.08,
    angular_tolerance_rad: float = 0.1,
) -> Path:
    """Export a printable STL with explicit tessellation tolerances."""
    target = _ensure_parent(path)
    if target.suffix.lower() != ".stl":
        raise ValueError("STL export path must end in .stl")
    # Defensive copy keeps CAD primitives stable for later geometric reviews.
    source = part.shape.val().copy()
    cq.exporters.export(
        cq.Workplane(obj=source),
        str(target),
        exportType="STL",
        tolerance=linear_tolerance_mm,
        angularTolerance=angular_tolerance_rad,
    )
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"STL export failed: {target}")
    return target
