import json
import sys
from pathlib import Path

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
