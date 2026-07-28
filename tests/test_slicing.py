from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ai_cad_designer.slicing import (
    OrcaProfileResolver,
    OrcaSlicerError,
    SliceResult,
    _parse_orca_duration,
    _support_removal_access_stats,
    _support_impact,
    _support_threshold_sweep_report,
    _support_toolpath_stats,
    parse_sliced_3mf,
)


def test_parse_orca_duration() -> None:
    assert _parse_orca_duration("2h 10m 2s") == 7802
    assert _parse_orca_duration("14m 7s") == 847


def test_support_removal_access_requires_bottom_connected_interfaces() -> None:
    def cell(
        index: tuple[int, int, int],
        bounds: list[float],
        *,
        interface_moves: int,
    ) -> dict[str, object]:
        return {
            "cell_index": list(index),
            "actual_local_bbox_xyz_mm": bounds,
            "extrusion_move_count": max(1, interface_moves),
            "feature_move_counts": {
                "support_interface": interface_moves,
            },
        }

    accessible = _support_removal_access_stats(
        {
            "xyz_cells": [
                cell((12, 12, 0), [125, 125, 0.2, 130, 130, 0.4], interface_moves=0),
                cell((12, 12, 1), [125, 125, 4.8, 130, 130, 5.0], interface_moves=100),
                cell((19, 12, 5), [190, 125, 25, 195, 130, 25.2], interface_moves=2),
            ]
        },
        bed_center_xy_mm=(128.0, 128.0),
    )
    assert accessible["passed"]
    assert accessible["build_plate_connected_interface_ratio"] == 0.9804
    assert accessible["detached_interface_move_ratio"] == 0.0196
    assert accessible["all_detached_interfaces_side_pickable"]
    assert accessible["permanent_airway_support_move_count"] == 0

    exterior_micro_island = _support_removal_access_stats(
        {
            "xyz_cells": [
                cell(
                    (12, 12, 0),
                    [125, 125, 0.2, 130, 130, 0.4],
                    interface_moves=0,
                ),
                cell(
                    (12, 12, 1),
                    [125, 125, 4.8, 130, 130, 5.0],
                    interface_moves=100,
                ),
                cell(
                    (19, 12, 5),
                    [191, 125, 25, 195, 130, 25.2],
                    interface_moves=7,
                ),
            ]
        },
        bed_center_xy_mm=(128.0, 128.0),
    )
    assert exterior_micro_island["passed"]
    assert exterior_micro_island["detached_interface_move_ratio"] > 0.02
    assert exterior_micro_island[
        "detached_interface_micro_exception"
    ]
    assert (
        exterior_micro_island["detached_interface_move_count"]
        <= exterior_micro_island["maximum_side_pick_interface_moves"]
    )

    trapped = _support_removal_access_stats(
        {
            "xyz_cells": [
                cell((12, 12, 6), [125, 125, 30, 130, 130, 30.2], interface_moves=100),
            ]
        },
        bed_center_xy_mm=(128.0, 128.0),
    )
    assert not trapped["passed"]
    assert not trapped["all_detached_interfaces_side_pickable"]
    assert trapped["central_airway_non_bed_connected_move_count"] == 100
    assert trapped["permanent_airway_support_move_count"] == 100


def test_support_removal_access_defaults_to_object_local_origin() -> None:
    stats = _support_toolpath_stats(
        "\n".join(
            (
                "; FEATURE: Support",
                "G1 X-65 Y0 Z0.2 E0.2",
                "; FEATURE: Support interface",
                "G1 X-65 Y0 Z50 E0.2",
            )
        ),
        {},
    )

    access = _support_removal_access_stats(stats)

    assert access["passed"]
    assert access["central_airway_non_bed_connected_move_count"] == 0


def test_support_removal_allows_five_non_contact_pre_airway_moves() -> None:
    def cell(
        index: tuple[int, int, int],
        bounds: list[float],
        *,
        interface_moves: int = 0,
    ) -> dict[str, object]:
        return {
            "cell_index": list(index),
            "actual_local_bbox_xyz_mm": bounds,
            "extrusion_move_count": 1,
            "feature_move_counts": {
                "support_interface": interface_moves,
            },
        }

    bed_component = [
        cell((20, 0, 0), [60, 0, 0.2, 61, 1, 0.4]),
        cell(
            (20, 0, 1),
            [60, 0, 4.8, 61, 1, 5.0],
            interface_moves=100,
        ),
    ]
    five_move_micro_path = [
        cell(
            (0, 0, index),
            [0, 0, 10 + index, 1, 1, 10.2 + index],
        )
        for index in range(5)
    ]
    accepted = _support_removal_access_stats(
        {"xyz_cells": bed_component + five_move_micro_path}
    )

    assert accepted["passed"]
    assert accepted[
        "central_airway_non_contact_micro_path_exception"
    ]
    assert accepted["maximum_central_non_contact_micro_moves"] == 5

    six_move_micro_path = five_move_micro_path + [
        cell((0, 0, 5), [0, 0, 15, 1, 1, 15.2])
    ]
    rejected = _support_removal_access_stats(
        {"xyz_cells": bed_component + six_move_micro_path}
    )

    assert not rejected["passed"]
    assert not rejected[
        "central_airway_non_contact_micro_path_exception"
    ]


def _manifest(root: Path, entries: list[dict[str, str]]) -> None:
    (root / "TEST").mkdir(parents=True)
    (root / "TEST.json").write_text(
        json.dumps(
            {
                "machine_list": [],
                "process_list": [],
                "filament_list": entries,
            }
        ),
        encoding="utf-8",
    )


def test_profile_resolver_flattens_parent_chain(tmp_path: Path) -> None:
    _manifest(
        tmp_path,
        [
            {"name": "base", "sub_path": "base.json"},
            {"name": "PETG", "sub_path": "petg.json"},
        ],
    )
    (tmp_path / "TEST" / "base.json").write_text(
        json.dumps({"name": "base", "filament_type": ["PETG"], "speed": ["40"]}),
        encoding="utf-8",
    )
    (tmp_path / "TEST" / "petg.json").write_text(
        json.dumps({"name": "PETG", "inherits": "base", "speed": ["60"]}),
        encoding="utf-8",
    )

    profile = OrcaProfileResolver(tmp_path, "TEST").resolve("PETG")

    assert profile["filament_type"] == ["PETG"]
    assert profile["speed"] == ["60"]
    assert profile["inherits"] == ""


def test_profile_resolver_rejects_cycles(tmp_path: Path) -> None:
    _manifest(
        tmp_path,
        [
            {"name": "a", "sub_path": "a.json"},
            {"name": "b", "sub_path": "b.json"},
        ],
    )
    (tmp_path / "TEST" / "a.json").write_text(
        json.dumps({"name": "a", "inherits": "b"}),
        encoding="utf-8",
    )
    (tmp_path / "TEST" / "b.json").write_text(
        json.dumps({"name": "b", "inherits": "a"}),
        encoding="utf-8",
    )

    with pytest.raises(OrcaSlicerError, match="cyclic"):
        OrcaProfileResolver(tmp_path, "TEST").resolve("a")


def test_parse_sliced_3mf_extracts_measured_petg_data(tmp_path: Path) -> None:
    artifact = tmp_path / "part.gcode.3mf"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(
            "Metadata/plate_1.gcode",
            "; filament_type = PETG\n"
                "; total layer number: 42\n"
                "; FEATURE: Bridge\n"
                "G1 X1 Y1 E.1\n",
        )
        archive.writestr(
            "Metadata/slice_info.config",
            '<config><metadata key="prediction" value="1234"/>'
            '<metadata key="support_used" value="false"/>'
            '<filament type="PETG" used_m="12.5" used_g="37.2"/></config>',
        )
        archive.writestr(
            "Metadata/plate_1.json",
            json.dumps({"layer_height": 0.2}),
        )

    result = parse_sliced_3mf(artifact, part="part", rotation=(180, 0, 0))

    assert result.printable
    assert result.material == "PETG"
    assert result.layers == 42
    assert result.estimated_seconds == 1234
    assert result.filament_weight_g == 37.2
    assert result.bridge_regions == 1
    assert result.overhang_regions == 0
    assert result.max_bridge_span_mm == 1.414
    assert result.rotation_deg == [180.0, 0.0, 0.0]


def test_support_impact_measures_material_and_time_delta() -> None:
    def result(
        *,
        weight: float,
        seconds: int,
        support: bool,
    ) -> SliceResult:
        return SliceResult(
            part="shell",
            artifact="/tmp/shell.3mf",
            printable=not support,
            material="PETG",
            layer_height_mm=0.2,
            layers=100,
            estimated_seconds=seconds,
            filament_length_m=10.0,
            filament_weight_g=weight,
            support_used=support,
            bridge_regions=0,
            overhang_regions=0,
            max_bridge_span_mm=0.0,
            rotation_deg=[0.0, 0.0, 0.0],
        )

    impact = _support_impact(
        [result(weight=80.0, seconds=10000, support=False)],
        [result(weight=82.5, seconds=10800, support=True)],
    )

    assert impact["passed"]
    assert impact["auto_support_generated"]
    assert not impact["support_required"]
    assert impact["additional_filament_weight_g"] == 2.5
    assert impact["additional_time_seconds"] == 800
    assert impact["additional_filament_ratio"] == 0.0312
    assert impact["additional_time_ratio"] == 0.08
    assert impact["acceptance_limits"]["additional_filament_ratio"] == 0.05
    assert impact["acceptance_limits"]["additional_time_ratio"] == 0.10
    assert impact["parts"]["shell"]["additional_filament_ratio"] == 0.0312
    assert impact["parts"]["shell"]["additional_time_ratio"] == 0.08


def test_support_impact_none_strategy_blocks_auto_support_even_when_printable() -> None:
    def result(
        *,
        weight: float,
        seconds: int,
        printable: bool,
        support: bool,
    ) -> SliceResult:
        return SliceResult(
            part="shell",
            artifact="/tmp/shell.3mf",
            printable=printable,
            material="PETG",
            layer_height_mm=0.2,
            layers=100,
            estimated_seconds=seconds,
            filament_length_m=10.0,
            filament_weight_g=weight,
            support_used=support,
            bridge_regions=0,
            overhang_regions=0,
            max_bridge_span_mm=0.0,
            rotation_deg=[0.0, 0.0, 0.0],
        )

    impact = _support_impact(
        [result(weight=80.0, seconds=10000, printable=False, support=False)],
        [result(weight=82.5, seconds=10800, printable=True, support=True)],
        support_strategy="none",
    )

    assert not impact["passed"]
    assert impact["support_required"]


def test_support_impact_required_strategy_accepts_when_support_enables_print() -> None:
    def result(
        *,
        weight: float,
        seconds: int,
        printable: bool,
        support: bool,
    ) -> SliceResult:
        return SliceResult(
            part="shell",
            artifact="/tmp/shell.3mf",
            printable=printable,
            material="PETG",
            layer_height_mm=0.2,
            layers=100,
            estimated_seconds=seconds,
            filament_length_m=10.0,
            filament_weight_g=weight,
            support_used=support,
            bridge_regions=0,
            overhang_regions=0,
            max_bridge_span_mm=0.0,
            rotation_deg=[0.0, 0.0, 0.0],
        )

    impact = _support_impact(
        [result(weight=80.0, seconds=10000, printable=False, support=False)],
        [result(weight=82.5, seconds=10800, printable=True, support=True)],
        support_strategy="required",
    )

    assert impact["passed"]
    assert impact["support_required"]
def test_support_threshold_sweep_reports_material_time_and_contact_cost() -> None:
    baseline = SliceResult(
        part="fan_chassis",
        artifact="/tmp/fan_chassis.gcode.3mf",
        printable=True,
        material="PETG",
        layer_height_mm=0.2,
        layers=300,
        estimated_seconds=7000,
        filament_length_m=15.0,
        filament_weight_g=46.0,
        support_used=False,
        bridge_regions=12,
        overhang_regions=60,
        max_bridge_span_mm=17.0,
        rotation_deg=[0.0, 0.0, 0.0],
    )

    def supported(
        threshold: float,
        weight: float,
        seconds: int,
        moves: int,
        interfaces: int,
    ) -> tuple[float, SliceResult]:
        return (
            threshold,
            SliceResult(
                part="fan_chassis",
                artifact=f"/tmp/fan_chassis-{threshold:g}.gcode.3mf",
                printable=False,
                material="PETG",
                layer_height_mm=0.2,
                layers=300,
                estimated_seconds=seconds,
                filament_length_m=18.0,
                filament_weight_g=weight,
                support_used=True,
                bridge_regions=12,
                overhang_regions=60,
                max_bridge_span_mm=17.0,
                rotation_deg=[0.0, 0.0, 0.0],
                support_toolpath={
                    "extrusion_move_count": moves,
                    "feature_move_counts": {
                        "support": moves - interfaces,
                        "support_interface": interfaces,
                    },
                    "footprint_mm": [150.0, 150.0],
                    "z_range_mm": [0.2, 56.0],
                },
            ),
        )

    report = _support_threshold_sweep_report(
        baseline,
        [
            supported(25.0, 52.0, 8200, 20000, 500),
            supported(30.0, 54.0, 8600, 30000, 900),
            supported(35.0, 58.0, 9300, 45000, 1400),
            supported(45.0, 64.0, 10500, 70000, 2200),
        ],
    )

    assert report["passed"]
    assert report["part"] == "fan_chassis"
    assert report["first_tested_threshold_with_support_deg"] == 25.0
    assert report["reference_threshold_deg"] == 30.0
    assert [row["threshold_angle_deg"] for row in report["trials"]] == [
        25.0,
        30.0,
        35.0,
        45.0,
    ]
    assert report["trials"][1]["additional_filament_weight_g"] == 8.0
    assert report["trials"][1]["additional_time_seconds"] == 1600
    assert report["trials"][1]["support_interface_move_count"] == 900


def test_support_toolpath_stats_measure_generated_envelope() -> None:
    gcode = """
G1 X100 Y100 Z0.2
; FEATURE: Support
G1 X95 Y96 E0.2
G2 X110 Y112 I2 J3 E0.3
; FEATURE: Support interface
G1 Z12.4
G1 X108 Y106 E0.1
; FEATURE: Outer wall
G1 X200 Y200 E0.4
"""
    stats = _support_toolpath_stats(
        gcode,
        {
            "bbox_objects": [
                {"bbox": [98.0, 98.0, 108.0, 108.0]},
            ]
        },
    )

    assert stats["extrusion_move_count"] == 3
    assert stats["feature_move_counts"] == {
        "support": 2,
        "support_interface": 1,
    }
    assert stats["z_range_mm"] == [0.2, 12.4]
    assert stats["height_mm"] == 12.2
    assert stats["footprint_mm"] == [15.0, 16.0]
    assert stats["local_bbox_xy_mm"] == [-8.0, -7.0, 7.0, 9.0]
    assert stats["footprint_extension_l_r_f_b_mm"] == [
        3.0,
        2.0,
        2.0,
        4.0,
    ]
    assert stats["z_band_size_mm"] == 5.0
    assert len(stats["z_bands"]) == 2
    assert sum(
        band["extrusion_move_count"] for band in stats["z_bands"]
    ) == stats["extrusion_move_count"]
    assert stats["z_bands"][0]["actual_z_range_mm"] == [0.2, 0.2]
    assert stats["z_bands"][0]["move_ratio"] == 0.6667
    assert stats["z_bands"][0]["feature_move_counts"] == {"support": 2}
    assert stats["z_bands"][1]["actual_z_range_mm"] == [12.4, 12.4]
    assert stats["z_bands"][1]["feature_move_counts"] == {
        "support_interface": 1
    }
    assert stats["xy_tile_size_mm"] == 20.0
    assert sum(
        tile["extrusion_move_count"] for tile in stats["xy_tiles"]
    ) == stats["extrusion_move_count"]
    assert stats["xy_tiles"][0]["tile_index"] == [0, 0]
    assert stats["xy_tiles"][0]["extrusion_move_count"] == 2
    assert stats["xyz_cell_size_mm"] == [10.0, 10.0, 5.0]
    assert sum(
        cell["extrusion_move_count"] for cell in stats["xyz_cells"]
    ) == stats["extrusion_move_count"]
    assert stats["xyz_cells"][0]["feature_move_counts"] == {
        "support_interface": 1
    }
    assert stats["xyz_cells"][0]["nominal_local_bbox_xyz_mm"] == [
        0.0,
        0.0,
        10.0,
        10.0,
        10.0,
        15.0,
    ]
