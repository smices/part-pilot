import base64
import json
from pathlib import Path

import pytest

from ai_cad_designer import gui_server
from ai_cad_designer.gui_server import AICADRequestHandler, decode_uploaded_images
from ai_cad_designer.llm import DesignLLMProvider, OpenAICompatibleProvider
from ai_cad_designer.llm import providers as provider_module
from ai_cad_designer.llm.schema import hardware_from_payload, proposal_from_payload
from ai_cad_designer.workflow import IndustrialDesignWorkflow


def robot_payload() -> dict:
    return {
        "title": "Vision-assisted desktop robot",
        "design_family": "desktop_robot",
        "product": "desktop robot enclosure",
        "components": [
            {
                "name": "ESP32",
                "dimensions_mm": [55, 28, 13],
                "access": "service",
                "clearance_mm": 0.25,
            },
            {
                "name": "18650 battery",
                "dimensions_mm": [65, 18.6, 18.6],
                "access": "frequent",
                "clearance_mm": 0.25,
            },
        ],
        "material": "PETG",
        "screwless": True,
        "removable": True,
        "layer_height_mm": 0.2,
        "tolerance_mm": 0.25,
        "wall_thickness_mm": 2.5,
        "parts": [
            {
                "name": "body",
                "purpose": "electronics shell",
                "assembly_method": "dovetail",
                "dimensions_mm": [105, 78, 68],
            },
            {
                "name": "cover",
                "purpose": "removable service cover",
                "assembly_method": "snap_fit",
                "dimensions_mm": [100, 70, 4],
            },
            {
                "name": "battery",
                "purpose": "battery drawer",
                "assembly_method": "sliding_rail",
                "dimensions_mm": [74, 27, 24],
            },
            {
                "name": "camera_mount",
                "purpose": "camera bracket",
                "assembly_method": "mortise_tenon",
                "dimensions_mm": [36, 30, 18],
            },
        ],
        "support_strategy": "minimal",
        "engineering_notes": ["Use conservative component clearances."],
    }


def hardware_payload() -> dict:
    return {
        "source_kind": "photo",
        "components": [
            {
                "name": "ESP32 development board",
                "category": "esp32_board",
                "dimensions_mm": [55, 28, 13],
                "confidence": 0.94,
                "evidence": "Visible RF can and dual header layout.",
                "dimension_source": "known_reference",
            },
            {
                "name": "18650 lithium cell",
                "category": "battery",
                "dimensions_mm": [65, 18.6, 18.6],
                "confidence": 0.88,
                "evidence": "Cylindrical cell aspect ratio.",
                "dimension_source": "estimated",
            },
        ],
        "scene_notes": ["No ruler is visible."],
        "requires_user_confirmation": ["Measure battery holder, not bare cell."],
    }


def test_constraint_analysis_falls_back_to_editable_reference_values() -> None:
    result = AICADRequestHandler._constraints(
        None,
        {"planner": "rules", "request": "设计一个 PETG 传感器外壳"},
    )

    assert result["analyzed"] is False
    assert result["parameters"]["material"] == {
        "value": "PETG",
        "source": "default_reference",
    }
    assert result["parameters"]["tolerance_mm"]["value"] == 0.25
    assert "手工确认" in result["notes"][0]


def test_gui_design_passes_requested_blender_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class Result:
        exported_files: list[str] = []

        @staticmethod
        def to_dict():
            return {"preview": {"visual": {"status": "passed"}}}

    class Workflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, request, **kwargs):
            captured["request"] = request
            captured.update(kwargs)
            return Result()

    monkeypatch.setattr(gui_server, "IndustrialDesignWorkflow", Workflow)
    handler = object.__new__(AICADRequestHandler)
    handler.export_root = tmp_path

    response = handler._design(
        {
            "planner": "rules",
            "request": "Design a portable sensor enclosure",
            "blender_preview": True,
        }
    )

    assert captured["blender_preview"] is True
    assert response["preview"]["visual"]["status"] == "passed"


class FakeVisionProvider(DesignLLMProvider):
    name = "fake-vision"

    def plan(self, request: str) -> dict:
        assert "VERIFIED HARDWARE INVENTORY" in request
        return robot_payload()

    def analyze_hardware(
        self,
        image_paths: list[str | Path],
        request: str = "",
    ) -> dict:
        assert image_paths
        return hardware_payload()

    def healthcheck(self) -> dict:
        return {"available": True, "provider": self.name}


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_untrusted_proposal_is_bounded() -> None:
    payload = robot_payload()
    proposal = proposal_from_payload(payload, "robot", planner="test")
    assert proposal.planner == "test"
    assert proposal.brief.support_strategy == "minimal"
    assert proposal.support_strategy == "minimal"
    payload["parts"][0]["dimensions_mm"][0] = 10
    with pytest.raises(ValueError, match="must be at least"):
        proposal_from_payload(payload, "robot", planner="test")


def test_smart_fan_cover_must_match_controller_pod() -> None:
    payload = robot_payload()
    payload["design_family"] = "smart_fan"
    payload["product"] = "smart fan enclosure"
    payload["parts"] = [
        {
            "name": "fan_chassis",
            "purpose": "fan bay and controller pod",
            "assembly_method": "dovetail",
            "dimensions_mm": [132, 132, 58],
        },
        {
            "name": "controller_cover",
            "purpose": "service cover",
            "assembly_method": "snap_fit",
            "dimensions_mm": [110, 100, 25],
        },
        {
            "name": "fan_guard",
            "purpose": "airflow guard",
            "assembly_method": "snap_fit",
            "dimensions_mm": [126, 126, 3],
        },
        {
            "name": "mac_mini_cradle",
            "purpose": "Mac mini M4 locating cradle",
            "assembly_method": "snap_fit",
            "dimensions_mm": [136, 136, 5.5],
        },
        {
            "name": "power_button_plunger",
            "purpose": "underside power button actuator",
            "assembly_method": "sliding_rail",
            "dimensions_mm": [58.75, 23.25, 34.1],
        },
    ]
    with pytest.raises(ValueError, match="controller_cover length"):
        proposal_from_payload(payload, "smart fan", planner="test")


def test_smart_fan_safe_llm_dimensions_are_generator_calibrated() -> None:
    payload = robot_payload()
    payload["design_family"] = "smart_fan"
    payload["product"] = "smart fan enclosure"
    payload["parts"] = [
        {
            "name": "fan_chassis",
            "purpose": "fan bay and controller pod",
            "assembly_method": "dovetail",
            "dimensions_mm": [134, 134, 60],
        },
        {
            "name": "controller_cover",
            "purpose": "service cover",
            "assembly_method": "snap_fit",
            "dimensions_mm": [53, 53, 20],
        },
        {
            "name": "fan_guard",
            "purpose": "airflow guard",
            "assembly_method": "snap_fit",
            "dimensions_mm": [126, 126, 3],
        },
        {
            "name": "mac_mini_cradle",
            "purpose": "Mac mini M4 locating cradle",
            "assembly_method": "mortise_tenon",
            "dimensions_mm": [136, 136, 5.5],
        },
        {
            "name": "power_button_plunger",
            "purpose": "underside power button actuator",
            "assembly_method": "sliding_rail",
            "dimensions_mm": [59, 12, 12],
        },
    ]

    proposal = proposal_from_payload(
        payload,
        "smart fan",
        planner="test",
    )
    assert {
        part.name: part.dimensions_mm for part in proposal.parts
    } == {
        "fan_chassis": (132.0, 132.0, 58.0),
        "controller_cover": (52.5, 52.5, 20.0),
        "fan_guard": (124.0, 124.0, 2.0),
        "mac_mini_cradle": (134.0, 134.0, 5.5),
        "power_button_plunger": (58.75, 23.25, 34.1),
    }
    assert proposal.engineering_notes[-1].startswith(
        "Generator-calibrated smart-fan envelopes applied:"
    )


def test_hardware_analysis_is_normalized() -> None:
    result = hardware_from_payload(hardware_payload())
    assert result["components"][0]["category"] == "esp32_board"
    invalid = hardware_payload()
    invalid["components"][0]["category"] = "unknown"
    with pytest.raises(ValueError, match="unsupported hardware category"):
        hardware_from_payload(invalid)


def test_browser_image_decode_is_bounded(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"test"
    images = decode_uploaded_images(
        [
            {
                "name": "board.png",
                "data_url": "data:image/png;base64,"
                + base64.b64encode(png).decode("ascii"),
            }
        ],
        tmp_path,
    )
    assert images[0].read_bytes() == png
    with pytest.raises(ValueError, match="between 1 and 6"):
        decode_uploaded_images([], tmp_path)


def test_browser_pdf_schematic_decode_is_supported(tmp_path: Path) -> None:
    pdf = b"%PDF-1.4\n% schematic fixture\n%%EOF\n"
    sources = decode_uploaded_images(
        [
            {
                "name": "wiring.pdf",
                "data_url": "data:application/pdf;base64,"
                + base64.b64encode(pdf).decode("ascii"),
            }
        ],
        tmp_path,
    )
    assert sources[0].suffix == ".pdf"
    assert sources[0].read_bytes() == pdf


def test_vision_to_parametric_cad_workflow(tmp_path: Path) -> None:
    image = tmp_path / "hardware.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    output = tmp_path / "exports"
    result = IndustrialDesignWorkflow(
        output,
        provider=FakeVisionProvider(),
        fallback_to_rules=False,
    ).run("Design a removable desktop robot enclosure", image_paths=[image])

    assert result.passed
    assert result.vision["components"][0]["category"] == "esp32_board"
    assert (output / "hardware_analysis.json").is_file()
    assert (output / "body.step").is_file()
    assert (output / "cover.stl").is_file()
    assert (output / "battery.step").is_file()
    assert (output / "camera_mount.stl").is_file()
    assert len(result.preview["assembly"]["items"]) == 4
    cover_preview = next(
        item
        for item in result.preview["assembly"]["items"]
        if item["name"] == "cover"
    )
    assert cover_preview["translation_mm"][2] > 68
    report = (output / "validation_report.json").read_text(encoding="utf-8")
    assert "hardware_analysis.json" in report
    assert "validation_report.json" in report
    assert '"preview"' in report


def test_openai_compatible_responses_and_vision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []
    responses = [
        {"output_text": json.dumps(robot_payload())},
        {"output_text": json.dumps(hardware_payload())},
    ]

    def fake_urlopen(request, timeout):
        requests.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data),
                "timeout": timeout,
            }
        )
        return FakeHTTPResponse(responses.pop(0))

    monkeypatch.setattr(provider_module.urllib.request, "urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        base_url="https://compatible.example/v1",
        api_key="test-only",
        model="vision-model",
        protocol="responses",
    )
    proposal = provider.plan("Design a robot")
    assert proposal["design_family"] == "desktop_robot"
    assert requests[0]["url"] == "https://compatible.example/v1/responses"
    assert requests[0]["body"]["text"]["format"]["strict"] is True

    image = tmp_path / "board.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    vision = provider.analyze_hardware([image], "Enclose this board")
    assert vision["components"][0]["category"] == "esp32_board"
    image_block = requests[1]["body"]["input"][0]["content"][1]
    assert image_block["type"] == "input_image"
    assert image_block["image_url"].startswith("data:image/png;base64,")
