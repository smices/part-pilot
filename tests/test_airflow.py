from ai_cad_designer.airflow import (
    airflow_inputs_from_request,
    analyze_smart_fan_airflow,
)
from ai_cad_designer.agents.joint_agent import JointAgent


def _smart_fan_parts():
    return JointAgent().smart_fan_parts(
        wall_mm=2.5,
        tolerance_mm=0.25,
        material="PETG",
    )


def test_airflow_defaults_are_conservative_and_explicit() -> None:
    report = analyze_smart_fan_airflow(_smart_fan_parts(), "smart fan")

    assert report["passed"]
    assert report["confidence"] == "pre-prototype engineering estimate; not CFD"
    assert report["inputs"]["sources"]["fan_free_air_cfm"] == (
        "conservative_default"
    )
    assert report["operating_point"]["effective_airflow_cfm"] >= 20.0
    assert report["operating_point"]["throat_velocity_m_s"] <= 3.5


def test_airflow_prompt_overrides_are_parsed() -> None:
    inputs = airflow_inputs_from_request(
        "Fan free-air flow: 58 CFM\n"
        "Maximum static pressure: 24 Pa\n"
        "Thermal load: 80 W\n"
        "Allowed air temperature rise: 7 C"
    )

    assert inputs["fan_free_air_cfm"] == 58.0
    assert inputs["fan_max_static_pressure_pa"] == 24.0
    assert inputs["thermal_load_w"] == 80.0
    assert inputs["allowed_air_temperature_rise_c"] == 7.0
    assert set(inputs["sources"].values()) == {"user_prompt"}
