import pytest

from ai_cad_designer.cli import _parameters_from_calibration


def test_calibration_template_maps_measurements_to_structured_parameters() -> None:
    engineering, manufacturing = _parameters_from_calibration(
        {
            "current_values": {
                "engineering_parameters": {
                    "power_button_x_mm": -49.0,
                    "power_button_y_mm": 49.0,
                    "front_interface_delta_x_mm": 0.3,
                    "front_interface_delta_z_mm": -0.1,
                    "rear_interface_delta_x_mm": -0.2,
                    "rear_interface_delta_z_mm": 0.4,
                }
            },
            "measurement_results": {
                "selected_petg_clearance_per_side_mm": 0.35,
                "mac_corner_radius_mm": 9.3,
                "power_button_delta_x_mm": 0.4,
                "power_button_delta_y_mm": -0.2,
                "front_interface_residual_delta_x_mm": 0.6,
                "front_interface_residual_delta_z_mm": -0.3,
                "rear_interface_residual_delta_x_mm": 0.1,
                "rear_interface_residual_delta_z_mm": -0.5,
                "fan_mount_spacing_mm": 104.8,
                "fan_mount_hole_diameter_mm": 4.5,
                "ds18b20_probe_diameter_mm": 6.05,
                "ds18b20_snap_interference_per_side_mm": 0.08,
            },
        }
    )

    assert manufacturing["tolerance_mm"] == {
        "value": 0.35,
        "source": "calibration_coupon",
    }
    assert engineering["power_button_x_mm"] == {
        "value": -48.6,
        "source": "calibration_coupon",
    }
    assert engineering["power_button_y_mm"] == {
        "value": 48.8,
        "source": "calibration_coupon",
    }
    assert engineering["front_interface_delta_x_mm"]["value"] == pytest.approx(0.9)
    assert engineering["front_interface_delta_z_mm"]["value"] == pytest.approx(-0.4)
    assert engineering["rear_interface_delta_x_mm"]["value"] == pytest.approx(-0.1)
    assert engineering["rear_interface_delta_z_mm"]["value"] == pytest.approx(-0.1)
    assert engineering["front_interface_delta_x_mm"]["source"] == (
        "calibration_coupon"
    )
    assert engineering["fan_mount_spacing_mm"]["value"] == 104.8
    assert engineering["ds18b20_probe_diameter_mm"]["value"] == 6.05
    assert (
        engineering["ds18b20_snap_interference_per_side_mm"]["value"]
        == 0.08
    )
    assert engineering["mac_corner_radius_mm"]["source"] == (
        "calibration_coupon"
    )
