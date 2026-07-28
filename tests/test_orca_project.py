from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import trimesh

from ai_cad_designer.orca_project import (
    OrcaProjectError,
    create_support_enforcer_project,
    inspect_support_enforcer_project,
)


def _write_template(path: Path) -> Path:
    object_path = "3D/Objects/body.model"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("3D/_rels/3dmodel.model.rels", "<Relationships/>")
        archive.writestr(object_path, "<model/>")
        archive.writestr("3D/3dmodel.model", "<model/>")
        archive.writestr("Metadata/model_settings.config", "<config/>")
        archive.writestr(
            "Metadata/project_settings.config",
            '{"enable_support":"0","support_type":"normal(auto)"}',
        )
        archive.writestr("Metadata/plate_1.gcode", "stale")
        archive.writestr("Metadata/plate_1.gcode.md5", "stale")
        archive.writestr("Metadata/plate_1.json", "{}")
    return path


def test_create_support_enforcer_project(tmp_path: Path) -> None:
    template = _write_template(tmp_path / "template.3mf")
    chassis = trimesh.creation.box((20.0, 20.0, 10.0))
    chassis.apply_translation((0.0, 0.0, 5.0))
    modifier = trimesh.creation.box((6.0, 6.0, 4.0))
    modifier.apply_translation((0.0, 0.0, 8.0))
    chassis_path = tmp_path / "chassis.stl"
    modifier_path = tmp_path / "modifier.stl"
    chassis.export(chassis_path)
    modifier.export(modifier_path)

    output = tmp_path / "manual_support.3mf"
    report = create_support_enforcer_project(
        template_3mf=template,
        chassis_stl=chassis_path,
        modifier_stl=modifier_path,
        output_3mf=output,
        project_name="manual support",
        support_settings={
            "support_base_pattern_spacing": 3.0,
            "tree_support_branch_distance": 6,
            "tree_support_top_rate": "25%",
            "support_on_build_plate_only": 1,
            "bridge_no_support": 1,
        },
    )
    inspection = inspect_support_enforcer_project(output)

    assert report["passed"]
    assert report["volume_roles"]["modifier.stl"] == "support_enforcer"
    assert inspection["passed"]
    assert inspection["support_type"] == "tree(manual)"
    assert inspection["support_settings"][
        "support_base_pattern_spacing"
    ] == "3"
    assert inspection["support_settings"][
        "tree_support_branch_distance"
    ] == "6"
    assert inspection["support_settings"]["tree_support_top_rate"] == "25%"
    assert (
        inspection["support_settings"]["support_on_build_plate_only"]
        == "1"
    )
    assert inspection["support_settings"]["bridge_no_support"] == "1"
    assert inspection["stale_gcode_entries"] == []


def test_support_enforcer_project_rejects_unknown_tuning_key(
    tmp_path: Path,
) -> None:
    template = _write_template(tmp_path / "template.3mf")
    chassis = trimesh.creation.box((20.0, 20.0, 10.0))
    modifier = trimesh.creation.box((6.0, 6.0, 4.0))
    chassis_path = tmp_path / "chassis.stl"
    modifier_path = tmp_path / "modifier.stl"
    chassis.export(chassis_path)
    modifier.export(modifier_path)

    with pytest.raises(ValueError, match="unsupported OrcaSlicer"):
        create_support_enforcer_project(
            template_3mf=template,
            chassis_stl=chassis_path,
            modifier_stl=modifier_path,
            output_3mf=tmp_path / "invalid.3mf",
            project_name="invalid",
            support_settings={"made_up_tree_setting": 1},
        )


def test_support_enforcer_project_rejects_disjoint_meshes(
    tmp_path: Path,
) -> None:
    template = _write_template(tmp_path / "template.3mf")
    chassis = trimesh.creation.box((10.0, 10.0, 10.0))
    modifier = trimesh.creation.box((2.0, 2.0, 2.0))
    modifier.apply_translation((100.0, 0.0, 0.0))
    chassis_path = tmp_path / "chassis.stl"
    modifier_path = tmp_path / "modifier.stl"
    chassis.export(chassis_path)
    modifier.export(modifier_path)

    with pytest.raises(OrcaProjectError, match="same coordinate system"):
        create_support_enforcer_project(
            template_3mf=template,
            chassis_stl=chassis_path,
            modifier_stl=modifier_path,
            output_3mf=tmp_path / "invalid.3mf",
            project_name="invalid",
        )
