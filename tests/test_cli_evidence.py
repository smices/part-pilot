import json
import sys
from pathlib import Path

from ai_cad_designer import cli
from ai_cad_designer.cli import main


def test_rules_cli_reports_unsliced_evidence(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-cad",
            "sensor",
            "--planner",
            "rules",
            "--output",
            str(tmp_path),
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["evidence"]["slicing"]["status"] == "not_run"
    assert payload["evidence"]["physical"]["status"] == "not_run"
    assert payload["planner"]["actual"] == "rules"
    assert not payload["manufacturable"]


def test_cli_passes_requested_blender_preview(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    captured = {}

    class Result:
        passed = True

        @staticmethod
        def to_dict():
            return {"preview": {"visual": {"status": "passed"}}}

    class Workflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, request, **kwargs):
            captured["request"] = request
            captured.update(kwargs)
            return Result()

    monkeypatch.setattr(cli, "IndustrialDesignWorkflow", Workflow)
    monkeypatch.setattr(cli, "validate_pythonocc_bridge", lambda: {"valid": True})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-cad",
            "sensor",
            "--planner",
            "rules",
            "--blender-preview",
            "--output",
            str(tmp_path),
        ],
    )

    assert main() == 0
    assert captured["blender_preview"] is True
    assert (
        json.loads(capsys.readouterr().out)["preview"]["visual"]["status"]
        == "passed"
    )
