"""Loopback-only GUI server for vision-assisted parametric CAD generation."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import mimetypes
import re
import tempfile
import threading
import uuid
import webbrowser
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .llm import (
    LLMPlanningError,
    build_provider,
    hardware_from_payload,
    proposal_from_payload,
)
from .agents.design_agent import DesignAgent
from .workflow import IndustrialDesignWorkflow


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = Path(__file__).resolve().parent / "web"
DEFAULT_EXPORT_ROOT = PROJECT_ROOT / "ai_cad_designer" / "exports" / "gui"
MAX_REQUEST_BYTES = 128 * 1024 * 1024
MAX_IMAGES = 6
ALLOWED_SOURCE_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
DATA_URL_PATTERN = re.compile(
    r"^data:(image/(?:jpeg|png|webp)|application/pdf);base64,"
    r"([A-Za-z0-9+/=\s]+)$"
)
CAD_LOCK = threading.Lock()


def decode_uploaded_images(items: Any, directory: Path) -> list[Path]:
    """Decode bounded browser data URLs into a temporary private directory."""
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_IMAGES:
        raise ValueError("images must contain between 1 and 6 files")
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"images[{index}] must be an object")
        data_url = item.get("data_url")
        if not isinstance(data_url, str):
            raise ValueError(f"images[{index}].data_url is required")
        match = DATA_URL_PATTERN.fullmatch(data_url)
        if not match:
            raise ValueError(f"images[{index}] is not a supported source data URL")
        mime, encoded = match.groups()
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"images[{index}] contains invalid base64") from exc
        if not content or len(content) > 20 * 1024 * 1024:
            raise ValueError(f"images[{index}] must be between 1 byte and 20MB")
        path = directory / f"hardware-{index + 1}{ALLOWED_SOURCE_MIME[mime]}"
        path.write_bytes(content)
        paths.append(path)
    return paths


def _provider(payload: dict[str, Any]):
    planner = str(payload.get("planner", "codex"))
    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("model must be a string")
    return build_provider(
        planner,
        model=model.strip() if isinstance(model, str) and model.strip() else None,
        working_directory=PROJECT_ROOT,
    )


def _request_text(payload: dict[str, Any]) -> str:
    request = payload.get("request")
    if not isinstance(request, str) or not request.strip():
        raise ValueError("request must be a non-empty string")
    if len(request) > 8_000:
        raise ValueError("request must be at most 8000 characters")
    return request.strip()


class AICADRequestHandler(BaseHTTPRequestHandler):
    """Serve static UI and a small JSON API on localhost."""

    export_root = DEFAULT_EXPORT_ROOT
    server_version = "AICADDesigner/0.2"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[gui] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._status()
            return
        if parsed.path.startswith("/api/files/"):
            self._download(unquote(parsed.path.removeprefix("/api/files/")))
            return
        self._static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/vision", "/api/constraints", "/api/design", "/api/pcb"}:
            self._json_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return
        try:
            payload = self._read_json()
            if parsed.path == "/api/vision":
                result = self._vision(payload)
            elif parsed.path == "/api/constraints":
                result = self._constraints(payload)
            elif parsed.path == "/api/pcb":
                result = self._pcb(payload)
            else:
                result = self._design(payload)
        except (LLMPlanningError, ValueError) as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self._json_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"{type(exc).__name__}: {exc}",
            )
            return
        self._send_json(HTTPStatus.OK, result)

    def _read_json(self) -> dict[str, Any]:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("Content-Length is required")
        try:
            length = int(content_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ValueError("request body is empty or exceeds 128MB")
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("request body must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _status(self) -> None:
        codex = build_provider("codex", working_directory=PROJECT_ROOT)
        api = build_provider("api", working_directory=PROJECT_ROOT)
        self._send_json(
            HTTPStatus.OK,
            {
                "codex": codex.healthcheck(),
                "api": api.healthcheck(),
                "rules": {"available": True, "provider": "rules"},
                "computer_vision": True,
                "export_root": str(self.export_root),
            },
        )

    def _vision(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = _provider(payload)
        if provider is None:
            raise ValueError("computer vision requires the codex or api planner")
        request = _request_text(payload)
        with tempfile.TemporaryDirectory(prefix="ai-cad-vision-") as temp:
            images = decode_uploaded_images(payload.get("images"), Path(temp))
            return provider.analyze_hardware(images, request)

    def _constraints(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Infer manufacturing inputs, keeping unresolved values editable."""
        provider = _provider(payload)
        request = _request_text(payload)
        vision_report = payload.get("vision_report")
        if vision_report is not None:
            vision_report = hardware_from_payload(vision_report)
        planning_request = request
        if vision_report:
            planning_request += (
                "\n\nVERIFIED HARDWARE INVENTORY FROM VISION STAGE:\n"
                + json.dumps(vision_report, ensure_ascii=False, indent=2)
            )

        if provider is None:
            brief = DesignAgent().analyze(request)
            source = "default_reference"
            analyzed = False
            planner = "rules"
            notes = ["未连接可用的分析模型，以下为参考值，请手工确认。"]
        else:
            proposal = proposal_from_payload(
                provider.plan(planning_request), request, planner=provider.name
            )
            brief = proposal.brief
            source = "auto_analyzed"
            analyzed = True
            planner = proposal.planner
            notes = list(proposal.engineering_notes)

        parameters = {
            "material": {"value": brief.material, "source": source},
            "tolerance_mm": {"value": brief.tolerance_mm, "source": source},
            "wall_thickness_mm": {
                "value": brief.wall_thickness_mm,
                "source": source,
            },
            "layer_height_mm": {
                "value": brief.layer_height_mm,
                "source": source,
            },
        }
        return {
            "analyzed": analyzed,
            "planner": planner,
            "parameters": parameters,
            "notes": notes,
        }

    def _design(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = _provider(payload)
        request = _request_text(payload)
        vision_report = payload.get("vision_report")
        if vision_report is not None:
            vision_report = hardware_from_payload(vision_report)
        engineering_parameters = payload.get("engineering_parameters")
        if (
            engineering_parameters is not None
            and not isinstance(engineering_parameters, dict)
        ):
            raise ValueError("engineering_parameters must be an object")
        manufacturing_parameters = payload.get("manufacturing_parameters")
        if (
            manufacturing_parameters is not None
            and not isinstance(manufacturing_parameters, dict)
        ):
            raise ValueError("manufacturing_parameters must be an object")
        images_payload = payload.get("images")
        if images_payload and provider is None:
            raise ValueError("computer vision requires the codex or api planner")

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output_dir = self.export_root / f"{stamp}-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory(prefix="ai-cad-design-") as temp:
            images = (
                decode_uploaded_images(images_payload, Path(temp))
                if images_payload
                else []
            )
            workflow = IndustrialDesignWorkflow(
                output_dir,
                provider=provider,
                fallback_to_rules=not bool(payload.get("strict_planner", False)),
            )
            with CAD_LOCK:
                result = workflow.run(
                    request,
                    image_paths=images,
                    vision_report=vision_report,
                    slice_manufacturing=bool(
                        payload.get("slice_manufacturing", False)
                    ),
                    blender_preview=bool(payload.get("blender_preview", False)),
                    engineering_parameters=engineering_parameters,
                    manufacturing_parameters=manufacturing_parameters,
                )
        response = result.to_dict()
        response["run_id"] = output_dir.name
        response["downloads"] = [
            {
                "name": Path(path).name,
                "url": "/api/files/"
                + str(Path(path).resolve().relative_to(self.export_root.resolve())),
            }
            for path in result.exported_files
        ]
        return response

    def _pcb(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the measured-PCB path without accepting image-derived dimensions."""
        pcb_input = payload.get("pcb_input")
        if not isinstance(pcb_input, dict):
            raise ValueError("pcb_input must be an object")
        print_configuration = payload.get("print_configuration")
        if print_configuration is not None and not isinstance(
            print_configuration, dict
        ):
            raise ValueError("print_configuration must be an object")
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output_dir = self.export_root / f"{stamp}-{uuid.uuid4().hex[:8]}"
        workflow = IndustrialDesignWorkflow(output_dir)
        with CAD_LOCK:
            result = workflow.run_pcb(
                pcb_input,
                slice_manufacturing=bool(payload.get("slice_manufacturing", False)),
                blender_preview=bool(payload.get("blender_preview", False)),
                print_configuration=print_configuration,
            )
        response = result.to_dict()
        response["run_id"] = output_dir.name
        response["downloads"] = [
            {
                "name": Path(path).name,
                "url": "/api/files/"
                + str(Path(path).resolve().relative_to(self.export_root.resolve())),
            }
            for path in result.exported_files
        ]
        return response

    def _download(self, relative_path: str) -> None:
        root = self.export_root.resolve()
        path = (root / relative_path).resolve()
        if root not in path.parents or not path.is_file():
            self._json_error(HTTPStatus.NOT_FOUND, "export file not found")
            return
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{path.name}"',
        )
        self.end_headers()
        self.wfile.write(content)

    def _static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path[1:]
        path = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in path.parents or not path.is_file():
            self._json_error(HTTPStatus.NOT_FOUND, "asset not found")
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _json_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"ok": False, "error": message})

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local AI CAD Designer GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", default=str(DEFAULT_EXPORT_ROOT))
    parser.add_argument("--no-open", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("GUI only supports a loopback host")
    AICADRequestHandler.export_root = Path(args.output).expanduser().resolve()
    AICADRequestHandler.export_root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), AICADRequestHandler)
    url = f"http://{args.host}:{server.server_address[1]}"
    print(f"AI CAD Designer GUI: {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
