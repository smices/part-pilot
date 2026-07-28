"""Requirement analysis and engineering part decomposition."""

from __future__ import annotations

from ai_cad_designer.schema import (
    ComponentSpec,
    DesignBrief,
    DesignProposal,
    PartPlan,
)
from ai_cad_designer.hardware_specs import smart_fan_component_records


class DesignAgent:
    """Convert Chinese or English product intent into an auditable CAD plan."""

    COMPONENT_LIBRARY = {
        "esp32": ComponentSpec("ESP32", (55.0, 28.0, 13.0), "service"),
        "18650": ComponentSpec("18650 battery", (65.0, 18.6, 18.6), "frequent"),
        "摄像头": ComponentSpec("camera", (25.0, 25.0, 22.0), "external"),
        "camera": ComponentSpec("camera", (25.0, 25.0, 22.0), "external"),
        "风扇": ComponentSpec("fan", (40.0, 40.0, 10.0), "external"),
        "fan": ComponentSpec("fan", (40.0, 40.0, 10.0), "external"),
        "esp32-c3": ComponentSpec("ESP32-C3 Super Mini", (25.0, 22.0, 6.0), "service"),
        "ds18b20": ComponentSpec(
            "DS18B20 probe",
            (30.0, 6.0, 6.0),
            "service",
        ),
        "dc-dc": ComponentSpec("DC-DC module", (45.0, 25.0, 15.0), "service"),
        "mosfet": ComponentSpec("MOSFET PWM driver", (25.0, 15.0, 8.0), "service"),
        "120mm": ComponentSpec("120 mm fan", (120.0, 120.0, 25.0), "frequent"),
        "mac mini": ComponentSpec("Mac mini M4", (127.0, 127.0, 50.0), "frequent"),
        "sensor": ComponentSpec("sensor module", (35.0, 25.0, 12.0), "external"),
        "传感器": ComponentSpec("sensor module", (35.0, 25.0, 12.0), "external"),
    }

    def analyze(self, request: str) -> DesignBrief:
        normalized = request.lower()
        compact = (
            normalized.replace(" ", "")
            .replace("×", "x")
            .replace("*", "x")
        )
        has_120_mm_fan = (
            "fan" in normalized or "风扇" in normalized
        ) and any(
            token in compact
            for token in (
                "120mm",
                "120x120",
                "12cm",
                "12x12cm",
            )
        )
        components: list[ComponentSpec] = []
        seen: set[str] = set()
        for alias, component in self.COMPONENT_LIBRARY.items():
            if alias == "esp32" and "esp32-c3" in normalized:
                continue
            if alias in {"fan", "风扇"} and has_120_mm_fan:
                continue
            if (
                alias == "dc-dc"
                and alias in normalized
                and "12v" in normalized
                and "5v" in normalized
            ):
                for voltage in ("12V", "5V"):
                    voltage_component = ComponentSpec(
                        f"{voltage} DC-DC module",
                        component.dimensions_mm,
                        component.access,
                    )
                    components.append(voltage_component)
                    seen.add(voltage_component.name)
                continue
            alias_matches = alias in normalized or (
                alias == "120mm" and has_120_mm_fan
            )
            if alias_matches and component.name not in seen:
                components.append(component)
                seen.add(component.name)
        if not components:
            components.append(self.COMPONENT_LIBRARY["sensor"])

        if any(
            token in normalized
            for token in ("smart fan", "智能风扇", "智能散热", "散热控制器")
        ):
            product = "smart fan enclosure"
            design_family = "smart_fan"
        elif "机器人" in normalized or "robot" in normalized:
            product = "desktop robot enclosure"
            design_family = "desktop_robot"
        else:
            product = "portable sensor enclosure"
            design_family = "sensor_enclosure"
        support_strategy = self._parse_support_strategy(normalized)
        if design_family == "smart_fan" and (
            "mac mini" in normalized or "hw_smart_fan" in normalized
        ):
            components = [
                ComponentSpec(
                    record["name"],
                    record["dimensions_mm"],
                    record["access"],
                )
                for record in smart_fan_component_records()
            ]
        material = "PETG" if "petg" in normalized else "PETG"
        screwless = any(
            token in normalized
            for token in ("不用螺丝", "无螺丝", "no screw", "screwless")
        )
        removable = any(
            token in normalized for token in ("可拆卸", "removable", "serviceable")
        )
        return DesignBrief(
            request=request,
            design_family=design_family,
            product=product,
            components=tuple(components),
            material=material,
            screwless=screwless or True,
            removable=removable or True,
            support_strategy=support_strategy,
        )

    def propose(self, brief: DesignBrief) -> DesignProposal:
        if brief.product == "smart fan enclosure":
            parts = [
                PartPlan(
                    "fan_chassis",
                    "vertically stacked electronics plenum and 120 mm fan bay",
                    "dovetail",
                    (132, 132, 58),
                ),
                PartPlan(
                    "controller_cover",
                    "removable ESP32 and power electronics service cover",
                    "snap_fit",
                    (52.5, 52.5, 20),
                ),
                PartPlan(
                    "fan_guard",
                    "support-free removable airflow guard",
                    "captured_fit",
                    (124, 124, 2),
                ),
                PartPlan(
                    "mac_mini_cradle",
                    (
                        "continuous 127.5mm locating ring with a 115mm "
                        "circular bottom airflow opening"
                    ),
                    "keyed_pin_fit",
                    (134, 134, 5.5),
                ),
                PartPlan(
                    "power_button_plunger",
                    (
                        "captured vertical actuator with an integrated "
                        "rear-portal finger-lift paddle"
                    ),
                    "sliding_rail",
                    (58.75, 23.25, 34.1),
                ),
            ]
            notes = [
                "120mm fan bay uses a 120.5mm cavity and integrated retention clips.",
                "The electronics cassette sits below the fan and remains fully inside the 134mm Mac mini cradle footprint, with zero lateral accessory extension.",
                "The lower tray supports and snap-retains both DC-DC modules; the upper carrier snap-retains ESP32-C3 and the MOSFET PWM driver.",
                "The DS18B20 metal capsule snap-fits into two open-top PETG saddles on the removable carrier; the lead uses the releasable chassis strain relief.",
                "The removable bottom carrier uses eight DC-DC standoffs, four DC-DC hooks, four upper-board hooks, four lateral guides, two outer rails, and a center divider.",
                "The populated electronics carrier releases downward through the bottom opening; its 30mm service path is checked with all four retained PCBs installed.",
                "A smooth inboard USB service port supports ESP32 firmware access without removing the carrier.",
                "Twelve terminal-tool zones and eight clip-release zones define the off-chassis PCB maintenance sequence.",
                "The 120x120x25mm PWM fan is modeled at its real envelope above the electronics plenum.",
                "Mac mini M4 envelope is 127x127x50mm; the cradle uses 0.25mm clearance per side.",
                "The cradle uses a continuous rounded-square locating ring around a 115mm circular opening, matching the measured reference-3MF airflow geometry.",
                "Four locating pins, including one keyed pin, constrain the removable cradle without screws.",
                "The fan guard seats on four modeled chassis shelves, is located by four 0.25mm-clearance guide faces, and lifts out after fan removal.",
                "Four 45-degree gussets support the guard shelves and four more support the fan-clip anchors, converting floating horizontal ledges into load-bearing self-supporting ribs.",
                "Front and rear faces remain fully open for ports, power, and cable bend clearance.",
                "A rear-left enclosed access bore treats the underside power button without cutting a notch through the cradle edge.",
                "A captured 4mm PETG plunger passes through the standard fan mounting bore; its lower end is recessed 1mm above the desk plane.",
                "DS18B20 cable exit and exact power-module envelopes require user confirmation.",
                "The wiring diagram supplies electrical topology, not mechanical scale.",
                "Manufacturing gates prioritize no supports, short bridges, low PETG use, and a stable four-point Mac support path.",
            ]
        elif brief.product == "desktop robot enclosure":
            parts = [
                PartPlan("body", "structural electronics shell", "dovetail", (105, 78, 68)),
                PartPlan("cover", "removable front service cover", "snap_fit", (100, 70, 4)),
                PartPlan(
                    "battery",
                    "tool-free 18650 battery drawer",
                    "sliding_rail",
                    (74, 27, 24),
                ),
                PartPlan(
                    "camera_mount",
                    "replaceable camera angle bracket",
                    "mortise_tenon",
                    (36, 30, 18),
                ),
            ]
            notes = [
                "Fan opening is integrated into the body to avoid an extra grille part.",
                "Battery remains independently removable without opening the electronics bay.",
                "Camera mount is replaceable while preserving the front cover.",
            ]
        else:
            parts = [
                PartPlan(
                    "sensor_base",
                    "electronics tray and protective walls",
                    "snap_fit",
                    (80, 50, 20),
                ),
                PartPlan(
                    "sensor_lid",
                    "removable protective lid",
                    "snap_fit",
                    (84.5, 54.5, 10),
                ),
            ]
            notes = [
                "Four side snap beams distribute retention and permit repeated service.",
                "The lid is exported upside-down for support-free FDM printing.",
            ]
        notes.append("All mating clearances use 0.25mm per designed interface.")
        return DesignProposal(
            title=brief.product.title(),
            brief=brief,
            parts=parts,
            support_strategy=brief.support_strategy,
            engineering_notes=notes,
            planner="rules",
        )

    @staticmethod
    def _parse_support_strategy(request: str) -> str:
        """Derive support strategy from explicit user wording."""

        if any(
            token in request
            for token in (
                "no support",
                "无支撑",
                "不要支撑",
                "不用支撑",
                "不允许支撑",
                "support-free",
                "support free",
                "无支撑打印",
            )
        ):
            return "none"
        if any(
            token in request
            for token in (
                "minimal support",
                "最少支撑",
                "最小支撑",
                "尽量少支撑",
                "允许支撑",
                "允许支撑打印",
                "least support",
                "minimal",
            )
        ):
            return "minimal"
        if any(
            token in request
            for token in (
                "required support",
                "需要支撑",
                "必须支撑",
                "可以支撑",
                "允许使用支撑",
                "use support",
                "required",
            )
        ):
            return "required"
        return "minimal"
