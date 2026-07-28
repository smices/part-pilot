"""Conservative lumped-parameter airflow and heat-removal estimates."""

from __future__ import annotations

from math import pi, sqrt
import re
from typing import Any

from .core import CADPart


CFM_TO_M3_S = 0.00047194745
AIR_DENSITY_KG_M3 = 1.184
AIR_HEAT_CAPACITY_J_KG_K = 1006.0


def _prompt_value(
    request: str,
    patterns: tuple[str, ...],
    default: float,
) -> tuple[float, str]:
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if match:
            value = float(match.group(1))
            if value > 0:
                return value, "user_prompt"
    return default, "conservative_default"


def airflow_inputs_from_request(request: str) -> dict[str, Any]:
    """Extract optional fan and thermal assumptions from Chinese/English text."""

    airflow, airflow_source = _prompt_value(
        request,
        (
            r"fan\s+(?:free[- ]air\s+)?flow\s*[:=]\s*([0-9.]+)\s*cfm",
            r"风扇(?:自由)?风量\s*[:：=]?\s*([0-9.]+)\s*cfm",
        ),
        45.0,
    )
    pressure, pressure_source = _prompt_value(
        request,
        (
            r"(?:maximum\s+)?static\s+pressure\s*[:=]\s*([0-9.]+)\s*pa",
            r"最大静压\s*[:：=]?\s*([0-9.]+)\s*pa",
        ),
        12.0,
    )
    load, load_source = _prompt_value(
        request,
        (
            r"thermal\s+load\s*[:=]\s*([0-9.]+)\s*w",
            r"热负载\s*[:：=]?\s*([0-9.]+)\s*w",
        ),
        65.0,
    )
    rise, rise_source = _prompt_value(
        request,
        (
            r"allowed\s+air\s+temperature\s+rise\s*[:=]\s*"
            r"([0-9.]+)\s*(?:c|°c)",
            r"允许空气温升\s*[:：=]?\s*([0-9.]+)\s*(?:c|°c|℃)",
        ),
        8.0,
    )
    return {
        "fan_free_air_cfm": airflow,
        "fan_max_static_pressure_pa": pressure,
        "thermal_load_w": load,
        "allowed_air_temperature_rise_c": rise,
        "sources": {
            "fan_free_air_cfm": airflow_source,
            "fan_max_static_pressure_pa": pressure_source,
            "thermal_load_w": load_source,
            "allowed_air_temperature_rise_c": rise_source,
        },
    }


def analyze_smart_fan_airflow(
    parts: list[CADPart],
    request: str,
) -> dict[str, Any]:
    """Estimate the enclosure operating point without claiming CFD accuracy."""

    by_name = {part.name: part for part in parts}
    chassis = by_name["fan_chassis"]
    guard = by_name["fan_guard"]
    cradle = by_name["mac_mini_cradle"]
    inputs = airflow_inputs_from_request(request)

    fan_diameter_mm = 120.0
    fan_disk_area_mm2 = pi * (fan_diameter_mm / 2) ** 2
    guard_area_mm2 = (
        fan_disk_area_mm2 * float(guard.metadata["open_area_ratio"])
    )
    lateral_area_mm2 = float(chassis.metadata["lateral_airflow_area_mm2"])
    controller_obstruction_area_mm2 = float(
        chassis.metadata["controller_flow_obstruction"][
            "projected_footprint_mm2"
        ]
    )
    controller_clear_area_mm2 = max(
        fan_disk_area_mm2 - controller_obstruction_area_mm2,
        0.0,
    )
    bottom_opening_mm = float(cradle.metadata["airflow_opening_mm"])
    bottom_area_mm2 = float(cradle.metadata["airflow_open_area_mm2"])
    throat_area_mm2 = min(
        guard_area_mm2,
        lateral_area_mm2,
        controller_clear_area_mm2,
        bottom_area_mm2,
    )
    throat_area_m2 = throat_area_mm2 / 1_000_000

    free_air_m3_s = inputs["fan_free_air_cfm"] * CFM_TO_M3_S
    maximum_pressure_pa = inputs["fan_max_static_pressure_pa"]
    loss_coefficient = 3.5
    system_coefficient = (
        0.5
        * AIR_DENSITY_KG_M3
        * loss_coefficient
        / throat_area_m2**2
    )
    fan_curve_slope = maximum_pressure_pa / free_air_m3_s
    operating_flow_m3_s = (
        -fan_curve_slope
        + sqrt(
            fan_curve_slope**2
            + 4 * system_coefficient * maximum_pressure_pa
        )
    ) / (2 * system_coefficient)
    operating_pressure_pa = system_coefficient * operating_flow_m3_s**2
    operating_cfm = operating_flow_m3_s / CFM_TO_M3_S
    throat_velocity_m_s = operating_flow_m3_s / throat_area_m2
    air_temperature_rise_c = inputs["thermal_load_w"] / (
        AIR_DENSITY_KG_M3
        * AIR_HEAT_CAPACITY_J_KG_K
        * operating_flow_m3_s
    )
    thermal_capacity_w = (
        AIR_DENSITY_KG_M3
        * AIR_HEAT_CAPACITY_J_KG_K
        * operating_flow_m3_s
        * inputs["allowed_air_temperature_rise_c"]
    )
    flow_retention = operating_flow_m3_s / free_air_m3_s
    throat_ratio = throat_area_mm2 / fan_disk_area_mm2
    desk_pad = chassis.metadata["desk_pad_interface"]
    installed_underbody_gap_mm = float(
        desk_pad["installed_pad_thickness_mm"]
    )
    chassis_perimeter_mm = 2.0 * (
        float(chassis.solid().BoundingBox().xlen)
        + float(chassis.solid().BoundingBox().ylen)
    )
    secondary_underbody_entry_area_mm2 = (
        chassis_perimeter_mm * installed_underbody_gap_mm
    )

    checks = {
        "continuous_flow_throat": {
            "passed": throat_ratio >= 0.55,
            "minimum_effective_area_mm2": round(throat_area_mm2, 1),
            "ratio_to_fan_disk": round(throat_ratio, 3),
            "limiting_section": (
                "fan_guard"
                if throat_area_mm2 == guard_area_mm2
                else "lateral_arches"
                if throat_area_mm2 == lateral_area_mm2
                else "controller_projection"
                if throat_area_mm2 == controller_clear_area_mm2
                else "bottom_opening"
            ),
        },
        "effective_airflow": {
            "passed": operating_cfm >= 20.0,
            "operating_cfm": round(operating_cfm, 2),
            "minimum_cfm": 20.0,
            "free_air_flow_retained": round(flow_retention, 3),
        },
        "throat_velocity": {
            "passed": throat_velocity_m_s <= 3.5,
            "velocity_m_s": round(throat_velocity_m_s, 2),
            "maximum_m_s": 3.5,
        },
        "bulk_air_temperature_rise": {
            "passed": (
                air_temperature_rise_c
                <= inputs["allowed_air_temperature_rise_c"]
            ),
            "estimated_rise_c": round(air_temperature_rise_c, 2),
            "allowed_rise_c": inputs["allowed_air_temperature_rise_c"],
            "thermal_load_w": inputs["thermal_load_w"],
        },
        "secondary_underbody_air_gap": {
            "passed": (
                installed_underbody_gap_mm >= 1.2
                and secondary_underbody_entry_area_mm2 >= 700.0
                and int(desk_pad["count"]) == 4
            ),
            "installed_gap_mm": installed_underbody_gap_mm,
            "perimeter_entry_area_mm2": round(
                secondary_underbody_entry_area_mm2,
                1,
            ),
            "ratio_to_fan_disk": round(
                secondary_underbody_entry_area_mm2 / fan_disk_area_mm2,
                3,
            ),
            "role": (
                "secondary inlet and pressure equalization only; four "
                "lateral arches remain the primary fan inlet"
            ),
        },
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "method": (
            "lumped-parameter estimate: linear fan curve intersected with "
            "quadratic enclosure resistance"
        ),
        "confidence": "pre-prototype engineering estimate; not CFD",
        "inputs": inputs,
        "geometry": {
            "fan_disk_area_mm2": round(fan_disk_area_mm2, 1),
            "guard_effective_area_mm2": round(guard_area_mm2, 1),
            "lateral_open_area_mm2": round(lateral_area_mm2, 1),
            "controller_projected_obstruction_mm2": round(
                controller_obstruction_area_mm2,
                1,
            ),
            "controller_clear_fan_plane_area_mm2": round(
                controller_clear_area_mm2,
                1,
            ),
            "bottom_opening_area_mm2": round(bottom_area_mm2, 1),
            "installed_underbody_gap_mm": installed_underbody_gap_mm,
            "secondary_underbody_entry_area_mm2": round(
                secondary_underbody_entry_area_mm2,
                1,
            ),
            "minimum_effective_area_mm2": round(throat_area_mm2, 1),
            "system_loss_coefficient": loss_coefficient,
        },
        "operating_point": {
            "effective_airflow_cfm": round(operating_cfm, 2),
            "effective_airflow_m3_h": round(operating_flow_m3_s * 3600, 2),
            "estimated_pressure_drop_pa": round(operating_pressure_pa, 2),
            "throat_velocity_m_s": round(throat_velocity_m_s, 2),
            "bulk_air_temperature_rise_c": round(
                air_temperature_rise_c,
                2,
            ),
            "thermal_capacity_at_allowed_rise_w": round(
                thermal_capacity_w,
                1,
            ),
        },
        "checks": checks,
        "required_physical_validation": [
            "replace default fan flow and static pressure with its datasheet curve",
            "measure Mac mini foot and inlet pressure loss",
            "measure inlet, exhaust, ambient, and Mac mini surface temperatures",
            "check recirculation, acoustic tone, vibration, and dust loading",
        ],
    }
