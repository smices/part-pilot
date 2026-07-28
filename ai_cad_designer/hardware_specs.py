"""Canonical hardware envelopes for the Mac mini smart-fan product family."""

from __future__ import annotations

from typing import Any


SMART_FAN_COMPONENT_ORDER = (
    "Mac mini M4",
    "120 mm PWM fan",
    "12V DC-DC module",
    "5V DC-DC module",
    "ESP32-C3 Super Mini",
    "MOSFET PWM driver",
    "DS18B20 temperature probe",
)

SMART_FAN_DEFAULT_ENVELOPES_MM = {
    "Mac mini M4": (127.0, 127.0, 50.0),
    "120 mm PWM fan": (120.0, 120.0, 25.0),
    "12V DC-DC module": (25.0, 45.0, 15.0),
    "5V DC-DC module": (25.0, 45.0, 15.0),
    "ESP32-C3 Super Mini": (25.0, 22.0, 6.0),
    "MOSFET PWM driver": (25.0, 15.0, 8.0),
    "DS18B20 temperature probe": (30.0, 6.0, 6.0),
}

SMART_FAN_COMPONENT_ACCESS = {
    "Mac mini M4": "frequent",
    "120 mm PWM fan": "frequent",
    "12V DC-DC module": "service",
    "5V DC-DC module": "service",
    "ESP32-C3 Super Mini": "service",
    "MOSFET PWM driver": "service",
    "DS18B20 temperature probe": "service",
}


def smart_fan_component_records(
    *,
    dimensions: dict[str, tuple[float, float, float]] | None = None,
    sources: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return stable ordered BOM records with optional resolved overrides."""

    resolved_dimensions = {
        **SMART_FAN_DEFAULT_ENVELOPES_MM,
        **(dimensions or {}),
    }
    resolved_sources = sources or {}
    return [
        {
            "name": name,
            "dimensions_mm": tuple(
                float(value) for value in resolved_dimensions[name]
            ),
            "access": SMART_FAN_COMPONENT_ACCESS[name],
            "quantity": 1,
            "dimension_source": resolved_sources.get(
                name,
                "default_reference",
            ),
        }
        for name in SMART_FAN_COMPONENT_ORDER
    ]
