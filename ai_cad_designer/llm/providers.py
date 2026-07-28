"""Local Codex and OpenAI-compatible structured planning providers."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .schema import (
    DESIGN_PROPOSAL_JSON_SCHEMA,
    HARDWARE_ANALYSIS_JSON_SCHEMA,
    hardware_from_payload,
)


SYSTEM_PROMPT = """You are the engineering-planning stage of an AI CAD system.
Analyze the user's components, access needs, assembly, material, and FDM constraints.
Return only a JSON object conforming to the supplied schema.

The current parametric generator supports exactly three design families:
1. sensor_enclosure: exactly sensor_base, sensor_lid in that order.
2. desktop_robot: exactly body, cover, battery, camera_mount in that order.
3. smart_fan: exactly fan_chassis, controller_cover, fan_guard,
   mac_mini_cradle, power_button_plunger in that order.

The generator has hard minimum part envelopes in length x width x height:
- sensor_base 40 x 35 x 12 mm; sensor_lid 40 x 35 x 6 mm.
- body 75 x 55 x 45 mm; cover 65 x 45 x 2 mm.
- battery 45 x 22 x 16 mm; camera_mount 20 x 18 x 8 mm.
- fan_chassis 132 x 132 x 58 mm; controller_cover 52 x 52 x 20 mm;
  fan_guard 120 x 120 x 1.2 mm; mac_mini_cradle 132 x 132 x 5.5 mm;
  power_button_plunger 55 x 10 x 10 mm.
Never return a smaller part. The proposal must be screwless and removable.

Use realistic component envelopes and include assembly clearance. Prefer few parts,
screwless serviceable joints, PETG, 0.2 mm layers, 0.25 mm tolerance, and minimal
supports when the user does not specify otherwise. Preserve explicit user constraints.
For desktop_robot use dovetail for body, snap_fit for cover, sliding_rail for battery,
and mortise_tenon for camera_mount unless another supported method is clearly better.
Use smart_fan for a 120 mm smart cooling fan, ESP32-C3 fan controller, or the
smices/hw_smart_fan reference. Its fan bay must provide 120.5 mm clearance and
the control pod must remain serviceable without removing the fan. For smart_fan,
prefer the proven dimensions fan_chassis 132 x 132 x 58, controller_cover
52.5 x 52.5 x 20, fan_guard 124 x 124 x 2, and mac_mini_cradle
136 x 136 x 5.5 mm, plus a support-free power_button_plunger with an
integrated rear-access lift paddle in a 58.75 x 23.25 x 34.1 mm envelope.
The cradle must locate a 127 x 127 x 50 mm Mac mini M4
with 0.25 mm clearance on each side, use a continuous rounded-square ring
around a 115 mm circular airflow opening, provide a bounded rear-left power
button access bore without an edge notch, and leave the front and rear ports
unobstructed. Place the removable
electronics cassette below the fan, entirely inside the Mac mini footprint:
there must be zero lateral accessory-box extension. Model the fan as
120 x 120 x 25 mm and preserve ESP32-C3, both DC-DC modules, MOSFET driver,
and DS18B20 as assembly references. Keep controller_cover near
52.5 x 52.5 x 20 mm and keep the fan_guard inside the fan_chassis width.
Optimize jointly for compactness,
support-free printing, PETG consumption, short bridges, and structural stability.
Do not claim simulation, structural certification, or physical testing."""

VISION_PROMPT = """You are the visual-input stage of an AI CAD system.
The attachments may be hardware photos, electrical schematics, PCB diagrams, or a
mixture. Set source_kind accordingly. For photos, identify visible hardware. For
schematics, extract functional blocks, named parts, connectors, power sources,
motors, cameras, sensors, displays, and heat-producing components. Do not treat
schematic symbols as physical scale.

Identify Arduino boards, ESP32 boards, batteries, motors, cameras, fans, sensors,
microcontrollers, power modules, connectors, displays, speakers, and PCBs.
Return only JSON conforming to the supplied schema.

Never invent a precise measurement from pixels alone. If a ruler or known scale is
visible, use visible_scale. If a board or cell is confidently identifiable, use a
conservative known_reference envelope. For an exact identified component or board
from a schematic, use datasheet_reference only when the package or board variant is
unambiguous. Otherwise use estimated, lower confidence, and add a user-confirmation
item. Dimensions are physical bounding-box length, width, and height in millimeters
and must include connectors or protrusions that affect an enclosure. Explicitly ask
the user to measure PCB outline, maximum assembled height, mounting holes, connector
locations, cable exits, and keep-out zones when a schematic cannot provide them."""


class LLMPlanningError(RuntimeError):
    """Raised when a planning provider cannot return valid structured output."""


class DesignLLMProvider(ABC):
    name: str

    @abstractmethod
    def plan(self, request: str) -> dict[str, Any]:
        """Return an untrusted JSON-compatible design proposal."""

    @abstractmethod
    def analyze_hardware(
        self,
        image_paths: list[str | Path],
        request: str = "",
    ) -> dict[str, Any]:
        """Identify hardware from one or more local images."""

    @abstractmethod
    def healthcheck(self) -> dict[str, Any]:
        """Return provider availability without exposing credentials."""


def _decode_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMPlanningError(f"provider returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LLMPlanningError("provider response must be a JSON object")
    return payload


class CodexCLIProvider(DesignLLMProvider):
    """Use the user's authenticated local Codex CLI in read-only mode."""

    name = "codex"

    def __init__(
        self,
        *,
        model: str | None = None,
        timeout_seconds: float = 240.0,
        codex_binary: str | None = None,
        working_directory: str | Path | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.codex_binary = codex_binary or shutil.which("codex") or "codex"
        self.working_directory = Path(
            working_directory or Path(__file__).resolve().parents[2]
        ).resolve()

    def healthcheck(self) -> dict[str, Any]:
        binary = (
            shutil.which(self.codex_binary)
            if "/" not in self.codex_binary
            else self.codex_binary
        )
        if not binary or not Path(binary).exists():
            return {
                "available": False,
                "provider": self.name,
                "error": "codex not found",
            }
        try:
            version = subprocess.run(
                [binary, "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            auth = subprocess.run(
                [binary, "login", "status"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "available": False,
                "provider": self.name,
                "error": type(exc).__name__,
            }
        auth_text = f"{auth.stdout}\n{auth.stderr}".strip()
        return {
            "available": auth.returncode == 0,
            "provider": self.name,
            "version": version,
            "authenticated": auth.returncode == 0,
            "auth_status": auth_text,
            "model": self.model or "codex-config-default",
        }

    def _run_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        image_paths: list[Path] | None = None,
    ) -> dict[str, Any]:
        health = self.healthcheck()
        if not health.get("available"):
            raise LLMPlanningError(f"local Codex unavailable: {health.get('error')}")
        with tempfile.TemporaryDirectory(prefix="ai-cad-codex-") as temp_dir:
            temp = Path(temp_dir)
            schema_path = temp / "design-proposal.schema.json"
            output_path = temp / "design-proposal.json"
            schema_path.write_text(
                json.dumps(schema, ensure_ascii=False),
                encoding="utf-8",
            )
            command = [
                self.codex_binary,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
            ]
            for image_path in image_paths or []:
                command.extend(["--image", str(image_path)])
            if self.model:
                command.extend(["--model", self.model])
            command.extend(["--cd", str(self.working_directory), prompt])
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=self.working_directory,
                )
            except subprocess.TimeoutExpired as exc:
                raise LLMPlanningError(
                    f"local Codex timed out after {self.timeout_seconds:g}s"
                ) from exc
            except OSError as exc:
                raise LLMPlanningError(f"failed to start Codex: {exc}") from exc
            if result.returncode != 0:
                detail = result.stderr.strip().splitlines()
                message = detail[-1] if detail else f"exit code {result.returncode}"
                raise LLMPlanningError(f"local Codex failed: {message[:500]}")
            text = (
                output_path.read_text(encoding="utf-8")
                if output_path.is_file()
                else result.stdout
            )
            return _decode_json(text)

    def plan(self, request: str) -> dict[str, Any]:
        prompt = f"{SYSTEM_PROMPT}\n\nUSER DESIGN REQUEST:\n{request.strip()}"
        return self._run_structured(prompt, DESIGN_PROPOSAL_JSON_SCHEMA)

    def analyze_hardware(
        self,
        image_paths: list[str | Path],
        request: str = "",
    ) -> dict[str, Any]:
        prompt = VISION_PROMPT
        if request.strip():
            prompt += f"\n\nPRODUCT CONTEXT:\n{request.strip()}"
        with _prepared_images(image_paths) as images:
            payload = self._run_structured(
                prompt,
                HARDWARE_ANALYSIS_JSON_SCHEMA,
                image_paths=images,
            )
        return hardware_from_payload(payload)


class OpenAICompatibleProvider(DesignLLMProvider):
    """Call a configurable Responses or Chat Completions compatible endpoint."""

    name = "api"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        protocol: str | None = None,
        timeout_seconds: float | None = None,
        structured_outputs: bool | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("AI_CAD_API_BASE")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = api_key or os.getenv("AI_CAD_API_KEY")
        self.model = model or os.getenv("AI_CAD_API_MODEL") or "gpt-5.6-sol"
        self.protocol = (
            protocol or os.getenv("AI_CAD_API_PROTOCOL") or "responses"
        ).lower()
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("AI_CAD_API_TIMEOUT", "240")
        )
        if structured_outputs is None:
            structured_outputs = os.getenv(
                "AI_CAD_API_STRUCTURED_OUTPUTS", "true"
            ).lower() not in {"0", "false", "no", "off"}
        self.structured_outputs = structured_outputs
        if self.protocol not in {"responses", "chat_completions"}:
            raise ValueError("API protocol must be responses or chat_completions")

    def healthcheck(self) -> dict[str, Any]:
        return {
            "available": bool(self.api_key),
            "provider": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "protocol": self.protocol,
            "structured_outputs": self.structured_outputs,
            "authenticated": bool(self.api_key),
        }

    def _request_body(self, request: str) -> tuple[str, dict[str, Any]]:
        if self.protocol == "responses":
            body: dict[str, Any] = {
                "model": self.model,
                "instructions": SYSTEM_PROMPT,
                "input": request,
                "reasoning": {"effort": "medium"},
            }
            if self.structured_outputs:
                body["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "ai_cad_design_proposal",
                        "strict": True,
                        "schema": DESIGN_PROPOSAL_JSON_SCHEMA,
                    }
                }
            return f"{self.base_url}/responses", body

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": request},
            ],
            "reasoning_effort": "medium",
        }
        if self.structured_outputs:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "ai_cad_design_proposal",
                    "strict": True,
                    "schema": DESIGN_PROPOSAL_JSON_SCHEMA,
                },
            }
        return f"{self.base_url}/chat/completions", body

    def _structured_format(self, schema: dict[str, Any], name: str) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "name": name,
            "strict": True,
            "schema": schema,
        }

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise LLMPlanningError("AI_CAD_API_KEY is not configured")
        http_request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=self.timeout_seconds
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise LLMPlanningError(
                f"external API returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMPlanningError(f"external API request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise LLMPlanningError("external API response must be a JSON object")
        return payload

    @staticmethod
    def _responses_text(payload: dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    return content["text"]
        raise LLMPlanningError("Responses API returned no output text")

    def plan(self, request: str) -> dict[str, Any]:
        url, body = self._request_body(request)
        payload = self._post(url, body)
        if self.protocol == "responses":
            return _decode_json(self._responses_text(payload))
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMPlanningError(
                "Chat Completions API returned no assistant content"
            ) from exc
        return _decode_json(content)

    def analyze_hardware(
        self,
        image_paths: list[str | Path],
        request: str = "",
    ) -> dict[str, Any]:
        with _prepared_images(image_paths) as images:
            return self._analyze_hardware_images(images, request)

    def _analyze_hardware_images(
        self,
        images: list[Path],
        request: str,
    ) -> dict[str, Any]:
        encoded = [_image_data_url(path) for path in images]
        prompt = VISION_PROMPT
        if request.strip():
            prompt += f"\n\nPRODUCT CONTEXT:\n{request.strip()}"

        if self.protocol == "responses":
            content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
            content.extend(
                {"type": "input_image", "image_url": data_url}
                for data_url in encoded
            )
            body: dict[str, Any] = {
                "model": self.model,
                "input": [{"role": "user", "content": content}],
                "reasoning": {"effort": "medium"},
            }
            if self.structured_outputs:
                body["text"] = {
                    "format": self._structured_format(
                        HARDWARE_ANALYSIS_JSON_SCHEMA,
                        "ai_cad_hardware_analysis",
                    )
                }
            payload = self._post(f"{self.base_url}/responses", body)
            result = _decode_json(self._responses_text(payload))
        else:
            content = [{"type": "text", "text": prompt}]
            content.extend(
                {"type": "image_url", "image_url": {"url": data_url}}
                for data_url in encoded
            )
            body = {
                "model": self.model,
                "messages": [{"role": "user", "content": content}],
                "reasoning_effort": "medium",
            }
            if self.structured_outputs:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ai_cad_hardware_analysis",
                        "strict": True,
                        "schema": HARDWARE_ANALYSIS_JSON_SCHEMA,
                    },
                }
            payload = self._post(f"{self.base_url}/chat/completions", body)
            try:
                result = _decode_json(payload["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMPlanningError(
                    "Chat Completions API returned no vision content"
                ) from exc
        return hardware_from_payload(result)


def build_provider(
    name: str,
    *,
    model: str | None = None,
    working_directory: str | Path | None = None,
) -> DesignLLMProvider | None:
    normalized = name.strip().lower()
    if normalized == "rules":
        return None
    if normalized == "codex":
        return CodexCLIProvider(model=model, working_directory=working_directory)
    if normalized == "api":
        return OpenAICompatibleProvider(model=model)
    raise ValueError("planner must be codex, api, or rules")


@contextmanager
def _prepared_images(
    image_paths: list[str | Path],
) -> Iterator[list[Path]]:
    if not image_paths:
        raise LLMPlanningError("at least one hardware photo or schematic is required")
    if len(image_paths) > 6:
        raise LLMPlanningError("at most six source files are supported per run")
    sources = []
    for image_path in image_paths:
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            raise LLMPlanningError(f"hardware source not found: {path}")
        mime, _ = mimetypes.guess_type(path.name)
        if mime not in {"image/jpeg", "image/png", "image/webp", "application/pdf"}:
            raise LLMPlanningError(f"unsupported source format: {path.suffix}")
        if path.stat().st_size > 20 * 1024 * 1024:
            raise LLMPlanningError(f"hardware source exceeds 20MB: {path.name}")
        sources.append((path, mime))

    with tempfile.TemporaryDirectory(prefix="ai-cad-schematic-") as temp_dir:
        result: list[Path] = []
        temp = Path(temp_dir)
        for source_index, (path, mime) in enumerate(sources):
            if mime != "application/pdf":
                result.append(path)
                continue
            environment_renderer = Path(sys.executable).resolve().parent / "pdftoppm"
            renderer = shutil.which("pdftoppm") or (
                str(environment_renderer) if environment_renderer.is_file() else None
            )
            if renderer is None:
                raise LLMPlanningError(
                    "PDF schematic support requires pdftoppm (Poppler)"
                )
            remaining = 6 - len(result)
            if remaining <= 0:
                break
            prefix = temp / f"schematic-{source_index + 1}"
            try:
                conversion = subprocess.run(
                    [
                        renderer,
                        "-png",
                        "-r",
                        "160",
                        "-f",
                        "1",
                        "-l",
                        str(remaining),
                        str(path),
                        str(prefix),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise LLMPlanningError(
                    f"failed to render PDF schematic: {exc}"
                ) from exc
            if conversion.returncode != 0:
                detail = conversion.stderr.strip()[-500:]
                raise LLMPlanningError(
                    f"failed to render PDF schematic: {detail}"
                )
            pages = sorted(temp.glob(f"{prefix.name}-*.png"))
            if not pages:
                raise LLMPlanningError("PDF schematic contains no renderable pages")
            result.extend(pages[:remaining])

        if not result:
            raise LLMPlanningError("no renderable hardware sources were found")
        for path in result:
            if path.stat().st_size > 20 * 1024 * 1024:
                raise LLMPlanningError(
                    f"rendered schematic page exceeds 20MB: {path.name}"
                )
        yield result[:6]


def _image_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
