"""Validate a human-supplied physical print and assembly observation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_physical_evidence(
    expected_models: list[dict[str, str]], payload: dict[str, Any]
) -> dict[str, Any]:
    """Never promote a physical check unless it names the exact printed models."""
    observations = payload.get("printed_parts")
    assembly = payload.get("assembly")
    measurements = payload.get("measurements")
    observed = {
        (item.get("file_name"), item.get("model_sha256"))
        for item in observations
    } if isinstance(observations, list) else set()
    expected = {(item["file_name"], item["model_sha256"]) for item in expected_models}
    reasons = []
    if not expected_models:
        reasons.append("no current STL models were found for this output directory")
    if observed != expected:
        reasons.append("printed_parts must exactly match the current STL file names and hashes")
    if not isinstance(assembly, dict) or assembly.get("passed") is not True:
        reasons.append("assembly.passed must be true after physical assembly")
    if not isinstance(measurements, list) or not measurements:
        reasons.append("at least one physical measurement is required")
    return {
        "status": "passed" if not reasons else "failed",
        "summary": "Physical print and assembly evidence recorded." if not reasons else "Physical evidence is incomplete or does not match this design version.",
        "details": {"expected_models": expected_models, "reasons": reasons, "payload": payload},
    }


def record_physical_evidence(
    output_dir: str | Path, expected_models: list[dict[str, str]], payload: dict[str, Any]
) -> dict[str, Any]:
    result = validate_physical_evidence(expected_models, payload)
    path = Path(output_dir) / "physical_evidence.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    result["details"]["report_path"] = str(path.resolve())
    return result
