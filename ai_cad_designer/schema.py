"""Typed engineering inputs and outputs shared by the design agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


MATERIALS = ("PETG", "PLA", "ABS", "ASA")
EVIDENCE_STATUSES = ("not_run", "passed", "failed", "blocked")


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


@dataclass(frozen=True)
class Evidence:
    """One serializable verification result with an explicit execution state."""

    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError(f"unsupported evidence status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "details": self.details,
        }


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
    repair: dict[str, Any] | None = None
    evidence: dict[str, Evidence] = field(default_factory=dict)
    requested_planner: str | None = None
    actual_planner: str | None = None
    fallback: Evidence = field(
        default_factory=lambda: Evidence(
            "not_run",
            "Rules fallback was not requested.",
        )
    )

    def evidence_records(self) -> dict[str, Evidence]:
        """Return the four evidence classes even for partial workflow output."""
        missing_files = [
            path for path in self.exported_files if not Path(path).is_file()
        ]
        files = Evidence(
            "passed" if self.exported_files and not missing_files else "failed",
            (
                f"{len(self.exported_files)} exported files were found."
                if self.exported_files and not missing_files
                else "One or more exported files are missing."
            ),
            {
                "checked": len(self.exported_files),
                "missing": missing_files,
            },
        )
        geometry = Evidence(
            (
                "passed"
                if self.validation
                and all(
                    report.get("printable", False)
                    for report in self.validation.values()
                )
                else "failed"
            ),
            (
                "All geometry validations are printable."
                if self.validation
                and all(
                    report.get("printable", False)
                    for report in self.validation.values()
                )
                else "No passing geometry validation was produced."
            ),
            {"part_count": len(self.validation)},
        )
        if self.manufacturing is None:
            slicing = Evidence(
                "not_run",
                "Real slicing was not requested.",
            )
        elif not self.manufacturing:
            slicing = Evidence(
                "failed",
                "Slicing returned no diagnostic report.",
            )
        else:
            status = self.manufacturing.get("status")
            if status not in EVIDENCE_STATUSES:
                status = "passed" if self.manufacturing.get("passed") else "failed"
            slicing = Evidence(
                status,
                (
                    "Real slicing report passed."
                    if status == "passed"
                    else (
                        "Real slicing is blocked; diagnostics were retained."
                        if status == "blocked"
                        else "Real slicing report failed; diagnostics were retained."
                    )
                ),
                {
                    "report_path": self.manufacturing.get("report_path"),
                    "diagnostic": self.manufacturing.get("diagnostic"),
                },
            )
        records = {
            "files": files,
            "geometry": geometry,
            "slicing": slicing,
            "physical": Evidence(
                "not_run",
                "No physical print or assembly evidence was recorded.",
            ),
        }
        records.update(self.evidence)
        return records

    @property
    def passed(self) -> bool:
        evidence = self.evidence_records()
        return (
            evidence["files"].status == "passed"
            and evidence["geometry"].status == "passed"
            and (
                self.manufacturing is None
                or bool(self.manufacturing.get("passed", False))
            )
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

    @property
    def manufacturable(self) -> bool:
        evidence = self.evidence_records()
        return all(
            evidence[name].status == "passed"
            for name in ("files", "geometry", "slicing")
        ) and ("input" not in evidence or evidence["input"].status == "passed")

    def to_dict(self) -> dict[str, Any]:
        evidence = self.evidence_records()
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
            "repair": self.repair,
            "evidence": {
                name: record.to_dict() for name, record in evidence.items()
            },
            "planner": {
                "requested": self.requested_planner or self.proposal.planner,
                "actual": self.actual_planner or self.proposal.planner,
                "fallback": self.fallback.to_dict(),
            },
            "manufacturable": self.manufacturable,
            "passed": self.passed,
        }
