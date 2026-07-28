import pytest

from ai_cad_designer.agents.assembly_agent import AssemblyAgent
from ai_cad_designer.agents.calibration_agent import CalibrationAgent
from ai_cad_designer.agents.joint_agent import JointAgent


def test_smart_fan_engineering_parameters_drive_geometry_and_assembly() -> None:
    parameters = {
        "mac_length_mm": {"value": 127.2, "source": "user_supplied"},
        "mac_width_mm": {"value": 126.8, "source": "user_supplied"},
        "mac_height_mm": {"value": 50.3, "source": "user_supplied"},
        "mac_corner_radius_mm": {"value": 9.4, "source": "user_supplied"},
        "mac_foot_outer_diameter_mm": {
            "value": 99.5,
            "source": "user_supplied",
        },
        "mac_foot_height_mm": {"value": 2.2, "source": "user_supplied"},
        "power_button_x_mm": {"value": -48.5, "source": "user_supplied"},
        "power_button_y_mm": {"value": 48.2, "source": "user_supplied"},
        "power_button_diameter_mm": {
            "value": 8.2,
            "source": "user_supplied",
        },
        "fan_size_mm": {"value": 120.0, "source": "datasheet_reference"},
        "fan_thickness_mm": {"value": 24.0, "source": "user_supplied"},
        "fan_mount_spacing_mm": {
            "value": 104.8,
            "source": "user_supplied",
        },
        "fan_mount_hole_diameter_mm": {
            "value": 4.4,
            "source": "user_supplied",
        },
        "ds18b20_probe_diameter_mm": {
            "value": 6.1,
            "source": "user_supplied",
        },
        "ds18b20_snap_interference_per_side_mm": {
            "value": 0.08,
            "source": "calibration_coupon",
        },
    }
    parts = JointAgent().smart_fan_parts(
        engineering_parameters=parameters,
    )
    by_name = {part.name: part for part in parts}
    chassis = by_name["fan_chassis"]
    cradle = by_name["mac_mini_cradle"]
    plunger = by_name["power_button_plunger"]
    cover = by_name["controller_cover"]

    assert cradle.metadata["device_dimensions_mm"] == (127.2, 126.8, 50.3)
    assert cradle.metadata["airflow_bellmouth"][
        "mac_foot_outer_diameter_mm"
    ] == 99.5
    assert cradle.metadata["power_button_access"]["center_mm"] == (
        -48.5,
        48.2,
    )
    assert chassis.metadata["fan_deck_height_mm"] == 57.0
    assert chassis.metadata["fan_mount_interface"]["spacing_mm"] == (
        104.8,
        104.8,
    )
    assert chassis.metadata["fan_mount_interface"]["hole_diameter_mm"] == 4.4
    assert cover.metadata["ds18b20_probe_retention"][
        "probe_diameter_mm"
    ] == 6.1
    assert cover.metadata["ds18b20_probe_retention"][
        "entry_slot_width_mm"
    ] == pytest.approx(5.94)
    assert plunger.metadata["shaft_center_mm"] == (-52.4, 52.4)
    assert plunger.metadata["head_center_mm"] == (-48.5, 48.2)
    assert cradle.metadata["engineering_parameter_sources"][
        "mac_foot_outer_diameter_mm"
    ] == "user_supplied"

    assembly = AssemblyAgent().smart_fan(parts)
    translation, _ = assembly.placements["power_button_plunger"].toTuple()
    assert translation[0] == pytest.approx(-52.4)
    assert translation[1] == pytest.approx(52.4)


def test_smart_fan_rejects_out_of_range_engineering_parameter() -> None:
    with pytest.raises(
        ValueError,
        match="fan_mount_spacing_mm must be between 104 and 106 mm",
    ):
        JointAgent().smart_fan_parts(
            engineering_parameters={"fan_mount_spacing_mm": 108},
        )


def test_smart_fan_calibration_parts_are_low_cost_and_parameter_derived() -> None:
    agent = JointAgent()
    parts = agent.smart_fan_parts(
        engineering_parameters={
            "fan_mount_spacing_mm": 104.8,
            "fan_mount_hole_diameter_mm": 4.4,
            "power_button_x_mm": -48.5,
            "power_button_y_mm": 48.2,
            "front_interface_delta_x_mm": 0.6,
            "front_interface_delta_z_mm": -0.4,
            "rear_interface_delta_x_mm": -0.8,
            "rear_interface_delta_z_mm": 0.5,
        }
    )
    reference = agent.mac_mini_m4_fit_reference(
        front_interface_delta_x_mm=0.6,
        front_interface_delta_z_mm=-0.4,
        rear_interface_delta_x_mm=-0.8,
        rear_interface_delta_z_mm=0.5,
    )
    coupons = CalibrationAgent().smart_fan(parts, [reference])
    by_name = {part.name: part for part in coupons}

    assert list(by_name) == [
        "mac_corner_button_fit_coupon",
        "mac_front_io_alignment_gauge",
        "mac_rear_io_alignment_gauge",
        "fan_mount_fit_gauge",
        "petg_clearance_socket_gauge",
        "petg_clearance_test_pin",
        "ds18b20_snap_fit_coupon",
        "portal_bridge_support_coupon",
    ]
    assert all(part.solid().isValid() for part in coupons)
    assert all(len(part.solid().Solids()) == 1 for part in coupons)
    assert sum(part.solid().Volume() for part in coupons) < 25_000
    assert by_name["mac_front_io_alignment_gauge"].metadata[
        "coordinate_offsets_mm"
    ] == [0.6, -0.4]
    assert by_name["mac_rear_io_alignment_gauge"].metadata[
        "coordinate_offsets_mm"
    ] == [-0.8, 0.5]
    assert len(
        by_name["mac_front_io_alignment_gauge"].metadata[
            "interface_markers"
        ]
    ) == 3
    assert len(
        by_name["mac_rear_io_alignment_gauge"].metadata[
            "interface_markers"
        ]
    ) == 6
    assert all(
        by_name[f"mac_{face}_io_alignment_gauge"].metadata[
            "support_strategy"
        ]
        == "none"
        for face in ("front", "rear")
    )
    assert by_name["fan_mount_fit_gauge"].metadata[
        "mount_spacing_mm"
    ] == (104.8, 104.8)
    assert by_name["fan_mount_fit_gauge"].metadata[
        "mount_hole_diameter_mm"
    ] == 4.4
    assert by_name["mac_corner_button_fit_coupon"].metadata[
        "engineering_parameters"
    ]["power_button_x_mm"] == -48.5
    assert by_name["petg_clearance_socket_gauge"].metadata[
        "clearance_per_side_mm"
    ] == (0.15, 0.25, 0.35)
    assert by_name["ds18b20_snap_fit_coupon"].metadata[
        "bearing_count"
    ] == 2
    assert by_name["ds18b20_snap_fit_coupon"].metadata[
        "support_strategy"
    ] == "none"
    bridge_coupon = by_name["portal_bridge_support_coupon"]
    assert bridge_coupon.metadata["support_strategy"] == "none"
    assert bridge_coupon.metadata["features"][
        "main_portal_crown_bridge_mm"
    ] == 14.5
    assert bridge_coupon.metadata["features"][
        "usb_effective_bridge_mm"
    ] == 5.2
