"""Validated mechanical inputs for a PCB enclosure design.

Coordinates use the PCB's lower-left corner: X follows board length, Y follows
board width, and Z points upward.  All measurements are millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SOURCES = {"user_measurement", "datasheet", "photo_estimate", "calibration"}


@dataclass(frozen=True)
class Measurement:
    value: float
    source: str
    confirmed: bool

    @classmethod
    def parse(cls, payload: Any, name: str) -> "Measurement":
        if not isinstance(payload, dict):
            raise ValueError(f"{name} must include value, unit, source, and confirmed")
        if payload.get("unit") != "mm":
            raise ValueError(f"{name}.unit must be mm")
        if payload.get("source") not in SOURCES:
            raise ValueError(f"{name}.source is unsupported")
        if not isinstance(payload.get("confirmed"), bool):
            raise ValueError(f"{name}.confirmed must be boolean")
        try:
            value = float(payload["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{name}.value must be numeric") from exc
        return cls(value, str(payload["source"]), payload["confirmed"])


@dataclass(frozen=True)
class Hole:
    x: Measurement
    y: Measurement
    diameter: Measurement


@dataclass(frozen=True)
class Interface:
    name: str
    face: str
    x: Measurement
    y: Measurement
    width: Measurement
    height: Measurement


@dataclass(frozen=True)
class Keepout:
    x: Measurement
    y: Measurement
    width: Measurement
    height: Measurement


@dataclass(frozen=True)
class PCBMechanicalInput:
    length: Measurement
    width: Measurement
    thickness: Measurement
    max_component_height: Measurement
    mounting_holes: tuple[Hole, ...]
    interfaces: tuple[Interface, ...]
    keepouts: tuple[Keepout, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PCBMechanicalInput":
        if not isinstance(payload, dict):
            raise ValueError("pcb input must be an object")
        scalar = lambda name: Measurement.parse(payload.get(name), name)
        holes = tuple(
            Hole(*(Measurement.parse(item.get(key), f"mounting_holes[{index}].{key}") for key in ("x", "y", "diameter")))
            for index, item in enumerate(_objects(payload.get("mounting_holes", []), "mounting_holes"))
        )
        interfaces = tuple(
            Interface(
                _name(item.get("name"), f"interfaces[{index}].name"),
                _face(item.get("face"), f"interfaces[{index}].face"),
                *(Measurement.parse(item.get(key), f"interfaces[{index}].{key}") for key in ("x", "y", "width", "height")),
            )
            for index, item in enumerate(_objects(payload.get("interfaces", []), "interfaces"))
        )
        keepouts = tuple(
            Keepout(*(Measurement.parse(item.get(key), f"keepouts[{index}].{key}") for key in ("x", "y", "width", "height")))
            for index, item in enumerate(_objects(payload.get("keepouts", []), "keepouts"))
        )
        result = cls(scalar("length"), scalar("width"), scalar("thickness"), scalar("max_component_height"), holes, interfaces, keepouts)
        result.validate()
        return result

    def pending_confirmation(self) -> list[str]:
        values = [("length", self.length), ("width", self.width), ("thickness", self.thickness), ("max_component_height", self.max_component_height)]
        values += [(f"mounting_holes[{i}].{key}", value) for i, hole in enumerate(self.mounting_holes) for key, value in (("x", hole.x), ("y", hole.y), ("diameter", hole.diameter))]
        values += [(f"interfaces[{i}].{key}", value) for i, interface in enumerate(self.interfaces) for key, value in (("x", interface.x), ("y", interface.y), ("width", interface.width), ("height", interface.height))]
        return [name for name, value in values if not value.confirmed]

    def validate(self) -> None:
        if min(self.length.value, self.width.value, self.thickness.value, self.max_component_height.value) <= 0:
            raise ValueError("PCB dimensions and component height must be positive")
        for index, hole in enumerate(self.mounting_holes):
            if hole.diameter.value <= 0 or not _inside(hole.x.value, hole.y.value, hole.diameter.value / 2, self.length.value, self.width.value):
                raise ValueError(f"mounting_holes[{index}] is outside the PCB boundary")
        for first, hole in enumerate(self.mounting_holes):
            for second in range(first + 1, len(self.mounting_holes)):
                other = self.mounting_holes[second]
                if (hole.x.value - other.x.value) ** 2 + (hole.y.value - other.y.value) ** 2 < ((hole.diameter.value + other.diameter.value) / 2) ** 2:
                    raise ValueError("mounting holes overlap")
        for index, item in enumerate(self.keepouts):
            if item.width.value <= 0 or item.height.value <= 0 or item.x.value < 0 or item.y.value < 0 or item.x.value + item.width.value > self.length.value or item.y.value + item.height.value > self.width.value:
                raise ValueError(f"feature[{index}] is outside the PCB boundary")
        for index, interface in enumerate(self.interfaces):
            if interface.width.value <= 0 or interface.height.value <= 0 or not (0 <= interface.x.value <= self.length.value and 0 <= interface.y.value <= self.width.value):
                raise ValueError(f"interfaces[{index}] is outside the PCB boundary")
            on_edge = (interface.y.value == {"front": 0.0, "rear": self.width.value}[interface.face] if interface.face in {"front", "rear"} else interface.x.value == {"left": 0.0, "right": self.length.value}[interface.face])
            if not on_edge:
                raise ValueError(f"interfaces[{index}] position does not match its face")
            span = interface.x.value if interface.face in {"front", "rear"} else interface.y.value
            limit = self.length.value if interface.face in {"front", "rear"} else self.width.value
            if span - interface.width.value / 2 < 0 or span + interface.width.value / 2 > limit:
                raise ValueError(f"interfaces[{index}] opening exceeds its PCB edge")


def _objects(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be an array of objects")
    return value


def _name(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _face(value: Any, name: str) -> str:
    if value not in {"front", "rear", "left", "right"}:
        raise ValueError(f"{name} must be front, rear, left, or right")
    return str(value)


def _inside(x: float, y: float, radius: float, length: float, width: float) -> bool:
    return radius <= x <= length - radius and radius <= y <= width - radius
