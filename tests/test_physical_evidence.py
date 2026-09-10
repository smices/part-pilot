from ai_cad_designer.physical_evidence import validate_physical_evidence


MODELS = [{"file_name": "pcb_base.stl", "model_sha256": "a"}, {"file_name": "pcb_lid.stl", "model_sha256": "b"}]


def test_physical_evidence_requires_exact_models_measurement_and_assembly():
    incomplete = validate_physical_evidence(MODELS, {"printed_parts": MODELS})
    complete = validate_physical_evidence(MODELS, {
        "printed_parts": MODELS,
        "assembly": {"passed": True, "cycles": 3},
        "measurements": [{"feature": "lid_clearance", "value_mm": 0.25}],
    })

    assert incomplete["status"] == "failed"
    assert complete["status"] == "passed"


def test_physical_evidence_rejects_stale_model_hashes():
    result = validate_physical_evidence(MODELS, {
        "printed_parts": [{"file_name": "pcb_base.stl", "model_sha256": "old"}],
        "assembly": {"passed": True},
        "measurements": [{"feature": "fit", "value_mm": 0}],
    })
    assert result["status"] == "failed"
    assert "exactly match" in result["details"]["reasons"][0]


def test_physical_evidence_rejects_an_empty_design_version():
    result = validate_physical_evidence([], {
        "printed_parts": [], "assembly": {"passed": True}, "measurements": [{"feature": "fit", "value_mm": 0}],
    })
    assert result["status"] == "failed"
