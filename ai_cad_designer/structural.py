"""Conservative whole-assembly structural screening for the smart-fan stand."""

from __future__ import annotations

from math import hypot, pi
from typing import Any

from .core import CADPart


GRAVITY_M_S2 = 9.81


def analyze_smart_fan_structure(
    parts: list[CADPart],
    assembly,
) -> dict[str, Any]:
    """Screen the complete load path without claiming nonlinear FEA accuracy."""

    by_name = {part.name: part for part in parts}
    chassis = by_name["fan_chassis"]
    guard = by_name["fan_guard"]
    cradle = by_name["mac_mini_cradle"]
    parameters = cradle.metadata["engineering_parameters"]
    design_mass_kg = float(parameters["mac_design_mass_kg"])
    parameter_source = cradle.metadata["engineering_parameter_sources"][
        "mac_design_mass_kg"
    ]
    pad = cradle.metadata["support_pad_interface"]
    pad_positions = [tuple(position) for position in pad["positions_mm"]]
    pad_count = len(pad_positions)
    pad_diameter_mm = float(pad["pad_diameter_mm"])
    pad_area_mm2 = pi * (pad_diameter_mm / 2.0) ** 2
    remaining_skin_mm = float(pad["remaining_bottom_skin_mm"])

    vertical_load_factor_g = 3.0
    lateral_load_factor_g = 0.25
    vertical_force_n = design_mass_kg * GRAVITY_M_S2 * vertical_load_factor_g
    force_per_pad_n = vertical_force_n / pad_count
    static_force_per_pad_n = (
        design_mass_kg * GRAVITY_M_S2 / pad_count
    )
    contact_pressure_mpa = force_per_pad_n / pad_area_mm2
    static_contact_pressure_mpa = static_force_per_pad_n / pad_area_mm2

    # A conservative radial strip cut from the continuous annular shelf.  The
    # 12 mm span is deliberately longer than the actual local edge ligament.
    petg_modulus_mpa = 1500.0
    petg_yield_mpa = 35.0
    effective_beam_span_mm = 12.0
    effective_beam_width_mm = max(pad_diameter_mm, 8.5)
    second_moment_mm4 = (
        effective_beam_width_mm * remaining_skin_mm**3 / 12.0
    )
    petg_deflection_mm = (
        force_per_pad_n
        * effective_beam_span_mm**3
        / (3.0 * petg_modulus_mpa * second_moment_mm4)
    )
    petg_bending_stress_mpa = (
        6.0
        * force_per_pad_n
        * effective_beam_span_mm
        / (effective_beam_width_mm * remaining_skin_mm**2)
    )
    material_safety_factor = petg_yield_mpa / petg_bending_stress_mpa

    silicone_modulus_range_mpa = (3.0, 8.0)
    silicone_thickness_mm = float(pad["installed_pad_thickness_mm"])
    silicone_compression_soft_mm = (
        force_per_pad_n
        * silicone_thickness_mm
        / (pad_area_mm2 * silicone_modulus_range_mpa[0])
    )
    silicone_compression_stiff_mm = (
        force_per_pad_n
        * silicone_thickness_mm
        / (pad_area_mm2 * silicone_modulus_range_mpa[1])
    )
    combined_worst_displacement_mm = (
        petg_deflection_mm + silicone_compression_soft_mm
    )
    petg_free_travel_mm = 0.15
    hard_stop_travel_mm = 0.21

    desk_pad = chassis.metadata["desk_pad_interface"]
    desk_pad_positions = [
        tuple(position) for position in desk_pad["positions_mm"]
    ]
    desk_pad_count = len(desk_pad_positions)
    desk_pad_diameter_mm = float(desk_pad["pad_diameter_mm"])
    desk_pad_thickness_mm = float(
        desk_pad["installed_pad_thickness_mm"]
    )
    desk_pad_area_mm2 = pi * (desk_pad_diameter_mm / 2.0) ** 2
    desk_pad_pressure_mpa = force_per_pad_n / desk_pad_area_mm2
    support_span_x_mm = (
        max(float(position[0]) for position in desk_pad_positions)
        - min(float(position[0]) for position in desk_pad_positions)
        + desk_pad_diameter_mm
    )
    support_span_y_mm = (
        max(float(position[1]) for position in desk_pad_positions)
        - min(float(position[1]) for position in desk_pad_positions)
        + desk_pad_diameter_mm
    )
    conservative_silicone_friction_coefficient = 0.45
    lateral_design_force_n = (
        design_mass_kg * GRAVITY_M_S2 * lateral_load_factor_g
    )
    friction_capacity_n = (
        design_mass_kg
        * GRAVITY_M_S2
        * conservative_silicone_friction_coefficient
    )
    friction_safety_factor = friction_capacity_n / lateral_design_force_n
    cradle_translation, _ = assembly.placements[cradle.name].toTuple()
    mac_support_z_mm = (
        float(cradle_translation[2])
        + float(cradle.metadata["device_body_support_plane_mm"])
    )
    mac_height_mm = float(
        cradle.metadata["engineering_parameters"]["mac_height_mm"]
    )
    conservative_com_height_mm = mac_support_z_mm + mac_height_mm / 2.0
    conservative_com_offset_mm = 8.0
    minimum_half_span_mm = min(
        support_span_x_mm,
        support_span_y_mm,
    ) / 2.0
    restoring_arm_mm = minimum_half_span_mm - conservative_com_offset_mm
    tipping_threshold_g = restoring_arm_mm / conservative_com_height_mm
    tipping_safety_factor = tipping_threshold_g / lateral_load_factor_g

    fan_isolation = guard.metadata["isolator_interface"]
    rigid_guard_to_fan_gap_mm = float(
        fan_isolation["installed_protrusion_above_guard_mm"]
    )
    checks = {
        "four_point_contact_pressure": {
            "passed": contact_pressure_mpa <= 0.35,
            "pad_count": pad_count,
            "static_pressure_mpa": round(static_contact_pressure_mpa, 4),
            "3g_pressure_mpa": round(contact_pressure_mpa, 4),
            "screening_limit_mpa": 0.35,
        },
        "annular_shelf_deflection": {
            "passed": combined_worst_displacement_mm < petg_free_travel_mm,
            "petg_deflection_at_3g_mm": round(petg_deflection_mm, 4),
            "soft_silicone_compression_at_3g_mm": round(
                silicone_compression_soft_mm,
                4,
            ),
            "combined_worst_displacement_mm": round(
                combined_worst_displacement_mm,
                4,
            ),
            "petg_free_travel_mm": petg_free_travel_mm,
            "hard_stop_travel_mm": hard_stop_travel_mm,
        },
        "petg_bending_strength": {
            "passed": material_safety_factor >= 3.0,
            "3g_bending_stress_mpa": round(petg_bending_stress_mpa, 3),
            "screening_yield_strength_mpa": petg_yield_mpa,
            "safety_factor": round(material_safety_factor, 2),
        },
        "whole_assembly_tipping": {
            "passed": tipping_safety_factor >= 2.0,
            "support_span_mm": [
                support_span_x_mm,
                support_span_y_mm,
            ],
            "conservative_com_height_mm": round(
                conservative_com_height_mm,
                2,
            ),
            "conservative_com_offset_mm": conservative_com_offset_mm,
            "tipping_threshold_g": round(tipping_threshold_g, 3),
            "design_lateral_acceleration_g": lateral_load_factor_g,
            "safety_factor": round(tipping_safety_factor, 2),
        },
        "fan_vibration_load_path": {
            "passed": (
                int(fan_isolation["pocket_count"]) == 4
                and 0.1
                <= float(fan_isolation["compression_ratio"])
                <= 0.2
                and rigid_guard_to_fan_gap_mm > 0
            ),
            "isolator_count": int(fan_isolation["pocket_count"]),
            "compression_ratio": round(
                float(fan_isolation["compression_ratio"]),
                4,
            ),
            "rigid_guard_to_fan_gap_mm": rigid_guard_to_fan_gap_mm,
            "dynamic_envelope": (
                "3g vertical and 0.25g lateral screening; transmissibility "
                "requires measured fan imbalance and silicone hardness"
            ),
        },
        "desk_pad_contact_and_anti_slip": {
            "passed": (
                desk_pad_count == 4
                and desk_pad_thickness_mm >= 1.2
                and desk_pad_pressure_mpa <= 0.35
                and friction_safety_factor >= 1.5
                and bool(desk_pad["printed_base_remains_planar"])
                and not bool(desk_pad["support_required"])
            ),
            "pad_count": desk_pad_count,
            "pad_dimensions_mm": [
                desk_pad_diameter_mm,
                desk_pad_diameter_mm,
                desk_pad_thickness_mm,
            ],
            "3g_contact_pressure_mpa": round(
                desk_pad_pressure_mpa,
                4,
            ),
            "screening_pressure_limit_mpa": 0.35,
            "conservative_friction_coefficient": (
                conservative_silicone_friction_coefficient
            ),
            "design_lateral_force_n": round(lateral_design_force_n, 3),
            "friction_capacity_n": round(friction_capacity_n, 3),
            "friction_safety_factor": round(friction_safety_factor, 2),
            "installed_underbody_gap_mm": desk_pad_thickness_mm,
            "printed_base_remains_planar": bool(
                desk_pad["printed_base_remains_planar"]
            ),
        },
    }
    pad_centroid = [
        sum(float(position[index]) for position in pad_positions) / pad_count
        for index in range(2)
    ]
    maximum_pad_radius_mm = max(
        hypot(float(x), float(y)) for x, y in pad_positions
    )
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "method": (
            "closed-form static screening of the complete Mac-to-silicone-to-"
            "PETG-to-desk load path"
        ),
        "confidence": "pre-prototype analytical screen; not nonlinear FEA",
        "inputs": {
            "mac_design_mass_kg": design_mass_kg,
            "mac_design_mass_source": parameter_source,
            "vertical_load_factor_g": vertical_load_factor_g,
            "lateral_load_factor_g": lateral_load_factor_g,
            "petg_modulus_mpa": petg_modulus_mpa,
            "petg_screening_yield_mpa": petg_yield_mpa,
            "silicone_compressive_modulus_range_mpa": list(
                silicone_modulus_range_mpa
            ),
        },
        "load_path": {
            "sequence": [
                "Mac mini body",
                "four replaceable silicone contact pads",
                "3.7 mm PETG annular shelf",
                "continuous chassis perimeter ring",
                "four replaceable silicone desk isolation pads",
                "coplanar desk contact",
            ],
            "total_vertical_force_at_3g_n": round(vertical_force_n, 3),
            "force_per_pad_at_3g_n": round(force_per_pad_n, 3),
            "pad_centroid_xy_mm": [
                round(value, 3) for value in pad_centroid
            ],
            "maximum_pad_radius_mm": round(maximum_pad_radius_mm, 3),
            "effective_strip_model_mm": {
                "span": effective_beam_span_mm,
                "width": effective_beam_width_mm,
                "thickness": remaining_skin_mm,
                "second_moment_mm4": round(second_moment_mm4, 3),
            },
        },
        "checks": checks,
        "visualization": {
            "support_plane_z_mm": round(mac_support_z_mm, 3),
            "pad_positions_xy_mm": [
                [float(x), float(y)] for x, y in pad_positions
            ],
            "desk_support_span_mm": [
                support_span_x_mm,
                support_span_y_mm,
            ],
            "desk_pad_positions_xy_mm": [
                [float(x), float(y)] for x, y in desk_pad_positions
            ],
            "desk_contact_plane_z_mm": float(
                desk_pad["desk_contact_plane_z_mm"]
            ),
            "desk_pad_diameter_mm": desk_pad_diameter_mm,
            "desk_pad_thickness_mm": desk_pad_thickness_mm,
        },
        "required_physical_validation": [
            "weigh the installed Mac mini and enter its measured design mass",
            "print in the selected PETG orientation and measure 3g-equivalent shelf deflection",
            "verify all four silicone pads carry load without rocking",
            "measure fan vibration and acoustic tone across the PWM range",
            "repeat the lateral stability check with all cables connected",
        ],
    }
