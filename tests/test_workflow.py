import json
from pathlib import Path

import pytest

from ai_cad_designer.agents.design_agent import DesignAgent
from ai_cad_designer.agents.joint_agent import JointAgent
from ai_cad_designer.core import create_part
from ai_cad_designer.workflow import IndustrialDesignWorkflow


def test_workflow_rejects_invalid_structured_manufacturing_parameter(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="tolerance_mm must be between 0.1 and 1 mm",
    ):
        IndustrialDesignWorkflow(tmp_path).run(
            "Design a portable sensor enclosure",
            manufacturing_parameters={"tolerance_mm": 1.5},
        )


def test_smart_fan_rejects_out_of_range_design_mass() -> None:
    with pytest.raises(
        ValueError,
        match="mac_design_mass_kg must be between 0.5 and 2 kg",
    ):
        JointAgent().smart_fan_parts(
            engineering_parameters={"mac_design_mass_kg": 2.1},
        )


def test_hw_smart_fan_analysis_uses_canonical_hardware_bom() -> None:
    brief = DesignAgent().analyze(
        "基于 smices/hw_smart_fan 为 Mac mini M4 设计智能散热底座"
    )

    assert [component.name for component in brief.components] == [
        "Mac mini M4",
        "120 mm PWM fan",
        "12V DC-DC module",
        "5V DC-DC module",
        "ESP32-C3 Super Mini",
        "MOSFET PWM driver",
        "DS18B20 temperature probe",
    ]
    assert brief.components[1].dimensions_mm == (120.0, 120.0, 25.0)
    assert brief.components[4].dimensions_mm == (25.0, 22.0, 6.0)


def test_support_aware_print_layout_uses_measured_slicer_envelopes() -> None:
    parts = [
        create_part("shell", (100.0, 80.0, 30.0)),
        create_part("cover", (60.0, 50.0, 4.0)),
    ]
    manufacturing = {
        "parts": {
            "shell": {
                "filament_weight_g": 20.0,
                "estimated_seconds": 3600,
                "bridge_regions": 12,
                "overhang_regions": 30,
                "max_bridge_span_mm": 11.5,
                "support_used": False,
                "rotation_deg": [0.0, 0.0, 0.0],
            },
            "cover": {
                "filament_weight_g": 4.0,
                "estimated_seconds": 900,
                "bridge_regions": 0,
                "overhang_regions": 0,
                "max_bridge_span_mm": 0.0,
                "support_used": False,
                "rotation_deg": [0.0, 0.0, 0.0],
            },
        },
        "support_analysis": {
            "parts": {
                "shell": {
                    "additional_filament_weight_g": 5.0,
                    "additional_time_seconds": 1200,
                    "additional_filament_ratio": 0.25,
                    "additional_time_ratio": 0.3333,
                    "support_toolpath_envelope": {
                        "extrusion_move_count": 100,
                        "footprint_mm": [110.0, 90.0],
                        "local_bbox_xy_mm": [
                            -55.0,
                            -45.0,
                            55.0,
                            45.0,
                        ],
                        "z_range_mm": [0.2, 28.0],
                        "height_mm": 27.8,
                    },
                },
                "cover": {
                    "additional_filament_weight_g": 0.0,
                    "additional_time_seconds": 0,
                    "additional_filament_ratio": 0.0,
                    "additional_time_ratio": 0.0,
                    "support_toolpath_envelope": {},
                },
            }
        },
    }

    layout = IndustrialDesignWorkflow._print_layout_manifest(
        parts,
        manufacturing,
    )

    assert layout["measured_from_slicer"]
    assert layout["production_support_policy"] == "disabled"
    printed = [
        item for item in layout["items"] if not item.get("is_reference")
    ]
    support = [
        item
        for item in layout["items"]
        if item.get("reference_kind") == "auto_support_envelope"
    ]
    assert len(printed) == 2
    assert len(support) == 1
    assert support[0]["dimensions_mm"] == [110.0, 90.0, 27.8]
    assert printed[0]["print_metrics"]["overhang_regions"] == 30
    assert (
        printed[0]["print_metrics"][
            "auto_support_additional_filament_weight_g"
        ]
        == 5.0
    )


def test_opening_support_economy_counts_support_against_void_savings() -> None:
    chassis = create_part("fan_chassis", (10.0, 10.0, 10.0))
    chassis.metadata.update(
        {
            "lateral_airflow_area_mm2": 8000.0,
            "lateral_airflow_ratio_to_fan": 0.8,
            "lateral_airflow_slot_count": 4,
            "exterior_continuity": {
                "opening_style": "self-supporting test arch",
                "maximum_opening_bridge_mm": 10.0,
                "minimum_roof_slope_deg": 45.0,
            },
            "controller_vent_pattern": {
                "external_self_supporting_arch_count": 3,
                "internal_self_supporting_arch_count": 2,
                "strategy": "functional self-supporting test arches",
                "external_maximum_closing_bridge_mm": 8.0,
                "maximum_closing_bridge_mm": 8.0,
                "external_arch_minimum_roof_slope_deg": 45.0,
                "internal_minimum_roof_slope_deg": 45.0,
            },
            "controller_service_access": {
                "port_style": "self-supporting USB test arch",
                "port_effective_bridge_mm": 5.0,
                "port_minimum_roof_slope_deg": 45.0,
            },
        }
    )
    control = create_part(
        "fan_chassis_sealed_portal_control_DO_NOT_PRINT",
        (12.0, 10.0, 10.0),
    )
    control.metadata.update(
        {
            "control_kind": "sealed_main_air_portals",
            "restored_portal_count": 4,
        }
    )
    manufacturing = {
        "parts": {
            "fan_chassis": {
                "filament_weight_g": 10.0,
                "estimated_seconds": 100,
                "support_used": False,
            }
        },
        "support_analysis": {
            "support_required": False,
            "parts": {
                "fan_chassis": {
                    "additional_filament_weight_g": 3.0,
                    "additional_time_seconds": 60,
                }
            },
        },
    }
    control_manufacturing = {
        "parts": {
            control.name: {
                "filament_weight_g": 15.0,
                "estimated_seconds": 120,
            }
        }
    }
    control_validation = {
        control.name: {
            "printable": True,
            "geometry": {
                "kernel": "OpenCascade/OCP",
                "solid_count": 1,
            },
        }
    }

    report = IndustrialDesignWorkflow._opening_support_economy(
        [chassis],
        [control],
        manufacturing,
        control_manufacturing,
        control_validation,
    )

    assert report["passed"]
    assert report["support_free_comparison"]["material_saved_g"] == 5.0
    assert report["support_free_comparison"]["time_saved_seconds"] == 20
    assert (
        report["if_auto_support_is_enabled"][
            "net_material_advantage_vs_sealed_g"
        ]
        == 2.0
    )
    assert (
        report["if_auto_support_is_enabled"][
            "net_time_advantage_vs_sealed_seconds"
        ]
        == -40
    )
    support_cost_gate = report["checks"][
        "support_cost_vs_void_benefit"
    ]
    assert support_cost_gate["passed"]
    assert support_cost_gate["production_void_accepted"]
    assert not support_cost_gate[
        "support_dependent_void_economy_passed"
    ]
    assert not support_cost_gate["support_dependent_void_accepted"]
    assert support_cost_gate["rejection_triggers"][
        "non_positive_time_advantage"
    ]
    assert report["checks"]["opening_inventory_gate"]["passed"]
    assert report["checks"]["opening_inventory_gate"][
        "opening_count"
    ] == 10
    assert len(report["opening_decisions"]) == 3
    assert all(
        opening["accepted"]
        and not opening["decorative"]
        and not opening["support_required"]
        for opening in report["opening_decisions"]
    )


def test_localized_support_plan_classifies_all_contact_bands() -> None:
    chassis = create_part("fan_chassis", (132.0, 132.0, 61.0))
    chassis.metadata["controller_service_access"] = {
        "usb_port_center_mm": (7.0, 30.0, 22.65),
        "usb_port_dimensions_mm": (20.0, 12.5),
        "port_bottom_z_mm": 16.4,
        "port_roof_start_z_mm": 20.9,
        "port_top_z_mm": 28.9,
    }
    manufacturing = {
        "support_analysis": {
            "support_free_baseline_passed": True,
            "additional_filament_weight_g": 8.63,
            "additional_time_seconds": 1868,
            "parts": {
                "fan_chassis": {
                    "support_toolpath_envelope": {
                        "feature_move_counts": {
                            "support": 31587,
                            "support_interface": 962,
                        },
                        "z_bands": [
                            {
                                "nominal_z_range_mm": [25.0, 30.0],
                                "actual_z_range_mm": [25.0, 29.8],
                                "extrusion_move_count": 2891,
                                "feature_move_counts": {
                                    "support": 2556,
                                    "support_interface": 335,
                                },
                            },
                            {
                                "nominal_z_range_mm": [50.0, 55.0],
                                "actual_z_range_mm": [50.0, 54.8],
                                "extrusion_move_count": 2760,
                                "feature_move_counts": {
                                    "support": 2228,
                                    "support_interface": 532,
                                },
                            },
                            {
                                "nominal_z_range_mm": [55.0, 60.0],
                                "actual_z_range_mm": [55.0, 56.6],
                                "extrusion_move_count": 529,
                                "feature_move_counts": {
                                    "support": 434,
                                    "support_interface": 95,
                                },
                            },
                        ],
                    }
                }
            },
        },
        "support_threshold_sweep": {
            "passed": True,
            "trials": [
                {
                    "threshold_angle_deg": 30.0,
                    "additional_filament_weight_g": 8.63,
                    "additional_time_seconds": 1868,
                    "support_extrusion_move_count": 32549,
                },
                {
                    "threshold_angle_deg": 35.0,
                    "additional_filament_weight_g": 20.74,
                    "additional_time_seconds": 5201,
                    "support_extrusion_move_count": 106019,
                },
                {
                    "threshold_angle_deg": 45.0,
                    "additional_filament_weight_g": 29.0,
                    "additional_time_seconds": 7698,
                    "support_extrusion_move_count": 169297,
                },
            ],
        },
    }
    calibration = {
        "parts": {
            "portal_bridge_support_coupon": {
                "features": {
                    "main_portal_crown_bridge_mm": 14.5,
                    "usb_effective_bridge_mm": 5.2,
                },
                "acceptance": {
                    "maximum_crown_sag_mm": 0.5,
                },
            }
        }
    }

    plan = IndustrialDesignWorkflow._localized_support_decision_plan(
        manufacturing,
        calibration,
        chassis,
    )

    assert plan["passed"]
    assert not plan["production_default"]["support_enabled"]
    assert plan["classified_support_interface_move_count"] == 962
    assert plan["total_support_interface_move_count"] == 962
    assert [region["id"] for region in plan["regions"]] == [
        "controller_and_service_roofs",
        "main_portal_crowns",
        "upper_retention_details",
    ]
    assert plan["threshold_guardrail"][
        "cost_increase_at_35_deg_vs_30_deg"
    ] == {
        "filament_weight_g": 12.11,
        "time_seconds": 3333,
    }
    assert plan["physical_gate"]["maximum_crown_sag_mm"] == 0.5


def test_robot_request_is_decomposed() -> None:
    request = (
        "我有 ESP32、18650电池、摄像头、风扇。设计一个桌面机器人外壳。"
        "要求不用螺丝、可拆卸、3D打印、PETG材料。"
    )
    agent = DesignAgent()
    brief = agent.analyze(request)
    proposal = agent.propose(brief)
    assert brief.product == "desktop robot enclosure"
    assert [part.name for part in proposal.parts] == [
        "body",
        "cover",
        "battery",
        "camera_mount",
    ]
    assert {part.assembly_method for part in proposal.parts} >= {
        "dovetail",
        "snap_fit",
        "sliding_rail",
        "mortise_tenon",
    }


def test_support_strategy_is_detected_and_carried_through_proposal() -> None:
    request = (
        "我要一个桌面机器人外壳，尽量少支撑；不用螺丝、可拆卸、3D打印、PETG。"
    )
    agent = DesignAgent()
    brief = agent.analyze(request)
    proposal = agent.propose(brief)

    assert brief.support_strategy == "minimal"
    assert proposal.support_strategy == "minimal"

    request = (
        "设计一个桌面机器人外壳，不要支撑，其他都一样。"
    )
    brief = agent.analyze(request)
    proposal = agent.propose(brief)

    assert brief.support_strategy == "none"
    assert proposal.support_strategy == "none"


def test_sensor_workflow_exports_printable_parts(tmp_path: Path) -> None:
    result = IndustrialDesignWorkflow(tmp_path).run(
        "Design a portable sensor enclosure, screwless and removable",
        manufacturing_parameters={
            "material": {"value": "PETG", "source": "user_supplied"},
            "tolerance_mm": {
                "value": 0.3,
                "source": "calibration_coupon",
            },
            "wall_thickness_mm": {
                "value": 2.8,
                "source": "user_supplied",
            },
            "layer_height_mm": {
                "value": 0.24,
                "source": "user_supplied",
            },
        },
    )
    assert result.passed
    payload = result.to_dict()
    assert payload["evidence"]["files"]["status"] == "passed"
    assert payload["evidence"]["geometry"]["status"] == "passed"
    assert payload["evidence"]["slicing"]["status"] == "not_run"
    assert payload["evidence"]["physical"]["status"] == "not_run"
    assert payload["preview"]["visual"]["status"] == "not_run"
    assert not payload["manufacturable"]
    assert payload["planner"] == {
        "requested": "rules",
        "actual": "rules",
        "fallback": {
            "status": "not_run",
            "summary": "Rules fallback was not requested.",
            "details": {"coverage": "not_applicable"},
        },
    }
    assert result.proposal.brief.tolerance_mm == 0.3
    assert result.proposal.brief.wall_thickness_mm == 2.8
    assert result.proposal.brief.layer_height_mm == 0.24
    assert (tmp_path / "sensor_base.step").is_file()
    assert (tmp_path / "sensor_base.stl").is_file()
    assert (tmp_path / "sensor_lid.step").is_file()
    assert (tmp_path / "sensor_lid.stl").is_file()
    assert (tmp_path / "two_piece_sensor_enclosure.step").is_file()


def test_requested_blender_preview_failure_keeps_cad_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_preview(stl_paths, output_dir):
        assert [path.name for path in stl_paths] == [
            "sensor_base.stl",
            "sensor_lid.stl",
        ]
        preview_dir = output_dir / "blender_preview"
        preview_dir.mkdir()
        manifest = preview_dir / "visual_preview.json"
        diagnostic = preview_dir / "diagnostic.json"
        manifest.write_text("{}", encoding="utf-8")
        diagnostic.write_text("render failed", encoding="utf-8")
        return {
            "status": "failed",
            "summary": "Blender preview failed; diagnostics were retained.",
            "artifacts": [
                "blender_preview/visual_preview.json",
                "blender_preview/diagnostic.json",
            ],
        }

    monkeypatch.setattr(
        "ai_cad_designer.workflow.render_isometric_preview",
        failed_preview,
    )
    result = IndustrialDesignWorkflow(tmp_path).run(
        "Design a portable sensor enclosure",
        blender_preview=True,
    )

    assert result.passed
    assert result.to_dict()["preview"]["visual"]["status"] == "failed"
    assert (tmp_path / "blender_preview" / "visual_preview.json").is_file()
    assert (tmp_path / "blender_preview" / "diagnostic.json").is_file()
    assert all(
        "blender_preview" not in path or Path(path).is_file()
        for path in result.exported_files
    )


def test_smart_fan_demo_exports_complete_assembly(tmp_path: Path) -> None:
    result = IndustrialDesignWorkflow(tmp_path).run(
        "基于 smices/hw_smart_fan 设计智能散热控制器：ESP32-C3、"
        "DS18B20、MOSFET、12V 与 5V DC-DC 和 120mm PWM 风扇；"
        "不用螺丝，可拆卸，PETG。"
    )

    assert result.passed
    assert result.proposal.brief.design_family == "smart_fan"
    fan_component = next(
        component
        for component in result.proposal.brief.components
        if component.name == "120 mm PWM fan"
    )
    assert fan_component.dimensions_mm == (120.0, 120.0, 25.0)
    probe_component = next(
        component
        for component in result.proposal.brief.components
        if component.name == "DS18B20 temperature probe"
    )
    assert probe_component.dimensions_mm == (30.0, 6.0, 6.0)
    assert result.bom is not None
    assert result.bom["passed"]
    assert result.bom["active_hardware_count"] == 7
    assert result.bom["matched_hardware_count"] == 7
    assert all(item["passed"] for item in result.bom["items"])
    assert len(result.bom["consumables"]) == 3
    assert result.bom["consumables"][-1] == {
        "name": "desk silicone isolation pad",
        "quantity": 4,
        "installed_reference_count": 4,
    }
    assert (tmp_path / "hardware_bom_consistency.json").is_file()
    cover_plan = next(
        part
        for part in result.proposal.parts
        if part.name == "controller_cover"
    )
    assert cover_plan.dimensions_mm == (52.5, 52.5, 20)
    assert [part.name for part in result.proposal.parts] == [
        "fan_chassis",
        "controller_cover",
        "fan_guard",
        "mac_mini_cradle",
        "power_button_plunger",
    ]
    assert (tmp_path / "fan_chassis.step").is_file()
    assert (tmp_path / "controller_cover.stl").is_file()
    assert (tmp_path / "fan_guard.stl").is_file()
    assert (tmp_path / "mac_mini_cradle.stl").is_file()
    assert (tmp_path / "power_button_plunger.stl").is_file()
    assert (tmp_path / "mac_mini_m4_fit_reference.step").is_file()
    assert (tmp_path / "mac_mini_m4_fit_reference.stl").is_file()
    for reference_name in (
        "pwm_fan_120mm_reference",
        "dc_dc_12v_reference",
        "dc_dc_5v_reference",
        "esp32_c3_super_mini_reference",
        "mosfet_pwm_driver_reference",
        "ds18b20_probe_reference",
        "fan_isolator_1_reference",
        "fan_isolator_2_reference",
        "fan_isolator_3_reference",
        "fan_isolator_4_reference",
        "mac_support_pad_1_reference",
        "mac_support_pad_2_reference",
        "mac_support_pad_3_reference",
        "mac_support_pad_4_reference",
        "desk_isolation_pad_1_reference",
        "desk_isolation_pad_2_reference",
        "desk_isolation_pad_3_reference",
        "desk_isolation_pad_4_reference",
    ):
        assert (tmp_path / f"{reference_name}.step").is_file()
        assert (tmp_path / f"{reference_name}.stl").is_file()
    assert (tmp_path / "smart_fan_enclosure.step").is_file()
    assert (tmp_path / "smart_fan_installed_assembly.step").is_file()
    control_name = "fan_chassis_sealed_portal_control_DO_NOT_PRINT"
    assert (
        tmp_path / "manufacturing_controls" / f"{control_name}.step"
    ).is_file()
    assert (
        tmp_path / "manufacturing_controls" / f"{control_name}.stl"
    ).is_file()
    control_preview = result.preview["manufacturing_controls"]
    assert len(control_preview["items"]) == 1
    assert control_preview["items"][0]["do_not_print"]
    assert (
        control_preview["items"][0]["reference_kind"]
        == "manufacturing_control"
    )
    for calibration_name in (
        "mac_corner_button_fit_coupon",
        "mac_front_io_alignment_gauge",
        "mac_rear_io_alignment_gauge",
        "fan_mount_fit_gauge",
        "petg_clearance_socket_gauge",
        "petg_clearance_test_pin",
        "ds18b20_snap_fit_coupon",
        "portal_bridge_support_coupon",
    ):
        assert (tmp_path / f"{calibration_name}.step").is_file()
        assert (tmp_path / f"{calibration_name}.stl").is_file()
    assert (tmp_path / "fit_calibration_report.json").is_file()
    assert (tmp_path / "calibration_measurement_template.json").is_file()
    assert result.calibration is not None
    assert result.calibration["passed"]
    assert len(result.calibration["parts"]) == 8
    assert len(result.preview["calibration"]["items"]) == 8
    for face in ("front", "rear"):
        gauge = result.calibration["parts"][
            f"mac_{face}_io_alignment_gauge"
        ]
        assert gauge["dimensions_mm"] == [127.0, 18.0, 1.2]
        assert gauge["acceptance"]["support_material_allowed"] is False
        gauge_part = next(
            item
            for item in result.preview["calibration"]["items"]
            if item["name"] == f"mac_{face}_io_alignment_gauge"
        )
        assert gauge_part["dimensions_mm"] == [127.0, 18.0, 1.2]
    measurement_template = json.loads(
        (tmp_path / "calibration_measurement_template.json").read_text()
    )
    assert measurement_template["allowed_clearance_coupon_values_mm"] == [
        0.15,
        0.25,
        0.35,
    ]
    assert (
        measurement_template["regeneration_mapping"][
            "power_button_delta_x_mm"
        ]
        == "add to engineering_parameters.power_button_x_mm"
    )
    assert measurement_template["schema_version"] == 3
    assert len(
        measurement_template["mac_io_interface_snapshot"]["front"][
            "interface_markers"
        ]
    ) == 3
    assert len(
        measurement_template["mac_io_interface_snapshot"]["rear"][
            "interface_markers"
        ]
    ) == 6
    assert (
        measurement_template["regeneration_mapping"][
            "front_interface_residual_delta_x_mm"
        ]
        == "add to engineering_parameters.front_interface_delta_x_mm"
    )
    assert (
        measurement_template["measurement_results"][
            "portal_bridge_coupon_passed"
        ]
        is None
    )
    assert (
        measurement_template["regeneration_mapping"][
            "ds18b20_probe_diameter_mm"
        ]
        == "engineering_parameters.ds18b20_probe_diameter_mm"
    )
    assert (tmp_path / "airflow_thermal_report.json").is_file()
    assert (tmp_path / "structural_load_report.json").is_file()
    assert result.airflow is not None
    assert result.airflow["passed"]
    assert result.airflow["operating_point"]["effective_airflow_cfm"] >= 20
    assert (
        result.airflow["operating_point"]["bulk_air_temperature_rise_c"]
        <= result.airflow["inputs"]["allowed_air_temperature_rise_c"]
    )
    assert result.airflow["checks"]["secondary_underbody_air_gap"][
        "passed"
    ]
    assert result.airflow["checks"]["secondary_underbody_air_gap"][
        "installed_gap_mm"
    ] == 1.5
    assert result.structure is not None
    assert result.structure["passed"]
    assert result.structure["inputs"]["mac_design_mass_kg"] == 1.0
    assert result.structure["checks"]["annular_shelf_deflection"]["passed"]
    assert result.structure["checks"]["desk_pad_contact_and_anti_slip"][
        "passed"
    ]
    assert (
        result.structure["checks"]["whole_assembly_tipping"]["safety_factor"]
        >= 2.0
    )
    assert len(result.preview["structural_load_path"]["items"]) == 9
    assert len(result.preview["assembly"]["items"]) == 24
    preview_printed = {
        item["name"]: item
        for item in result.preview["assembly"]["items"]
        if not item.get("is_reference")
    }
    assert preview_printed["fan_chassis"]["color_rgb"] == [
        0.55,
        0.74,
        0.12,
    ]
    assert (
        preview_printed["mac_mini_cradle"]["color_rgb"]
        == preview_printed["fan_chassis"]["color_rgb"]
    )
    references = [
        item
        for item in result.preview["assembly"]["items"]
        if item.get("is_reference")
    ]
    assert references[0]["name"].startswith("Mac mini M4")
    assert references[0]["dimensions_mm"] == [127.0, 127.0, 50.0]
    assert references[0]["reference_kind"] == "device"
    assert (
        references[0]["file_name"]
        == "mac_mini_m4_fit_reference.stl"
    )
    assert references[0]["translation_mm"][2] == 60.2
    mac_interface_access = result.preview["mac_interface_access"]
    assert len(mac_interface_access["items"]) == 9
    assert sum(
        item["face"] == "front"
        for item in mac_interface_access["items"]
    ) == 3
    assert sum(
        item["face"] == "rear"
        for item in mac_interface_access["items"]
    ) == 6
    assert all(
        item["reference_kind"] == "device_interface_access"
        and item["primitive"] == "box"
        for item in mac_interface_access["items"]
    )
    assert [item["name"] for item in references[1:]] == [
        "120 mm PWM fan",
        "12V DC-DC module",
        "5V DC-DC module",
        "ESP32-C3 Super Mini",
        "MOSFET PWM driver",
        "DS18B20 Ø6 mm temperature probe",
        "Fan isolator 1 · silicone 10×4.6×1.5 mm",
        "Fan isolator 2 · silicone 10×4.6×1.5 mm",
        "Fan isolator 3 · silicone 10×4.6×1.5 mm",
        "Fan isolator 4 · silicone 10×4.6×1.5 mm",
        "Mac support pad 1 · silicone Ø8×0.5 mm",
        "Mac support pad 2 · silicone Ø8×0.5 mm",
        "Mac support pad 3 · silicone Ø8×0.5 mm",
        "Mac support pad 4 · silicone Ø8×0.5 mm",
        "Desk isolation pad 1 · silicone Ø6×1.5 mm",
        "Desk isolation pad 2 · silicone Ø6×1.5 mm",
        "Desk isolation pad 3 · silicone Ø6×1.5 mm",
        "Desk isolation pad 4 · silicone Ø6×1.5 mm",
    ]
    assert all(
        item["reference_kind"] == "internal_hardware"
        for item in references[1:7]
    )
    assert all(
        item["reference_kind"] == "service_hardware"
        for item in references[7:11]
    )
    assert all(
        item["reference_kind"] == "contact_hardware"
        for item in references[11:15]
    )
    assert all(
        item["reference_kind"] == "desk_contact_hardware"
        for item in references[15:]
    )
    assert all(0.0 < float(item["opacity"]) < 1.0 for item in references)
    assert (
        references[1]["file_name"]
        == "pwm_fan_120mm_reference.stl"
    )
    assert all(
        "primitive" not in item
        for item in references
    )
    review = json.loads(
        (tmp_path / "industrial_design_review.json").read_text()
    )
    assert review["passed"]
    assert result.design_review is not None
    assert result.design_review["passed"]
    passing_review = result.design_review
    result.design_review = {"passed": False}
    assert not result.passed
    result.design_review = passing_review
    assert (
        review["checks"]["lateral_airflow_capacity"]["ratio_to_fan_disk"]
        >= 0.65
    )
    assert review["checks"]["airflow_thermal_operating_point"]["passed"]
    assert review["checks"]["flat_stable_desk_base"]["passed"]
    assert review["checks"]["flat_stable_desk_base"][
        "coplanarity_error_mm"
    ] <= 0.01
    assert review["checks"]["flat_stable_desk_base"][
        "total_planar_contact_area_mm2"
    ] >= 5000.0
    desk_feet = review["checks"]["replaceable_desk_isolation_feet"]
    assert desk_feet["passed"]
    assert desk_feet["reference_count"] == 4
    assert desk_feet["installed_underbody_gap_mm"] == 1.5
    assert desk_feet["lateral_footprint_overrun_mm"] == 0.0
    assert desk_feet["power_plunger_to_desk_clearance_mm"] >= 2.0
    assert desk_feet["printed_base_remains_planar"]
    assert not desk_feet["support_required"]
    assert (
        desk_feet["minimum_preload_contact_coverage_ratio"]
        >= desk_feet["minimum_required_contact_coverage_ratio"]
    )
    assert max(desk_feet["preload_pad_cover_overlaps_mm3"]) <= 0.01
    fixed_island = desk_feet["fixed_corner_load_island"]
    assert fixed_island["single_solid_after_union"]
    assert fixed_island["existing_chassis_overlap_mm3"] >= 15.0
    assert fixed_island["added_chassis_volume_mm3"] >= 85.0
    assert fixed_island["cover_overlap_mm3"] <= 0.01
    assert fixed_island["pad_containment_margin_mm"] >= 0.25
    assert (
        fixed_island["cover_clearance"]["removed_cover_volume_mm3"]
        <= 0.01
    )
    assert review["checks"]["guard_open_area"]["open_area_ratio"] >= 0.6
    assert review["checks"]["internal_hardware_layout"]["passed"]
    probe_retention = review["checks"][
        "serviceable_ds18b20_probe_retention"
    ]
    assert probe_retention["passed"]
    assert probe_retention["bearing_count"] == 2
    assert probe_retention["support_column_count"] == 1
    assert probe_retention["support_platform_corbel_count"] == 2
    assert probe_retention["support_platform_corbel_run_mm"] == 4.0
    assert probe_retention["support_platform_corbel_rise_mm"] == 4.0
    assert probe_retention["support_platform_corbel_slope_deg"] >= 45.0
    assert probe_retention["support_platform_corbel_depth_mm"] == 8.0
    assert probe_retention["support_platform_bridge_span_mm"] == 0.0
    assert probe_retention["nominal_cover_overlap_mm3"] <= 0.01
    assert probe_retention["release_path_max_overlap_mm3"] >= 0.001
    assert probe_retention["release_path_final_overlap_mm3"] <= 0.01
    assert probe_retention["chassis_overlap_mm3"] <= 0.01
    assert probe_retention["guard_overlap_mm3"] <= 0.01
    assert probe_retention["fan_overlap_mm3"] <= 0.01
    probe_coupon = review["checks"]["physical_ds18b20_fit_coupon"]
    assert probe_coupon["passed"]
    assert probe_coupon["validation"]["geometry"]["solid_count"] == 1
    bridge_coupon = review["checks"][
        "physical_portal_bridge_support_coupon"
    ]
    assert bridge_coupon["passed"]
    assert bridge_coupon["validation"]["geometry"]["solid_count"] == 1
    assert bridge_coupon["part"]["features"][
        "main_portal_crown_bridge_mm"
    ] == 14.5
    assert bridge_coupon["part"]["features"][
        "usb_effective_bridge_mm"
    ] == 5.2
    assert not bridge_coupon["part"]["acceptance"][
        "support_material_allowed"
    ]
    component_retention = review["checks"][
        "physical_component_retention"
    ]
    assert component_retention["passed"]
    assert component_retention["cover_solid_count"] == 1
    assert component_retention["cover_max_z_mm"] <= 29.0
    assert component_retention["dc_dc_retention"][
        "cantilever_arm_count"
    ] == 4
    assert (
        component_retention["dc_dc_retention"][
            "nominal_surface_strain"
        ]
        <= component_retention["dc_dc_retention"][
            "recommended_petg_strain_limit"
        ]
    )
    assert component_retention["upper_board_retention"][
        "cantilever_hook_count"
    ] == 4
    assert component_retention["upper_board_retention"][
        "y_guide_count"
    ] == 4
    assert all(
        value <= 0.01
        for value in component_retention[
            "installed_overlap_mm3"
        ].values()
    )
    assert all(
        value >= 0.001
        for value in component_retention[
            "upward_stop_overlap_mm3"
        ].values()
    )
    assert all(
        min(values) >= 0.001
        for values in component_retention[
            "four_axis_lateral_stop_overlaps_mm3"
        ].values()
    )
    service_access = review["checks"][
        "serviceable_electronics_carrier"
    ]
    assert service_access["passed"]
    assert service_access["carrier_removal_direction"] == "-Z"
    assert service_access["terminal_tool_zone_count"] == 12
    assert service_access["release_tool_zone_count"] == 8
    assert (
        service_access["carrier_payload_path_max_overlap_mm3"]
        <= 0.01
    )
    assert (
        service_access["rigid_floor_path_max_overlap_mm3"]
        <= 0.01
    )
    assert (
        service_access["usb_corridor_chassis_obstruction_mm3"]
        <= 0.01
    )
    controller_service_access = service_access[
        "controller_service_access"
    ]
    assert (
        controller_service_access["port_style"]
        == "rounded self-supporting inboard service arch"
    )
    assert (
        controller_service_access["port_minimum_roof_slope_deg"]
        >= 45.0
    )
    assert controller_service_access["port_effective_bridge_mm"] <= 5.2
    assert controller_service_access["port_open_area_mm2"] >= 185.0
    assert (
        controller_service_access["residual_after_cut_mm3"]
        <= 0.01
    )
    assert (
        component_retention["external_service_cover_overlap_mm3"]
        <= 0.01
    )
    assert review["checks"]["exportable_reference_cad"]["passed"]
    assert review["checks"]["exportable_reference_cad"][
        "actual_count"
    ] == 19
    installed_assembly = review["checks"][
        "complete_installed_assembly_cad"
    ]
    assert installed_assembly["passed"]
    assert installed_assembly["component_count"] == 24
    assert installed_assembly["includes_printed_parts"]
    assert installed_assembly["includes_reference_parts"]
    assert installed_assembly["envelope_mm"][0] <= 134.01
    assert installed_assembly["envelope_mm"][1] <= 134.01
    assert abs(installed_assembly["envelope_mm"][2] - 111.7) <= 0.1
    assert (
        installed_assembly["step_file"]
        == "smart_fan_installed_assembly.step"
    )
    step_roundtrip = review["checks"][
        "exported_step_roundtrip_envelope"
    ]
    assert step_roundtrip["passed"]
    assert step_roundtrip["roundtrip"]["printable"]["solid_count"] == 5
    assert step_roundtrip["roundtrip"]["installed"]["solid_count"] == 24
    assert all(
        value <= 134.01
        for value in step_roundtrip["roundtrip"]["installed"][
            "envelope_mm"
        ][:2]
    )
    assert review["checks"]["mac_mini_interface_reference"]["passed"]
    assert review["checks"]["continuous_design_language"]["passed"]
    assert review["checks"]["continuous_design_language"][
        "continuous_top_rail"
    ]
    assert not review["checks"]["continuous_design_language"][
        "openings_break_outer_edge"
    ]
    assert review["checks"]["continuous_design_language"][
        "window_count"
    ] == 4
    assert review["checks"]["continuous_design_language"][
        "opening_width_mm"
    ] == 114.0
    assert review["checks"]["continuous_design_language"][
        "minimum_continuous_side_web_mm"
    ] >= 9.0
    assert review["checks"]["continuous_design_language"][
        "top_rail_minimum_mm"
    ] >= 5.0
    assert review["checks"]["continuous_design_language"][
        "continuous_lower_skirt"
    ]
    assert review["checks"]["continuous_design_language"][
        "lower_skirt_minimum_mm"
    ] >= 7.5
    assert review["checks"]["continuous_design_language"][
        "repeated_vertical_mullion_count"
    ] == 0
    assert review["checks"]["continuous_design_language"][
        "external_auxiliary_vent_slot_count"
    ] == 0
    assert (
        "one continuous-tangent rounded-crown spline air portal per face"
        in review["checks"]["continuous_design_language"]["opening_style"]
    )
    assert review["checks"]["continuous_design_language"][
        "continuous_curvature_roof"
    ]
    assert (
        review["checks"]["continuous_design_language"]["roof_curve_kind"]
        == (
            "symmetric self-supporting spline flanks with "
            "tangent-continuous rounded crown"
        )
    )
    assert review["checks"]["continuous_design_language"][
        "roof_endpoint_tangents_constrained"
    ]
    assert review["checks"]["continuous_design_language"][
        "crown_center_tangent_horizontal"
    ]
    assert review["checks"]["continuous_design_language"][
        "crown_flank_tangent_continuity"
    ]
    assert (
        review["checks"]["continuous_design_language"]["crown_rise_mm"]
        >= 2.5
    )
    assert (
        review["checks"]["continuous_design_language"][
            "crown_print_strategy"
        ]
        == "one-layer integral tear-away bridge membrane"
    )
    assert review["checks"]["continuous_design_language"][
        "crown_membrane_count"
    ] == 4
    assert (
        review["checks"]["continuous_design_language"][
            "crown_membrane_thickness_mm"
        ]
        <= 0.2
    )
    assert (
        review["checks"]["continuous_design_language"][
            "crown_membrane_estimated_petg_g"
        ]
        <= 0.05
    )
    assert (
        review["checks"]["continuous_design_language"][
            "roof_curve_amplitude_mm"
        ]
        >= 0.3
    )
    assert (
        review["checks"]["continuous_design_language"]["top_edge_radius_mm"]
        >= 1.5
    )
    assert (
        review["checks"]["continuous_design_language"]["portal_cut_margin_mm"]
        <= 1.0
    )
    assert (
        review["checks"]["continuous_design_language"][
            "minimum_self_supporting_flank_slope_deg"
        ]
        >= 31.0
    )
    assert (
        review["checks"]["continuous_design_language"][
            "slicer_support_threshold_deg"
        ]
        == 30.0
    )
    assert (
        review["checks"]["continuous_design_language"][
            "roof_slope_margin_deg"
        ]
        >= 1.0
    )
    assert review["checks"]["continuous_design_language"][
        "crown_bridge_mm"
    ] == 14.5
    assert (
        review["checks"]["continuous_design_language"][
            "profile_fillet_radius_mm"
        ]
        >= 2.0
    )
    cradle_style = review["checks"]["continuous_design_language"]["cradle"]
    assert cradle_style["curved_landing_surfaces"]
    assert cradle_style["lead_in_radius_mm"] >= 0.6
    assert cradle_style["support_shelf_edge_radius_mm"] >= 0.6
    assert cradle_style["chassis_overhang_per_side_mm"] <= 1.0
    cradle_interface = review["checks"][
        "physical_screwless_stack_interface"
    ]["cradle_interface"]
    assert cradle_interface["socket_type"] == "through"
    assert cradle_interface["through_sockets"]
    assert cradle_interface["pin_tip_recess_below_support_plane_mm"] >= 0.75
    assert cradle_interface["minimum_outer_ligament_mm"] >= 4.5
    assert cradle_interface["minimum_device_cover_mm"] >= 1.0
    assert review["checks"]["standard_fan_mount_and_isolation"]["passed"]
    assert review["checks"]["standard_fan_mount_and_isolation"][
        "isolator_geometry"
    ]["pocket_count"] == 4
    pin_anchor = review["checks"]["locating_pin_anchor_geometry"]
    assert pin_anchor["passed"]
    assert pin_anchor["anchor_fan_clearance_mm"] >= 0.25
    assert pin_anchor["pin_positions_mm"] == [
        [-59.5, -59.5],
        [-59.5, 59.5],
        [59.5, -59.5],
        [59.5, 59.5],
    ]
    assert pin_anchor["anchor_maximum_flat_span_mm"] <= 3.25
    assert pin_anchor["anchor_mm"][1] >= 4.25
    assert pin_anchor["anchor_gusset_drop_mm"] >= 3.6
    assert pin_anchor["anchor_gusset_angle_deg"] == 45.0
    assert pin_anchor["fan_chassis_overlap_mm3"] <= 0.01
    assert review["checks"]["standard_fan_mount_and_isolation"][
        "isolator_geometry"
    ]["modeled_as_geometry"]
    assert review["checks"]["standard_fan_mount_and_isolation"][
        "fan_retention"
    ]["fastener_free"]
    fan_retention = review["checks"][
        "releasable_fan_cantilever_retention"
    ]
    assert fan_retention["passed"]
    assert fan_retention["clip_count"] == 4
    assert fan_retention["modeled_as_geometry"]
    assert (
        fan_retention["wall_relief_mm"]
        >= fan_retention["required_deflection_mm"]
    )
    assert (
        fan_retention["nominal_surface_strain"]
        <= fan_retention["recommended_petg_strain_limit"]
    )
    assert fan_retention["hook_overlap_mm"] >= 0.2
    assert fan_retention["hook_contact_flat_span_mm"] == 0.4
    assert fan_retention["hook_undercut_ramp_run_mm"] >= 1.29
    assert fan_retention["hook_undercut_angle_deg"] >= 45.0
    assert fan_retention["fan_top_clearance_mm"] >= 0.25
    assert fan_retention["lead_in_angle_deg"] == 45.0
    assert fan_retention["fan_chassis_overlap_mm3"] <= 0.01
    fan_clip_support = review["checks"].get(
        "fan_clip_undercut_support_optimization"
    )
    if fan_clip_support is not None:
        assert fan_clip_support["passed"]
        assert (
            fan_clip_support["current"][
                "upper_retention_interface_move_count"
            ]
            <= 100
        )
    cradle_socket_support = review["checks"].get(
        "cradle_through_socket_support_optimization"
    )
    if cradle_socket_support is not None:
        assert cradle_socket_support["passed"]
        assert (
            cradle_socket_support["current"][
                "cradle_support_filament_weight_g"
            ]
            == 0.0
        )
        assert (
            cradle_socket_support["current"][
                "cradle_support_extrusion_move_count"
            ]
            == 0
        )
    usb_service_arch_support = review["checks"].get(
        "usb_service_arch_support_optimization"
    )
    if usb_service_arch_support is not None:
        assert usb_service_arch_support["passed"]
        assert (
            usb_service_arch_support["current"][
                "usb_hotspot_cell_count"
            ]
            <= 2
        )
        assert (
            usb_service_arch_support["current"][
                "usb_hotspot_extrusion_move_count"
            ]
            <= 250
        )
        assert (
            usb_service_arch_support["current"][
                "usb_hotspot_interface_move_count"
            ]
            <= 25
        )
    isolation = review["checks"]["controlled_fan_vibration_isolation"]
    assert isolation["passed"]
    assert isolation["reference_part_count"] == 4
    assert 0.10 <= isolation["compression_ratio"] <= 0.20
    assert isolation["installed_protrusion_above_guard_mm"] >= 0.4
    assert isolation["rigid_guard_to_fan_gap_mm"] >= 0.4
    assert isolation["fan_guard_overlap_mm3"] <= 0.01
    assert isolation["fan_chassis_overlap_mm3"] <= 0.01
    assert isolation["isolator_fan_overlap_mm3"] <= 0.01
    assert isolation["isolator_guard_overlap_mm3"] <= 0.01
    assert isolation["isolator_chassis_overlap_mm3"] <= 0.01
    assert isolation["isolator_top_alignment_error_mm"] <= 0.01
    assert isolation["isolator_pocket_base_alignment_error_mm"] <= 0.01
    assert isolation["total_elastomer_contact_area_mm2"] >= 200.0
    guard_retention = review["checks"][
        "serviceable_fan_guard_retention"
    ]
    assert guard_retention["passed"]
    assert guard_retention["support_count"] == 4
    assert guard_retention["guide_face_count"] == 4
    assert guard_retention["guide_clearance_mm"] == 0.25
    assert guard_retention["guard_chassis_installed_overlap_mm3"] <= 0.01
    assert guard_retention["downward_stop_overlap_mm3"] >= 1.0
    assert min(guard_retention["lateral_stop_overlaps_mm3"]) >= 0.001
    assert guard_retention["vertical_service_path_max_overlap_mm3"] <= 0.01
    assert guard_retention["fan_hook_stop_overlap_mm3"] >= 0.01
    cable_relief = review["checks"]["releasable_cable_strain_relief"]
    assert cable_relief["passed"]
    assert cable_relief["arm_count"] == 2
    assert cable_relief["host_part"] == "controller_cover"
    assert cable_relief["root_embed_depth_mm"] >= 0.5
    assert cable_relief["horizontal_anchor_count"] == 0
    assert cable_relief["maximum_unsupported_root_span_mm"] == 0.0
    assert cable_relief["hook_flat_stop_span_mm"] == 0.0
    assert cable_relief["hook_self_supporting_ramp_angle_deg"] == 45.0
    assert cable_relief["arm_length_mm"] <= 17.1
    assert cable_relief["target_bundle_diameter_mm"] == 4.0
    assert cable_relief["relaxed_throat_mm"] < 4.0
    assert (
        cable_relief["nominal_surface_strain"]
        <= cable_relief["recommended_petg_strain_limit"]
    )
    assert cable_relief["installed_bundle_chassis_overlap_mm3"] <= 0.01
    assert cable_relief["upward_hook_stop_overlap_mm3"] >= 0.01
    assert min(cable_relief["lateral_arm_stop_overlaps_mm3"]) >= 0.001
    assert cable_relief["ds18b20_reference_overlap_mm3"] <= 0.01
    assert max(
        cable_relief["cable_internal_hardware_overlaps_mm3"].values()
    ) <= 0.01
    assert review["checks"]["front_rear_port_access"]["passed"]
    assert review["checks"]["front_rear_port_access"][
        "front_obstruction_volume_mm3"
    ] <= 0.01
    assert review["checks"]["front_rear_port_access"][
        "rear_obstruction_volume_mm3"
    ] <= 0.01
    interface_access = review["checks"][
        "individual_mac_interface_service_corridors"
    ]
    assert interface_access["passed"]
    assert interface_access["corridor_count"] == 9
    assert interface_access["front_corridor_count"] == 3
    assert interface_access["rear_corridor_count"] == 6
    assert interface_access["maximum_obstruction_volume_mm3"] <= 0.01
    assert all(
        corridor["total_obstruction_mm3"] <= 0.01
        for corridor in interface_access["corridors"]
    )
    assert (
        interface_access["coordinate_accuracy"]
        == "type verified; position approximate"
    )
    rear_service_relief = interface_access["rear_service_relief"]
    assert rear_service_relief["width_mm"] >= 42.0
    assert rear_service_relief["inward_overlap_mm"] >= 0.25
    assert rear_service_relief["removed_volume_mm3"] > 0.0
    assert rear_service_relief["bottom_ring_height_mm"] >= 4.0
    assert not rear_service_relief["breaks_bottom_outer_edge"]
    assert not rear_service_relief["support_required"]
    io_gauges = review["checks"]["physical_mac_io_alignment_gauges"]
    assert io_gauges["passed"]
    assert io_gauges["gauges"]["front"]["passed"]
    assert io_gauges["gauges"]["rear"]["passed"]
    assert io_gauges["regeneration_parameters"] == [
        "front_interface_delta_x_mm",
        "front_interface_delta_z_mm",
        "rear_interface_delta_x_mm",
        "rear_interface_delta_z_mm",
    ]
    assert review["checks"]["controller_cover_real_snap_fit"]["passed"]
    assert review["checks"]["power_button_access"]["passed"]
    component_names = {
        component.name
        for component in result.proposal.brief.components
    }
    assert "12V DC-DC module" in component_names
    assert "5V DC-DC module" in component_names
    assert "MOSFET PWM driver" in component_names
    assert review["checks"]["power_button_access"][
        "shaft_obstruction_volume_mm3"
    ] <= 0.01
    assert review["checks"]["power_button_access"][
        "head_obstruction_volume_mm3"
    ] <= 0.01
    assert review["checks"]["power_button_access"][
        "plunger"
    ]["bottom_recess_mm"] == 1.0
    installed_button_path = review["checks"]["power_button_access"][
        "installed_path_validation"
    ]
    assert installed_button_path["head_alignment_error_mm"] <= 0.01
    assert (
        installed_button_path["shaft_fan_mount_alignment_error_mm"] <= 0.01
    )
    assert installed_button_path["shaft_radial_clearance_mm"] >= 0.25
    assert installed_button_path["fan_overlap_mm3"] <= 0.01
    assert installed_button_path["guard_overlap_mm3"] <= 0.01
    assert installed_button_path["mac_overlap_mm3"] <= 0.01
    assert abs(installed_button_path["resting_top_gap_mm"] - 0.25) <= 0.01
    assert installed_button_path["available_upward_travel_mm"] >= 2.0
    assert installed_button_path["buckling_safety_factor"] >= 5.0
    tolerant_contact = review["checks"][
        "uncertainty_tolerant_power_button_contact"
    ]
    assert tolerant_contact["passed"]
    assert tolerant_contact["modeled_from_actual_end_face"]
    assert tolerant_contact["angular_sample_count"] == 16
    assert tolerant_contact["coordinate_uncertainty_mm"] >= 2.0
    assert tolerant_contact["minimum_full_button_coverage_ratio"] >= 0.93
    assert tolerant_contact["minimum_actuation_core_coverage_ratio"] >= 0.999
    assert tolerant_contact["head_bore_radial_clearance_mm"] >= 0.25
    assert tolerant_contact["print_flat_included_in_measurement"]
    rear_operation = review["checks"][
        "rear_access_power_button_operation"
    ]
    assert rear_operation["passed"]
    assert rear_operation["modeled_as_geometry"]
    assert rear_operation["integrated_single_piece"]
    assert rear_operation["additional_exterior_openings"] == 0
    assert rear_operation["lateral_footprint_extension_mm"] == 0.0
    assert rear_operation["minimum_finger_corridor_width_mm"] >= 15.0
    assert rear_operation["finger_corridor_obstruction_volume_mm3"] <= 0.01
    assert rear_operation["resting_chassis_overlap_mm3"] <= 0.01
    assert rear_operation["actuated_chassis_overlap_mm3"] <= 0.01
    assert rear_operation["actuated_guard_overlap_mm3"] <= 0.01
    assert rear_operation["actuated_fan_overlap_mm3"] <= 0.01
    assert (
        rear_operation["required_actuation_travel_mm"]
        <= rear_operation["available_upward_travel_mm"]
    )
    assert rear_operation["arm_profile"] == "constant-width rounded capsule"
    assert rear_operation["arm_thickness_mm"] >= 4.0
    assert rear_operation["arm_end_radius_mm"] >= 2.5
    assert rear_operation["shares_shaft_build_plane"]
    assert rear_operation["root_print_flat_z_mm"] == -1.6
    assert rear_operation["conservative_bending_stress_mpa"] <= 6.0
    assert rear_operation["conservative_tip_deflection_mm"] <= 0.6
    assert rear_operation["conservative_yield_safety_factor"] >= 5.0
    assert rear_operation["resting_minimum_z_mm"] >= 1.0
    assert not review["checks"]["power_button_access"][
        "installed_edge_notch"
    ]
    assert review["checks"]["cradle_integrated_outer_contour"]["passed"]
    assert review["checks"]["cradle_integrated_outer_contour"][
        "outer_edge_notch_count"
    ] == 0
    assert review["checks"]["cradle_integrated_outer_contour"][
        "through_locating_sockets"
    ]
    assert not review["checks"]["cradle_integrated_outer_contour"][
        "locating_sockets_break_outer_edge"
    ]
    transition = review["checks"]["reference_informed_cradle_transition"]
    assert transition["passed"]
    assert transition["modeled_as_geometry"]
    assert not transition["reference_mesh_copied"]
    assert transition["transition_radius_mm"] >= 0.3
    assert transition["maximum_footprint_mismatch_mm"] <= 0.1
    assert transition["continuous_outer_transition"]
    assert transition["planar_mating_face_retained"]
    assert transition["outer_band_style"] == (
        "five-section convex rounded-square annular loft"
    )
    assert len(transition["outer_band_profile"]) == 5
    assert not transition["visible_constant_thickness_plate_edge"]
    assert "underside tangent line" in transition["seam_location"]
    assert transition["maximum_band_overhang_per_side_mm"] <= 0.4 + 1e-6
    assert transition["lower_slope_from_horizontal_deg"] >= 60.0
    assert transition["upper_shelf_footprint_mm"] == [133.2, 133.2]
    crown = transition["chassis_crown"]
    assert crown["modeled_as_geometry"]
    assert crown["body_footprint_mm"] == [132.0, 132.0]
    assert crown["mating_footprint_mm"] == [133.2, 133.2]
    assert crown["height_mm"] == 3.0
    assert crown["slope_from_horizontal_deg"] >= 60.0
    assert crown["wall_optimized_loft"]
    assert crown["bottom_side_wall_mm"] == 2.5
    assert crown["minimum_top_side_wall_mm"] == 2.0
    assert crown["inner_cavity_bottom_mm"] == [127.0, 127.0]
    assert crown["inner_cavity_top_mm"] == [129.2, 129.2]
    assert crown["inner_top_corner_radius_mm"] == 8.0
    assert crown["maximum_installed_footprint_mm"] == [134.0, 134.0]
    assert not crown["support_required"]
    bellmouth = review["checks"]["continuous_airflow_bellmouth"]
    assert bellmouth["passed"]
    assert bellmouth["modeled_as_geometry"]
    assert not bellmouth["sharp_lower_airflow_edge"]
    assert bellmouth["lower_inlet_radius_mm"] >= 0.8
    assert bellmouth["lower_inlet_diameter_mm"] >= 116.8
    assert bellmouth["minimum_throat_diameter_mm"] >= 115.0
    assert bellmouth["straight_throat_height_mm"] >= 2.0
    assert bellmouth["minimum_mac_foot_radial_clearance_mm"] >= 7.0
    assert review["checks"]["bottom_airflow_keepout"][
        "opening_shape"
    ] == "circular"
    assert review["checks"]["bottom_airflow_keepout"][
        "opening_diameter_mm"
    ] == 115.0
    assert review["checks"]["bottom_airflow_keepout"][
        "opening_area_mm2"
    ] >= 10_200.0
    assert review["checks"]["cradle_integrated_outer_contour"][
        "continuous_side_rail_count"
    ] == 0
    assert review["checks"]["cradle_integrated_outer_contour"][
        "continuous_annular_cradle"
    ]
    assert review["checks"]["underbody_air_gap"]["passed"]
    contact_interface = review["checks"][
        "modeled_silicone_contact_interface"
    ]
    assert contact_interface["passed"]
    assert contact_interface["count"] == 4
    assert contact_interface["pad_diameter_mm"] == 8.0
    assert contact_interface["recess_depth_mm"] == 0.3
    assert contact_interface["recess_diameter_mm"] == 8.5
    assert contact_interface["installed_pad_thickness_mm"] == 0.5
    assert contact_interface["installed_protrusion_mm"] == 0.2
    assert (
        contact_interface["actual_removed_volume_mm3"]
        >= 0.98 * contact_interface["expected_removed_volume_mm3"]
    )
    assert contact_interface["boolean_residual_volume_mm3"] <= 0.01
    assert contact_interface["minimum_airflow_edge_clearance_mm"] >= 0.5
    assert contact_interface["minimum_power_button_clearance_mm"] >= 1.5
    primary_contact = review["checks"]["proud_silicone_primary_contact"]
    assert primary_contact["passed"]
    assert primary_contact["pad_reference_count"] == 4
    assert primary_contact["nominal_pad_mac_overlap_mm3"] <= 0.01
    assert primary_contact["preload_pad_mac_overlap_mm3"] >= 8.0
    assert primary_contact["nominal_mac_petg_overlap_mm3"] <= 0.01
    assert primary_contact["free_travel_mac_petg_overlap_mm3"] <= 0.01
    assert primary_contact["hard_stop_mac_petg_overlap_mm3"] >= 0.01
    assert primary_contact["pad_mac_foot_overlap_mm3"] <= 0.01
    assert review["checks"]["physical_screwless_stack_interface"]["passed"]
    assert review["checks"]["assembly_interference"]["passed"]
    assert review["checks"]["integrated_stack_compaction"]["passed"]
    assert review["checks"]["structural_stability"]["passed"]
    carrier_corbels = component_retention[
        "self_supporting_base_corbels"
    ]
    assert carrier_corbels["modeled_as_geometry"]
    assert carrier_corbels["rail_corbel_count"] == 2
    assert carrier_corbels["snap_root_corbel_count"] == 2
    assert carrier_corbels["total_count"] == 4
    assert carrier_corbels["base_plate_length_mm"] == 52.5
    assert carrier_corbels["carrier_outer_span_mm"] == 54.9
    assert carrier_corbels["service_opening_length_mm"] == 55.4
    assert (
        carrier_corbels["bottom_contact_footprint_expansion_mm"]
        == 0.0
    )
    assert carrier_corbels["rail_corbel_slope_deg"] >= 69.0
    assert carrier_corbels["snap_root_corbel_slope_deg"] >= 69.0
    snap_fit = review["checks"]["controller_cover_real_snap_fit"]
    assert snap_fit["passed"]
    assert snap_fit["chassis_slots"]["slot_roof_chamfer_length_mm"] == 2.0
    assert snap_fit["chassis_slots"]["maximum_flat_roof_span_mm"] <= 3.0
    assert "45 degree" in snap_fit["chassis_slots"]["slot_roof_strategy"]
    controller_ventilation = review["checks"]["controller_cover_ventilation"]
    assert controller_ventilation["passed"]
    assert controller_ventilation["top_edge_radius_mm"] >= 1.5
    assert controller_ventilation["internal_elliptical_port_count"] == 0
    assert controller_ventilation["internal_self_supporting_arch_count"] == 2
    assert controller_ventilation["internal_port_dimensions_mm"] == [52.0, 23.0]
    assert controller_ventilation["internal_open_area_mm2"] >= 1500.0
    assert controller_ventilation["visible_wall_open_ratio"] >= 0.45
    assert controller_ventilation["minimum_continuous_web_mm"] >= 3.0
    assert controller_ventilation["maximum_closing_bridge_mm"] <= 12.0
    assert controller_ventilation["external_slot_count"] == 0
    assert controller_ventilation["external_elliptical_port_count"] == 0
    assert controller_ventilation["external_self_supporting_arch_count"] == 3
    assert controller_ventilation["external_port_dimensions_mm"] == [
        [24.0, 12.75],
        [24.0, 12.75],
        [54.0, 22.0],
    ]
    snap_arch_geometry = controller_ventilation[
        "external_snap_arch_geometry"
    ]
    assert snap_arch_geometry["count"] == 2
    assert snap_arch_geometry["effective_crown_bridge_mm"] == 5.7
    assert snap_arch_geometry["minimum_roof_slope_deg"] >= 45.0
    assert snap_arch_geometry["continuous_central_load_rib_mm"] >= 3.0
    assert controller_ventilation["external_open_area_mm2"] >= 1200.0
    assert (
        controller_ventilation["external_visible_wall_open_ratio"] >= 0.35
    )
    assert (
        controller_ventilation["external_minimum_continuous_web_mm"] >= 3.0
    )
    assert (
        controller_ventilation["external_maximum_closing_bridge_mm"] <= 12.0
    )
    assert controller_ventilation["internal_minimum_roof_slope_deg"] >= 40.0
    assert (
        controller_ventilation["external_arch_minimum_roof_slope_deg"] >= 38.0
    )
    assert controller_ventilation["boolean_validation"]["cutter_count"] == 4
    assert (
        controller_ventilation["boolean_validation"][
            "residual_intersection_volume_mm3"
        ]
        <= 0.01
    )
    assert (
        controller_ventilation["boolean_validation"][
            "functional_feature_volume_in_openings_mm3"
        ]
        <= 40.0
    )
    assert (
        review["checks"]["integrated_stack_compaction"][
            "lateral_extension_from_cradle_mm"
        ]
        <= 0.01
    )
    assert all(
        abs(value - 134.0) <= 0.02
        for value in review["checks"]["integrated_stack_compaction"][
            "assembly_planar_envelope_mm"
        ]
    )
