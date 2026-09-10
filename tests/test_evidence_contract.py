from pathlib import Path

import pytest

from ai_cad_designer.llm import LLMPlanningError
from ai_cad_designer.llm.schema import DESIGN_PROPOSAL_JSON_SCHEMA
from ai_cad_designer.schema import (
    ComponentSpec,
    DesignBrief,
    DesignProposal,
    MATERIALS,
    WorkflowResult,
)
from ai_cad_designer.slicing import OrcaSlicerError
from ai_cad_designer.workflow import IndustrialDesignWorkflow


def _proposal() -> DesignProposal:
    return DesignProposal(
        title="Evidence contract",
        brief=DesignBrief(
            request="Design a sensor enclosure",
            design_family="sensor_enclosure",
            product="sensor enclosure",
            components=(
                ComponentSpec("sensor", (20.0, 20.0, 5.0), "internal"),
            ),
        ),
        parts=[],
    )


def test_empty_validation_is_failed_but_unsliced_is_not_run(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "proposal.md"
    artifact.write_text("diagnostic", encoding="utf-8")

    payload = WorkflowResult(_proposal(), [str(artifact)], {}).to_dict()

    assert payload["evidence"]["files"]["status"] == "passed"
    assert payload["evidence"]["geometry"]["status"] == "failed"
    assert payload["evidence"]["slicing"]["status"] == "not_run"
    assert payload["evidence"]["physical"]["status"] == "not_run"
    assert not payload["manufacturable"]
    assert not payload["passed"]


def test_failed_slicing_keeps_diagnostic_and_is_not_manufacturable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSlicer:
        def slice_parts(self, *args, **kwargs):
            raise OrcaSlicerError("simulated slicer failure")

    monkeypatch.setattr("ai_cad_designer.workflow.OrcaSlicerRunner", FailingSlicer)
    result = IndustrialDesignWorkflow(tmp_path).run(
        "Design a portable sensor enclosure",
        slice_manufacturing=True,
    )
    payload = result.to_dict()
    diagnostic = Path(payload["manufacturing"]["report_path"])

    assert diagnostic.is_file()
    assert str(diagnostic) in payload["exported_files"]
    assert payload["evidence"]["slicing"]["status"] == "failed"
    assert payload["evidence"]["slicing"]["details"]["report_path"] == str(
        diagnostic
    )
    assert not payload["manufacturable"]


def test_non_petg_slice_is_blocked_with_a_diagnostic(tmp_path: Path) -> None:
    result = IndustrialDesignWorkflow(tmp_path).run(
        "Design a portable sensor enclosure",
        slice_manufacturing=True,
        manufacturing_parameters={"material": "PLA"},
    )

    payload = result.to_dict()
    assert payload["evidence"]["slicing"]["status"] == "blocked"
    diagnostic = Path(payload["manufacturing"]["report_path"])
    assert diagnostic.is_file()
    assert str(diagnostic) in payload["exported_files"]
    assert not payload["manufacturable"]


class _FailingPlanner:
    name = "offline-planner"

    def plan(self, request: str) -> dict:
        raise LLMPlanningError("planner offline")


def test_rules_fallback_is_recorded_and_strict_mode_raises(tmp_path: Path) -> None:
    fallback = IndustrialDesignWorkflow(tmp_path, provider=_FailingPlanner())
    result = fallback.run("Design a portable sensor enclosure")

    assert result.to_dict()["planner"] == {
        "requested": "offline-planner",
        "actual": "rules",
        "fallback": {
            "status": "blocked",
            "summary": "Rules fallback used; template coverage is unverified.",
            "details": {
                "reason": "LLMPlanningError",
                "coverage": "unverified",
            },
        },
    }
    with pytest.raises(LLMPlanningError, match="planner offline"):
        IndustrialDesignWorkflow(
            tmp_path / "strict",
            provider=_FailingPlanner(),
            fallback_to_rules=False,
        ).run("Design a portable sensor enclosure")


def test_material_contract_removes_unsupported_tpu(tmp_path: Path) -> None:
    assert MATERIALS == ("PETG", "PLA", "ABS", "ASA")
    assert DESIGN_PROPOSAL_JSON_SCHEMA["properties"]["material"]["enum"] == list(
        MATERIALS
    )
    with pytest.raises(ValueError, match="material must be PETG, PLA, ABS, ASA"):
        IndustrialDesignWorkflow(tmp_path).run(
            "Design a portable sensor enclosure",
            manufacturing_parameters={"material": "TPU"},
        )
