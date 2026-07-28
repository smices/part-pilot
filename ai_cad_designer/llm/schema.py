"""Strict JSON contract shared by local Codex and external API providers."""

from __future__ import annotations

from typing import Any

from ai_cad_designer.schema import (
    ComponentSpec,
    DesignBrief,
    DesignProposal,
    PartPlan,
)


DESIGN_FAMILIES = ("sensor_enclosure", "desktop_robot", "smart_fan")
MATERIALS = ("PETG", "PLA", "ABS", "ASA", "TPU")
ASSEMBLY_METHODS = (
    "snap_fit",
    "dovetail",
    "mortise_tenon",
    "magnet",
    "sliding_rail",
)
EXPECTED_PARTS = {
    "sensor_enclosure": ("sensor_base", "sensor_lid"),
    "desktop_robot": ("body", "cover", "battery", "camera_mount"),
    "smart_fan": (
        "fan_chassis",
        "controller_cover",
        "fan_guard",
        "mac_mini_cradle",
        "power_button_plunger",
    ),
}
SMART_FAN_CALIBRATED_DIMENSIONS = {
    "fan_chassis": (132.0, 132.0, 58.0),
    "controller_cover": (52.5, 52.5, 20.0),
    "fan_guard": (124.0, 124.0, 2.0),
    "mac_mini_cradle": (134.0, 134.0, 5.5),
    "power_button_plunger": (58.75, 23.25, 34.1),
}

DIMENSIONS_SCHEMA = {
    "type": "array",
    "items": {"type": "number", "minimum": 1.0, "maximum": 400.0},
    "minItems": 3,
    "maxItems": 3,
}

DESIGN_PROPOSAL_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 3, "maxLength": 120},
        "design_family": {"type": "string", "enum": list(DESIGN_FAMILIES)},
        "product": {"type": "string", "minLength": 3, "maxLength": 120},
        "components": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                    "dimensions_mm": DIMENSIONS_SCHEMA,
                    "access": {
                        "type": "string",
                        "enum": ["internal", "service", "frequent", "external"],
                    },
                    "clearance_mm": {
                        "type": "number",
                        "minimum": 0.05,
                        "maximum": 2.0,
                    },
                },
                "required": ["name", "dimensions_mm", "access", "clearance_mm"],
            },
        },
        "material": {"type": "string", "enum": list(MATERIALS)},
        "screwless": {"type": "boolean"},
        "removable": {"type": "boolean"},
        "layer_height_mm": {
            "type": "number",
            "minimum": 0.08,
            "maximum": 0.4,
        },
        "tolerance_mm": {
            "type": "number",
            "minimum": 0.1,
            "maximum": 0.8,
        },
        "wall_thickness_mm": {
            "type": "number",
            "minimum": 1.2,
            "maximum": 6.0,
        },
        "parts": {
            "type": "array",
            "minItems": 2,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                    "purpose": {"type": "string", "minLength": 3, "maxLength": 240},
                    "assembly_method": {
                        "type": "string",
                        "enum": list(ASSEMBLY_METHODS),
                    },
                    "dimensions_mm": DIMENSIONS_SCHEMA,
                },
                "required": [
                    "name",
                    "purpose",
                    "assembly_method",
                    "dimensions_mm",
                ],
            },
        },
        "support_strategy": {
            "type": "string",
            "enum": ["none", "minimal", "required"],
        },
        "engineering_notes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {"type": "string", "minLength": 3, "maxLength": 300},
        },
    },
    "required": [
        "title",
        "design_family",
        "product",
        "components",
        "material",
        "screwless",
        "removable",
        "layer_height_mm",
        "tolerance_mm",
        "wall_thickness_mm",
        "parts",
        "support_strategy",
        "engineering_notes",
    ],
}

HARDWARE_ANALYSIS_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source_kind": {
            "type": "string",
            "enum": ["photo", "schematic", "mixed"],
        },
        "components": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "category": {
                        "type": "string",
                        "enum": [
                            "arduino_board",
                            "esp32_board",
                            "battery",
                            "motor",
                            "camera",
                            "fan",
                            "sensor",
                            "microcontroller",
                            "power_supply",
                            "connector",
                            "display",
                            "speaker",
                            "pcb",
                            "other",
                        ],
                    },
                    "dimensions_mm": DIMENSIONS_SCHEMA,
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "evidence": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 300,
                    },
                    "dimension_source": {
                        "type": "string",
                        "enum": [
                            "visible_scale",
                            "known_reference",
                            "datasheet_reference",
                            "user_supplied",
                            "estimated",
                        ],
                    },
                },
                "required": [
                    "name",
                    "category",
                    "dimensions_mm",
                    "confidence",
                    "evidence",
                    "dimension_source",
                ],
            },
        },
        "scene_notes": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "minLength": 3, "maxLength": 300},
        },
        "requires_user_confirmation": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "minLength": 3, "maxLength": 300},
        },
    },
    "required": [
        "source_kind",
        "components",
        "scene_notes",
        "requires_user_confirmation",
    ],
}


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


def _dimensions(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} must contain exactly three dimensions")
    return tuple(
        _number(item, f"{name}[{index}]", 1.0, 400.0)
        for index, item in enumerate(value)
    )


def _string(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{name} is longer than {maximum} characters")
    return normalized


def proposal_from_payload(
    payload: dict[str, Any],
    request: str,
    *,
    planner: str,
) -> DesignProposal:
    """Convert untrusted model JSON into bounded engineering dataclasses."""
    if not isinstance(payload, dict):
        raise ValueError("planner output must be a JSON object")

    family = _string(payload.get("design_family"), "design_family")
    if family not in DESIGN_FAMILIES:
        raise ValueError(f"unsupported design_family: {family}")

    material = _string(payload.get("material"), "material").upper()
    if material not in MATERIALS:
        raise ValueError(f"unsupported material: {material}")

    components_payload = payload.get("components")
    if not isinstance(components_payload, list) or not 1 <= len(components_payload) <= 12:
        raise ValueError("components must contain between 1 and 12 entries")
    components = tuple(
        ComponentSpec(
            name=_string(item.get("name"), f"components[{index}].name", maximum=80),
            dimensions_mm=_dimensions(
                item.get("dimensions_mm"), f"components[{index}].dimensions_mm"
            ),
            access=_string(
                item.get("access"), f"components[{index}].access", maximum=20
            ),
            clearance_mm=_number(
                item.get("clearance_mm"),
                f"components[{index}].clearance_mm",
                0.05,
                2.0,
            ),
        )
        for index, item in enumerate(components_payload)
        if isinstance(item, dict)
    )
    if len(components) != len(components_payload):
        raise ValueError("every component must be an object")

    parts_payload = payload.get("parts")
    if not isinstance(parts_payload, list):
        raise ValueError("parts must be an array")
    parts = [
        PartPlan(
            name=_string(item.get("name"), f"parts[{index}].name", maximum=80),
            purpose=_string(
                item.get("purpose"), f"parts[{index}].purpose", maximum=240
            ),
            assembly_method=_string(
                item.get("assembly_method"),
                f"parts[{index}].assembly_method",
                maximum=40,
            ),
            dimensions_mm=_dimensions(
                item.get("dimensions_mm"), f"parts[{index}].dimensions_mm"
            ),
        )
        for index, item in enumerate(parts_payload)
        if isinstance(item, dict)
    ]
    if len(parts) != len(parts_payload):
        raise ValueError("every part must be an object")
    if tuple(part.name for part in parts) != EXPECTED_PARTS[family]:
        expected = ", ".join(EXPECTED_PARTS[family])
        raise ValueError(f"{family} parts must be ordered exactly as: {expected}")
    if any(part.assembly_method not in ASSEMBLY_METHODS for part in parts):
        raise ValueError("planner selected an unsupported assembly method")
    _validate_part_envelopes(family, parts)
    calibrated_dimension_changes = []
    if family == "smart_fan":
        calibrated_parts = []
        for part in parts:
            calibrated_dimensions = SMART_FAN_CALIBRATED_DIMENSIONS[
                part.name
            ]
            if part.dimensions_mm != calibrated_dimensions:
                calibrated_dimension_changes.append(
                    f"{part.name} {part.dimensions_mm} -> "
                    f"{calibrated_dimensions}"
                )
            calibrated_parts.append(
                PartPlan(
                    name=part.name,
                    purpose=part.purpose,
                    assembly_method=part.assembly_method,
                    dimensions_mm=calibrated_dimensions,
                )
            )
        parts = calibrated_parts

    notes_payload = payload.get("engineering_notes")
    if not isinstance(notes_payload, list) or not notes_payload:
        raise ValueError("engineering_notes must be a non-empty array")
    support_strategy = _string(
        payload.get("support_strategy"), "support_strategy", maximum=20
    )
    if support_strategy not in {"none", "minimal", "required"}:
        raise ValueError(f"unsupported support strategy: {support_strategy}")

    brief = DesignBrief(
        request=request,
        design_family=family,
        product=_string(payload.get("product"), "product", maximum=120),
        components=components,
        material=material,
        screwless=bool(payload.get("screwless")),
        removable=bool(payload.get("removable")),
        layer_height_mm=_number(
            payload.get("layer_height_mm"), "layer_height_mm", 0.08, 0.4
        ),
        tolerance_mm=_number(
            payload.get("tolerance_mm"), "tolerance_mm", 0.1, 0.8
        ),
        wall_thickness_mm=_number(
            payload.get("wall_thickness_mm"), "wall_thickness_mm", 1.2, 6.0
        ),
        support_strategy=support_strategy,
    )
    if not brief.screwless:
        raise ValueError("this prototype only supports screwless designs")
    if not brief.removable:
        raise ValueError("this prototype only supports removable enclosures")

    engineering_notes = [
        _string(note, f"engineering_notes[{index}]")
        for index, note in enumerate(notes_payload)
    ]
    if calibrated_dimension_changes:
        engineering_notes.append(
            "Generator-calibrated smart-fan envelopes applied: "
            + "; ".join(calibrated_dimension_changes)
        )

    return DesignProposal(
        title=_string(payload.get("title"), "title", maximum=120),
        brief=brief,
        parts=parts,
        support_strategy=support_strategy,
        engineering_notes=engineering_notes,
        planner=planner,
    )


def _validate_part_envelopes(family: str, parts: list[PartPlan]) -> None:
    """Keep untrusted model dimensions inside the proven generator envelope."""
    minimums = {
        "sensor_enclosure": {
            "sensor_base": (40.0, 35.0, 12.0),
            "sensor_lid": (40.0, 35.0, 6.0),
        },
        "desktop_robot": {
            "body": (75.0, 55.0, 45.0),
            "cover": (65.0, 45.0, 2.0),
            "battery": (45.0, 22.0, 16.0),
            "camera_mount": (20.0, 18.0, 8.0),
        },
        "smart_fan": {
            "fan_chassis": (132.0, 132.0, 58.0),
            "controller_cover": (52.0, 52.0, 20.0),
            "fan_guard": (120.0, 120.0, 1.2),
            "mac_mini_cradle": (132.0, 132.0, 5.5),
            "power_button_plunger": (55.0, 10.0, 10.0),
        },
    }
    for part in parts:
        required = minimums[family][part.name]
        for axis, (actual, minimum) in enumerate(
            zip(part.dimensions_mm, required, strict=True)
        ):
            if actual < minimum:
                raise ValueError(
                    f"{part.name}.dimensions_mm[{axis}] must be at least "
                    f"{minimum:g} for the parametric generator"
                )
    if family == "smart_fan":
        by_name = {part.name: part for part in parts}
        chassis = by_name["fan_chassis"].dimensions_mm
        cover = by_name["controller_cover"].dimensions_mm
        guard = by_name["fan_guard"].dimensions_mm
        cradle = by_name["mac_mini_cradle"].dimensions_mm
        if abs(cover[0] - 52.5) > 2.0:
            raise ValueError(
                "controller_cover length must match the integrated smart-fan "
                "underside electronics cassette inner opening (52.5mm)"
            )
        if not 52.0 <= cover[1] <= 54.0:
            raise ValueError(
                "controller_cover width must fit the underside electronics cassette"
            )
        if guard[0] > chassis[1] or guard[1] > chassis[1]:
            raise ValueError("fan_guard must fit inside the fan chassis width")
        if cradle[0] < 127.5 or cradle[1] < 127.5:
            raise ValueError(
                "mac_mini_cradle must provide clearance for a 127x127mm Mac mini M4"
            )
        if cradle[0] > chassis[1] + 8.0 or cradle[1] > chassis[1] + 8.0:
            raise ValueError(
                "mac_mini_cradle must remain aligned with the fan chassis"
            )


def hardware_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate hardware detections before they enter the design prompt."""
    if not isinstance(payload, dict):
        raise ValueError("hardware analysis must be a JSON object")
    components_payload = payload.get("components")
    if not isinstance(components_payload, list) or not 1 <= len(components_payload) <= 20:
        raise ValueError("hardware analysis must contain 1 to 20 components")
    allowed_categories = {
        "arduino_board",
        "esp32_board",
        "battery",
        "motor",
        "camera",
        "fan",
        "sensor",
        "microcontroller",
        "power_supply",
        "connector",
        "display",
        "speaker",
        "pcb",
        "other",
    }
    allowed_sources = {
        "visible_scale",
        "known_reference",
        "datasheet_reference",
        "user_supplied",
        "estimated",
    }
    source_kind = _string(payload.get("source_kind"), "source_kind", maximum=20)
    if source_kind not in {"photo", "schematic", "mixed"}:
        raise ValueError(f"unsupported source_kind: {source_kind}")
    components = []
    for index, item in enumerate(components_payload):
        if not isinstance(item, dict):
            raise ValueError(f"components[{index}] must be an object")
        category = _string(
            item.get("category"), f"components[{index}].category", maximum=40
        )
        dimension_source = _string(
            item.get("dimension_source"),
            f"components[{index}].dimension_source",
            maximum=40,
        )
        if category not in allowed_categories:
            raise ValueError(f"unsupported hardware category: {category}")
        if dimension_source not in allowed_sources:
            raise ValueError(f"unsupported dimension source: {dimension_source}")
        components.append(
            {
                "name": _string(
                    item.get("name"), f"components[{index}].name", maximum=100
                ),
                "category": category,
                "dimensions_mm": list(
                    _dimensions(
                        item.get("dimensions_mm"),
                        f"components[{index}].dimensions_mm",
                    )
                ),
                "confidence": _number(
                    item.get("confidence"),
                    f"components[{index}].confidence",
                    0.0,
                    1.0,
                ),
                "evidence": _string(
                    item.get("evidence"),
                    f"components[{index}].evidence",
                    maximum=300,
                ),
                "dimension_source": dimension_source,
            }
        )

    result: dict[str, Any] = {
        "source_kind": source_kind,
        "components": components,
    }
    for field in ("scene_notes", "requires_user_confirmation"):
        values = payload.get(field)
        if not isinstance(values, list) or len(values) > 12:
            raise ValueError(f"{field} must be an array of at most 12 strings")
        result[field] = [
            _string(value, f"{field}[{index}]")
            for index, value in enumerate(values)
        ]
    return result
