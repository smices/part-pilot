"""Assembly placement decisions for generated CAD parts."""

from __future__ import annotations

import cadquery as cq

from ai_cad_designer.core import CADAssembly, CADPart, create_assembly


class AssemblyAgent:
    def sensor_enclosure(self, base: CADPart, lid: CADPart) -> CADAssembly:
        base_height = float(base.metadata["dimensions_mm"][2])
        lid_wall = float(lid.metadata["wall_thickness_mm"])
        lid_location = cq.Location(
            cq.Vector(0, 0, base_height + 2 * lid_wall),
            cq.Vector(1, 0, 0),
            180.0,
        )
        return create_assembly(
            "two_piece_sensor_enclosure",
            [base, (lid, lid_location)],
        )

    def desktop_robot(self, parts: list[CADPart]) -> CADAssembly:
        by_name = {part.name: part for part in parts}
        body_length, body_width, body_height = by_name["body"].metadata[
            "dimensions_mm"
        ]
        cover_height = by_name["cover"].metadata["dimensions_mm"][2]
        return create_assembly(
            "desktop_robot_enclosure",
            [
                by_name["body"],
                (
                    by_name["cover"],
                    cq.Location(cq.Vector(0, 0, body_height + cover_height / 2)),
                ),
                (by_name["battery"], cq.Location(cq.Vector(0, 0, 3))),
                (
                    by_name["camera_mount"],
                    cq.Location(
                        cq.Vector(0, -body_width / 2, body_height * 0.66)
                    ),
                ),
            ],
        )

    def smart_fan(self, parts: list[CADPart]) -> CADAssembly:
        by_name = {part.name: part for part in parts}
        chassis = by_name["fan_chassis"]
        pod_x, pod_y, _ = chassis.metadata["controller_pod_center_mm"]
        fan_deck_height = chassis.metadata["fan_deck_height_mm"]
        shaft_x, shaft_y = by_name["power_button_plunger"].metadata[
            "shaft_center_mm"
        ]
        return create_assembly(
            "smart_fan_enclosure",
            [
                chassis,
                (
                    by_name["controller_cover"],
                    cq.Location(cq.Vector(pod_x, pod_y, 0.0)),
                ),
                (
                    by_name["fan_guard"],
                    cq.Location(
                        cq.Vector(
                            0,
                            0,
                            chassis.metadata["electronics_layer_height_mm"],
                        )
                    ),
                ),
                (
                    by_name["mac_mini_cradle"],
                    cq.Location(
                        cq.Vector(0, 0, fan_deck_height)
                    ),
                ),
                (
                    by_name["power_button_plunger"],
                    cq.Location(
                        cq.Vector(
                            float(shaft_x),
                            float(shaft_y),
                            1.0
                            + float(
                                by_name["mac_mini_cradle"].metadata[
                                    "support_pad_interface"
                                ]["installed_protrusion_mm"]
                            ),
                        ),
                        cq.Vector(0.0, 1.0, 0.0),
                        90.0,
                    ),
                ),
            ],
        )

    def smart_fan_installed(
        self,
        printable_assembly: CADAssembly,
        reference_parts: list[CADPart],
    ) -> CADAssembly:
        """Create the complete installed assembly, including all hardware."""
        printable_by_name = {
            part.name: part for part in printable_assembly.parts
        }
        cradle = printable_by_name["mac_mini_cradle"]
        cradle_translation, _ = printable_assembly.placements[
            cradle.name
        ].toTuple()
        assembly = cq.Assembly(name="smart_fan_installed_assembly")
        placements: dict[str, cq.Location] = {}

        printed_colors = {
            "fan_chassis": cq.Color(0.55, 0.74, 0.12, 1.0),
            "controller_cover": cq.Color(0.24, 0.42, 0.10, 1.0),
            "fan_guard": cq.Color(0.68, 0.52, 0.18, 1.0),
            # The cradle and chassis are the same PETG exterior skin.
            # Component identity remains available in the BOM/visibility
            # controls, while the installed material view no longer invents
            # a contrasting stacked plate that does not exist physically.
            "mac_mini_cradle": cq.Color(0.55, 0.74, 0.12, 1.0),
            "power_button_plunger": cq.Color(0.86, 0.66, 0.22, 1.0),
        }
        for part in printable_assembly.parts:
            location = printable_assembly.placements[part.name]
            assembly.add(
                part.shape,
                name=part.name,
                loc=location,
                color=printed_colors[part.name],
            )
            placements[part.name] = location

        for part in reference_parts:
            if part.name == "mac_mini_m4_fit_reference":
                location = cq.Location(
                    cq.Vector(
                        0.0,
                        0.0,
                        float(cradle_translation[2])
                        + float(
                            cradle.metadata["device_support_height_mm"]
                        ),
                    )
                )
            else:
                location = cq.Location(
                    cq.Vector(
                        *(
                            float(value)
                            for value in part.metadata["translation_mm"]
                        )
                    )
                )
            red, green, blue = (
                float(value) for value in part.metadata["color_rgb"]
            )
            assembly.add(
                part.shape,
                name=part.name,
                loc=location,
                color=cq.Color(
                    red,
                    green,
                    blue,
                    float(part.metadata["opacity"]),
                ),
            )
            placements[part.name] = location

        return CADAssembly(
            name="smart_fan_installed_assembly",
            assembly=assembly,
            parts=[*printable_assembly.parts, *reference_parts],
            placements=placements,
        )
