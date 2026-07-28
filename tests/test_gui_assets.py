from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "ai_cad_designer" / "web"


def test_gui_loads_local_interactive_stl_viewer() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    viewer = (WEB_ROOT / "viewer.js").read_text(encoding="utf-8")
    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert html.index('src="/viewer.js') < html.index('src="/app.js')
    assert 'id="modelCanvas"' in html
    assert 'id="dimensionX"' in html
    assert 'id="dimensionY"' in html
    assert 'id="dimensionZ"' in html
    assert 'id="assemblyInspector"' in html
    assert 'id="inspectorList"' in html
    assert 'id="showAllItems"' in html
    assert 'id="topView"' in html
    assert 'id="bottomView"' in html
    assert 'id="frontView"' in html
    assert 'id="rearView"' in html
    assert 'id="leftView"' in html
    assert 'id="rightView"' in html
    assert "application/pdf" in html
    assert 'id="loadDemo"' in html
    assert 'id="sliceManufacturing"' in html
    assert 'id="manufacturingSection"' in html
    assert 'id="fanAirflow"' in html
    assert 'id="fanStaticPressure"' in html
    assert 'id="thermalLoad"' in html
    assert 'id="allowedAirRise"' in html
    assert 'id="fanThickness"' in html
    assert 'data-engineering-parameter="mac_foot_outer_diameter_mm"' in html
    assert 'data-engineering-parameter="power_button_x_mm"' in html
    assert 'data-engineering-parameter="fan_mount_spacing_mm"' in html
    assert (
        'data-engineering-parameter="ds18b20_probe_diameter_mm"'
        in html
    )
    assert 'id="calibratedProbeDiameter"' in html
    assert 'id="calibratedProbeInterference"' in html
    assert 'id="airflowSection"' in html
    assert 'id="calibrationSection"' in html
    assert 'id="calibrationList"' in html
    assert 'id="applyCalibration"' in html
    assert 'id="saveProfile"' in html
    assert 'id="loadProfile"' in html
    assert 'data-manufacturing-parameter="tolerance_mm"' in html
    assert 'data-step="3"' in html
    assert "class STLViewer" in viewer
    assert 'canvas.getContext("webgl"' in viewer
    assert "async loadScene(scene)" in viewer
    assert "setView(view)" in viewer
    assert "front: [0, -Math.PI / 2, 0.72]" in viewer
    assert "rear: [Math.PI, -Math.PI / 2, 0.72]" in viewer
    assert "left: [-Math.PI / 2, -Math.PI / 2, 0.72]" in viewer
    assert "right: [Math.PI / 2, -Math.PI / 2, 0.72]" in viewer
    assert "bottom: [0, Math.PI" in viewer
    assert "http://" not in viewer and "https://" not in viewer
    assert "完整装配" in app
    assert "爆炸装配" in app
    assert "内部硬件布置" in app
    assert "DS18B20 探头卡座" in app
    assert "电源键机构" in app
    assert "powerButtonMechanism" in app
    assert "mat3 rz" in viewer
    assert "item.color_rgb" in viewer
    assert "fanMesh(dimensions)" in viewer
    assert "roundedBoxMesh(dimensions" in viewer
    assert "SMART_FAN_DEMO" in app
    assert "dimension-editor" in app
    assert "renderModels(result.downloads, result.preview)" in app
    assert "renderManufacturing(result.manufacturing)" in app
    assert "renderAirflow(result.airflow)" in app
    assert "renderCalibration(result.calibration)" in app
    assert "preview?.calibration?.items" in app
    assert "manufacturing_parameters: manufacturingParameters" in app
    assert 'const CAD_PROFILE_KEY = "forge.aiCadProfile.v1"' in app
    assert "applyCalibrationFeedback" in app
    assert '"calibration_coupon"' in app
    assert "Fan free-air flow:" in app
    assert "Maximum static pressure:" in app
    assert "engineering_parameters: engineeringParameters" in app
    assert "additional_filament_ratio" in app
    assert "additional_time_ratio" in app
    assert "自动支撑对照" in app
    assert "dimensions_mm: [30, 6, 6]" in app
    assert "dimensions_mm: [6, 6, 50]" not in app
    assert "打印方向与自动支撑包络" in app
    assert "支撑 XY 热点地图" in app
    assert "auto_support_xy_tile" in app
    assert "支撑 XYZ 接触热点" in app
    assert "auto_support_xyz_cell" in app
    assert "auto_support_envelope" in app
    assert "preview?.print_layout?.items" in app
    assert "item.print_metrics" in app
    assert 'input.dataset.source = "user_supplied"' in app
    assert "ASSEMBLY BOM" in html
    assert "displayItems" in app
    assert "sceneState.hidden" in app
    assert "sceneState.highlightIndex" in app
    assert "formattedVector(item.dimensions_mm)" in app
    assert "formattedVector(item.translation_mm" in app
