"""Typed engineering inputs and outputs shared by the design agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    dimensions_mm: tuple[float, float, float]
    access: str
    clearance_mm: float = 0.25


@dataclass(frozen=True)
class DesignBrief:
    request: str
    design_family: str
    product: str
    components: tuple[ComponentSpec, ...]
    material: str = "PETG"
    screwless: bool = True
    removable: bool = True
    layer_height_mm: float = 0.2
    tolerance_mm: float = 0.25
    wall_thickness_mm: float = 2.5
    support_strategy: str = "minimal"


@dataclass(frozen=True)
class PartPlan:
    name: str
    purpose: str
    assembly_method: str
    dimensions_mm: tuple[float, float, float]


@dataclass
class DesignProposal:
    title: str
    brief: DesignBrief
    parts: list[PartPlan]
    support_strategy: str = "minimal"
    engineering_notes: list[str] = field(default_factory=list)
    planner: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# Design Proposal: {self.title}",
            "",
            f"Planner: {self.planner}",
            "",
            "## Components",
            "",
        ]
        lines.extend(
            f"- {component.name}: "
            f"{component.dimensions_mm[0]:g} × {component.dimensions_mm[1]:g} × "
            f"{component.dimensions_mm[2]:g} mm; access={component.access}"
            for component in self.brief.components
        )
        lines.extend(["", "## Parts and assembly", ""])
        lines.extend(
            f"{index}. {part.name} — {part.purpose}; joint: "
            f"{part.assembly_method}; envelope: "
            f"{part.dimensions_mm[0]:g} × {part.dimensions_mm[1]:g} × "
            f"{part.dimensions_mm[2]:g} mm"
            for index, part in enumerate(self.parts, start=1)
        )
        lines.extend(
            [
                "",
                "## Printing",
                "",
                f"- Material: {self.brief.material}",
                f"- Wall: {self.brief.wall_thickness_mm:g} mm",
                f"- Tolerance: {self.brief.tolerance_mm:g} mm",
                f"- Layer height: {self.brief.layer_height_mm:g} mm",
                f"- Supports: {self.support_strategy}",
                "",
                "## Engineering notes",
                "",
            ]
        )
        lines.extend(f"- {note}" for note in self.engineering_notes)
        return "\n".join(lines) + "\n"


@dataclass
class WorkflowResult:
    proposal: DesignProposal
    exported_files: list[str]
    validation: dict[str, dict[str, Any]]
    vision: dict[str, Any] | None = None
    preview: dict[str, Any] | None = None
    manufacturing: dict[str, Any] | None = None
    airflow: dict[str, Any] | None = None
    structure: dict[str, Any] | None = None
    bom: dict[str, Any] | None = None
    calibration: dict[str, Any] | None = None
    design_review: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        geometry_passed = all(
            report.get("printable", False) for report in self.validation.values()
        )
        return geometry_passed and (
            self.manufacturing is None
            or bool(self.manufacturing.get("passed", False))
        ) and (
            self.airflow is None
            or bool(self.airflow.get("passed", False))
        ) and (
            self.structure is None
            or bool(self.structure.get("passed", False))
        ) and (
            self.bom is None
            or bool(self.bom.get("passed", False))
        ) and (
            self.calibration is None
            or bool(self.calibration.get("passed", False))
        ) and (
            self.design_review is None
            or bool(self.design_review.get("passed", False))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.to_dict(),
            "exported_files": self.exported_files,
            "validation": self.validation,
            "vision": self.vision,
            "preview": self.preview,
            "manufacturing": self.manufacturing,
            "airflow": self.airflow,
            "structure": self.structure,
            "bom": self.bom,
            "calibration": self.calibration,
            "design_review": self.design_review,
            "passed": self.passed,
        }
