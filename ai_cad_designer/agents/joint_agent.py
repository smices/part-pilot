"""Parametric screwless joints and complete enclosure generators."""

from __future__ import annotations

import math

import cadquery as cq

from ai_cad_designer.core import CADPart, create_part, generate_joint
from ai_cad_designer.hardware_specs import SMART_FAN_DEFAULT_ENVELOPES_MM
from ai_cad_designer.pcb_input import PCBMechanicalInput


def _rounded_box(
    length_mm: float,
    width_mm: float,
    height_mm: float,
    radius_mm: float,
) -> cq.Workplane:
    shape = cq.Workplane("XY").box(
        length_mm,
        width_mm,
        height_mm,
        centered=(True, True, False),
    )
    usable_radius = min(radius_mm, length_mm / 2 - 0.1, width_mm / 2 - 0.1)
    return shape.edges("|Z").fillet(max(0.2, usable_radius))


class JointAgent:
    """Apply manufacturing-aware joints to enclosure parts."""

    def __init__(self) -> None:
        self.manufacturing_control_parts: list[CADPart] = []

    def reference_joint(self, joint_type: str, tolerance_mm: float = 0.25):
        return generate_joint(joint_type, tolerance_mm=tolerance_mm)

    def pcb_two_piece_enclosure(
        self,
        pcb: PCBMechanicalInput,
        *,
        wall_mm: float = 2.0,
        tolerance_mm: float = 0.25,
        material: str = "PETG",
    ) -> tuple[CADPart, CADPart]:
        """Create a removable enclosure whose posts and ports follow PCB input."""
        pcb.validate()
        clearance = tolerance_mm + 0.5
        length = pcb.length.value + 2 * (wall_mm + clearance)
        width = pcb.width.value + 2 * (wall_mm + clearance)
        base_height = wall_mm + pcb.thickness.value + pcb.max_component_height.value + 3.0
        base, lid = self.two_piece_snap_enclosure(
            length_mm=length, width_mm=width, base_height_mm=base_height,
            wall_mm=wall_mm, lid_height_mm=wall_mm + 6.0,
            tolerance_mm=tolerance_mm, material=material,
        )
        shape = base.shape
        for hole in pcb.mounting_holes:
            x = hole.x.value - pcb.length.value / 2
            y = hole.y.value - pcb.width.value / 2
            pin = (
                cq.Workplane("XY")
                .center(x, y)
                .circle(hole.diameter.value * 0.35)
                .extrude(wall_mm + pcb.thickness.value)
            )
            shape = shape.union(pin)
        for port in pcb.interfaces:
            z = wall_mm + pcb.thickness.value + port.height.value / 2
            if port.face in {"front", "rear"}:
                x = port.x.value - pcb.length.value / 2
                y = (-1 if port.face == "front" else 1) * width / 2
                cut = cq.Workplane("XY").box(
                    port.width.value + 2 * tolerance_mm,
                    wall_mm + 2,
                    port.height.value + 2 * tolerance_mm,
                    centered=(True, True, True),
                ).translate((x, y, z))
            else:
                x = (-1 if port.face == "left" else 1) * length / 2
                y = port.y.value - pcb.width.value / 2
                cut = cq.Workplane("XY").box(
                    wall_mm + 2,
                    port.width.value + 2 * tolerance_mm,
                    port.height.value + 2 * tolerance_mm,
                    centered=(True, True, True),
                ).translate((x, y, z))
            shape = shape.cut(cut)
        base.name = "pcb_base"
        lid.name = "pcb_lid"
        base.shape = shape
        base.metadata.update(
            {
                "pcb_input": pcb.to_dict(),
                "dimensions_mm": (length, width, base_height),
                "joint": "snap-fit PCB enclosure",
                "locator": "screwless PCB hole pins",
            }
        )
        lid.metadata["pcb_input"] = base.metadata["pcb_input"]
        return base, lid

    def mac_mini_m4_fit_reference(
        self,
        *,
        length_mm: float = 127.0,
        width_mm: float = 127.0,
        height_mm: float = 50.0,
        corner_radius_mm: float = 9.0,
        foot_outer_diameter_mm: float = 100.0,
        foot_height_mm: float = 2.0,
        power_button_x_mm: float = -49.0,
        power_button_y_mm: float = 49.0,
        power_button_diameter_mm: float = 8.0,
        front_interface_delta_x_mm: float = 0.0,
        front_interface_delta_z_mm: float = 0.0,
        rear_interface_delta_x_mm: float = 0.0,
        rear_interface_delta_z_mm: float = 0.0,
    ) -> CADPart:
        """Create a lightweight, full-scale Mac mini M4 assembly reference."""
        length = float(length_mm)
        width = float(width_mm)
        height = float(height_mm)
        wall = 2.0
        foot_height = float(foot_height_mm)
        body_height = height - foot_height
        outer = _rounded_box(
            length,
            width,
            body_height,
            corner_radius_mm,
        ).translate(
            (0.0, 0.0, foot_height)
        )
        inner = _rounded_box(
            length - 2 * wall,
            width - 2 * wall,
            body_height - wall,
            max(0.2, corner_radius_mm - wall),
        ).translate((0.0, 0.0, foot_height))
        shape = outer.cut(inner)
        # Retain the real underside landing surface outside the Ø100 foot.
        # The previous hollow-shell proxy had no material above the four
        # cradle pads, so it could visualize the envelope but could not prove
        # the physical order of contact.
        underside = (
            _rounded_box(length, width, 1.0, corner_radius_mm)
            .translate((0.0, 0.0, foot_height))
            .cut(
                cq.Workplane("XY")
                .circle(foot_outer_diameter_mm / 2)
                .extrude(1.1)
                .translate((0.0, 0.0, foot_height))
            )
        )
        shape = shape.union(underside)

        # A simplified annular bottom foot is joined to the open-bottom shell
        # by four thin radial webs. It makes the reference printable as one
        # connected fit-test object while preserving the central airflow area.
        foot_outer_radius = foot_outer_diameter_mm / 2
        foot_inner_radius = max(1.0, foot_outer_radius - 3.0)
        foot = (
            cq.Workplane("XY")
            .circle(foot_outer_radius)
            .circle(foot_inner_radius)
            .extrude(foot_height)
        )
        web_length = length / 2 - foot_outer_radius + wall
        web_center = foot_outer_radius + web_length / 2 - wall
        for angle in (0.0, 90.0, 180.0, 270.0):
            web = (
                cq.Workplane("XY")
                .box(
                    web_length,
                    3.0,
                    foot_height,
                    centered=(True, True, False),
                )
                .translate((web_center, 0.0, 0.0))
                .rotate((0, 0, 0), (0, 0, 1), angle)
            )
            shape = shape.union(web)
        shape = shape.union(foot)

        # The exact production coordinate is not published. This connected
        # shallow marker follows Apple's verified rear-left underside location
        # so the assembly preview and cradle reserve a real button interface.
        power_button_center = (
            float(power_button_x_mm),
            float(power_button_y_mm),
        )
        power_button_diameter = float(power_button_diameter_mm)
        power_button = (
            cq.Workplane("XY")
            .center(*power_button_center)
            .circle(power_button_diameter / 2)
            .extrude(foot_height)
        )
        button_web_length = length / 2 + power_button_center[0]
        button_web = (
            cq.Workplane("XY")
            .box(
                max(button_web_length + wall, wall),
                1.2,
                foot_height,
                centered=(True, True, False),
            )
            .translate(
                (
                    -length / 2
                    + max(button_web_length + wall, wall) / 2,
                    power_button_center[1],
                    0.0,
                )
            )
        )
        shape = shape.union(power_button).union(button_web)

        # Apple publishes the port types but not their mechanical coordinates.
        # These shallow, full-scale interface markers follow the official
        # front/rear grouping and remain explicitly tagged as approximate.
        front_y = -width / 2 + wall / 2
        rear_y = width / 2 - wall / 2
        interface_z = 8.0
        front_interface_z = interface_z + float(
            front_interface_delta_z_mm
        )
        rear_interface_z = interface_z + float(
            rear_interface_delta_z_mm
        )
        front_ports = (
            (
                "front_usb_c_1",
                -12.0 + float(front_interface_delta_x_mm),
                9.0,
                3.4,
                "USB-C",
            ),
            (
                "front_usb_c_2",
                2.0 + float(front_interface_delta_x_mm),
                9.0,
                3.4,
                "USB-C",
            ),
        )
        for _, x_pos, port_width, port_height, _ in front_ports:
            usb_c = (
                cq.Workplane("XY")
                .box(
                    port_width,
                    wall + 2.0,
                    port_height,
                    centered=(True, True, True),
                )
                .translate((x_pos, front_y, front_interface_z))
            )
            shape = shape.cut(usb_c)
        headphone_x = 23.0 + float(front_interface_delta_x_mm)
        headphone = (
            cq.Workplane("XZ")
            .center(headphone_x, front_interface_z)
            .circle(2.1)
            .extrude((wall + 2.0) / 2, both=True)
            .translate((0.0, front_y, 0.0))
        )
        status_led_x = 41.0 + float(front_interface_delta_x_mm)
        status_led = (
            cq.Workplane("XZ")
            .center(status_led_x, front_interface_z)
            .circle(0.9)
            .extrude((wall + 2.0) / 2, both=True)
            .translate((0.0, front_y, 0.0))
        )
        shape = shape.cut(headphone).cut(status_led)

        rear_ports = (
            ("rear_power", -48.0, 11.0, 15.0, "power"),
            ("rear_ethernet", -31.0, 15.0, 14.0, "ethernet"),
            ("rear_hdmi", -12.0, 15.0, 6.5, "HDMI"),
            ("rear_tb_1", 8.0, 9.0, 3.4, "Thunderbolt 4 USB-C"),
            ("rear_tb_2", 22.0, 9.0, 3.4, "Thunderbolt 4 USB-C"),
            ("rear_tb_3", 36.0, 9.0, 3.4, "Thunderbolt 4 USB-C"),
        )
        rear_ports = tuple(
            (
                port_id,
                x_pos + float(rear_interface_delta_x_mm),
                port_width,
                port_height,
                label,
            )
            for port_id, x_pos, port_width, port_height, label in rear_ports
        )
        for _, x_pos, port_width, port_height, _ in rear_ports:
            port = (
                cq.Workplane("XY")
                .box(
                    port_width,
                    wall + 2.0,
                    port_height,
                    centered=(True, True, True),
                )
                .translate((x_pos, rear_y, rear_interface_z))
            )
            shape = shape.cut(port)
        interface_markers = [
            {
                "id": port_id,
                "label": label,
                "face": "front",
                "center_x_mm": x_pos,
                "center_z_mm": front_interface_z,
                "opening_width_mm": port_width,
                "opening_height_mm": port_height,
            }
            for port_id, x_pos, port_width, port_height, label in front_ports
        ]
        interface_markers.append(
            {
                "id": "front_headphone",
                "label": "3.5 mm headphone",
                "face": "front",
                "center_x_mm": headphone_x,
                "center_z_mm": front_interface_z,
                "opening_width_mm": 4.2,
                "opening_height_mm": 4.2,
            }
        )
        interface_markers.extend(
            {
                "id": port_id,
                "label": label,
                "face": "rear",
                "center_x_mm": x_pos,
                "center_z_mm": rear_interface_z,
                "opening_width_mm": port_width,
                "opening_height_mm": port_height,
            }
            for port_id, x_pos, port_width, port_height, label in rear_ports
        )
        return CADPart(
            "mac_mini_m4_fit_reference",
            shape,
            {
                "dimensions_mm": (length, width, height),
                "engineering_parameters": {
                    "mac_length_mm": length,
                    "mac_width_mm": width,
                    "mac_height_mm": height,
                    "mac_corner_radius_mm": float(corner_radius_mm),
                    "mac_foot_outer_diameter_mm": float(
                        foot_outer_diameter_mm
                    ),
                    "mac_foot_height_mm": foot_height,
                    "power_button_x_mm": power_button_center[0],
                    "power_button_y_mm": power_button_center[1],
                    "power_button_diameter_mm": power_button_diameter,
                },
                "wall_thickness_mm": wall,
                "material": "REFERENCE_ONLY",
                "is_reference": True,
                "reference_kind": "device",
                "opacity": 0.34,
                "color_rgb": (0.52, 0.56, 0.58),
                "device": "Apple Mac mini M4",
                "foot_ring_mm": (
                    2 * foot_outer_radius,
                    2 * foot_inner_radius,
                    foot_height,
                ),
                "underside_landing_surface": {
                    "modeled_as_geometry": True,
                    "z_mm": foot_height,
                    "central_foot_keepout_diameter_mm": (
                        2 * foot_outer_radius
                    ),
                },
                "power_button_reference": {
                    "center_mm": power_button_center,
                    "diameter_mm": power_button_diameter,
                    "face": "bottom",
                    "location": "rear-left when viewed from the front",
                    "coordinate_accuracy": "approximate; verify on hardware",
                },
                "purpose": (
                    "full-scale assembly visualization and optional fit test"
                ),
                "accuracy_note": (
                    "127 x 127 x 50 mm envelope is authoritative for this "
                    "project; bottom foot and port coordinates remain "
                    "simplified and require physical measurement"
                ),
                "official_interface_inventory": {
                    "front": (
                        "2 x USB-C",
                        "3.5 mm headphone",
                        "status LED",
                    ),
                    "rear": (
                        "power",
                        "Gigabit Ethernet",
                        "HDMI",
                        "3 x Thunderbolt 4 USB-C",
                    ),
                    "bottom": ("power button", "ventilation through foot"),
                    "source": "Apple Mac mini M4 support and specifications",
                },
                "interface_marker_accuracy": "type verified; position approximate",
                "interface_coordinate_offsets_mm": {
                    "front": [
                        float(front_interface_delta_x_mm),
                        float(front_interface_delta_z_mm),
                    ],
                    "rear": [
                        float(rear_interface_delta_x_mm),
                        float(rear_interface_delta_z_mm),
                    ],
                    "source": (
                        "default_reference until the flat I/O alignment "
                        "gauges are measured"
                    ),
                },
                "interface_markers": interface_markers,
                "service_corridor": {
                    "external_depth_mm": 25.0,
                    "insertion_depth_mm": 3.0,
                    "lateral_clearance_per_side_mm": 2.0,
                    "vertical_clearance_per_side_mm": 2.0,
                    "coordinate_system": (
                        "Mac reference local coordinates; front is -Y, "
                        "rear is +Y, Z=0 is the bottom of the foot"
                    ),
                },
                "print_orientation": "top face on build plate",
                "support_strategy": "none",
            },
        )

    def smart_fan_hardware_reference_parts(
        self,
        chassis: CADPart,
        cradle: CADPart | None = None,
    ) -> list[CADPart]:
        """Create exportable CAD references for every installed component."""
        items = {
            item["name"]: item
            for item in chassis.metadata["hardware_references"]
        }

        def metadata_for(
            safe_name: str,
            display_name: str,
        ) -> dict[str, object]:
            item = items[display_name]
            return {
                "dimensions_mm": tuple(item["dimensions_mm"]),
                "material": "REFERENCE_ONLY",
                "is_reference": True,
                "reference_kind": "internal_hardware",
                "display_name": display_name,
                "translation_mm": tuple(item["translation_mm"]),
                "rotation_deg": (0.0, 0.0, 0.0),
                "color_rgb": tuple(item["color_rgb"]),
                "opacity": float(item.get("opacity", 0.46)),
                "source_name": safe_name,
                "support_strategy": "reference only; not a production print",
            }

        fan_item = items["120 mm PWM fan"]
        fan_length, fan_width, fan_height = (
            float(value) for value in fan_item["dimensions_mm"]
        )
        fan_shape = _rounded_box(
            fan_length,
            fan_width,
            fan_height,
            4.0,
        ).cut(
            cq.Workplane("XY").circle(55.0).extrude(fan_height)
        )
        fan_mount = chassis.metadata["fan_mount_interface"]
        for x_pos, y_pos in fan_mount["positions_mm"]:
            hole = (
                cq.Workplane("XY")
                .center(x_pos, y_pos)
                .circle(float(fan_mount["hole_diameter_mm"]) / 2)
                .extrude(fan_height + 1.0)
            )
            fan_shape = fan_shape.cut(hole)
        hub = cq.Workplane("XY").circle(18.0).extrude(fan_height)
        fan_shape = fan_shape.union(hub)
        for angle in (45.0, 135.0, 225.0, 315.0):
            strut = (
                cq.Workplane("XY")
                .box(42.0, 3.0, 3.0, centered=(True, True, False))
                .translate((37.0, 0.0, 2.0))
                .rotate((0, 0, 0), (0, 0, 1), angle)
            )
            fan_shape = fan_shape.union(strut)
        for index in range(7):
            blade = (
                cq.Workplane("XY")
                .box(39.0, 8.0, 2.4, centered=(True, True, False))
                .translate((36.5, 0.0, fan_height / 2 - 1.2))
                .rotate(
                    (0, 0, 0),
                    (0, 0, 1),
                    index * 360.0 / 7.0 + 12.0,
                )
            )
            fan_shape = fan_shape.union(blade)
        references = [
            CADPart(
                "pwm_fan_120mm_reference",
                fan_shape,
                metadata_for(
                    "pwm_fan_120mm_reference",
                    "120 mm PWM fan",
                ),
            )
        ]

        def dc_dc_reference(
            safe_name: str,
            display_name: str,
        ) -> CADPart:
            length, width, height = (
                float(value)
                for value in items[display_name]["dimensions_mm"]
            )
            shape = cq.Workplane("XY").box(
                length,
                width,
                1.6,
                centered=(True, True, False),
            )
            for y_pos in (-width / 2 + 3.0, width / 2 - 3.0):
                terminal = (
                    cq.Workplane("XY")
                    .box(
                        length - 5.0,
                        6.0,
                        min(8.0, height - 1.6),
                        centered=(True, True, False),
                    )
                    .translate((0.0, y_pos, 1.6))
                )
                shape = shape.union(terminal)
            inductor = (
                cq.Workplane("XY")
                .center(-4.0, 0.0)
                .circle(5.5)
                .extrude(min(10.0, height - 1.6))
                .translate((0.0, 0.0, 1.6))
            )
            capacitor = (
                cq.Workplane("XY")
                .center(7.0, 0.0)
                .circle(3.0)
                .extrude(height - 1.6)
                .translate((0.0, 0.0, 1.6))
            )
            return CADPart(
                safe_name,
                shape.union(inductor).union(capacitor),
                metadata_for(safe_name, display_name),
            )

        references.extend(
            [
                dc_dc_reference(
                    "dc_dc_12v_reference",
                    "12V DC-DC module",
                ),
                dc_dc_reference(
                    "dc_dc_5v_reference",
                    "5V DC-DC module",
                ),
            ]
        )

        esp_name = "ESP32-C3 Super Mini"
        esp_length, esp_width, _ = (
            float(value) for value in items[esp_name]["dimensions_mm"]
        )
        esp_shape = cq.Workplane("XY").box(
            esp_length,
            esp_width,
            1.2,
            centered=(True, True, False),
        )
        esp_module = (
            cq.Workplane("XY")
            .box(14.0, 16.0, 2.2, centered=(True, True, False))
            .translate((1.5, 0.0, 1.2))
        )
        esp_keepout = (
            cq.Workplane("XY")
            .box(8.0, 8.0, 4.8, centered=(True, True, False))
            .translate((3.0, 0.0, 1.2))
        )
        esp_usb = (
            cq.Workplane("XY")
            .box(6.0, 7.0, 3.4, centered=(True, True, False))
            .translate((-esp_length / 2 + 3.0, 0.0, 1.2))
        )
        references.append(
            CADPart(
                "esp32_c3_super_mini_reference",
                esp_shape.union(esp_module).union(esp_keepout).union(esp_usb),
                metadata_for(
                    "esp32_c3_super_mini_reference",
                    esp_name,
                ),
            )
        )

        mosfet_name = "MOSFET PWM driver"
        mosfet_length, mosfet_width, mosfet_height = (
            float(value) for value in items[mosfet_name]["dimensions_mm"]
        )
        mosfet_shape = cq.Workplane("XY").box(
            mosfet_length,
            mosfet_width,
            1.6,
            centered=(True, True, False),
        )
        for x_pos in (-mosfet_length / 2 + 3.0, mosfet_length / 2 - 3.0):
            terminal = (
                cq.Workplane("XY")
                .box(6.0, mosfet_width - 3.0, 5.0, centered=(True, True, False))
                .translate((x_pos, 0.0, 1.6))
            )
            mosfet_shape = mosfet_shape.union(terminal)
        heatsink = (
            cq.Workplane("XY")
            .box(
                9.0,
                8.0,
                mosfet_height - 1.6,
                centered=(True, True, False),
            )
            .translate((0.0, 0.0, 1.6))
        )
        references.append(
            CADPart(
                "mosfet_pwm_driver_reference",
                mosfet_shape.union(heatsink),
                metadata_for(
                    "mosfet_pwm_driver_reference",
                    mosfet_name,
                ),
            )
        )

        probe_item = next(
            item
            for item in items.values()
            if str(item["name"]).startswith("DS18B20")
        )
        probe_diameter = float(probe_item["dimensions_mm"][1])
        probe_name = str(probe_item["name"])
        probe = (
            cq.Workplane("YZ")
            .circle(probe_diameter / 2)
            .extrude(20.0)
            .translate((-15.0, 0.0, 0.0))
        )
        lead = (
            cq.Workplane("YZ")
            .circle(1.2)
            .extrude(10.0)
            .translate((5.0, 0.0, 0.0))
        )
        references.append(
            CADPart(
                "ds18b20_probe_reference",
                probe.union(lead),
                metadata_for(
                    "ds18b20_probe_reference",
                    probe_name,
                ),
            )
        )

        isolation = chassis.metadata["fan_mount_interface"]
        isolator_outer_diameter = float(
            isolation["isolator_pocket_diameter_mm"]
        )
        isolator_inner_diameter = float(isolation["hole_diameter_mm"])
        isolator_installed_thickness = float(
            isolation["isolator_installed_thickness_mm"]
        )
        isolator_nominal_thickness = float(
            isolation["isolator_nominal_thickness_mm"]
        )
        fan_bottom_z = float(fan_item["translation_mm"][2])
        isolator_base_z = fan_bottom_z - isolator_installed_thickness
        isolator_shape = (
            cq.Workplane("XY")
            .circle(isolator_outer_diameter / 2)
            .circle(isolator_inner_diameter / 2)
            .extrude(isolator_installed_thickness)
        )
        for index, (x_pos, y_pos) in enumerate(
            isolation["positions_mm"],
            start=1,
        ):
            safe_name = f"fan_isolator_{index}_reference"
            references.append(
                CADPart(
                    safe_name,
                    isolator_shape,
                    {
                        "dimensions_mm": (
                            isolator_outer_diameter,
                            isolator_outer_diameter,
                            isolator_installed_thickness,
                        ),
                        "material": "SILICONE_REFERENCE",
                        "is_reference": True,
                        "reference_kind": "service_hardware",
                        "display_name": (
                            f"Fan isolator {index} · silicone "
                            "10×4.6×1.5 mm"
                        ),
                        "translation_mm": (
                            float(x_pos),
                            float(y_pos),
                            isolator_base_z,
                        ),
                        "rotation_deg": (0.0, 0.0, 0.0),
                        "color_rgb": (0.25, 0.78, 0.86),
                        "opacity": 0.72,
                        "source_name": safe_name,
                        "outer_diameter_mm": isolator_outer_diameter,
                        "inner_diameter_mm": isolator_inner_diameter,
                        "nominal_thickness_mm": (
                            isolator_nominal_thickness
                        ),
                        "installed_thickness_mm": (
                            isolator_installed_thickness
                        ),
                        "compression_mm": float(
                            isolation["isolator_compression_mm"]
                        ),
                        "compression_ratio": float(
                            isolation["isolator_compression_ratio"]
                        ),
                        "support_strategy": (
                            "purchased elastomer; not a production print"
                        ),
                    },
                )
            )
        if cradle is not None:
            contact = cradle.metadata["support_pad_interface"]
            pad_diameter = float(contact["pad_diameter_mm"])
            pad_thickness = float(
                contact["installed_pad_thickness_mm"]
            )
            pad_base_z = (
                float(chassis.metadata["fan_deck_height_mm"])
                + float(contact["installed_pad_base_z_mm"])
            )
            pad_shape = (
                cq.Workplane("XY")
                .circle(pad_diameter / 2)
                .extrude(pad_thickness)
            )
            for index, (x_pos, y_pos) in enumerate(
                contact["positions_mm"],
                start=1,
            ):
                safe_name = f"mac_support_pad_{index}_reference"
                references.append(
                    CADPart(
                        safe_name,
                        pad_shape,
                        {
                            "dimensions_mm": (
                                pad_diameter,
                                pad_diameter,
                                pad_thickness,
                            ),
                            "material": "SILICONE_REFERENCE",
                            "is_reference": True,
                            "reference_kind": "contact_hardware",
                            "display_name": (
                                f"Mac support pad {index} · silicone "
                                "Ø8×0.5 mm"
                            ),
                            "translation_mm": (
                                float(x_pos),
                                float(y_pos),
                                pad_base_z,
                            ),
                            "rotation_deg": (0.0, 0.0, 0.0),
                            "color_rgb": (0.96, 0.43, 0.20),
                            "opacity": 0.88,
                            "source_name": safe_name,
                            "installed_protrusion_mm": float(
                                contact["installed_protrusion_mm"]
                            ),
                            "recess_diameter_mm": float(
                                contact["recess_diameter_mm"]
                            ),
                            "support_strategy": (
                                "purchased adhesive silicone contact pad; "
                                "not a production print"
                            ),
                        },
                    )
                )
        desk_contact = chassis.metadata["desk_pad_interface"]
        desk_pad_diameter = float(desk_contact["pad_diameter_mm"])
        desk_pad_thickness = float(
            desk_contact["installed_pad_thickness_mm"]
        )
        desk_pad_shape = (
            cq.Workplane("XY")
            .circle(desk_pad_diameter / 2)
            .extrude(desk_pad_thickness)
        )
        for index, (x_pos, y_pos) in enumerate(
            desk_contact["positions_mm"],
            start=1,
        ):
            safe_name = f"desk_isolation_pad_{index}_reference"
            references.append(
                CADPart(
                    safe_name,
                    desk_pad_shape,
                    {
                        "dimensions_mm": (
                            desk_pad_diameter,
                            desk_pad_diameter,
                            desk_pad_thickness,
                        ),
                        "material": "SILICONE_REFERENCE",
                        "is_reference": True,
                        "reference_kind": "desk_contact_hardware",
                        "display_name": (
                            f"Desk isolation pad {index} · silicone "
                            "Ø6×1.5 mm"
                        ),
                        "translation_mm": (
                            float(x_pos),
                            float(y_pos),
                            -desk_pad_thickness,
                        ),
                        "rotation_deg": (0.0, 0.0, 0.0),
                        "color_rgb": (0.28, 0.34, 0.38),
                        "opacity": 0.9,
                        "source_name": safe_name,
                        "attachment": desk_contact["attachment"],
                        "support_strategy": (
                            "purchased adhesive silicone desk pad; "
                            "not a production print"
                        ),
                    },
                )
            )
        return references

    def two_piece_snap_enclosure(
        self,
        *,
        length_mm: float = 80.0,
        width_mm: float = 50.0,
        base_height_mm: float = 20.0,
        wall_mm: float = 2.0,
        lid_wall_mm: float = 2.0,
        lid_height_mm: float = 10.0,
        tolerance_mm: float = 0.25,
        material: str = "PETG",
    ) -> tuple[CADPart, CADPart]:
        base = create_part(
            "sensor_base",
            (length_mm, width_mm, base_height_mm),
            wall_thickness_mm=wall_mm,
            open_top=True,
            material=material,
        )
        tab_centers = (-length_mm * 0.28, length_mm * 0.28)
        beam_width = 10.0
        relief_width = 1.0
        beam_bottom = 7.0
        hook_bottom = base_height_mm - 4.0

        shape = base.shape
        for side in (-1, 1):
            side_y = side * width_mm / 2
            for x_center in tab_centers:
                for x_cut in (
                    x_center - beam_width / 2 - relief_width / 2,
                    x_center + beam_width / 2 + relief_width / 2,
                ):
                    relief = (
                        cq.Workplane("XY")
                        .box(
                            relief_width,
                            wall_mm + 1.2,
                            base_height_mm - beam_bottom,
                            centered=(True, True, False),
                        )
                        .translate((x_cut, side_y, beam_bottom))
                    )
                    shape = shape.cut(relief)
                hook_y = side * (width_mm / 2 + 0.6)
                hook = (
                    cq.Workplane("XY")
                    .box(beam_width, 1.2, 2.0, centered=(True, True, False))
                    .translate((x_center, hook_y, hook_bottom))
                )
                shape = shape.union(hook)

        base.shape = shape
        base.metadata.update(
            {
                "joint": "four cantilever snap hooks",
                "tolerance_mm": tolerance_mm,
                "print_orientation": "floor on build plate",
                "support_strategy": "none",
            }
        )

        inner_length = length_mm + 2 * tolerance_mm
        inner_width = width_mm + 2 * tolerance_mm
        lid_length = inner_length + 2 * lid_wall_mm
        lid_width = inner_width + 2 * lid_wall_mm
        lid_outer = cq.Workplane("XY").box(
            lid_length, lid_width, lid_height_mm, centered=(True, True, False)
        )
        lid_cavity = (
            cq.Workplane("XY")
            .box(
                inner_length,
                inner_width,
                lid_height_mm - lid_wall_mm,
                centered=(True, True, False),
            )
            .translate((0, 0, lid_wall_mm))
        )
        lid_shape = lid_outer.cut(lid_cavity)

        slot_width = beam_width + 2 * tolerance_mm
        slot_height = 2.0 + 2 * tolerance_mm
        slot_center_z = 6.0
        for side in (-1, 1):
            for x_center in tab_centers:
                slot = (
                    cq.Workplane("XY")
                    .box(
                        slot_width,
                        lid_wall_mm + 1.0,
                        slot_height,
                        centered=(True, True, True),
                    )
                    .translate((x_center, side * lid_width / 2, slot_center_z))
                )
                lid_shape = lid_shape.cut(slot)

        lid = CADPart(
            "sensor_lid",
            lid_shape,
            {
                "dimensions_mm": (lid_length, lid_width, lid_height_mm),
                "wall_thickness_mm": lid_wall_mm,
                "material": material,
                "joint": "snap receiving windows",
                "tolerance_mm": tolerance_mm,
                "print_orientation": "outer roof on build plate",
                "support_strategy": "none",
            },
        )
        return base, lid

    def desktop_robot_parts(
        self,
        *,
        wall_mm: float = 2.5,
        tolerance_mm: float = 0.25,
        dimensions: dict[str, tuple[float, float, float]] | None = None,
    ) -> list[CADPart]:
        dimensions = dimensions or {
            "body": (105.0, 78.0, 68.0),
            "cover": (100.0, 70.0, 4.0),
            "battery": (74.0, 27.0, 24.0),
            "camera_mount": (36.0, 30.0, 18.0),
        }
        body_length, body_width, body_height = dimensions["body"]
        cover_length, cover_width, cover_height = dimensions["cover"]
        battery_length, battery_width, battery_height = dimensions["battery"]
        camera_length, camera_width, _ = dimensions["camera_mount"]
        body = create_part(
            "body",
            (body_length, body_width, body_height),
            wall_thickness_mm=wall_mm,
            open_top=True,
        )
        body.metadata.update(
            {
                "joint": "integrated dovetail service edge",
                "tolerance_mm": tolerance_mm,
                "print_orientation": "base down",
                "support_strategy": "minimal",
            }
        )
        rail = self.reference_joint("dovetail", tolerance_mm=tolerance_mm).male.shape
        body.shape = body.shape.union(
            rail.translate(
                (
                    -body_length / 2 + 14.0,
                    -body_width / 2 + 9.0,
                    wall_mm,
                )
            )
        )

        cover = CADPart(
            "cover",
            cq.Workplane("XY").box(
                cover_length,
                cover_width,
                cover_height,
                centered=(True, True, False),
            ),
            {
                "dimensions_mm": (cover_length, cover_width, cover_height),
                "wall_thickness_mm": wall_mm,
                "material": "PETG",
                "joint": "snap_fit",
                "tolerance_mm": tolerance_mm,
                "print_orientation": "flat",
                "support_strategy": "none",
            },
        )
        for x_pos in (-cover_length * 0.35, cover_length * 0.35):
            tab = (
                cq.Workplane("XY")
                .box(10.0, 2.5, 8.0, centered=(True, True, False))
                .translate((x_pos, -cover_width / 2 + 1.25, cover_height))
            )
            cover.shape = cover.shape.union(tab)

        battery = create_part(
            "battery",
            (battery_length, battery_width, battery_height),
            wall_thickness_mm=wall_mm,
            open_top=True,
        )
        battery.metadata.update(
            {
                "joint": "sliding_rail",
                "tolerance_mm": tolerance_mm,
                "print_orientation": "tray down",
                "support_strategy": "none",
            }
        )
        for side in (-1, 1):
            rib = (
                cq.Workplane("XY")
                .box(
                    max(4.0, battery_length - 9.0),
                    1.5,
                    1.5,
                    centered=(True, True, False),
                )
                .translate((0, side * battery_width / 2, wall_mm + 1.5))
            )
            battery.shape = battery.shape.union(rib)

        camera_mount = CADPart(
            "camera_mount",
            cq.Workplane("XY")
            .box(camera_length, camera_width, wall_mm, centered=(True, True, False))
            .faces(">Z")
            .workplane()
            .circle(8.5)
            .cutThruAll(),
            {
                "dimensions_mm": (camera_length, camera_width, wall_mm),
                "wall_thickness_mm": wall_mm,
                "material": "PETG",
                "joint": "mortise_tenon",
                "tolerance_mm": tolerance_mm,
                "print_orientation": "flat",
                "support_strategy": "none",
            },
        )
        tenon = (
            cq.Workplane("XY")
            .box(12.0, 5.0, 4.0, centered=(True, True, False))
            .translate((0, -camera_width / 2 - 2.5, 0))
        )
        camera_mount.shape = camera_mount.shape.union(tenon)
        return [body, cover, battery, camera_mount]

    def smart_fan_parts(
        self,
        *,
        wall_mm: float = 2.5,
        tolerance_mm: float = 0.25,
        material: str = "PETG",
        dimensions: dict[str, tuple[float, float, float]] | None = None,
        engineering_parameters: dict[str, object] | None = None,
    ) -> list[CADPart]:
        """Build a screwless 120 mm fan chassis with a serviceable control pod."""
        self.manufacturing_control_parts = []
        dimensions = dimensions or {
            "fan_chassis": (132.0, 132.0, 58.0),
            "controller_cover": (52.5, 52.5, 20.0),
            "fan_guard": (124.0, 124.0, 2.0),
            "mac_mini_cradle": (134.0, 134.0, 5.5),
            "power_button_plunger": (58.75, 23.25, 34.1),
        }
        chassis_length, chassis_width, chassis_height = dimensions["fan_chassis"]
        cover_length, cover_width, cover_height = dimensions["controller_cover"]
        guard_length, guard_width, guard_height = dimensions["fan_guard"]
        cradle_length, cradle_width, cradle_height = dimensions[
            "mac_mini_cradle"
        ]
        plunger_length, plunger_width, plunger_height = dimensions[
            "power_button_plunger"
        ]

        parameter_defaults = {
            "mac_length_mm": 127.0,
            "mac_width_mm": 127.0,
            "mac_height_mm": 50.0,
            "mac_corner_radius_mm": 9.0,
            "mac_foot_outer_diameter_mm": 100.0,
            "mac_foot_height_mm": 2.0,
            "mac_design_mass_kg": 1.0,
            "power_button_x_mm": -49.0,
            "power_button_y_mm": 49.0,
            "power_button_diameter_mm": 8.0,
            "front_interface_delta_x_mm": 0.0,
            "front_interface_delta_z_mm": 0.0,
            "rear_interface_delta_x_mm": 0.0,
            "rear_interface_delta_z_mm": 0.0,
            "fan_size_mm": 120.0,
            "fan_thickness_mm": 25.0,
            "fan_mount_spacing_mm": 105.0,
            "fan_mount_hole_diameter_mm": 4.6,
            "ds18b20_probe_diameter_mm": 6.0,
            "ds18b20_snap_interference_per_side_mm": 0.1,
        }
        parameter_ranges = {
            "mac_length_mm": (125.0, 130.0),
            "mac_width_mm": (125.0, 130.0),
            "mac_height_mm": (48.0, 53.0),
            "mac_corner_radius_mm": (7.0, 12.0),
            "mac_foot_outer_diameter_mm": (96.0, 101.0),
            "mac_foot_height_mm": (1.0, 3.0),
            "mac_design_mass_kg": (0.5, 2.0),
            "power_button_x_mm": (-53.0, -45.0),
            "power_button_y_mm": (45.0, 53.0),
            "power_button_diameter_mm": (6.0, 10.0),
            "front_interface_delta_x_mm": (-5.0, 5.0),
            "front_interface_delta_z_mm": (-5.0, 5.0),
            "rear_interface_delta_x_mm": (-5.0, 5.0),
            "rear_interface_delta_z_mm": (-5.0, 5.0),
            "fan_size_mm": (119.0, 121.0),
            "fan_thickness_mm": (20.0, 27.0),
            "fan_mount_spacing_mm": (104.0, 106.0),
            "fan_mount_hole_diameter_mm": (4.0, 5.2),
            "ds18b20_probe_diameter_mm": (5.5, 6.5),
            "ds18b20_snap_interference_per_side_mm": (0.02, 0.25),
        }
        raw_parameters = engineering_parameters or {}
        resolved_parameters: dict[str, float] = {}
        parameter_sources: dict[str, str] = {}
        for name, default in parameter_defaults.items():
            raw_value = raw_parameters.get(name, default)
            source = (
                str(raw_value.get("source", "user_supplied"))
                if isinstance(raw_value, dict)
                else (
                    "default_reference"
                    if name not in raw_parameters
                    else "user_supplied"
                )
            )
            value = (
                raw_value.get("value", default)
                if isinstance(raw_value, dict)
                else raw_value
            )
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"engineering parameter {name} must be numeric"
                ) from exc
            minimum, maximum = parameter_ranges[name]
            if not minimum <= numeric <= maximum:
                raise ValueError(
                    f"engineering parameter {name} must be between "
                    f"{minimum:g} and {maximum:g} "
                    f"{'kg' if name == 'mac_design_mass_kg' else 'mm'}"
                )
            resolved_parameters[name] = numeric
            parameter_sources[name] = source

        mac_length = resolved_parameters["mac_length_mm"]
        mac_width = resolved_parameters["mac_width_mm"]
        mac_height = resolved_parameters["mac_height_mm"]
        mac_corner_radius = resolved_parameters["mac_corner_radius_mm"]
        mac_foot_outer_diameter = resolved_parameters[
            "mac_foot_outer_diameter_mm"
        ]
        mac_foot_height = resolved_parameters["mac_foot_height_mm"]
        power_button_center_parameter = (
            resolved_parameters["power_button_x_mm"],
            resolved_parameters["power_button_y_mm"],
        )
        power_button_diameter_parameter = resolved_parameters[
            "power_button_diameter_mm"
        ]

        fan_size = resolved_parameters["fan_size_mm"]
        fan_installed_height_parameter = resolved_parameters[
            "fan_thickness_mm"
        ]
        fan_clearance = fan_size + 2 * tolerance_mm
        frame_outer = max(126.0, chassis_width)
        plenum_inner = frame_outer - 2 * wall_mm
        electronics_layer_height = 29.0
        fan_deck_height = (
            electronics_layer_height
            + wall_mm
            + fan_installed_height_parameter
            + 1.5
        )
        fan_depth = fan_deck_height - wall_mm
        aperture_width = 118.0
        pod_length = 60.0
        pod_width = 58.0
        pod_height = electronics_layer_height
        pod_frame_overlap = 8.0
        pod_x = frame_outer / 2 - pod_length / 2
        pod_y = frame_outer / 2 - pod_width / 2
        cover_plate_height = min(3.4, cover_height)
        desk_load_island_center = (63.0, 63.0)
        desk_load_island_radius = 3.3
        desk_load_island_clearance_radius = (
            desk_load_island_radius + tolerance_mm
        )
        controller_side_rail_thickness = 1.2
        controller_board_outer_edge = 26.0
        controller_side_rail_inner_face = (
            controller_board_outer_edge + tolerance_mm
        )
        controller_side_rail_center = (
            controller_side_rail_inner_face
            + controller_side_rail_thickness / 2
        )
        controller_carrier_outer_span = 2 * (
            controller_side_rail_center
            + controller_side_rail_thickness / 2
        )
        controller_service_opening_length = (
            controller_carrier_outer_span + 2 * tolerance_mm
        )
        controller_service_corner_radius = 3.0
        snap_tab_length = 10.0
        snap_tab_thickness = 1.3
        snap_tab_width = 10.0
        snap_hook_extension = 0.75
        snap_hook_height = 1.6
        snap_required_deflection = snap_hook_extension
        snap_nominal_strain = (
            1.5
            * snap_tab_thickness
            * snap_required_deflection
            / snap_tab_length**2
        )
        snap_tab_y_positions = (-10.0, 10.0)

        base_ring = _rounded_box(
            frame_outer,
            frame_outer,
            wall_mm,
            12.0,
        ).cut(
            _rounded_box(
                aperture_width,
                aperture_width,
                wall_mm + 1.0,
                7.0,
            )
        )
        wall_outer = _rounded_box(
            frame_outer,
            frame_outer,
            fan_depth,
            14.0,
        )
        chassis_top_edge_radius = 2.0
        wall_outer = (
            wall_outer.edges(">Z")
            .fillet(chassis_top_edge_radius)
            .translate((0, 0, wall_mm))
        )
        wall_inner = _rounded_box(
            plenum_inner,
            plenum_inner,
            fan_depth + 1.0,
            5.0,
        ).translate((0, 0, wall_mm))
        exterior_wall_shell = wall_outer.cut(wall_inner)
        chassis_shape = base_ring.union(exterior_wall_shell)

        # V92 removes the remaining "plate stacked on a box" seam seen in
        # orthographic assembly views.  The chassis body stays at 132 mm for
        # material economy, then expands through one continuous 3 mm crown to
        # the cradle's rolled lower footprint.  A 0.4 mm lower-edge roll on
        # the removable cradle leaves a 133.2 mm mating silhouette, so the
        # two printed parts meet without a visible ledge while the installed
        # product remains inside the existing 134 mm envelope.
        #
        # Keep the nominal rolled silhouette stable, but shape the crown and
        # cradle as a smooth convex bridge to avoid stepped silhouette artifacts
        # in perspective/orthographic seam views.
        chassis_cradle_seam_roll_radius = 0.4
        chassis_crown_height = 3.0
        chassis_crown_bottom_z = (
            fan_deck_height - chassis_crown_height
        )
        chassis_crown_bottom_outer = frame_outer
        # Keep the mating footprint identical to the reference 133.2 mm target.
        chassis_crown_top_outer = 133.2
        chassis_crown_overhang_per_side = (
            chassis_crown_top_outer - chassis_crown_bottom_outer
        ) / 2
        chassis_crown_slope_from_horizontal_deg = math.degrees(
            math.atan2(
                chassis_crown_height,
                chassis_crown_overhang_per_side,
            )
        )
        def rounded_square_wire(
            size: float,
            radius: float,
            z_position: float,
        ) -> cq.Wire:
            wire = cq.Workplane("XY").rect(size, size).val()
            return wire.fillet2D(
                radius,
                wire.Vertices(),
            ).moved(
                cq.Location(
                    cq.Vector(0.0, 0.0, z_position)
                )
            )

        def rounded_square_wire_frame(
            size: float,
            radius: float,
            z_position: float,
        ) -> cq.Wire:
            wire = cq.Workplane("XY").square(size, centered=True).val()
            return wire.fillet2D(
                radius,
                wire.Vertices(),
            ).moved(
                cq.Location(
                    cq.Vector(0.0, 0.0, z_position)
                )
            )

        chassis_crown_outer = (
            cq.Workplane("XY")
            .add(
                rounded_square_wire(
                    chassis_crown_bottom_outer,
                    14.0,
                    chassis_crown_bottom_z,
                )
            )
            .add(
                rounded_square_wire(
                    chassis_crown_top_outer,
                    14.0,
                    fan_deck_height,
                )
            )
            .toPending()
            .loft(combine=False)
        )
        chassis_crown_inner_bottom = plenum_inner
        chassis_crown_minimum_wall = 2.0
        chassis_crown_inner_top = (
            chassis_crown_top_outer
            - 2 * chassis_crown_minimum_wall
        )
        chassis_crown_inner_overcut = 0.1
        chassis_crown_inner_growth_per_mm = (
            chassis_crown_inner_top
            - chassis_crown_inner_bottom
        ) / chassis_crown_height
        chassis_crown_inner = (
            cq.Workplane("XY")
            .add(
                rounded_square_wire(
                    chassis_crown_inner_bottom
                    - (
                        chassis_crown_inner_growth_per_mm
                        * chassis_crown_inner_overcut
                    ),
                    5.0,
                    chassis_crown_bottom_z
                    - chassis_crown_inner_overcut,
                )
            )
            .add(
                rounded_square_wire(
                    chassis_crown_inner_top
                    + (
                        chassis_crown_inner_growth_per_mm
                        * chassis_crown_inner_overcut
                    ),
                    8.0,
                    fan_deck_height
                    + chassis_crown_inner_overcut,
                )
            )
            .toPending()
            .loft(combine=False)
        )
        chassis_crown = chassis_crown_outer.cut(
            chassis_crown_inner
        )
        crown_replacement_cut = (
            cq.Workplane("XY")
            .box(
                cradle_length + 2.0,
                cradle_width + 2.0,
                chassis_crown_height + 0.2,
                centered=(True, True, False),
            )
            .translate(
                (
                    0.0,
                    0.0,
                    chassis_crown_bottom_z - 0.1,
                )
            )
        )
        chassis_shape = (
            chassis_shape
            .cut(crown_replacement_cut)
            .union(chassis_crown)
            .clean()
        )

        # The 105 x 105 mm pattern is shared by standard square 120 mm fans.
        # Corner pads bridge the large inlet to the outer ring and accept
        # screwless silicone pull mounts or the integrated PETG clips.
        fan_mount_spacing = resolved_parameters["fan_mount_spacing_mm"]
        fan_mount_hole_diameter = resolved_parameters[
            "fan_mount_hole_diameter_mm"
        ]
        fan_isolator_pocket_diameter = 10.0
        fan_isolator_pocket_depth = 0.8
        fan_isolator_nominal_thickness = 1.5
        fan_isolator_installed_thickness = 1.3
        fan_isolator_compression = (
            fan_isolator_nominal_thickness
            - fan_isolator_installed_thickness
        )
        fan_isolator_compression_ratio = (
            fan_isolator_compression
            / fan_isolator_nominal_thickness
        )
        fan_isolator_protrusion = (
            fan_isolator_installed_thickness
            - fan_isolator_pocket_depth
        )
        fan_mount_pad_size = 12.0
        fan_mount_positions = tuple(
            (x_pos, y_pos)
            for x_pos in (-fan_mount_spacing / 2, fan_mount_spacing / 2)
            for y_pos in (-fan_mount_spacing / 2, fan_mount_spacing / 2)
        )

        # V95 replaces V94's visually flat 14.5 mm closing chord with a
        # tangent-continuous rounded crown. The two flanks remain above the
        # 30 degree support threshold. Only the 14.5 mm crown transition
        # intentionally rolls from that slope to a horizontal center tangent,
        # so it is treated as a short bridge and validated by OrcaSlicer plus
        # the physical portal coupon rather than being mislabeled as a wholly
        # self-supporting roof.
        intake_bottom_z = 7.5
        intake_top_z = fan_deck_height - 5.0
        intake_window_width = 114.0
        intake_window_height = intake_top_z - intake_bottom_z
        layer_height_mm = 0.2
        intake_half_width = intake_window_width / 2
        intake_lower_shoulder = intake_half_width - 4.0
        intake_roof_start_x = 49.0
        intake_roof_start_z = intake_bottom_z + 16.0
        intake_side_lower_z = intake_bottom_z + 6.0
        intake_side_upper_z = intake_bottom_z + 11.25
        intake_crown_half_width = 7.25
        slicer_support_threshold_deg = 30.0
        intake_profile_fillet_radius = 3.0
        intake_flank_minimum_slope_deg = 31.5
        intake_roof_minimum_slope = math.tan(
            math.radians(intake_flank_minimum_slope_deg)
        )
        intake_crown_rise = (
            intake_roof_minimum_slope
            * 2
            * intake_crown_half_width
            / math.pi
        )
        intake_crown_shoulder_z = intake_top_z - intake_crown_rise
        intake_roof_curve_span = (
            intake_roof_start_x - intake_crown_half_width
        )
        intake_roof_curve_rise = (
            intake_crown_shoulder_z - intake_roof_start_z
        )
        intake_roof_baseline_slope = (
            intake_roof_curve_rise / intake_roof_curve_span
        )
        intake_roof_curve_amplitude = (
            (
                intake_roof_baseline_slope
                - intake_roof_minimum_slope
            )
            * intake_roof_curve_span
            / math.pi
        )
        intake_roof_maximum_slope = (
            intake_roof_baseline_slope
            + intake_roof_curve_amplitude
            * math.pi
            / intake_roof_curve_span
        )
        intake_minimum_roof_slope_deg = math.degrees(
            math.atan(intake_roof_minimum_slope)
        )
        intake_roof_slope_margin_deg = (
            intake_minimum_roof_slope_deg
            - slicer_support_threshold_deg
        )
        intake_closing_chord = 2 * intake_crown_half_width
        intake_roof_samples = tuple(
            (
                intake_roof_start_x
                - intake_roof_curve_span * parameter,
                intake_roof_start_z
                + intake_roof_curve_rise * parameter
                + intake_roof_curve_amplitude
                * math.sin(math.pi * parameter),
            )
            for parameter in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
        )
        intake_right_roof_targets = intake_roof_samples[1:]
        intake_left_roof_targets = tuple(
            (-x_pos, z_pos)
            for x_pos, z_pos in reversed(intake_roof_samples[:-1])
        )
        intake_right_crown_samples = tuple(
            (
                intake_crown_half_width * (1.0 - parameter),
                intake_crown_shoulder_z
                + intake_crown_rise
                * math.sin(math.pi * parameter / 2),
            )
            for parameter in (0.2, 0.4, 0.6, 0.8, 1.0)
        )
        intake_left_crown_targets = tuple(
            (-x_pos, z_pos)
            for x_pos, z_pos in reversed(
                intake_right_crown_samples[:-1]
            )
        ) + ((-intake_crown_half_width, intake_crown_shoulder_z),)
        intake_crown_membrane_thickness = layer_height_mm
        intake_crown_membrane_attachment = 0.4
        intake_crown_membrane_span = (
            intake_closing_chord
            + 2 * intake_crown_membrane_attachment
        )
        intake_crown_membrane_z = (
            intake_crown_shoulder_z
            + intake_crown_membrane_thickness / 2
        )
        intake_crown_membrane_volume_per_portal = (
            intake_crown_membrane_span
            * wall_mm
            * intake_crown_membrane_thickness
        )
        portal_cut_margin = 0.8
        side_cut_depth = wall_mm + portal_cut_margin

        def self_supporting_air_portal(
            *,
            plane: str,
            side: float,
        ) -> cq.Workplane:
            profile_wire = (
                cq.Workplane(plane)
                .moveTo(-intake_lower_shoulder, intake_bottom_z)
                .lineTo(intake_lower_shoulder, intake_bottom_z)
                .lineTo(intake_half_width, intake_side_lower_z)
                .lineTo(intake_half_width, intake_side_upper_z)
                .lineTo(intake_roof_start_x, intake_roof_start_z)
                .spline(
                    intake_right_roof_targets,
                    tangents=(
                        (-1.0, intake_roof_maximum_slope),
                        (-1.0, intake_roof_minimum_slope),
                    ),
                    includeCurrent=True,
                )
                .spline(
                    intake_right_crown_samples,
                    tangents=(
                        (-1.0, intake_roof_minimum_slope),
                        (-1.0, 0.0),
                    ),
                    includeCurrent=True,
                )
                .spline(
                    intake_left_crown_targets,
                    tangents=(
                        (-1.0, 0.0),
                        (-1.0, -intake_roof_minimum_slope),
                    ),
                    includeCurrent=True,
                )
                .spline(
                    intake_left_roof_targets,
                    tangents=(
                        (-1.0, -intake_roof_minimum_slope),
                        (-1.0, -intake_roof_maximum_slope),
                    ),
                    includeCurrent=True,
                )
                .lineTo(-intake_half_width, intake_side_upper_z)
                .lineTo(-intake_half_width, intake_side_lower_z)
                .close()
                .val()
            )
            fillet_vertices = [
                vertex
                for vertex in profile_wire.Vertices()
                if abs(vertex.Z - intake_bottom_z) <= 0.01
            ]
            rounded_wire = profile_wire.fillet2D(
                intake_profile_fillet_radius,
                fillet_vertices,
            )
            profile = (
                cq.Workplane(plane)
                .add(rounded_wire)
                .toPending()
                .extrude(side_cut_depth / 2, both=True)
            )
            wall_center_side = side - math.copysign(
                wall_mm / 2,
                side,
            )
            if plane == "XZ":
                return profile.translate((0.0, wall_center_side, 0.0))
            return profile.translate((wall_center_side, 0.0, 0.0))

        air_portal_fillers: list[cq.Workplane] = []
        for side in (-frame_outer / 2, frame_outer / 2):
            for plane in ("XZ", "YZ"):
                cutter = self_supporting_air_portal(
                    plane=plane,
                    side=side,
                )
                filler_center_z = (
                    intake_bottom_z + intake_top_z
                ) / 2.0
                if plane == "XZ":
                    filler_envelope = (
                        cq.Workplane("XY")
                        .box(
                            intake_window_width,
                            side_cut_depth,
                            intake_window_height,
                        )
                        .translate((0.0, side, filler_center_z))
                    )
                else:
                    filler_envelope = (
                        cq.Workplane("XY")
                        .box(
                            side_cut_depth,
                            intake_window_width,
                            intake_window_height,
                        )
                        .translate((side, 0.0, filler_center_z))
                    )
                air_portal_fillers.append(
                    exterior_wall_shell.intersect(filler_envelope)
                )
                chassis_shape = chassis_shape.cut(cutter)
                wall_center_side = side - math.copysign(
                    wall_mm / 2,
                    side,
                )
                if plane == "XZ":
                    crown_membrane = (
                        cq.Workplane("XY")
                        .box(
                            intake_crown_membrane_span,
                            wall_mm,
                            intake_crown_membrane_thickness,
                        )
                        .translate(
                            (
                                0.0,
                                wall_center_side,
                                intake_crown_membrane_z,
                            )
                        )
                    )
                else:
                    crown_membrane = (
                        cq.Workplane("XY")
                        .box(
                            wall_mm,
                            intake_crown_membrane_span,
                            intake_crown_membrane_thickness,
                        )
                        .translate(
                            (
                                wall_center_side,
                                0.0,
                                intake_crown_membrane_z,
                            )
                        )
                    )
                chassis_shape = chassis_shape.union(crown_membrane)

        portal_area = (
            self_supporting_air_portal(plane="XZ", side=0.0)
            .val()
            .Volume()
            / side_cut_depth
        )
        intake_window_count = 4
        intake_area = intake_window_count * portal_area

        # The electronics cassette occupies the lower rear-right corner inside
        # the Mac mini footprint. The 120 mm fan is stacked above it, removing
        # all lateral accessory-box extension.
        pod_bottom_opening = _rounded_box(
            controller_service_opening_length,
            cover_width + 2 * tolerance_mm,
            cover_plate_height + 1.0,
            controller_service_corner_radius,
        ).translate((pod_x, pod_y, 0.0))
        chassis_shape = chassis_shape.cut(pod_bottom_opening)
        pod_outer = _rounded_box(
            pod_length,
            pod_width,
            pod_height,
            min(10.0, pod_length / 3),
        ).translate((pod_x, pod_y, 0.0))
        pod_top_edge_radius = 1.5
        pod_outer = pod_outer.edges(">Z").fillet(pod_top_edge_radius)
        pod_inner = _rounded_box(
            controller_service_opening_length,
            pod_width - 2 * wall_mm,
            pod_height + 1.0,
            controller_service_corner_radius,
        ).translate((pod_x, pod_y, 0.0))
        pod_shape = pod_outer.cut(pod_inner)
        # The two inboard pod faces and the exterior cable face use the same
        # rounded self-supporting arch language as the main chassis portals.
        # V61's layer-resolved support map proved that the previous shallow
        # ellipses concentrated support interfaces at Z=20-25 mm.  A short
        # vertical reveal preserves open area, while the 40-41 degree roof
        # and 12 mm effective crown bridge remove the ellipse's near-
        # horizontal closing layers without adding a mullion or another part.
        pod_crossflow_width = 52.0
        pod_external_cable_width = 54.0
        pod_crossflow_height = 23.0
        pod_external_cable_height = 22.0
        pod_external_cable_bottom_z = 3.5
        pod_external_cable_roof_start_z = 8.0
        pod_external_cable_top_z = 25.5
        pod_crossflow_center_z = pod_height / 2
        pod_crossflow_bottom_z = (
            pod_crossflow_center_z - pod_crossflow_height / 2
        )
        pod_crossflow_top_z = (
            pod_crossflow_center_z + pod_crossflow_height / 2
        )
        pod_crossflow_roof_start_z = pod_crossflow_bottom_z + 4.5
        pod_crossflow_crown_half_width = 5.4
        pod_crossflow_profile_fillet_radius = 0.6
        # Internal and external pod arches share the V70 crown geometry.
        # V71 trials that shortened only the inward crown either reduced
        # airflow area or increased total print time/support interfaces, so
        # the 3 mm load webs and 12 mm effective bridge remain unchanged.
        pod_internal_crossflow_bottom_z = pod_crossflow_bottom_z
        pod_internal_crossflow_roof_start_z = pod_crossflow_roof_start_z
        pod_internal_crossflow_crown_half_width = (
            pod_crossflow_crown_half_width
        )
        pod_crossflow_effective_bridge = (
            2
            * (
                pod_internal_crossflow_crown_half_width
                + pod_crossflow_profile_fillet_radius
            )
        )
        pod_external_cable_effective_bridge = 2 * (
            pod_crossflow_crown_half_width
            + pod_crossflow_profile_fillet_radius
        )
        pod_crossflow_minimum_roof_slope_deg = math.degrees(
            math.atan2(
                pod_crossflow_top_z
                - pod_internal_crossflow_roof_start_z,
                pod_crossflow_width / 2
                - pod_internal_crossflow_crown_half_width,
            )
        )
        pod_external_cable_minimum_roof_slope_deg = math.degrees(
            math.atan2(
                pod_external_cable_top_z
                - pod_external_cable_roof_start_z,
                pod_external_cable_width / 2
                - pod_crossflow_crown_half_width,
            )
        )
        pod_crossflow_minimum_web = min(
            pod_internal_crossflow_bottom_z,
            pod_height - pod_crossflow_top_z,
            (pod_width - pod_crossflow_width) / 2,
        )
        pod_crossflow_cut_depth = wall_mm + 0.8
        pod_crossflow_closing_chord = pod_crossflow_effective_bridge

        def self_supporting_pod_portal(
            *,
            plane: str,
            wall_center: float,
            center_u: float,
            width: float,
            bottom_z: float | None = None,
            roof_start_z: float | None = None,
            top_z: float | None = None,
            crown_half_width: float | None = None,
        ) -> cq.Workplane:
            resolved_bottom_z = (
                pod_crossflow_bottom_z
                if bottom_z is None
                else bottom_z
            )
            resolved_roof_start_z = (
                pod_crossflow_roof_start_z
                if roof_start_z is None
                else roof_start_z
            )
            resolved_top_z = (
                pod_crossflow_top_z if top_z is None else top_z
            )
            resolved_crown_half_width = (
                pod_crossflow_crown_half_width
                if crown_half_width is None
                else crown_half_width
            )
            half_width = width / 2
            points = (
                (
                    center_u - half_width,
                    resolved_bottom_z,
                ),
                (
                    center_u + half_width,
                    resolved_bottom_z,
                ),
                (
                    center_u + half_width,
                    resolved_roof_start_z,
                ),
                (
                    center_u + resolved_crown_half_width,
                    resolved_top_z,
                ),
                (
                    center_u - resolved_crown_half_width,
                    resolved_top_z,
                ),
                (
                    center_u - half_width,
                    resolved_roof_start_z,
                ),
            )
            profile_wire = (
                cq.Workplane(plane).polyline(points).close().val()
            )
            rounded_wire = profile_wire.fillet2D(
                pod_crossflow_profile_fillet_radius,
                profile_wire.Vertices(),
            )
            profile = (
                cq.Workplane(plane)
                .add(rounded_wire)
                .toPending()
                .extrude(pod_crossflow_cut_depth / 2, both=True)
            )
            if plane == "YZ":
                return profile.translate((wall_center, 0.0, 0.0))
            return profile.translate((0.0, wall_center, 0.0))

        pod_inner_x_wall_center = (
            pod_x - pod_length / 2 + wall_mm / 2
        )
        pod_inner_y_wall_center = (
            pod_y - pod_width / 2 + wall_mm / 2
        )
        pod_crossflow_x_wall = self_supporting_pod_portal(
            plane="YZ",
            wall_center=pod_inner_x_wall_center,
            center_u=pod_y,
            width=pod_crossflow_width,
            bottom_z=pod_internal_crossflow_bottom_z,
            roof_start_z=pod_internal_crossflow_roof_start_z,
            top_z=pod_crossflow_top_z,
            crown_half_width=pod_internal_crossflow_crown_half_width,
        )
        pod_crossflow_y_wall = self_supporting_pod_portal(
            plane="XZ",
            wall_center=pod_inner_y_wall_center,
            center_u=pod_x,
            width=pod_crossflow_width,
            bottom_z=pod_internal_crossflow_bottom_z,
            roof_start_z=pod_internal_crossflow_roof_start_z,
            top_z=pod_crossflow_top_z,
            crown_half_width=pod_internal_crossflow_crown_half_width,
        )
        pod_outer_x_wall_center = (
            pod_x + pod_length / 2 - wall_mm / 2
        )
        pod_outer_y_wall_center = (
            pod_y + pod_width / 2 - wall_mm / 2
        )
        # The support maps isolated the shallow snap-side ellipse as a major
        # remaining contact band. V72 raises each 24 mm opening to 12.75 mm
        # and shortens its crown bridge to 5.7 mm while retaining a 45 degree
        # roof and the continuous central latch-load rib.
        pod_external_snap_width = 24.0
        pod_external_snap_height = 12.75
        pod_external_snap_bottom_z = 13.25
        pod_external_snap_roof_start_z = 16.25
        pod_external_snap_top_z = 26.0
        pod_external_snap_crown_half_width = 2.25
        pod_external_snap_center_offsets = (-13.5, 13.5)
        pod_external_snap_portals = tuple(
            self_supporting_pod_portal(
                plane="YZ",
                wall_center=pod_outer_x_wall_center,
                center_u=pod_y + center_offset,
                width=pod_external_snap_width,
                bottom_z=pod_external_snap_bottom_z,
                roof_start_z=pod_external_snap_roof_start_z,
                top_z=pod_external_snap_top_z,
                crown_half_width=pod_external_snap_crown_half_width,
            )
            for center_offset in pod_external_snap_center_offsets
        )
        pod_external_snap_portal = (
            pod_external_snap_portals[0].union(
                pod_external_snap_portals[1]
            )
        )
        pod_external_cable_portal = self_supporting_pod_portal(
            plane="XZ",
            wall_center=pod_outer_y_wall_center,
            center_u=pod_x,
            width=pod_external_cable_width,
            bottom_z=pod_external_cable_bottom_z,
            roof_start_z=pod_external_cable_roof_start_z,
            top_z=pod_external_cable_top_z,
        )
        usb_service_center_y = pod_y - 11.0
        usb_service_center_z = 22.9
        usb_service_port_width = 20.0
        # The former 20 x 12 mm ellipse closed with near-horizontal layers
        # at Z=25-29 mm. Keep effectively the same service area, but use a
        # short reveal and 45-degree roof so the inboard USB port grows from
        # the wall without an enclosed support contact.
        usb_service_port_bottom_z = 16.4
        usb_service_port_roof_start_z = 20.9
        usb_service_port_top_z = 28.9
        usb_service_port_crown_half_width = 2.0
        usb_service_port_height = (
            usb_service_port_top_z - usb_service_port_bottom_z
        )
        usb_service_port_center_z = (
            usb_service_port_bottom_z + usb_service_port_top_z
        ) / 2
        usb_service_port = self_supporting_pod_portal(
            plane="YZ",
            wall_center=pod_inner_x_wall_center,
            center_u=usb_service_center_y,
            width=usb_service_port_width,
            bottom_z=usb_service_port_bottom_z,
            roof_start_z=usb_service_port_roof_start_z,
            top_z=usb_service_port_top_z,
            crown_half_width=usb_service_port_crown_half_width,
        )
        usb_service_port_area = (
            usb_service_port.val().Volume() / pod_crossflow_cut_depth
        )
        usb_service_port_effective_bridge = 2 * (
            usb_service_port_crown_half_width
            + pod_crossflow_profile_fillet_radius
        )
        usb_service_port_minimum_roof_slope_deg = math.degrees(
            math.atan2(
                usb_service_port_top_z
                - usb_service_port_roof_start_z,
                usb_service_port_width / 2
                - usb_service_port_crown_half_width,
            )
        )
        pod_shape = (
            pod_shape
            .cut(pod_crossflow_x_wall)
            .cut(pod_crossflow_y_wall)
            .cut(pod_external_snap_portal)
            .cut(pod_external_cable_portal)
            .cut(usb_service_port)
        )
        pod_crossflow_single_area = (
            pod_crossflow_x_wall.val().Volume()
            / pod_crossflow_cut_depth
        )
        pod_crossflow_area = 2 * pod_crossflow_single_area
        pod_crossflow_wall_open_ratio = pod_crossflow_area / (
            2 * pod_length * pod_height
        )
        pod_external_snap_area = sum(
            portal.val().Volume() / pod_crossflow_cut_depth
            for portal in pod_external_snap_portals
        )
        pod_external_cable_area = (
            pod_external_cable_portal.val().Volume()
            / pod_crossflow_cut_depth
        )
        pod_external_open_area = (
            pod_external_snap_area + pod_external_cable_area
        )
        pod_external_wall_open_ratio = pod_external_open_area / (
            2 * pod_length * pod_height
        )
        pod_external_snap_closing_chord = 2 * (
            pod_external_snap_crown_half_width
            + pod_crossflow_profile_fillet_radius
        )
        pod_external_snap_minimum_roof_slope_deg = math.degrees(
            math.atan2(
                pod_external_snap_top_z
                - pod_external_snap_roof_start_z,
                pod_external_snap_width / 2
                - pod_external_snap_crown_half_width,
            )
        )
        pod_external_minimum_web = min(
            pod_height - pod_external_snap_top_z,
            pod_crossflow_minimum_web,
            min(
                (
                    pod_external_snap_center_offsets[1]
                    - pod_external_snap_center_offsets[0]
                    - pod_external_snap_width
                ),
                (
                    pod_width
                    - (
                        pod_external_snap_center_offsets[1]
                        - pod_external_snap_center_offsets[0]
                    )
                    - pod_external_snap_width
                )
                / 2,
            ),
        )
        pod_right_inner_x = pod_x + pod_length / 2 - wall_mm
        snap_slot_depth = wall_mm + 2.5
        snap_slot_width = snap_tab_width + 2 * tolerance_mm
        snap_slot_height = snap_hook_height + 2 * tolerance_mm
        snap_slot_roof_chamfer_length = 2.0
        snap_slot_z = (
            cover_plate_height + snap_tab_length
            - snap_hook_height
            - tolerance_mm
        )
        snap_slots = []
        for y_pos in snap_tab_y_positions:
            snap_slot_center_x = (
                pod_right_inner_x + snap_slot_depth / 2 - 2.2
            )
            snap_slot_inner_x = (
                snap_slot_center_x - snap_slot_depth / 2
            )
            snap_slot_outer_x = (
                snap_slot_center_x + snap_slot_depth / 2
            )
            snap_slot_top_z = snap_slot_z + snap_slot_height
            snap_slot = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (snap_slot_inner_x, snap_slot_z),
                        (snap_slot_outer_x, snap_slot_z),
                        (
                            snap_slot_outer_x,
                            snap_slot_top_z
                            + snap_slot_roof_chamfer_length,
                        ),
                        (
                            snap_slot_outer_x
                            - snap_slot_roof_chamfer_length,
                            snap_slot_top_z,
                        ),
                        (snap_slot_inner_x, snap_slot_top_z),
                    )
                )
                .close()
                .extrude(snap_slot_width / 2, both=True)
                .translate(
                    (
                        0.0,
                        pod_y + y_pos,
                        0.0,
                    )
                )
            )
            snap_slots.append(snap_slot)
            pod_shape = pod_shape.cut(snap_slot)
        pod_clearance = _rounded_box(
            controller_service_opening_length,
            pod_width - 2 * wall_mm,
            fan_deck_height + 1.0,
            controller_service_corner_radius,
        ).translate((pod_x, pod_y, 0.0))
        chassis_shape = chassis_shape.union(pod_shape).cut(pod_clearance)
        for snap_slot in snap_slots:
            chassis_shape = chassis_shape.cut(snap_slot)
        # The cassette shares material with the original chassis wall.
        # Reapply the exterior portal cutters after the union so coincident
        # wall material cannot silently refill the intended openings.
        chassis_shape = (
            chassis_shape
            .cut(pod_external_snap_portal)
            .cut(pod_external_cable_portal)
        )
        cable_portal = (
            cq.Workplane("XY")
            .box(12.0, wall_mm + 2.0, 6.0, centered=(True, True, False))
            .translate(
                (
                    pod_x,
                    pod_y + pod_width / 2,
                    20.0,
                )
            )
        )
        chassis_shape = chassis_shape.cut(cable_portal)
        controller_portal_residual_after_cut_volume = sum(
            float(chassis_shape.intersect(cutter).val().Volume())
            for cutter in (
                pod_crossflow_x_wall,
                pod_crossflow_y_wall,
                pod_external_snap_portal,
                pod_external_cable_portal,
            )
        )

        # A two-arm snap clamp directly behind the 12 x 6 mm portal transfers
        # cable loads into the chassis instead of the PCB connectors. The
        # arms rise from the intact lower sill, stay clear of the DS18B20
        # keep-out, and accept a 4 mm sleeved bundle through 45-degree hooks.
        cable_clamp_target_diameter = 4.0
        cable_clamp_arm_thickness = 1.6
        cable_clamp_depth = 2.0
        cable_clamp_center_spacing = 6.0
        cable_clamp_hook_overlap = 0.8
        cable_clamp_hook_flat_span = 0.0
        cable_clamp_hook_height = 1.35
        cable_clamp_hook_bottom_z = 18.65
        cable_clamp_portal_center_z = 16.5
        # V67's largest remaining XYZ contact cell mapped to the two
        # 5 x 1.6 x 2 mm horizontal clamp anchors at Z=18-20 mm. They were
        # nominally small, but required dense support and did not provide a
        # clean load path through the open cable portal. Root both flexible
        # arms in the removable carrier's solid base instead: the vertical
        # arms print without support, travel with the serviced electronics,
        # and do not cross the chassis wall opening. A 0.5 mm embed prevents
        # a coplanar/tangent union.
        cable_clamp_root_embed_depth = 0.5
        cable_clamp_arm_bottom_z = (
            cover_plate_height - cable_clamp_root_embed_depth
        )
        cable_clamp_arm_length = (
            cable_clamp_hook_bottom_z
            + cable_clamp_hook_height
            - cable_clamp_arm_bottom_z
        )
        cable_clamp_center_x = pod_x + 8.0
        cable_clamp_carrier_edge_inset = tolerance_mm
        cable_clamp_center_y = (
            pod_y
            + cover_width / 2
            - cable_clamp_carrier_edge_inset
            - cable_clamp_depth / 2
        )
        cable_clamp_throat = (
            cable_clamp_center_spacing
            - cable_clamp_arm_thickness
            - 2 * cable_clamp_hook_overlap
        )
        cable_clamp_required_deflection = (
            cable_clamp_target_diameter - cable_clamp_throat
        ) / 2
        cable_clamp_nominal_strain = (
            1.5
            * cable_clamp_arm_thickness
            * cable_clamp_required_deflection
            / cable_clamp_arm_length**2
        )
        cable_clamp_arm_centers = (
            cable_clamp_center_x - cable_clamp_center_spacing / 2,
            cable_clamp_center_x + cable_clamp_center_spacing / 2,
        )

        # The guard sits 27 mm below the cradle, so the cradle cannot retain
        # it. Four short L-shaped shelves carry the guard directly from wall
        # regions beside the elliptical portals. Their inner guide faces sit
        # 0.25 mm beyond the guard pads and constrain +X, -X, +Y and -Y. The
        # installed fan and its top hooks limit upward movement, while fan
        # removal leaves a straight upward service path.
        guard_support_top_z = electronics_layer_height
        guard_support_height = 1.6
        guard_support_depth = 7.0
        guard_support_width = 9.0
        guard_support_wall_embed = 1.0
        guard_support_radial_center = (
            plenum_inner / 2
            - guard_support_depth / 2
            + guard_support_wall_embed
        )
        guard_guide_inner_face = fan_mount_spacing / 2 + (
            fan_mount_pad_size / 2 + tolerance_mm
        )
        guard_guide_outer_face = plenum_inner / 2 + (
            guard_support_wall_embed
        )
        guard_guide_depth = (
            guard_guide_outer_face - guard_guide_inner_face
        )
        guard_guide_height = guard_height
        guard_supports = []
        guard_guides = []
        guard_support_gussets = []
        guard_support_specs = (
            ("Y", 1.0, fan_mount_spacing / 2),
            ("X", -1.0, fan_mount_spacing / 2),
            ("Y", -1.0, -fan_mount_spacing / 2),
            ("X", 1.0, -fan_mount_spacing / 2),
        )
        for radial_axis, side, tangent_position in guard_support_specs:
            radial_center = side * guard_support_radial_center
            guide_center = side * (
                guard_guide_inner_face + guard_guide_depth / 2
            )
            if radial_axis == "Y":
                support = (
                    cq.Workplane("XY")
                    .box(
                        guard_support_width,
                        guard_support_depth,
                        guard_support_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            tangent_position,
                            radial_center,
                            guard_support_top_z
                            - guard_support_height,
                        )
                    )
                )
                guide = (
                    cq.Workplane("XY")
                    .box(
                        guard_support_width,
                        guard_guide_depth,
                        guard_guide_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            tangent_position,
                            guide_center,
                            guard_support_top_z,
                        )
                    )
                )
            else:
                support = (
                    cq.Workplane("XY")
                    .box(
                        guard_support_depth,
                        guard_support_width,
                        guard_support_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            radial_center,
                            tangent_position,
                            guard_support_top_z
                            - guard_support_height,
                        )
                    )
                )
                guide = (
                    cq.Workplane("XY")
                    .box(
                        guard_guide_depth,
                        guard_support_width,
                        guard_guide_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            guide_center,
                            tangent_position,
                            guard_support_top_z,
                        )
                    )
                )
            guard_supports.append(support)
            guard_guides.append(guide)
            support_inner_face = side * (
                abs(radial_center) - guard_support_depth / 2
            )
            wall_inner_face = side * (plenum_inner / 2)
            support_attach_face = (
                support_inner_face + side * 0.4
            )
            wall_attach_face = wall_inner_face + side * 0.4
            support_bottom_z = (
                guard_support_top_z - guard_support_height
            )
            gusset_drop = abs(wall_inner_face - support_inner_face)
            if radial_axis == "Y":
                gusset = (
                    cq.Workplane("YZ")
                    .polyline(
                        (
                            (support_attach_face, support_bottom_z),
                            (wall_attach_face, support_bottom_z),
                            (
                                wall_attach_face,
                                support_bottom_z - gusset_drop,
                            ),
                        )
                    )
                    .close()
                    .extrude(guard_support_width / 2, both=True)
                    .translate((tangent_position, 0.0, 0.0))
                )
            else:
                gusset = (
                    cq.Workplane("XZ")
                    .polyline(
                        (
                            (support_attach_face, support_bottom_z),
                            (wall_attach_face, support_bottom_z),
                            (
                                wall_attach_face,
                                support_bottom_z - gusset_drop,
                            ),
                        )
                    )
                    .close()
                    .extrude(guard_support_width / 2, both=True)
                    .translate((0.0, tangent_position, 0.0))
                )
            for portal_cutter in (
                pod_crossflow_x_wall,
                pod_crossflow_y_wall,
                pod_external_snap_portal,
                pod_external_cable_portal,
            ):
                gusset = gusset.cut(portal_cutter)
            guard_support_gussets.append(gusset)
            chassis_shape = (
                chassis_shape
                .union(support)
                .union(guide)
                .union(gusset)
            )

        # Four real cantilever clips replace the former rigid top blocks.
        # Each clip grows upward from a two-layer anchor, leaves a 0.7 mm
        # relief gap behind the flexible arm, and terminates in a 45-degree
        # lead-in wedge. The fan deflects the arm outward during insertion;
        # after seating, the hook retains the fan with 0.25 mm vertical
        # clearance and no hard solid overlap.
        clip_arm_length = 12.0
        clip_arm_thickness = 1.6
        clip_width = 10.0
        clip_wall_relief = 0.7
        clip_hook_height = 1.25
        clip_hook_overlap = 0.25
        clip_hook_arm_embed = 0.25
        clip_hook_flat_span = 0.4
        clip_required_deflection = 0.5
        clip_anchor_height = 2.0
        clip_fan_top_clearance = tolerance_mm
        clip_arm_inner = fan_size / 2 + 1.2
        clip_arm_outer = (
            plenum_inner / 2 - clip_wall_relief
        )
        clip_arm_center = (clip_arm_inner + clip_arm_outer) / 2
        clip_anchor_outer = plenum_inner / 2 + 0.3
        clip_anchor_depth = clip_anchor_outer - clip_arm_inner
        fan_installed_bottom_z = electronics_layer_height + wall_mm
        fan_installed_height = fan_installed_height_parameter
        clip_hook_bottom_z = (
            fan_installed_bottom_z
            + fan_installed_height
            + clip_fan_top_clearance
        )
        clip_arm_bottom_z = clip_hook_bottom_z - clip_arm_length
        clip_hook_tip = fan_size / 2 - clip_hook_overlap
        clip_hook_flat_root = fan_size / 2 + (
            clip_hook_flat_span - clip_hook_overlap
        )
        clip_hook_undercut_ramp_run = (
            clip_arm_inner
            + clip_hook_arm_embed
            - clip_hook_flat_root
        )
        clip_hook_ramp_root_z = (
            clip_hook_bottom_z - clip_hook_undercut_ramp_run
        )
        clip_hook_undercut_angle_deg = math.degrees(
            math.atan2(
                clip_hook_bottom_z - clip_hook_ramp_root_z,
                clip_hook_undercut_ramp_run,
            )
        )
        clip_nominal_strain = (
            1.5
            * clip_arm_thickness
            * clip_required_deflection
            / clip_arm_length**2
        )
        clip_tangent_offset = 55.25
        fan_clip_specs = (
            ("Y", -1.0, -clip_tangent_offset),
            ("Y", 1.0, clip_tangent_offset),
            ("X", -1.0, clip_tangent_offset),
            ("X", 1.0, -clip_tangent_offset),
        )
        fan_clip_anchor_gussets = []
        for radial_axis, side, tangent_position in fan_clip_specs:
            radial_center = side * clip_arm_center
            anchor_center = side * (
                clip_arm_inner + clip_anchor_depth / 2
            )
            arm_inner = side * clip_arm_inner
            hook_root = side * (
                clip_arm_inner + clip_hook_arm_embed
            )
            hook_tip = side * clip_hook_tip
            hook_flat_root = side * clip_hook_flat_root
            if radial_axis == "Y":
                arm = (
                    cq.Workplane("XY")
                    .box(
                        clip_width,
                        clip_arm_thickness,
                        clip_arm_length,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            tangent_position,
                            radial_center,
                            clip_arm_bottom_z,
                        )
                    )
                )
                anchor = (
                    cq.Workplane("XY")
                    .box(
                        clip_width,
                        clip_anchor_depth,
                        clip_anchor_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            tangent_position,
                            anchor_center,
                            clip_arm_bottom_z,
                        )
                    )
                )
                hook = (
                    cq.Workplane("YZ")
                    .polyline(
                        [
                            (hook_root, clip_hook_ramp_root_z),
                            (hook_flat_root, clip_hook_bottom_z),
                            (hook_tip, clip_hook_bottom_z),
                            (
                                hook_root,
                                clip_hook_bottom_z + clip_hook_height,
                            ),
                        ]
                    )
                    .close()
                    .extrude(clip_width / 2, both=True)
                    .translate((tangent_position, 0.0, 0.0))
                )
                wall_inner_face = side * (plenum_inner / 2)
                anchor_inner_face = side * clip_arm_inner
                anchor_attach_face = (
                    anchor_inner_face + side * 0.4
                )
                wall_attach_face = wall_inner_face + side * 0.4
                gusset_drop = abs(
                    wall_inner_face - anchor_inner_face
                )
                gusset = (
                    cq.Workplane("YZ")
                    .polyline(
                        (
                            (anchor_attach_face, clip_arm_bottom_z),
                            (wall_attach_face, clip_arm_bottom_z),
                            (
                                wall_attach_face,
                                clip_arm_bottom_z - gusset_drop,
                            ),
                        )
                    )
                    .close()
                    .extrude(clip_width / 2, both=True)
                    .translate((tangent_position, 0.0, 0.0))
                )
            else:
                arm = (
                    cq.Workplane("XY")
                    .box(
                        clip_arm_thickness,
                        clip_width,
                        clip_arm_length,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            radial_center,
                            tangent_position,
                            clip_arm_bottom_z,
                        )
                    )
                )
                anchor = (
                    cq.Workplane("XY")
                    .box(
                        clip_anchor_depth,
                        clip_width,
                        clip_anchor_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            anchor_center,
                            tangent_position,
                            clip_arm_bottom_z,
                        )
                    )
                )
                hook = (
                    cq.Workplane("XZ")
                    .polyline(
                        [
                            (hook_root, clip_hook_ramp_root_z),
                            (hook_flat_root, clip_hook_bottom_z),
                            (hook_tip, clip_hook_bottom_z),
                            (
                                hook_root,
                                clip_hook_bottom_z + clip_hook_height,
                            ),
                        ]
                    )
                    .close()
                    .extrude(clip_width / 2, both=True)
                    .translate((0.0, tangent_position, 0.0))
                )
                wall_inner_face = side * (plenum_inner / 2)
                anchor_inner_face = side * clip_arm_inner
                anchor_attach_face = (
                    anchor_inner_face + side * 0.4
                )
                wall_attach_face = wall_inner_face + side * 0.4
                gusset_drop = abs(
                    wall_inner_face - anchor_inner_face
                )
                gusset = (
                    cq.Workplane("XZ")
                    .polyline(
                        (
                            (anchor_attach_face, clip_arm_bottom_z),
                            (wall_attach_face, clip_arm_bottom_z),
                            (
                                wall_attach_face,
                                clip_arm_bottom_z - gusset_drop,
                            ),
                        )
                    )
                    .close()
                    .extrude(clip_width / 2, both=True)
                    .translate((0.0, tangent_position, 0.0))
                )
            for portal_cutter in (
                pod_crossflow_x_wall,
                pod_crossflow_y_wall,
                pod_external_snap_portal,
                pod_external_cable_portal,
            ):
                gusset = gusset.cut(portal_cutter)
            fan_clip_anchor_gussets.append(gusset)
            chassis_shape = (
                chassis_shape
                .union(anchor)
                .union(arm)
                .union(hook)
                .union(gusset)
            )

        # The earlier 59 mm station forced the keyed pin's inner edge 3.75 mm
        # across the fan envelope, creating four dense support-interface
        # islands at Z=55-60 mm.  Moving the stations outward by 0.5 mm
        # preserves a 4 mm minimum cradle edge ligament while shortening the
        # unavoidable fan-clear underside to 3.25 mm at the keyed pin and
        # 2.75 mm at the three round pins.
        locating_pin_x_station = 59.5
        locating_pin_y_station = 59.5
        locating_pin_positions = (
            (-locating_pin_x_station, -locating_pin_y_station),
            (-locating_pin_x_station, locating_pin_y_station),
            (locating_pin_x_station, -locating_pin_y_station),
            (locating_pin_x_station, locating_pin_y_station),
        )
        keyed_pin_position = (
            -locating_pin_x_station,
            locating_pin_y_station,
        )
        locating_pin_height = 3.0
        locating_pin_embed_depth = 0.3
        locating_pin_anchor_width = 4.25
        locating_pin_anchor_height = (
            fan_deck_height
            - (
                fan_installed_bottom_z
                + fan_installed_height
                + tolerance_mm
            )
        )
        locating_pin_anchor_fan_clearance = tolerance_mm
        locating_pin_anchor_flat_span = 0.0
        locating_pin_anchor_gusset_drop = 0.0
        locating_pin_anchor_effective_length = 0.0
        for position in locating_pin_positions:
            pin_radius = 2.5 if position == keyed_pin_position else 2.0
            direction_x = 1.0 if position[0] > 0 else -1.0
            anchor_angle = 0.0 if direction_x > 0 else 180.0
            anchor_inner_radius = abs(position[0]) - pin_radius
            anchor_outer_radius = plenum_inner / 2 + 0.4
            fan_clear_radius = (
                fan_size / 2
                + locating_pin_anchor_fan_clearance
            )
            anchor_gusset_start_radius = min(
                anchor_outer_radius,
                max(anchor_inner_radius, fan_clear_radius),
            )
            anchor_gusset_drop = (
                anchor_outer_radius - anchor_gusset_start_radius
            )
            locating_pin_anchor_flat_span = max(
                locating_pin_anchor_flat_span,
                anchor_gusset_start_radius - anchor_inner_radius,
            )
            locating_pin_anchor_gusset_drop = max(
                locating_pin_anchor_gusset_drop,
                anchor_gusset_drop,
            )
            locating_pin_anchor_effective_length = max(
                locating_pin_anchor_effective_length,
                anchor_outer_radius - anchor_inner_radius,
            )
            anchor_bottom_z = (
                fan_deck_height - locating_pin_anchor_height
            )
            anchor = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (anchor_inner_radius, anchor_bottom_z),
                        (
                            anchor_gusset_start_radius,
                            anchor_bottom_z,
                        ),
                        (
                            anchor_outer_radius,
                            anchor_bottom_z - anchor_gusset_drop,
                        ),
                        (anchor_outer_radius, fan_deck_height),
                        (anchor_inner_radius, fan_deck_height),
                    )
                )
                .close()
                .extrude(
                    locating_pin_anchor_width / 2,
                    both=True,
                )
                .rotate(
                    (0.0, 0.0, 0.0),
                    (0.0, 0.0, 1.0),
                    anchor_angle,
                )
                .translate((0.0, position[1], 0.0))
            )
            pin = (
                cq.Workplane("XY")
                .center(*position)
                .circle(pin_radius)
                .extrude(
                    locating_pin_height + locating_pin_embed_depth
                )
                .translate(
                    (
                        0.0,
                        0.0,
                        fan_deck_height - locating_pin_embed_depth,
                    )
                )
            )
            chassis_shape = chassis_shape.union(anchor).union(pin)
        desk_load_island = (
            cq.Workplane("XY")
            .center(*desk_load_island_center)
            .circle(desk_load_island_radius)
            .extrude(cover_plate_height)
            .intersect(
                cq.Workplane("XY").box(
                    frame_outer,
                    frame_outer,
                    cover_plate_height,
                    centered=(True, True, False),
                )
            )
        )
        desk_load_island_existing_overlap = float(
            chassis_shape.intersect(desk_load_island).val().Volume()
        )
        chassis_volume_before_desk_island = float(
            chassis_shape.val().Volume()
        )
        chassis_shape = chassis_shape.union(desk_load_island).clean()
        desk_load_island_added_volume = (
            float(chassis_shape.val().Volume())
            - chassis_volume_before_desk_island
        )

        controller_portal_cutters = (
            pod_crossflow_x_wall,
            pod_crossflow_y_wall,
            pod_external_snap_portal,
            pod_external_cable_portal,
        )
        controller_portal_functional_feature_volume = sum(
            float(chassis_shape.intersect(cutter).val().Volume())
            for cutter in controller_portal_cutters
        )
        usb_service_port_residual_after_cut_volume = float(
            chassis_shape.intersect(usb_service_port).val().Volume()
        )

        # Shared DS18B20 interface definition. These values are consumed by
        # both the chassis hardware-reference metadata and the removable
        # controller-carrier geometry, so they must be defined before either
        # part is constructed.
        probe_diameter = resolved_parameters[
            "ds18b20_probe_diameter_mm"
        ]
        probe_length = 20.0
        probe_lead_keepout_length = 10.0
        probe_bore_diameter = probe_diameter + 2 * tolerance_mm
        probe_center_local = (0.0, 19.5, 24.4)
        probe_station_x_positions = (-3.0, 3.0)
        probe_block_width = 3.0
        probe_block_depth = 8.0
        probe_block_bottom_z = 20.3
        probe_block_top_z = 28.5
        probe_snap_interference = resolved_parameters[
            "ds18b20_snap_interference_per_side_mm"
        ]
        probe_entry_slot_width = (
            probe_diameter - 2 * probe_snap_interference
        )

        chassis = CADPart(
            "fan_chassis",
            chassis_shape,
            {
                "dimensions_mm": (
                    chassis_crown_top_outer,
                    chassis_crown_top_outer,
                    fan_deck_height,
                ),
                "wall_thickness_mm": wall_mm,
                "material": material,
                "joint": (
                    "integrated vertical electronics cassette and fan stack"
                ),
                "tolerance_mm": tolerance_mm,
                "print_orientation": "air inlet ring on build plate",
                "support_strategy": "minimal",
                "design_language": (
                    "monolithic rounded-square air plinth with "
                    "zero-side-extension vertical stack"
                ),
                "integrated_cradle_crown": {
                    "modeled_as_geometry": True,
                    "body_footprint_mm": (
                        chassis_crown_bottom_outer,
                        chassis_crown_bottom_outer,
                    ),
                    "mating_footprint_mm": (
                        chassis_crown_top_outer,
                        chassis_crown_top_outer,
                    ),
                    "height_mm": chassis_crown_height,
                    "bottom_z_mm": chassis_crown_bottom_z,
                    "top_z_mm": fan_deck_height,
                    "outward_growth_per_side_mm": (
                        chassis_crown_overhang_per_side
                    ),
                    "inner_cavity_bottom_mm": (
                        chassis_crown_inner_bottom,
                        chassis_crown_inner_bottom,
                    ),
                    "inner_cavity_top_mm": (
                        chassis_crown_inner_top,
                        chassis_crown_inner_top,
                    ),
                    "inner_top_corner_radius_mm": 8.0,
                    "bottom_side_wall_mm": wall_mm,
                    "minimum_top_side_wall_mm": (
                        chassis_crown_minimum_wall
                    ),
                    "wall_optimized_loft": True,
                    "slope_from_horizontal_deg": round(
                        chassis_crown_slope_from_horizontal_deg,
                        3,
                    ),
                    "cradle_lower_edge_roll_radius_mm": (
                        chassis_cradle_seam_roll_radius
                    ),
                    "target_cradle_bottom_footprint_mm": (
                        chassis_crown_top_outer,
                        chassis_crown_top_outer,
                    ),
                    "maximum_installed_footprint_mm": (
                        cradle_length,
                        cradle_width,
                    ),
                    "support_required": False,
                    "purpose": (
                        "replace the visible stacked-plate ledge with one "
                        "continuous printable body-to-cradle transition"
                    ),
                },
                "design_priority": (
                    "zero lateral accessory extension; electronics below fan"
                ),
                "electronics_layer_height_mm": electronics_layer_height,
                "fan_deck_height_mm": fan_deck_height,
                "engineering_parameters": resolved_parameters,
                "engineering_parameter_sources": parameter_sources,
                "fan_cavity_mm": plenum_inner,
                "fan_envelope_clearance_mm": fan_clearance,
                "fan_centered_by": (
                    f"{fan_mount_spacing:g} x {fan_mount_spacing:g} mm "
                    "mount interface and four retention clips"
                ),
                "fan_retention": {
                    "clip_count": len(fan_clip_specs),
                    "type": "four releasable PETG cantilever hooks",
                    "arm_length_mm": clip_arm_length,
                    "arm_thickness_mm": clip_arm_thickness,
                    "clip_width_mm": clip_width,
                    "wall_relief_mm": clip_wall_relief,
                    "hook_height_mm": clip_hook_height,
                    "hook_overlap_mm": clip_hook_overlap,
                    "hook_arm_embed_mm": clip_hook_arm_embed,
                    "hook_contact_flat_span_mm": clip_hook_flat_span,
                    "hook_undercut_ramp_run_mm": (
                        clip_hook_undercut_ramp_run
                    ),
                    "hook_undercut_angle_deg": (
                        clip_hook_undercut_angle_deg
                    ),
                    "fan_top_clearance_mm": clip_fan_top_clearance,
                    "fan_installed_bottom_z_mm": fan_installed_bottom_z,
                    "fan_installed_height_mm": fan_installed_height,
                    "required_deflection_mm": clip_required_deflection,
                    "nominal_surface_strain": clip_nominal_strain,
                    "recommended_petg_strain_limit": 0.02,
                    "lead_in_angle_deg": 45.0,
                    "anchor_gusset_count": len(
                        fan_clip_anchor_gussets
                    ),
                    "anchor_gusset_angle_deg": 45.0,
                    "modeled_as_geometry": True,
                    "fastener_free": True,
                    "service_method": (
                        "lift the cradle, flex each top-access hook outward "
                        "by 0.5mm, and lift the fan"
                    ),
                },
                "fan_mount_interface": {
                    "standard": "120 mm square fan",
                    "spacing_mm": (fan_mount_spacing, fan_mount_spacing),
                    "hole_diameter_mm": fan_mount_hole_diameter,
                    "positions_mm": fan_mount_positions,
                    "pad_size_mm": fan_mount_pad_size,
                    "isolator_pocket_diameter_mm": (
                        fan_isolator_pocket_diameter
                    ),
                    "isolator_pocket_depth_mm": fan_isolator_pocket_depth,
                    "isolator_nominal_thickness_mm": (
                        fan_isolator_nominal_thickness
                    ),
                    "isolator_installed_thickness_mm": (
                        fan_isolator_installed_thickness
                    ),
                    "isolator_compression_mm": fan_isolator_compression,
                    "isolator_compression_ratio": (
                        fan_isolator_compression_ratio
                    ),
                    "isolator_protrusion_above_guard_mm": (
                        fan_isolator_protrusion
                    ),
                    "recommended_mount": (
                        "four replaceable 10 x 4.6 x 1.5mm silicone washers, "
                        "compressed to 1.3mm in molded recesses under the "
                        "integrated retention clips"
                    ),
                },
                "fan_guard_retention": {
                    "type": (
                        "four integrated short wall shelves with "
                        "four orthogonal guide faces"
                    ),
                    "support_count": len(guard_supports),
                    "support_top_z_mm": guard_support_top_z,
                    "support_height_mm": guard_support_height,
                    "support_depth_mm": guard_support_depth,
                    "support_width_mm": guard_support_width,
                    "support_wall_embed_mm": guard_support_wall_embed,
                    "support_specs": guard_support_specs,
                    "support_gusset_count": len(
                        guard_support_gussets
                    ),
                    "support_gusset_angle_deg": 45.0,
                    "support_radial_center_mm": (
                        guard_support_radial_center
                    ),
                    "guide_face_count": len(guard_guides),
                    "guide_inner_face_mm": guard_guide_inner_face,
                    "guide_depth_mm": guard_guide_depth,
                    "guide_height_mm": guard_guide_height,
                    "guide_clearance_mm": tolerance_mm,
                    "installed_vertical_free_play_mm": (
                        clip_fan_top_clearance
                    ),
                    "downward_constraint": (
                        "guard underside seats on four chassis shelves"
                    ),
                    "upward_constraint": (
                        "installed fan, isolators and four fan hooks"
                    ),
                    "service_method": (
                        "lift cradle, release and remove fan, remove "
                        "isolators, then lift guard vertically"
                    ),
                    "modeled_as_geometry": True,
                    "fastener_free": True,
                },
                "bottom_airflow_opening_mm": aperture_width,
                "desk_contact": {
                    "plane_z_mm": 0.0,
                    "strategy": (
                        "flat printable perimeter ring plus coplanar service "
                        "cover; four replaceable silicone desk pads carry "
                        "the installed assembly"
                    ),
                    "minimum_outer_span_mm": frame_outer,
                },
                "desk_pad_interface": {
                    "count": 4,
                    "positions_mm": (
                        (-60.0, -60.0),
                        (60.0, -60.0),
                        (-60.0, 60.0),
                        (63.0, 63.0),
                    ),
                    "pad_diameter_mm": 6.0,
                    "installed_pad_thickness_mm": 1.5,
                    "printed_mount_plane_z_mm": 0.0,
                    "desk_contact_plane_z_mm": -1.5,
                    "attachment": (
                        "replaceable pressure-sensitive adhesive silicone"
                    ),
                    "printed_base_remains_planar": True,
                    "support_required": False,
                    "lateral_footprint_extension_mm": 0.0,
                    "purpose": (
                        "anti-slip desk contact, fan vibration isolation and "
                        "a uniform secondary underbody air gap"
                    ),
                    "fixed_corner_load_island": {
                        "center_mm": desk_load_island_center,
                        "diameter_mm": 2 * desk_load_island_radius,
                        "height_mm": cover_plate_height,
                        "cover_radial_clearance_mm": tolerance_mm,
                        "existing_chassis_overlap_mm3": round(
                            desk_load_island_existing_overlap,
                            6,
                        ),
                        "added_chassis_volume_mm3": round(
                            desk_load_island_added_volume,
                            6,
                        ),
                        "modeled_as_chassis_geometry": True,
                        "single_solid_after_union": (
                            len(chassis_shape.val().Solids()) == 1
                        ),
                        "load_path": (
                            "desk pad directly into fixed chassis island; "
                            "removable electronics cover is unloaded"
                        ),
                    },
                },
                "controller_pod_center_mm": (pod_x, pod_y, 0.0),
                "controller_pod_frame_overlap_mm": pod_frame_overlap,
                "controller_pod_envelope_mm": (
                    pod_length,
                    pod_width,
                    pod_height,
                ),
                "controller_pod_minimum_wall_mm": (
                    pod_length - controller_service_opening_length
                )
                / 2,
                "controller_tower_stack": {
                    "levels": 2,
                    "layout": (
                        "DC-DC pair on lower tray; ESP32, MOSFET and "
                        "DS18B20 on upper tray"
                    ),
                    "fan_stacked_above": True,
                    "lateral_extension_from_cradle_mm": max(
                        0.0,
                        pod_x + pod_length / 2 - cradle_length / 2,
                    ),
                },
                "controller_cover_snap_slots": {
                    "count": len(snap_tab_y_positions),
                    "y_positions_mm": snap_tab_y_positions,
                    "slot_depth_mm": snap_slot_depth,
                    "slot_width_mm": snap_slot_width,
                    "slot_height_mm": snap_slot_height,
                    "slot_z_mm": snap_slot_z,
                    "slot_roof_strategy": (
                        "2 mm outward 45 degree lead-in with a retained "
                        "3 mm internal hook-stop ceiling"
                    ),
                    "slot_roof_chamfer_length_mm": (
                        snap_slot_roof_chamfer_length
                    ),
                    "maximum_flat_roof_span_mm": (
                        snap_slot_depth
                        - snap_slot_roof_chamfer_length
                    ),
                    "release_access": "through right service wall",
                },
                "controller_service_access": {
                    "usb_port_center_mm": (
                        pod_inner_x_wall_center,
                        usb_service_center_y,
                        usb_service_port_center_z,
                    ),
                    "usb_port_dimensions_mm": (
                        usb_service_port_width,
                        usb_service_port_height,
                    ),
                    "usb_plug_corridor_mm": (10.0, 9.0, 5.0),
                    "usb_plug_corridor_center_mm": (
                        pod_x - 31.0,
                        usb_service_center_y,
                        usb_service_center_z,
                    ),
                    "port_style": (
                        "rounded self-supporting inboard service arch"
                    ),
                    "port_bottom_z_mm": usb_service_port_bottom_z,
                    "port_roof_start_z_mm": (
                        usb_service_port_roof_start_z
                    ),
                    "port_top_z_mm": usb_service_port_top_z,
                    "port_crown_half_width_mm": (
                        usb_service_port_crown_half_width
                    ),
                    "port_effective_bridge_mm": (
                        usb_service_port_effective_bridge
                    ),
                    "port_minimum_roof_slope_deg": (
                        usb_service_port_minimum_roof_slope_deg
                    ),
                    "port_open_area_mm2": usb_service_port_area,
                    "residual_after_cut_mm3": (
                        usb_service_port_residual_after_cut_volume
                    ),
                    "modeled_as_geometry": True,
                },
                "lateral_airflow_windows_mm": (
                    intake_window_width,
                    intake_top_z - intake_bottom_z,
                ),
                "lateral_airflow_slot_count": intake_window_count,
                "lateral_airflow_area_mm2": intake_area,
                "lateral_airflow_ratio_to_fan": intake_area
                / (math.pi * (fan_size / 2.0) ** 2),
                "exterior_continuity": {
                    "continuous_top_rail": True,
                    "top_rail_minimum_mm": (
                        fan_deck_height - intake_top_z
                    ),
                    "continuous_lower_skirt": True,
                    "lower_skirt_minimum_mm": intake_bottom_z,
                    "window_count": intake_window_count,
                    "opening_width_mm": intake_window_width,
                    "minimum_continuous_side_web_mm": (
                        (frame_outer - intake_window_width) / 2
                    ),
                    "opening_style": (
                        "one continuous-tangent rounded-crown spline air "
                        "portal per face"
                    ),
                    "continuous_curvature_roof": True,
                    "roof_curve_kind": (
                        "symmetric self-supporting spline flanks with "
                        "tangent-continuous rounded crown"
                    ),
                    "roof_endpoint_tangents_constrained": True,
                    "crown_center_tangent_horizontal": True,
                    "crown_flank_tangent_continuity": True,
                    "crown_curve_kind": (
                        "quarter-sine interpolation with constrained "
                        "flank and center tangents"
                    ),
                    "crown_rise_mm": round(intake_crown_rise, 3),
                    "crown_shoulder_z_mm": round(
                        intake_crown_shoulder_z,
                        3,
                    ),
                    "roof_curve_amplitude_mm": (
                        intake_roof_curve_amplitude
                    ),
                    "roof_sample_count_per_side": len(
                        intake_roof_samples
                    ),
                    "roof_spring_line_z_mm": intake_roof_start_z,
                    "openings_break_outer_edge": False,
                    "maximum_opening_bridge_mm": round(
                        intake_closing_chord,
                        3,
                    ),
                    "repeated_vertical_mullion_count": 0,
                    "external_auxiliary_vent_slot_count": 0,
                    "outer_edge_break_count": 0,
                    "corner_radius_mm": 14.0,
                    "top_edge_radius_mm": chassis_top_edge_radius,
                    "portal_cut_margin_mm": portal_cut_margin,
                    "minimum_roof_slope_deg": round(
                        intake_minimum_roof_slope_deg,
                        3,
                    ),
                    "minimum_self_supporting_flank_slope_deg": round(
                        intake_minimum_roof_slope_deg,
                        3,
                    ),
                    "crown_local_minimum_slope_deg": 0.0,
                    "slicer_support_threshold_deg": (
                        slicer_support_threshold_deg
                    ),
                    "roof_slope_margin_deg": round(
                        intake_roof_slope_margin_deg,
                        3,
                    ),
                    "profile_fillet_radius_mm": (
                        intake_profile_fillet_radius
                    ),
                    "crown_bridge_mm": intake_closing_chord,
                    "crown_print_strategy": (
                        "one-layer integral tear-away bridge membrane"
                    ),
                    "crown_membrane_count": intake_window_count,
                    "crown_membrane_thickness_mm": (
                        intake_crown_membrane_thickness
                    ),
                    "crown_membrane_span_mm": (
                        intake_crown_membrane_span
                    ),
                    "crown_membrane_attachment_per_side_mm": (
                        intake_crown_membrane_attachment
                    ),
                    "crown_membrane_total_volume_mm3": round(
                        intake_crown_membrane_volume_per_portal
                        * intake_window_count,
                        3,
                    ),
                    "crown_membrane_estimated_petg_g": round(
                        intake_crown_membrane_volume_per_portal
                        * intake_window_count
                        * 1.27
                        / 1000,
                        4,
                    ),
                    "crown_membrane_removal_direction": (
                        "push outward through each open face before assembly"
                    ),
                    "crown_membrane_operationally_removed": True,
                },
                "controller_vent_pattern": {
                    "external_slot_count": 0,
                    "top_edge_radius_mm": pod_top_edge_radius,
                    "external_elliptical_port_count": 0,
                    "external_self_supporting_arch_count": 3,
                    "external_port_dimensions_mm": (
                        (
                            pod_external_snap_width,
                            pod_external_snap_height,
                        ),
                        (
                            pod_external_snap_width,
                            pod_external_snap_height,
                        ),
                        (
                            pod_external_cable_width,
                            pod_external_cable_height,
                        ),
                    ),
                    "external_snap_arch_geometry": {
                        "count": len(
                            pod_external_snap_center_offsets
                        ),
                        "width_mm": pod_external_snap_width,
                        "height_mm": pod_external_snap_height,
                        "bottom_z_mm": pod_external_snap_bottom_z,
                        "roof_start_z_mm": (
                            pod_external_snap_roof_start_z
                        ),
                        "top_z_mm": pod_external_snap_top_z,
                        "crown_half_width_mm": (
                            pod_external_snap_crown_half_width
                        ),
                        "effective_crown_bridge_mm": round(
                            pod_external_snap_closing_chord,
                            3,
                        ),
                        "minimum_roof_slope_deg": round(
                            pod_external_snap_minimum_roof_slope_deg,
                            3,
                        ),
                        "profile_fillet_radius_mm": (
                            pod_crossflow_profile_fillet_radius
                        ),
                        "continuous_central_load_rib_mm": 3.0,
                    },
                    "external_open_area_mm2": pod_external_open_area,
                    "external_visible_wall_open_ratio": (
                        pod_external_wall_open_ratio
                    ),
                    "external_minimum_continuous_web_mm": (
                        pod_external_minimum_web
                    ),
                    "external_maximum_closing_bridge_mm": round(
                        max(
                            pod_external_snap_closing_chord,
                            pod_external_cable_effective_bridge,
                        ),
                        3,
                    ),
                    "internal_elliptical_port_count": 0,
                    "internal_self_supporting_arch_count": 2,
                    "internal_port_dimensions_mm": (
                        pod_crossflow_width,
                        pod_crossflow_height,
                    ),
                    "internal_open_area_mm2": pod_crossflow_area,
                    "visible_wall_open_ratio": (
                        pod_crossflow_wall_open_ratio
                    ),
                    "minimum_continuous_web_mm": (
                        pod_crossflow_minimum_web
                    ),
                    "maximum_closing_bridge_mm": round(
                        pod_crossflow_closing_chord,
                        3,
                    ),
                    "internal_minimum_roof_slope_deg": round(
                        pod_crossflow_minimum_roof_slope_deg,
                        3,
                    ),
                    "external_arch_minimum_roof_slope_deg": round(
                        min(
                            pod_external_snap_minimum_roof_slope_deg,
                            pod_external_cable_minimum_roof_slope_deg,
                        ),
                        3,
                    ),
                    "arch_profile_fillet_radius_mm": (
                        pod_crossflow_profile_fillet_radius
                    ),
                    "strategy": (
                        "open internal top into fan plenum; two enlarged "
                        "rounded self-supporting inward arches, a full "
                        "self-supporting cable-side arch and two compact "
                        "snap-side arches with a continuous central load rib "
                        "continue the main chassis language through the "
                        "controller bay"
                    ),
                    "boolean_validation": {
                        "cutter_count": len(controller_portal_cutters),
                        "residual_intersection_volume_mm3": (
                            controller_portal_residual_after_cut_volume
                        ),
                        "functional_feature_volume_in_openings_mm3": (
                            controller_portal_functional_feature_volume
                        ),
                        "functional_feature": (
                            "two-arm cable strain-relief clamp behind the "
                            "cable-side opening"
                        ),
                        "kernel": "OpenCascade/CadQuery boolean intersection",
                    },
                },
                "controller_flow_obstruction": {
                    "projected_footprint_mm2": pod_length * pod_width,
                    "method": (
                        "conservative full controller envelope subtraction "
                        "from the fan disk"
                    ),
                },
                "cable_portal_mm": (12.0, wall_mm + 2.0, 6.0),
                "cable_strain_relief": {
                    "type": (
                        "integrated two-arm releasable PETG cable clamp"
                    ),
                    "arm_count": len(cable_clamp_arm_centers),
                    "arm_centers_mm": tuple(
                        (
                            x_pos,
                            cable_clamp_center_y,
                            cable_clamp_arm_bottom_z,
                        )
                        for x_pos in cable_clamp_arm_centers
                    ),
                    "arm_length_mm": cable_clamp_arm_length,
                    "arm_thickness_mm": cable_clamp_arm_thickness,
                    "clamp_depth_mm": cable_clamp_depth,
                    "host_part": "controller_cover",
                    "root_strategy": (
                        "both vertical cantilever arms embed directly into "
                        "the removable electronics carrier base"
                    ),
                    "root_z_mm": cable_clamp_arm_bottom_z,
                    "root_embed_depth_mm": (
                        cable_clamp_root_embed_depth
                    ),
                    "carrier_edge_inset_mm": (
                        cable_clamp_carrier_edge_inset
                    ),
                    "horizontal_anchor_count": 0,
                    "maximum_unsupported_root_span_mm": 0.0,
                    "target_bundle_diameter_mm": (
                        cable_clamp_target_diameter
                    ),
                    "relaxed_throat_mm": cable_clamp_throat,
                    "hook_overlap_mm": cable_clamp_hook_overlap,
                    "hook_flat_stop_span_mm": (
                        cable_clamp_hook_flat_span
                    ),
                    "hook_self_supporting_ramp_angle_deg": 45.0,
                    "hook_height_mm": cable_clamp_hook_height,
                    "required_deflection_per_arm_mm": (
                        cable_clamp_required_deflection
                    ),
                    "nominal_surface_strain": (
                        cable_clamp_nominal_strain
                    ),
                    "recommended_petg_strain_limit": 0.02,
                    "lead_in_angle_deg": 45.0,
                    "portal_center_mm": (
                        cable_clamp_center_x,
                        pod_y + pod_width / 2 + 2.0,
                        cable_clamp_portal_center_z,
                    ),
                    "minimum_ds18b20_keepout_clearance_mm": 0.5,
                    "service_method": (
                        "thread the cable through the portal, press the "
                        "sleeved bundle downward between the two hooks, "
                        "and flex both arms outward to release"
                    ),
                    "modeled_as_geometry": True,
                    "fastener_free": True,
                    "support_free": True,
                },
                "cradle_interface": {
                    "type": "keyed locating pins plus gravity seat",
                    "pin_positions_mm": locating_pin_positions,
                    "keyed_pin_position_mm": keyed_pin_position,
                    "pin_height_mm": locating_pin_height,
                    "pin_embed_depth_mm": locating_pin_embed_depth,
                    "anchor_mm": (
                        locating_pin_anchor_effective_length,
                        locating_pin_anchor_width,
                        locating_pin_anchor_height,
                    ),
                    "anchor_support_strategy": (
                        "orthogonal X-wall beam with a fan-clear flat "
                        "bridge followed by a 45 degree outboard gusset"
                    ),
                    "anchor_fan_clearance_mm": (
                        locating_pin_anchor_fan_clearance
                    ),
                    "anchor_maximum_flat_span_mm": (
                        locating_pin_anchor_flat_span
                    ),
                    "anchor_gusset_drop_mm": (
                        locating_pin_anchor_gusset_drop
                    ),
                    "anchor_gusset_angle_deg": 45.0,
                    "radial_clearance_mm": tolerance_mm,
                },
                "hardware_references": [
                    {
                        "name": "120 mm PWM fan",
                        "dimensions_mm": (
                            fan_size,
                            fan_size,
                            fan_installed_height,
                        ),
                        "translation_mm": (
                            0.0,
                            0.0,
                            electronics_layer_height + wall_mm,
                        ),
                        "color_rgb": (0.16, 0.18, 0.2),
                        "opacity": 0.38,
                    },
                    {
                        "name": "12V DC-DC module",
                        "dimensions_mm": SMART_FAN_DEFAULT_ENVELOPES_MM[
                            "12V DC-DC module"
                        ],
                        "translation_mm": (
                            pod_x - 13.5,
                            pod_y,
                            cover_plate_height + 0.5,
                        ),
                        "color_rgb": (0.18, 0.55, 0.34),
                        "opacity": 0.5,
                    },
                    {
                        "name": "5V DC-DC module",
                        "dimensions_mm": SMART_FAN_DEFAULT_ENVELOPES_MM[
                            "5V DC-DC module"
                        ],
                        "translation_mm": (
                            pod_x + 13.5,
                            pod_y,
                            cover_plate_height + 0.5,
                        ),
                        "color_rgb": (0.22, 0.48, 0.8),
                        "opacity": 0.5,
                    },
                    {
                        "name": "ESP32-C3 Super Mini",
                        "dimensions_mm": SMART_FAN_DEFAULT_ENVELOPES_MM[
                            "ESP32-C3 Super Mini"
                        ],
                        "translation_mm": (
                            pod_x - 13.5,
                            pod_y - 11.0,
                            20.0,
                        ),
                        "color_rgb": (0.78, 0.3, 0.22),
                        "opacity": 0.5,
                    },
                    {
                        "name": "MOSFET PWM driver",
                        "dimensions_mm": SMART_FAN_DEFAULT_ENVELOPES_MM[
                            "MOSFET PWM driver"
                        ],
                        "translation_mm": (
                            pod_x + 13.5,
                            pod_y - 12.0,
                            20.0,
                        ),
                        "color_rgb": (0.72, 0.46, 0.18),
                        "opacity": 0.5,
                    },
                    {
                        "name": (
                            f"DS18B20 Ø{probe_diameter:g} mm "
                            "temperature probe"
                        ),
                        "dimensions_mm": (
                            SMART_FAN_DEFAULT_ENVELOPES_MM[
                                "DS18B20 temperature probe"
                            ][0],
                            probe_diameter,
                            probe_diameter,
                        ),
                        "translation_mm": (
                            pod_x + probe_center_local[0],
                            pod_y + probe_center_local[1],
                            probe_center_local[2],
                        ),
                        "color_rgb": (0.74, 0.74, 0.78),
                        "opacity": 0.5,
                    },
                ],
            },
        )

        # Keep the flat base at its compact 52.5 mm production footprint.
        # Structure-specific self-supporting corbels below the outboard rails
        # and snap roots carry their Z=3.2-3.3 mm undersides without paying
        # for a full-width 54.9 mm plate.
        cover_base_length = cover_length
        cover_shape = _rounded_box(
            cover_base_length,
            cover_width,
            cover_plate_height,
            min(12.0, cover_base_length / 3),
        )
        cover_vent_length = min(40.0, cover_width - 12.0)
        cover_vent_width = 6.0
        cover_vent_x_positions = (-13.0, 13.0)
        for x_pos in cover_vent_x_positions:
            vent = _rounded_box(
                cover_vent_width,
                cover_vent_length,
                cover_plate_height + 1.0,
                cover_vent_width / 2,
            ).translate((x_pos, 0.0, 0.0))
            cover_shape = cover_shape.cut(vent)

        # The cable clamp belongs to the removable carrier, not the fixed
        # chassis. Its two long arms rise vertically from the solid rear edge
        # of the carrier, so there is no horizontal root overhang and no
        # obstruction to the carrier's -Z service path. Each hook is a full
        # 45 degree elastic barb with no horizontal underside.
        cable_clamp_center_y_local = cable_clamp_center_y - pod_y
        for index, arm_center_x_global in enumerate(
            cable_clamp_arm_centers
        ):
            side = 1.0 if index == 0 else -1.0
            arm_center_x = arm_center_x_global - pod_x
            arm_inner_x = arm_center_x + side * (
                cable_clamp_arm_thickness / 2
            )
            hook_root_x = arm_inner_x
            hook_tip_x = (
                arm_inner_x + side * cable_clamp_hook_overlap
            )
            hook_ramp_height = (
                cable_clamp_hook_overlap
                - cable_clamp_hook_flat_span
            )
            arm = (
                cq.Workplane("XY")
                .box(
                    cable_clamp_arm_thickness,
                    cable_clamp_depth,
                    cable_clamp_arm_length,
                    centered=(True, True, False),
                )
                .translate(
                    (
                        arm_center_x,
                        cable_clamp_center_y_local,
                        cable_clamp_arm_bottom_z,
                    )
                )
            )
            hook = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (
                            hook_root_x,
                            cable_clamp_hook_bottom_z
                            + hook_ramp_height,
                        ),
                        (
                            hook_tip_x,
                            cable_clamp_hook_bottom_z,
                        ),
                        (
                            hook_root_x,
                            cable_clamp_hook_bottom_z
                            + cable_clamp_hook_height,
                        ),
                    )
                )
                .close()
                .extrude(cable_clamp_depth / 2, both=True)
                .translate((0.0, cable_clamp_center_y_local, 0.0))
            )
            cover_shape = cover_shape.union(arm).union(hook)

        # The removable underside cover is also the electronics carrier.
        # Lower standoffs locate both DC-DC boards. Two edge rails and a
        # center divider rise through the 2 mm gap between those boards and
        # support the ESP32, MOSFET and DS18B20 keep-out on a second level.
        lower_standoff_height = 0.5
        lower_standoff_diameter = 4.0
        lower_standoff_positions = tuple(
            (x_pos, y_pos)
            for x_pos in (-21.0, -6.0, 6.0, 21.0)
            for y_pos in (-17.0, 17.0)
        )
        for x_pos, y_pos in lower_standoff_positions:
            standoff = (
                cq.Workplane("XY")
                .workplane(offset=cover_plate_height)
                .center(x_pos, y_pos)
                .circle(lower_standoff_diameter / 2)
                .extrude(lower_standoff_height)
            )
            cover_shape = cover_shape.union(standoff)

        # Each DC-DC board is inserted vertically between a pair of long,
        # low-strain cantilever hooks. The hooks sit outside the 45 mm board
        # edges, so the nominal installed keep-out has 0.25 mm clearance and
        # the hooks only deflect during insertion or release.
        dc_board_centers_x = (-13.5, 13.5)
        dc_board_half_y = 22.5
        dc_terminal_height_above_pcb = 8.0
        dc_pcb_thickness = 1.6
        dc_clip_arm_thickness = 1.6
        dc_clip_width = 3.0
        dc_clip_hook_overlap = 0.5
        dc_clip_hook_height = 0.7
        dc_clip_required_deflection = (
            dc_clip_hook_overlap - tolerance_mm
        )
        dc_clip_arm_center_y = (
            dc_board_half_y
            + tolerance_mm
            + dc_clip_arm_thickness / 2
        )
        dc_retention_surface_z = (
            cover_plate_height
            + lower_standoff_height
            + dc_pcb_thickness
            + dc_terminal_height_above_pcb
        )
        dc_clip_hook_bottom_z = (
            dc_retention_surface_z + tolerance_mm
        )
        dc_clip_arm_length = (
            dc_clip_hook_bottom_z - cover_plate_height
        )
        dc_clip_nominal_strain = (
            1.5
            * dc_clip_arm_thickness
            * dc_clip_required_deflection
            / dc_clip_arm_length**2
        )
        dc_clip_arm_centers = []
        for board_center_x in dc_board_centers_x:
            for side in (-1.0, 1.0):
                arm_center_y = side * dc_clip_arm_center_y
                arm_inner_y = side * (
                    dc_clip_arm_center_y
                    - dc_clip_arm_thickness / 2
                )
                hook_root_y = arm_inner_y + side * 0.2
                hook_tip_y = (
                    arm_inner_y - side * dc_clip_hook_overlap
                )
                arm = (
                    cq.Workplane("XY")
                    .box(
                        dc_clip_width,
                        dc_clip_arm_thickness,
                        dc_clip_arm_length,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            board_center_x,
                            arm_center_y,
                            cover_plate_height,
                        )
                    )
                )
                hook = (
                    cq.Workplane("YZ")
                    .polyline(
                        (
                            (hook_root_y, dc_clip_hook_bottom_z),
                            (hook_tip_y, dc_clip_hook_bottom_z),
                            (
                                hook_root_y,
                                dc_clip_hook_bottom_z
                                + dc_clip_hook_height,
                            ),
                        )
                    )
                    .close()
                    .extrude(dc_clip_width / 2, both=True)
                    .translate((board_center_x, 0.0, 0.0))
                )
                dc_clip_arm_centers.append(
                    (
                        board_center_x,
                        arm_center_y,
                        cover_plate_height,
                    )
                )
                cover_shape = cover_shape.union(arm).union(hook)

        upper_support_height = 16.0
        support_rail_thickness = controller_side_rail_thickness
        support_ledge_width = 2.4
        support_ledge_height = 0.8
        support_point_length = 4.0
        support_point_y_positions = (-12.0,)
        side_rail_x_positions = (
            -controller_side_rail_center,
            controller_side_rail_center,
        )
        for rail_x in side_rail_x_positions:
            ledge_x = rail_x - math.copysign(
                support_ledge_width / 2 - support_rail_thickness / 2,
                rail_x,
            )
            for support_y in support_point_y_positions:
                support_post = (
                    cq.Workplane("XY")
                    .box(
                        support_rail_thickness,
                        support_point_length,
                        upper_support_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            rail_x,
                            support_y,
                            cover_plate_height,
                        )
                    )
                )
                support_point = (
                    cq.Workplane("XY")
                    .box(
                        support_ledge_width,
                        support_point_length,
                        support_ledge_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            ledge_x,
                            support_y,
                            cover_plate_height
                            + upper_support_height
                            - support_ledge_height,
                        )
                    )
                )
                cover_shape = (
                    cover_shape.union(support_post).union(support_point)
                )
            rail_side = 1.0 if rail_x > 0 else -1.0
            rail_anchor = (
                cq.Workplane("XY")
                .box(
                    support_rail_thickness + 0.2,
                    support_point_length,
                    0.5,
                    centered=(True, True, False),
                )
                .translate(
                    (
                        rail_side
                        * (controller_side_rail_center - 0.1),
                        -12.0,
                        cover_plate_height - 0.1,
                    )
                )
            )
            cover_shape = cover_shape.union(rail_anchor)
        center_divider_width = 1.5
        center_support_points = []
        for support_y in support_point_y_positions:
            center_post = (
                cq.Workplane("XY")
                .box(
                    center_divider_width,
                    support_point_length,
                    upper_support_height,
                    centered=(True, True, False),
                )
                .translate((0.0, support_y, cover_plate_height))
            )
            center_support = (
                cq.Workplane("XY")
                .box(
                    2.0,
                    support_point_length,
                    support_ledge_height,
                    centered=(True, True, False),
                )
                .translate(
                    (
                        0.0,
                        support_y,
                        cover_plate_height
                        + upper_support_height
                        - support_ledge_height,
                    )
                )
            )
            center_support_points.append(center_support)
            cover_shape = (
                cover_shape.union(center_post).union(center_support)
            )

        # The upper ESP32 and MOSFET boards use the same outer rails and
        # center divider as vertical cantilever arms. Paired hooks prevent
        # lift-out; two edge guides per board constrain Y without crossing
        # through the lower DC-DC envelopes.
        upper_clip_width = 1.0
        upper_clip_hook_overlap = 0.5
        upper_clip_hook_height = 0.55
        upper_clip_required_deflection = (
            upper_clip_hook_overlap - tolerance_mm
        )
        upper_guide_thickness = 1.0
        upper_guide_inward_depth = 2.0
        upper_guide_height = 1.0
        upper_guide_post_height = (
            20.0 + upper_guide_height - cover_plate_height
        )
        upper_component_clip_specs = (
            {
                "name": "ESP32-C3 Super Mini",
                "side": -1.0,
                "retention_surface_z": 21.2,
                "component_top_z": 26.0,
                "hook_y": -21.5,
                "y_edges": (-22.0, 0.0),
            },
            {
                "name": "MOSFET PWM driver",
                "side": 1.0,
                "retention_surface_z": 21.6,
                "component_top_z": 28.0,
                "hook_y": -19.0,
                "y_edges": (-19.5, -4.5),
            },
        )
        upper_component_retention = []
        upper_rail_base_corbels = []
        upper_rail_corbel_rise = cover_plate_height - 0.1
        upper_rail_corbel_run = (
            controller_carrier_outer_span - cover_base_length
        ) / 2
        upper_rail_corbel_slope_deg = math.degrees(
            math.atan2(
                upper_rail_corbel_rise,
                upper_rail_corbel_run,
            )
        )
        for component in upper_component_clip_specs:
            side = float(component["side"])
            direction_to_board = -side
            hook_bottom_z = (
                float(component["retention_surface_z"])
                + tolerance_mm
            )
            outer_arm_center_x = side * controller_side_rail_center
            outer_inner_x = side * controller_side_rail_inner_face
            outer_hook_root_x = (
                outer_inner_x - direction_to_board * 0.05
            )
            outer_hook_tip_x = (
                outer_inner_x
                + direction_to_board * upper_clip_hook_overlap
            )
            center_face_x = side * center_divider_width / 2
            center_hook_root_x = center_face_x - side * 0.05
            center_hook_tip_x = (
                center_face_x + side * upper_clip_hook_overlap
            )
            arm_height = hook_bottom_z - cover_plate_height
            hook_y = float(component["hook_y"])
            outer_rail_y_min = min(component["y_edges"]) - (
                tolerance_mm + upper_guide_thickness
            )
            outer_rail_y_max = max(component["y_edges"]) + (
                tolerance_mm + upper_guide_thickness
            )
            outer_rail_y_center = (
                outer_rail_y_min + outer_rail_y_max
            ) / 2
            outer_rail_y_length = (
                outer_rail_y_max - outer_rail_y_min
            )
            outer_base_bridge_height = 0.6
            outer_base_bridge = (
                cq.Workplane("XY")
                .box(
                    support_rail_thickness,
                    outer_rail_y_length,
                    outer_base_bridge_height,
                    centered=(True, True, False),
                )
                .translate(
                    (
                        outer_arm_center_x,
                        outer_rail_y_center,
                        cover_plate_height - 0.1,
                    )
                )
            )
            base_plate_edge_x = side * (cover_base_length / 2)
            outer_rail_edge_x = side * (
                controller_side_rail_center
                + support_rail_thickness / 2
            )
            outer_base_bridge_bottom_z = cover_plate_height - 0.1
            outer_base_corbel = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (base_plate_edge_x, 0.0),
                        (
                            base_plate_edge_x,
                            outer_base_bridge_bottom_z,
                        ),
                        (
                            outer_rail_edge_x,
                            outer_base_bridge_bottom_z,
                        ),
                    )
                )
                .close()
                .extrude(outer_rail_y_length / 2, both=True)
                .translate((0.0, outer_rail_y_center, 0.0))
            )
            upper_rail_base_corbels.append(outer_base_corbel)
            outer_arm = (
                cq.Workplane("XY")
                .box(
                    support_rail_thickness,
                    upper_clip_width,
                    arm_height,
                    centered=(True, True, False),
                )
                .translate(
                    (
                        outer_arm_center_x,
                        hook_y,
                        cover_plate_height,
                    )
                )
            )
            center_arm = (
                cq.Workplane("XY")
                .box(
                    center_divider_width,
                    upper_clip_width,
                    arm_height,
                    centered=(True, True, False),
                )
                .translate((0.0, hook_y, cover_plate_height))
            )
            outer_hook = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (outer_hook_root_x, hook_bottom_z),
                        (outer_hook_tip_x, hook_bottom_z),
                        (
                            outer_hook_root_x,
                            hook_bottom_z + upper_clip_hook_height,
                        ),
                    )
                )
                .close()
                .extrude(upper_clip_width / 2, both=True)
                .translate((0.0, hook_y, 0.0))
            )
            center_hook = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (center_hook_root_x, hook_bottom_z),
                        (center_hook_tip_x, hook_bottom_z),
                        (
                            center_hook_root_x,
                            hook_bottom_z + upper_clip_hook_height,
                        ),
                    )
                )
                .close()
                .extrude(upper_clip_width / 2, both=True)
                .translate((0.0, hook_y, 0.0))
            )
            cover_shape = (
                cover_shape
                .union(outer_base_corbel)
                .union(outer_base_bridge)
                .union(outer_arm)
                .union(center_arm)
                .union(outer_hook)
                .union(center_hook)
            )
            guide_centers = []
            for y_edge in component["y_edges"]:
                edge_side = -1.0 if y_edge < -10.0 else 1.0
                guide_center_y = float(y_edge) + edge_side * (
                    tolerance_mm + upper_guide_thickness / 2
                )
                guide_post = (
                    cq.Workplane("XY")
                    .box(
                        support_rail_thickness,
                        upper_guide_thickness,
                        upper_guide_post_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            outer_arm_center_x,
                            guide_center_y,
                            cover_plate_height,
                        )
                    )
                )
                guide_nib_center_x = outer_inner_x + (
                    direction_to_board
                    * upper_guide_inward_depth
                    / 2
                )
                guide_nib = (
                    cq.Workplane("XY")
                    .box(
                        upper_guide_inward_depth,
                        upper_guide_thickness,
                        upper_guide_height,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            guide_nib_center_x,
                            guide_center_y,
                            20.0,
                        )
                    )
                )
                guide_centers.append(
                    (
                        guide_nib_center_x,
                        guide_center_y,
                        20.0,
                    )
                )
                cover_shape = (
                    cover_shape.union(guide_post).union(guide_nib)
                )
            upper_component_retention.append(
                {
                    "name": component["name"],
                    "hook_bottom_z_mm": hook_bottom_z,
                    "hook_pair_count": 1,
                    "guide_pair_count": 1,
                    "guide_centers_mm": tuple(guide_centers),
                    "required_deflection_mm": (
                        upper_clip_required_deflection
                    ),
                }
            )

        # The metal DS18B20 capsule is now a defined service component rather
        # than a loose keep-out. Two horizontal bearing blocks on the rear
        # edge of the removable carrier locate the Ø6 mm probe immediately
        # below the fan guard. The capsule slides through the 0.25 mm-clearance
        # bores after the carrier is removed; the existing releasable cable
        # clamp prevents axial pull-out in service.
        probe_block_height = (
            probe_block_top_z - probe_block_bottom_z
        )
        probe_bearing_blocks = []
        for station_x in probe_station_x_positions:
            block = (
                cq.Workplane("XY")
                .box(
                    probe_block_width,
                    probe_block_depth,
                    probe_block_height,
                    centered=(True, True, False),
                )
                .translate(
                    (
                        station_x,
                        probe_center_local[1],
                        probe_block_bottom_z,
                    )
                )
            )
            bore = (
                cq.Workplane("YZ")
                .center(
                    probe_center_local[1],
                    probe_center_local[2],
                )
                .circle(probe_bore_diameter / 2)
                .extrude(probe_block_width / 2 + 0.4, both=True)
                .translate((station_x, 0.0, 0.0))
            )
            entry_slot_height = (
                probe_block_top_z - probe_center_local[2] + 0.2
            )
            entry_slot = (
                cq.Workplane("YZ")
                .center(
                    probe_center_local[1],
                    probe_center_local[2] + entry_slot_height / 2,
                )
                .rect(probe_entry_slot_width, entry_slot_height)
                .extrude(probe_block_width / 2 + 0.4, both=True)
                .translate((station_x, 0.0, 0.0))
            )
            bearing = block.cut(bore.union(entry_slot))
            probe_bearing_blocks.append(bearing)
            cover_shape = cover_shape.union(bearing)
        probe_platform_height = 0.7
        probe_platform = (
            cq.Workplane("XY")
            .box(
                9.0,
                probe_block_depth,
                probe_platform_height,
                centered=(True, True, False),
            )
            .translate(
                (
                    0.0,
                    probe_center_local[1],
                    probe_block_bottom_z - probe_platform_height,
                )
            )
        )
        probe_column_width = 1.0
        probe_column_height = (
            probe_block_bottom_z
            - probe_platform_height
            - cover_plate_height
        )
        probe_support_column = (
            cq.Workplane("XY")
            .box(
                probe_column_width,
                probe_block_depth,
                probe_column_height,
                centered=(True, True, False),
            )
            .translate(
                (
                    0.0,
                    probe_center_local[1],
                    cover_plate_height,
                )
            )
        )
        probe_platform_width = 9.0
        probe_platform_corbel_run = (
            probe_platform_width - probe_column_width
        ) / 2
        probe_platform_corbel_rise = probe_platform_corbel_run
        probe_platform_corbel_slope_deg = math.degrees(
            math.atan2(
                probe_platform_corbel_rise,
                probe_platform_corbel_run,
            )
        )
        probe_platform_corbel_depth = probe_block_depth
        probe_platform_corbels = []
        for side in (-1.0, 1.0):
            column_face_x = side * probe_column_width / 2
            platform_edge_x = side * probe_platform_width / 2
            corbel = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (
                            column_face_x,
                            probe_block_bottom_z
                            - probe_platform_height
                            - probe_platform_corbel_rise,
                        ),
                        (
                            column_face_x,
                            probe_block_bottom_z
                            - probe_platform_height,
                        ),
                        (
                            platform_edge_x,
                            probe_block_bottom_z
                            - probe_platform_height,
                        ),
                    )
                )
                .close()
                .extrude(
                    probe_platform_corbel_depth / 2,
                    both=True,
                )
                .translate((0.0, probe_center_local[1], 0.0))
            )
            probe_platform_corbels.append(corbel)
        cover_shape = (
            cover_shape
            .union(probe_support_column)
            .union(probe_platform)
        )
        for corbel in probe_platform_corbels:
            cover_shape = cover_shape.union(corbel)

        tab_panel_embed = 0.0
        tab_center_x = (
            controller_side_rail_inner_face
            + snap_tab_thickness / 2
            - tab_panel_embed
        )
        tab_outer_x = tab_center_x + snap_tab_thickness / 2
        snap_tab_base_corbels = []
        snap_root_corbel_rise = cover_plate_height
        snap_root_corbel_run = (
            tab_outer_x - cover_base_length / 2
        )
        snap_root_corbel_slope_deg = math.degrees(
            math.atan2(
                snap_root_corbel_rise,
                snap_root_corbel_run,
            )
        )
        for y_pos in snap_tab_y_positions:
            snap_root_corbel = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (cover_base_length / 2, 0.0),
                        (
                            cover_base_length / 2,
                            cover_plate_height,
                        ),
                        (tab_outer_x, cover_plate_height),
                    )
                )
                .close()
                .extrude(snap_tab_width / 2, both=True)
                .translate((0.0, y_pos, 0.0))
            )
            snap_tab_base_corbels.append(snap_root_corbel)
            tab_anchor = (
                cq.Workplane("XY")
                .box(
                    1.2,
                    snap_tab_width,
                    0.6,
                    centered=(True, True, False),
                )
                .translate(
                    (
                        controller_side_rail_inner_face,
                        y_pos,
                        cover_plate_height - 0.2,
                    )
                )
            )
            tab = (
                cq.Workplane("XY")
                .box(
                    snap_tab_thickness,
                    snap_tab_width,
                    snap_tab_length,
                    centered=(True, True, False),
                )
                .translate(
                    (
                        tab_center_x,
                        y_pos,
                        cover_plate_height,
                    )
                )
            )
            hook = (
                cq.Workplane("XZ")
                .polyline(
                    (
                        (
                            tab_outer_x,
                            cover_plate_height + snap_tab_length,
                        ),
                        (
                            tab_outer_x + snap_hook_extension,
                            cover_plate_height + snap_tab_length - 0.6,
                        ),
                        (
                            tab_outer_x + snap_hook_extension,
                            cover_plate_height
                            + snap_tab_length
                            - snap_hook_height,
                        ),
                        (
                            tab_outer_x,
                            cover_plate_height
                            + snap_tab_length
                            - snap_hook_height,
                        ),
                    )
                )
                .close()
                .extrude(snap_tab_width / 2, both=True)
                .translate((0.0, y_pos, 0.0))
            )
            cover_shape = (
                cover_shape
                .union(snap_root_corbel)
                .union(tab_anchor)
                .union(tab)
                .union(hook)
            )
        dc_terminal_tool_zones = []
        dc_terminal_top_z = (
            cover_plate_height
            + lower_standoff_height
            + dc_pcb_thickness
            + dc_terminal_height_above_pcb
        )
        dc_terminal_tool_height = pod_height - (
            dc_terminal_top_z + 0.1
        )
        for board_center_x in dc_board_centers_x:
            for screw_x in (
                board_center_x - 5.0,
                board_center_x + 5.0,
            ):
                for terminal_y in (
                    -dc_board_half_y + 3.0,
                    dc_board_half_y - 3.0,
                ):
                    dc_terminal_tool_zones.append(
                        {
                            "name": (
                                f"DC 端子工具区 "
                                f"{len(dc_terminal_tool_zones) + 1}"
                            ),
                            "kind": "terminal_tool",
                            "dimensions_mm": (
                                3.5,
                                3.5,
                                dc_terminal_tool_height,
                            ),
                            "center_mm": (
                                screw_x,
                                terminal_y,
                                dc_terminal_top_z
                                + 0.1
                                + dc_terminal_tool_height / 2,
                            ),
                            "available_after": (
                                "先拆下上层 ESP32 与 MOSFET"
                            ),
                        }
                    )
        mosfet_terminal_tool_zones = []
        mosfet_center_x = 13.5
        mosfet_center_y = -12.0
        mosfet_terminal_top_z = 20.0 + 1.6 + 5.0
        mosfet_terminal_tool_height = 12.0
        for terminal_x in (
            mosfet_center_x - 9.5,
            mosfet_center_x + 9.5,
        ):
            for screw_y in (
                mosfet_center_y - 3.0,
                mosfet_center_y + 3.0,
            ):
                mosfet_terminal_tool_zones.append(
                    {
                        "name": (
                            f"MOSFET 端子工具区 "
                            f"{len(mosfet_terminal_tool_zones) + 1}"
                        ),
                        "kind": "terminal_tool",
                        "dimensions_mm": (
                            3.2,
                            3.2,
                            mosfet_terminal_tool_height,
                        ),
                        "center_mm": (
                            terminal_x,
                            screw_y,
                            mosfet_terminal_top_z
                            + 0.1
                            + mosfet_terminal_tool_height / 2,
                        ),
                        "available_after": (
                            "将载架从机架取出后"
                        ),
                    }
                )
        release_tool_zones = []
        dc_release_start_z = (
            dc_clip_hook_bottom_z + dc_clip_hook_height + 0.1
        )
        for arm_x, arm_y, _ in dc_clip_arm_centers:
            release_tool_zones.append(
                {
                    "name": (
                        f"DC 卡钩释放区 "
                        f"{len(release_tool_zones) + 1}"
                    ),
                    "kind": "clip_release",
                    "dimensions_mm": (
                        dc_clip_width,
                        3.0,
                        pod_height - dc_release_start_z,
                    ),
                    "center_mm": (
                        arm_x,
                        arm_y,
                        (
                            dc_release_start_z
                            + pod_height
                        )
                        / 2,
                    ),
                    "available_after": (
                        "将载架从机架取出后"
                    ),
                }
            )
        for component in upper_component_retention:
            side = next(
                float(spec["side"])
                for spec in upper_component_clip_specs
                if spec["name"] == component["name"]
            )
            hook_y = next(
                float(spec["hook_y"])
                for spec in upper_component_clip_specs
                if spec["name"] == component["name"]
            )
            release_start_z = (
                float(component["hook_bottom_z_mm"])
                + upper_clip_hook_height
                + 0.1
            )
            for hook_x in (
                side * controller_side_rail_center,
                0.0,
            ):
                release_tool_zones.append(
                    {
                        "name": (
                            f"{component['name']} 卡钩释放区 "
                            f"{1 if hook_x else 2}"
                        ),
                        "kind": "clip_release",
                        "dimensions_mm": (
                            1.6,
                            2.0,
                            pod_height - release_start_z,
                        ),
                        "center_mm": (
                            hook_x,
                            hook_y,
                            (
                                release_start_z
                                + pod_height
                            )
                            / 2,
                        ),
                        "available_after": (
                            "将载架从机架取出后"
                        ),
                    }
                )
        electronics_service_access = {
            "coordinate_space": "controller_cover_local",
            "carrier_removal_direction": "-Z",
            "carrier_payload_components": (
                "12V DC-DC module",
                "5V DC-DC module",
                "ESP32-C3 Super Mini",
                "MOSFET PWM driver",
            ),
            "carrier_path_test_distance_mm": 30.0,
            "carrier_path_test_increment_mm": 2.0,
            "usb_corridor": {
                "name": "ESP32 USB 插拔通道",
                "kind": "usb_service",
                "dimensions_mm": (10.0, 9.0, 5.0),
                "center_mm": (
                    -31.0,
                    -11.0,
                    usb_service_center_z,
                ),
                "available_after": "无需拆机",
            },
            "terminal_tool_zones": tuple(
                [
                    *dc_terminal_tool_zones,
                    *mosfet_terminal_tool_zones,
                ]
            ),
            "release_tool_zones": tuple(release_tool_zones),
            "service_sequence": (
                "断电并拔下外部线束",
                "抬起底座或将断电后的组件翻转",
                "从底部向内按压两个盖板卡扣",
                "将装有四块 PCB 的载架垂直向下抽出",
                "释放线缆夹并向上提取 DS18B20 金属探头",
                "先释放 ESP32 与 MOSFET，再维护 DC 端子",
                "逐块释放 DC-DC，并在载架外完成接线维护",
            ),
            "fastener_free": True,
        }
        desk_load_island_clearance_local = (
            desk_load_island_center[0] - pod_x,
            desk_load_island_center[1] - pod_y,
        )
        desk_load_island_clearance = (
            cq.Workplane("XY")
            .center(*desk_load_island_clearance_local)
            .circle(desk_load_island_clearance_radius)
            .extrude(cover_plate_height + 0.2)
        )
        cover_volume_before_desk_island_clearance = float(
            cover_shape.val().Volume()
        )
        cover_shape = cover_shape.cut(desk_load_island_clearance).clean()
        desk_load_island_clearance_removed_volume = (
            cover_volume_before_desk_island_clearance
            - float(cover_shape.val().Volume())
        )
        cover_bounds = cover_shape.val().BoundingBox()
        cover_actual_dimensions = (
            round(float(cover_bounds.xlen), 3),
            round(float(cover_bounds.ylen), 3),
            round(float(cover_bounds.zlen), 3),
        )
        controller_cover = CADPart(
            "controller_cover",
            cover_shape,
            {
                "dimensions_mm": cover_actual_dimensions,
                "nominal_panel_dimensions_mm": (
                    cover_length,
                    cover_width,
                    cover_height,
                ),
                "plate_height_mm": cover_plate_height,
                "mounting_face": "flush underside service cassette",
                "desk_contact_plane_z_mm": 0.0,
                "flush_to_chassis_bottom": True,
                "wall_thickness_mm": wall_mm,
                "material": material,
                "joint": "serviceable cantilever snap fit",
                "tolerance_mm": tolerance_mm,
                "print_orientation": "outer face on build plate",
                "support_strategy": "none",
                "fixed_corner_load_island_clearance": {
                    "center_local_mm": desk_load_island_clearance_local,
                    "radius_mm": desk_load_island_clearance_radius,
                    "radial_clearance_mm": tolerance_mm,
                    "height_mm": cover_plate_height + 0.2,
                    "removed_cover_volume_mm3": round(
                        desk_load_island_clearance_removed_volume,
                        6,
                    ),
                    "support_required": False,
                    "purpose": (
                        "verify the existing rounded cover corner remains "
                        "outside the fixed chassis desk-load island; the "
                        "clearance cutter removes no production material"
                    ),
                },
                "component_retention": {
                    "lower_dc_dc_standoff_count": len(
                        lower_standoff_positions
                    ),
                    "lower_standoff_height_mm": lower_standoff_height,
                    "lower_standoff_diameter_mm": lower_standoff_diameter,
                    "upper_side_rail_count": len(side_rail_x_positions),
                    "upper_support_height_mm": upper_support_height,
                    "upper_support_point_count": (
                        len(side_rail_x_positions) + 1
                    )
                    * len(support_point_y_positions),
                    "center_divider_width_mm": center_divider_width,
                    "upper_support_style": (
                        "three discrete self-supporting locator posts"
                    ),
                    "maximum_ledge_cantilever_mm": (
                        support_ledge_width - support_rail_thickness
                    ),
                    "carrier_outer_span_mm": (
                        controller_carrier_outer_span
                    ),
                    "service_opening_length_mm": (
                        controller_service_opening_length
                    ),
                    "side_rail_inner_face_mm": (
                        controller_side_rail_inner_face
                    ),
                    "side_rail_clearance_mm": tolerance_mm,
                    "self_supporting_base_corbels": {
                        "modeled_as_geometry": True,
                        "rail_corbel_count": len(
                            upper_rail_base_corbels
                        ),
                        "snap_root_corbel_count": len(
                            snap_tab_base_corbels
                        ),
                        "total_count": (
                            len(upper_rail_base_corbels)
                            + len(snap_tab_base_corbels)
                        ),
                        "base_plate_length_mm": cover_base_length,
                        "carrier_outer_span_mm": (
                            round(controller_carrier_outer_span, 3)
                        ),
                        "service_opening_length_mm": (
                            round(controller_service_opening_length, 3)
                        ),
                        "rail_corbel_run_mm": (
                            round(upper_rail_corbel_run, 3)
                        ),
                        "rail_corbel_rise_mm": (
                            round(upper_rail_corbel_rise, 3)
                        ),
                        "rail_corbel_slope_deg": (
                            round(upper_rail_corbel_slope_deg, 3)
                        ),
                        "snap_root_corbel_run_mm": (
                            round(snap_root_corbel_run, 3)
                        ),
                        "snap_root_corbel_rise_mm": (
                            round(snap_root_corbel_rise, 3)
                        ),
                        "snap_root_corbel_slope_deg": (
                            round(snap_root_corbel_slope_deg, 3)
                        ),
                        "bottom_contact_footprint_expansion_mm": 0.0,
                        "strategy": (
                            "local triangular XZ corbels replace a full-width "
                            "carrier plate extension beneath the outboard "
                            "upper-board rails and snap roots"
                        ),
                    },
                    "dc_dc_retention": {
                        "board_count": len(dc_board_centers_x),
                        "cantilever_arm_count": len(
                            dc_clip_arm_centers
                        ),
                        "arm_centers_mm": tuple(dc_clip_arm_centers),
                        "arm_length_mm": dc_clip_arm_length,
                        "arm_thickness_mm": dc_clip_arm_thickness,
                        "clip_width_mm": dc_clip_width,
                        "hook_overlap_mm": dc_clip_hook_overlap,
                        "hook_height_mm": dc_clip_hook_height,
                        "hook_bottom_z_mm": dc_clip_hook_bottom_z,
                        "required_deflection_mm": (
                            dc_clip_required_deflection
                        ),
                        "nominal_surface_strain": (
                            dc_clip_nominal_strain
                        ),
                        "recommended_petg_strain_limit": 0.02,
                        "lead_in_angle_deg": 45.0,
                    },
                    "upper_board_retention": {
                        "components": tuple(
                            upper_component_retention
                        ),
                        "cantilever_hook_count": 4,
                        "y_guide_count": 4,
                        "hook_overlap_mm": upper_clip_hook_overlap,
                        "hook_height_mm": upper_clip_hook_height,
                        "required_deflection_mm": (
                            upper_clip_required_deflection
                        ),
                        "lead_in_angle_deg": 45.0,
                    },
                    "retained_components": (
                        "12V DC-DC module",
                        "5V DC-DC module",
                        "ESP32-C3 Super Mini",
                        "MOSFET PWM driver",
                    ),
                    "external_service_component": (
                        f"DS18B20 Ø{probe_diameter:g} mm "
                        "temperature probe"
                    ),
                    "external_service_retention": (
                        "Ø6 mm capsule slides through two molded horizontal "
                        "bearing blocks; lead is captured by the releasable "
                        "chassis cable clamp"
                    ),
                },
                "ds18b20_probe_retention": {
                    "modeled_as_geometry": True,
                    "fastener_free": True,
                    "serviceable": True,
                    "probe_diameter_mm": probe_diameter,
                    "probe_length_mm": probe_length,
                    "lead_keepout_length_mm": (
                        probe_lead_keepout_length
                    ),
                    "probe_center_local_mm": probe_center_local,
                    "probe_center_global_mm": (
                        pod_x + probe_center_local[0],
                        pod_y + probe_center_local[1],
                        probe_center_local[2],
                    ),
                    "bearing_count": len(probe_bearing_blocks),
                    "station_x_local_mm": probe_station_x_positions,
                    "bore_diameter_mm": probe_bore_diameter,
                    "radial_clearance_mm": tolerance_mm,
                    "entry_slot_width_mm": probe_entry_slot_width,
                    "snap_interference_per_side_mm": (
                        probe_diameter - probe_entry_slot_width
                    )
                    / 2,
                    "block_dimensions_mm": (
                        probe_block_width,
                        probe_block_depth,
                        probe_block_height,
                    ),
                    "support_column_count": 1,
                    "support_column_width_mm": probe_column_width,
                    "support_platform_dimensions_mm": (
                        probe_platform_width,
                        probe_block_depth,
                        probe_platform_height,
                    ),
                    "support_platform_corbel_count": len(
                        probe_platform_corbels
                    ),
                    "support_platform_corbel_run_mm": (
                        probe_platform_corbel_run
                    ),
                    "support_platform_corbel_rise_mm": (
                        probe_platform_corbel_rise
                    ),
                    "support_platform_corbel_slope_deg": (
                        probe_platform_corbel_slope_deg
                    ),
                    "support_platform_corbel_depth_mm": (
                        probe_platform_corbel_depth
                    ),
                    "support_platform_bridge_span_mm": (
                        0.0
                    ),
                    "minimum_guard_clearance_mm": (
                        electronics_layer_height - probe_block_top_z
                    ),
                    "measurement_position": (
                        "rear edge of electronics outlet immediately below "
                        "the fan guard"
                    ),
                    "measurement_purpose": (
                        "controller exhaust-air temperature for fan-control "
                        "feedback; not a direct Mac chip temperature"
                    ),
                    "installation": (
                        "remove carrier, release cable clamp, press metal "
                        "capsule downward through both PETG entry slots, "
                        "then recapture the lead"
                    ),
                    "support_strategy": (
                        "open-top C saddles eliminate trapped bridge support"
                    ),
                },
                "electronics_service_access": (
                    electronics_service_access
                ),
                "vent_open_area_mm2": (
                    len(cover_vent_x_positions)
                    * cover_vent_length
                    * cover_vent_width
                ),
                "snap_fit": {
                    "tab_count": len(snap_tab_y_positions),
                    "tab_length_mm": snap_tab_length,
                    "tab_thickness_mm": snap_tab_thickness,
                    "tab_width_mm": snap_tab_width,
                    "hook_extension_mm": snap_hook_extension,
                    "required_deflection_mm": snap_required_deflection,
                    "nominal_surface_strain": snap_nominal_strain,
                    "recommended_petg_strain_limit": 0.025,
                    "paired_slot_count": len(snap_tab_y_positions),
                    "release_method": (
                        "press both tabs inward through underside-right release windows"
                    ),
                },
            },
        )

        guard_outer = min(116.0, guard_length, guard_width)
        guard_inner = min(110.0, guard_outer - 2 * wall_mm)
        guard_shape = (
            cq.Workplane("XY")
            .circle(guard_outer / 2)
            .circle(guard_inner / 2)
            .extrude(guard_height)
        )
        for ring_radius in (45.0, 31.0, 17.0):
            ring_width = 1.6
            ring = (
                cq.Workplane("XY")
                .circle(ring_radius)
                .circle(ring_radius - ring_width)
                .extrude(guard_height)
            )
            guard_shape = guard_shape.union(ring)
        guard_spoke_width = 1.6
        guard_spoke_angles = (0, 90)
        for angle in guard_spoke_angles:
            bar = (
                cq.Workplane("XY")
                .box(
                    guard_inner,
                    guard_spoke_width,
                    guard_height,
                    centered=(True, True, False),
                )
                .rotate((0, 0, 0), (0, 0, 1), angle)
            )
            guard_shape = guard_shape.union(bar)
        for x_pos, y_pos in fan_mount_positions:
            corner_pad = _rounded_box(
                fan_mount_pad_size,
                fan_mount_pad_size,
                guard_height,
                2.0,
            ).translate((x_pos, y_pos, 0.0))
            arm_angle = math.degrees(math.atan2(y_pos, x_pos))
            arm = (
                cq.Workplane("XY")
                .box(28.0, 5.0, guard_height, centered=(True, True, False))
                .rotate((0, 0, 0), (0, 0, 1), arm_angle)
                .translate((x_pos * 0.82, y_pos * 0.82, 0.0))
            )
            mount_hole = (
                cq.Workplane("XY")
                .center(x_pos, y_pos)
                .circle(fan_mount_hole_diameter / 2)
                .extrude(guard_height + 1.0)
            )
            isolator_pocket = (
                cq.Workplane("XY")
                .workplane(offset=guard_height - fan_isolator_pocket_depth)
                .center(x_pos, y_pos)
                .circle(fan_isolator_pocket_diameter / 2)
                .extrude(fan_isolator_pocket_depth + 0.05)
            )
            guard_shape = (
                guard_shape.union(corner_pad)
                .union(arm)
                .cut(mount_hole)
                .cut(isolator_pocket)
            )
        guard_locating_pin_clearance_diameter = 5.5
        for x_pos, y_pos in locating_pin_positions:
            locating_pin_clearance = (
                cq.Workplane("XY")
                .center(x_pos, y_pos)
                .circle(guard_locating_pin_clearance_diameter / 2)
                .extrude(guard_height + 1.0)
            )
            guard_shape = guard_shape.cut(locating_pin_clearance)
        guard_solid_area = guard_shape.val().Volume() / guard_height
        guard_reference_area = math.pi * (guard_outer / 2.0) ** 2
        guard_open_area_ratio = 1.0 - guard_solid_area / guard_reference_area
        fan_guard = CADPart(
            "fan_guard",
            guard_shape,
            {
                "dimensions_mm": (guard_length, guard_width, guard_height),
                "wall_thickness_mm": wall_mm,
                "material": material,
                "joint": (
                    "captured electronics shield and 120mm fan support plate"
                ),
                "tolerance_mm": tolerance_mm,
                "print_orientation": "flat",
                "support_strategy": "none",
                "open_area_ratio": guard_open_area_ratio,
                "fan_mount_positions_mm": fan_mount_positions,
                "isolator_interface": {
                    "pocket_count": len(fan_mount_positions),
                    "pocket_diameter_mm": fan_isolator_pocket_diameter,
                    "pocket_depth_mm": fan_isolator_pocket_depth,
                    "through_hole_diameter_mm": fan_mount_hole_diameter,
                    "elastomer": "10 x 4.6 x 1.5mm silicone washer",
                    "nominal_thickness_mm": (
                        fan_isolator_nominal_thickness
                    ),
                    "installed_thickness_mm": (
                        fan_isolator_installed_thickness
                    ),
                    "compression_mm": fan_isolator_compression,
                    "compression_ratio": fan_isolator_compression_ratio,
                    "installed_protrusion_above_guard_mm": (
                        fan_isolator_protrusion
                    ),
                    "modeled_as_geometry": True,
                },
                "guard_spoke_count": 2 * len(guard_spoke_angles),
                "guard_spoke_width_mm": guard_spoke_width,
                "guard_ring_count": 3,
                "vertical_service_clearance": {
                    "chassis_locating_pin_clearance_count": len(
                        locating_pin_positions
                    ),
                    "clearance_diameter_mm": (
                        guard_locating_pin_clearance_diameter
                    ),
                    "maximum_pin_diameter_mm": 5.0,
                    "diametral_clearance_mm": tolerance_mm * 2,
                    "straight_vertical_removal": True,
                },
            },
        )

        cradle_base_height = 4.0
        airflow_opening = 115.0
        mac_mini_size = max(mac_length, mac_width)
        locating_clearance = 2 * tolerance_mm
        locating_cavity = mac_mini_size + locating_clearance
        locating_lip_height = cradle_height - cradle_base_height
        locating_lip_outer = locating_cavity + 4.0
        power_button_center = power_button_center_parameter
        power_button_shaft_center = (
            -fan_mount_spacing / 2,
            fan_mount_spacing / 2,
        )
        power_button_access_diameter = 14.0
        power_button_diameter = power_button_diameter_parameter
        power_button_coordinate_uncertainty = 2.0
        power_button_shaft_diameter = 4.5
        power_button_shoulder_z = 1.0
        support_shelf_edge_radius = 0.8
        # The user-provided 138 mm reference stand uses one continuous
        # wrap-around shell instead of stacking visibly unrelated slabs.
        # V93 replaces the constant-thickness cradle plate with a five-section
        # convex annular band.  Its 133.2 mm lower silhouette exactly matches
        # the chassis crown, grows in a rounded bridge peak, then
        # returns to 133.2 mm at the Mac support shelf.  This avoids flat
        # crenel-like ridges at the seam while keeping the 134 mm envelope cap.
        cradle_chassis_transition_radius = (
            chassis_cradle_seam_roll_radius
        )
        cradle_band_profile = (
            (0.0, chassis_crown_top_outer, 14.0),
            (0.8, 133.7, 14.25),
            (2.0, 134.0, 14.4),
            (3.2, 133.7, 14.25),
            (cradle_base_height, chassis_crown_top_outer, 14.0),
        )
        cradle_outer_workplane = cq.Workplane("XY")
        for z_position, profile_size, profile_radius in (
            cradle_band_profile
        ):
            cradle_outer_workplane = cradle_outer_workplane.add(
                rounded_square_wire(
                    profile_size,
                    profile_radius,
                    z_position,
                )
            )
        cradle_outer = (
            cradle_outer_workplane
            .toPending()
            .loft(combine=False)
        )
        cradle_band_maximum_overhang_per_side = (
            cradle_length - chassis_crown_top_outer
        ) / 2
        cradle_band_lower_slope_from_horizontal_deg = math.degrees(
            math.atan2(
                2.0,
                cradle_band_maximum_overhang_per_side,
            )
        )
        cradle_shape = cradle_outer.cut(
            cq.Workplane("XY")
            .circle(airflow_opening / 2)
            .extrude(
                cradle_base_height + 1.0,
            )
        ).clean()
        # Avoid cutting the 133.2 mm lower seam while preserving a single,
        # continuous printed shell through the fan-deck interface.
        # Round only the lower edge of the Ø115 airflow opening. The custom
        # predicate deliberately excludes the outer perimeter, locating
        # sockets, and button bore. Air entering from the fan side sees a
        # 1 mm bellmouth instead of a sharp re-entrant edge, while the 115 mm
        # cylindrical throat and planar chassis interface remain unchanged.
        airflow_lower_bellmouth_radius = 1.0
        airflow_lower_edge = (
            cradle_shape.edges()
            .filter(
                lambda edge: (
                    edge.geomType() == "CIRCLE"
                    and abs(edge.radius() - airflow_opening / 2) <= 0.01
                    and abs(edge.Center().x) <= 0.01
                    and abs(edge.Center().y) <= 0.01
                    and abs(edge.BoundingBox().zmin) <= 0.01
                    and abs(edge.BoundingBox().zmax) <= 0.01
                )
            )
        )
        if len(airflow_lower_edge.vals()) != 1:
            raise ValueError(
                "Expected exactly one lower Ø115 airflow edge for bellmouth"
            )
        cradle_shape = airflow_lower_edge.fillet(
            airflow_lower_bellmouth_radius
        )
        cradle_shape = cradle_shape.edges(">Z").fillet(
            support_shelf_edge_radius
        )
        locating_lip = _rounded_box(
            locating_lip_outer,
            locating_lip_outer,
            locating_lip_height,
            12.25,
        ).cut(
            _rounded_box(
                locating_cavity,
                locating_cavity,
                locating_lip_height + 1.0,
                # A true offset increases both the enclosure size and its
                # corner radius by the single-side assembly tolerance.
                mac_corner_radius + tolerance_mm,
            )
        )
        locating_lip_edge_radius = 0.7
        locating_lip = locating_lip.edges(">Z").fillet(
            locating_lip_edge_radius
        )
        cradle_shape = cradle_shape.union(
            locating_lip.translate((0.0, 0.0, cradle_base_height))
        ).clean()
        # The power and Ethernet connectors extend lower than the other rear
        # ports in the conservative full-scale Mac reference. Preserve the
        # continuous 4 mm base ring, but lower the 1.5 mm locating lip across
        # one broad rounded service bay instead of cutting multiple
        # castellated notches. Rear corner lands remain available for
        # location, while plugs can enter horizontally without touching PETG.
        rear_service_relief_center_x = -38.5
        rear_service_relief_width = 42.0
        rear_service_relief_depth = 6.0
        rear_service_relief_radius = 2.5
        rear_service_relief_inward_overlap = 0.5
        rear_service_relief_center_y = (
            locating_cavity / 2
            + rear_service_relief_depth / 2
            - rear_service_relief_inward_overlap
        )
        rear_service_relief = _rounded_box(
            rear_service_relief_width,
            rear_service_relief_depth,
            locating_lip_height + 0.2,
            rear_service_relief_radius,
        ).translate(
            (
                rear_service_relief_center_x,
                rear_service_relief_center_y,
                cradle_base_height,
            )
        )
        cradle_before_rear_service_relief = cradle_shape
        cradle_shape = cradle_shape.cut(rear_service_relief).clean()
        rear_service_relief_removed_volume = (
            float(cradle_before_rear_service_relief.val().Volume())
            - float(cradle_shape.val().Volume())
        )
        # Four shallow silicone-dot seats turn the contact instruction into a
        # repeatable physical interface. Three seats follow a symmetric
        # diagonal pattern; the rear-left seat moves inward in Y to clear the
        # power-button access path. A 0.5 mm adhesive dot sits in a 0.3 mm
        # recess and remains 0.2 mm proud, ensuring that the Mac contacts soft
        # silicone rather than the surrounding PETG shelf.
        support_pad_diameter = 8.0
        support_pad_recess_diameter = (
            support_pad_diameter + 2 * tolerance_mm
        )
        support_pad_recess_depth = 0.3
        support_pad_installed_thickness = 0.5
        support_pad_protrusion = (
            support_pad_installed_thickness
            - support_pad_recess_depth
        )
        support_pad_positions = (
            (-50.0, -42.0),
            (50.0, -42.0),
            (50.0, 42.0),
            (-52.0, 36.0),
        )
        support_pad_recess_cutters = []
        support_pad_shape_before_recesses = cradle_shape
        for x_pos, y_pos in support_pad_positions:
            recess = (
                cq.Workplane("XY")
                .workplane(
                    offset=cradle_base_height
                    - support_pad_recess_depth
                )
                .center(x_pos, y_pos)
                .circle(support_pad_recess_diameter / 2)
                .extrude(support_pad_recess_depth + 0.01)
            )
            support_pad_recess_cutters.append(recess)
            cradle_shape = cradle_shape.cut(recess)
        support_pad_expected_removed_volume = (
            len(support_pad_positions)
            * math.pi
            * (support_pad_recess_diameter / 2) ** 2
            * support_pad_recess_depth
        )
        support_pad_removed_volume = (
            float(support_pad_shape_before_recesses.val().Volume())
            - float(cradle_shape.val().Volume())
        )
        support_pad_airflow_edge_clearance = min(
            math.hypot(x_pos, y_pos)
            - support_pad_recess_diameter / 2
            - airflow_opening / 2
            for x_pos, y_pos in support_pad_positions
        )
        support_pad_button_clearance = min(
            math.dist((x_pos, y_pos), power_button_center)
            - support_pad_diameter / 2
            - power_button_access_diameter / 2
            for x_pos, y_pos in support_pad_positions
        )
        power_button_shaft_bore = (
            cq.Workplane("XY")
            .center(*power_button_shaft_center)
            .circle(power_button_shaft_diameter / 2)
            .extrude(power_button_shoulder_z + 0.1)
        )
        power_button_head_bore_at_shaft = (
            cq.Workplane("XY")
            .center(*power_button_shaft_center)
            .circle(power_button_access_diameter / 2)
            .extrude(cradle_height - power_button_shoulder_z + 0.1)
            .translate((0.0, 0.0, power_button_shoulder_z))
        )
        power_button_head_bore_at_button = (
            cq.Workplane("XY")
            .center(*power_button_center)
            .circle(power_button_access_diameter / 2)
            .extrude(cradle_height - power_button_shoulder_z + 0.1)
            .translate((0.0, 0.0, power_button_shoulder_z))
        )
        button_path_dx = (
            power_button_center[0] - power_button_shaft_center[0]
        )
        button_path_dy = (
            power_button_center[1] - power_button_shaft_center[1]
        )
        button_path_length = math.hypot(button_path_dx, button_path_dy)
        button_path_angle = math.degrees(
            math.atan2(button_path_dy, button_path_dx)
        )
        button_path_midpoint = (
            (
                power_button_center[0]
                + power_button_shaft_center[0]
            )
            / 2,
            (
                power_button_center[1]
                + power_button_shaft_center[1]
            )
            / 2,
        )
        power_button_head_bore_bridge = (
            cq.Workplane("XY")
            .box(
                button_path_length,
                power_button_access_diameter,
                cradle_height - power_button_shoulder_z + 0.1,
                centered=(True, True, False),
            )
            .rotate(
                (0.0, 0.0, 0.0),
                (0.0, 0.0, 1.0),
                button_path_angle,
            )
            .translate(
                (
                    *button_path_midpoint,
                    power_button_shoulder_z,
                )
            )
        )
        power_button_head_bore = (
            power_button_head_bore_at_shaft
            .union(power_button_head_bore_at_button)
            .union(power_button_head_bore_bridge)
        )
        cradle_shape = (
            cradle_shape
            .cut(power_button_shaft_bore)
            .cut(power_button_head_bore)
        )
        # The locating pins transfer only lateral and anti-rotation loads;
        # the planar cradle/chassis faces carry the vertical Mac load.  The
        # former 0.75 mm blind roofs created four enclosed support islands.
        # Cut through the 4 mm base instead, leaving each 3 mm pin tip 1 mm
        # below the Mac support plane and keeping the holes fully hidden
        # beneath the installed device.
        locating_socket_overcut = 0.1
        locating_socket_depth = (
            cradle_base_height + locating_socket_overcut
        )
        maximum_locating_socket_radius = 2.5 + tolerance_mm
        locating_pin_tip_recess = (
            cradle_base_height - locating_pin_height
        )
        locating_socket_minimum_outer_ligament = (
            cradle_length / 2
            - (
                max(
                    abs(locating_pin_x_station),
                    abs(locating_pin_y_station),
                )
                + maximum_locating_socket_radius
            )
        )
        locating_socket_minimum_device_cover = (
            min(mac_length, mac_width) / 2
            - (
                max(
                    abs(locating_pin_x_station),
                    abs(locating_pin_y_station),
                )
                + maximum_locating_socket_radius
            )
        )
        for position in locating_pin_positions:
            hole_radius = (
                2.5 + tolerance_mm
                if position == keyed_pin_position
                else 2.0 + tolerance_mm
            )
            hole = (
                cq.Workplane("XY")
                .center(*position)
                .circle(hole_radius)
                .extrude(locating_socket_depth)
            )
            cradle_shape = cradle_shape.cut(hole)
        support_pad_recess_residual_volume = sum(
            float(cradle_shape.intersect(cutter).val().Volume())
            for cutter in support_pad_recess_cutters
        )
        airflow_bottom_edges = [
            edge
            for edge in cradle_shape.edges().vals()
            if (
                edge.geomType() == "CIRCLE"
                and abs(edge.Center().x) <= 0.01
                and abs(edge.Center().y) <= 0.01
                and abs(edge.BoundingBox().zmin) <= 0.01
                and abs(edge.BoundingBox().zmax) <= 0.01
                and edge.radius() > airflow_opening / 2
            )
        ]
        if len(airflow_bottom_edges) != 1:
            raise ValueError(
                "Expected exactly one expanded circular bellmouth inlet"
            )
        airflow_inlet_diameter = 2 * airflow_bottom_edges[0].radius()
        airflow_throat_height = (
            cradle_base_height
            - airflow_lower_bellmouth_radius
            - support_shelf_edge_radius
        )
        mac_foot_radial_clearance = (
            airflow_opening - mac_foot_outer_diameter
        ) / 2
        cradle_bottom_faces = cradle_shape.faces("<Z").vals()
        cradle_bottom_footprint_bbox = (
            min(face.BoundingBox().xmin for face in cradle_bottom_faces),
            min(face.BoundingBox().ymin for face in cradle_bottom_faces),
            max(face.BoundingBox().xmax for face in cradle_bottom_faces),
            max(face.BoundingBox().ymax for face in cradle_bottom_faces),
        )
        cradle_bottom_footprint = (
            cradle_bottom_footprint_bbox[2]
            - cradle_bottom_footprint_bbox[0],
            cradle_bottom_footprint_bbox[3]
            - cradle_bottom_footprint_bbox[1],
        )
        chassis_transition_mismatch = max(
            abs(
                cradle_bottom_footprint[0]
                - chassis_crown_top_outer
            ),
            abs(
                cradle_bottom_footprint[1]
                - chassis_crown_top_outer
            ),
        )
        underbody_air_gap = 2.0 + support_pad_protrusion
        mac_mini_cradle = CADPart(
            "mac_mini_cradle",
            cradle_shape,
            {
                "dimensions_mm": (
                    cradle_length,
                    cradle_width,
                    cradle_height,
                ),
                "device_envelope_mm": (
                    mac_length,
                    mac_width,
                    mac_height,
                ),
                "locating_cavity_mm": locating_cavity,
                "airflow_opening_mm": airflow_opening,
                "wall_thickness_mm": wall_mm,
                "material": material,
                "joint": (
                    "continuous rounded-square gravity locating ring with "
                    "keyed four-pin chassis interface"
                ),
                "tolerance_mm": tolerance_mm,
                "print_orientation": "airflow ring on build plate",
                "support_strategy": "none",
                "port_access": "front and rear fully open",
                "port_keepout": {
                    "open_face_width_mm": locating_cavity,
                    "external_service_depth_mm": 25.0,
                    "height_mm": 50.0,
                    "minimum_interface_z_mm": 6.0,
                    "front_rear_obstruction_volume_mm3": 0.0,
                    "verified_by": "solid intersection in design review",
                },
                "rear_service_relief": {
                    "style": (
                        "single broad rounded top-open service bay; "
                        "continuous lower base ring"
                    ),
                    "center_mm": (
                        rear_service_relief_center_x,
                        rear_service_relief_center_y,
                        cradle_base_height
                        + locating_lip_height / 2,
                    ),
                    "width_mm": rear_service_relief_width,
                    "depth_mm": rear_service_relief_depth,
                    "inward_overlap_mm": (
                        rear_service_relief_inward_overlap
                    ),
                    "height_mm": locating_lip_height,
                    "end_radius_mm": rear_service_relief_radius,
                    "removed_volume_mm3": (
                        rear_service_relief_removed_volume
                    ),
                    "covered_interfaces": (
                        "rear power",
                        "rear Ethernet",
                    ),
                    "breaks_bottom_outer_edge": False,
                    "bottom_ring_height_mm": cradle_base_height,
                    "support_required": False,
                },
                "power_button_access": {
                    "strategy": (
                        "rear-left enclosed vertical access bore aligned to "
                        "the underside button; no exterior edge notch"
                    ),
                    "installed_edge_notch": False,
                    "modeled_as_geometry": True,
                    "center_mm": power_button_center,
                    "shaft_center_mm": power_button_shaft_center,
                    "access_diameter_mm": power_button_access_diameter,
                    "shaft_bore_diameter_mm": power_button_shaft_diameter,
                    "shoulder_z_mm": power_button_shoulder_z,
                    "minimum_vertical_release_mm": cradle_height,
                    "actuator_part": "power_button_plunger",
                    "center_offset_mm": round(button_path_length, 3),
                    "coordinate_source": (
                        "scaled from Apple official bottom-view illustration "
                        "against the 127mm enclosure"
                    ),
                    "coordinate_uncertainty_mm": (
                        power_button_coordinate_uncertainty
                    ),
                    "operation": (
                        "reach through the rear-left elliptical air portal "
                        "and lift the integrated paddle; the captured upper "
                        "head presses the Mac mini button"
                    ),
                    "dimension_source": (
                        "rear-left location verified; exact coordinate "
                        "requires physical fit verification"
                    ),
                },
                "underbody_air_gap_mm": underbody_air_gap,
                "device_support_height_mm": underbody_air_gap,
                "device_body_support_plane_mm": (
                    cradle_base_height + support_pad_protrusion
                ),
                "engineering_parameters": resolved_parameters,
                "engineering_parameter_sources": parameter_sources,
                "support_pad_count": len(support_pad_positions),
                "surface_interface": (
                    "install four 8 x 0.5mm adhesive silicone dots in modeled "
                    "8.5 x 0.3mm annular-shelf recesses; each dot remains "
                    "0.2mm proud of PETG"
                ),
                "support_pad_interface": {
                    "modeled_as_geometry": True,
                    "count": len(support_pad_positions),
                    "positions_mm": support_pad_positions,
                    "pad_diameter_mm": support_pad_diameter,
                    "recess_diameter_mm": (
                        support_pad_recess_diameter
                    ),
                    "recess_depth_mm": support_pad_recess_depth,
                    "installed_pad_thickness_mm": (
                        support_pad_installed_thickness
                    ),
                    "installed_protrusion_mm": support_pad_protrusion,
                    "installed_condition": (
                        "0.2mm proud; Mac body contacts silicone before PETG"
                    ),
                    "installed_pad_base_z_mm": (
                        cradle_base_height - support_pad_recess_depth
                    ),
                    "installed_pad_top_z_mm": (
                        cradle_base_height + support_pad_protrusion
                    ),
                    "expected_removed_volume_mm3": (
                        support_pad_expected_removed_volume
                    ),
                    "actual_removed_volume_mm3": (
                        support_pad_removed_volume
                    ),
                    "boolean_residual_volume_mm3": (
                        support_pad_recess_residual_volume
                    ),
                    "minimum_airflow_edge_clearance_mm": (
                        support_pad_airflow_edge_clearance
                    ),
                    "minimum_power_button_clearance_mm": (
                        support_pad_button_clearance
                    ),
                    "remaining_bottom_skin_mm": (
                        cradle_base_height - support_pad_recess_depth
                    ),
                },
                "airflow_bellmouth": {
                    "modeled_as_geometry": True,
                    "lower_inlet_radius_mm": (
                        airflow_lower_bellmouth_radius
                    ),
                    "upper_outlet_radius_mm": (
                        support_shelf_edge_radius
                    ),
                    "lower_inlet_diameter_mm": airflow_inlet_diameter,
                    "minimum_throat_diameter_mm": airflow_opening,
                    "straight_throat_height_mm": airflow_throat_height,
                    "mac_foot_outer_diameter_mm": (
                        mac_foot_outer_diameter
                    ),
                    "minimum_mac_foot_radial_clearance_mm": (
                        mac_foot_radial_clearance
                    ),
                    "outer_mating_footprint_mm": (
                        *cradle_bottom_footprint,
                    ),
                    "sharp_lower_airflow_edge": False,
                    "support_strategy": "none",
                    "flow_claim": (
                        "geometry reduces sharp-edge separation risk; "
                        "airflow estimate remains conservatively unchanged"
                    ),
                },
                "reference_informed_transition": {
                    "modeled_as_geometry": True,
                    "reference_kind": "user-provided 3MF design reference",
                    "reference_title": "Mac mini M4 + UGREEN dock stand",
                    "measured_reference_envelope_mm": (
                        138.0,
                        138.0,
                        86.5,
                    ),
                    "reference_mesh_copied": False,
                    "adopted_principles": (
                        "continuous rounded perimeter",
                        "open service faces",
                        "smooth base-to-wall transition",
                        "widely spaced elastomer contact points",
                    ),
                    "rejected_features": (
                        "lateral dock bay",
                        "86.5mm vertical wrap walls",
                        "138mm target footprint",
                    ),
                    "transition_radius_mm": (
                        cradle_chassis_transition_radius
                    ),
                    "outer_band_style": (
                        "five-section convex rounded-square annular loft"
                    ),
                    "outer_band_profile": [
                        {
                            "z_mm": z_position,
                            "size_mm": profile_size,
                            "corner_radius_mm": profile_radius,
                        }
                        for (
                            z_position,
                            profile_size,
                            profile_radius,
                        ) in cradle_band_profile
                    ],
                    "maximum_band_overhang_per_side_mm": (
                        cradle_band_maximum_overhang_per_side
                    ),
                    "lower_slope_from_horizontal_deg": round(
                        cradle_band_lower_slope_from_horizontal_deg,
                        3,
                    ),
                    "upper_shelf_footprint_mm": (
                        chassis_crown_top_outer,
                        chassis_crown_top_outer,
                    ),
                    "seam_location": (
                        "underside tangent line at the matched 133.2 mm "
                        "chassis-crown footprint"
                    ),
                    "visible_constant_thickness_plate_edge": False,
                    "upper_envelope_mm": (
                        cradle_length,
                        cradle_width,
                    ),
                    "bottom_footprint_mm": cradle_bottom_footprint,
                    "target_chassis_footprint_mm": (
                        chassis_crown_top_outer,
                        chassis_crown_top_outer,
                    ),
                    "chassis_body_footprint_mm": (
                        frame_outer,
                        frame_outer,
                    ),
                    "maximum_footprint_mismatch_mm": (
                        chassis_transition_mismatch
                    ),
                    "continuous_outer_transition": True,
                    "planar_mating_face_retained": True,
                    "support_free": True,
                },
                "annular_cradle": {
                    "outer_profile": (
                        f"{cradle_length:g}mm rounded square"
                    ),
                    "central_opening_shape": "circular",
                    "central_opening_diameter_mm": airflow_opening,
                    "device_cavity_mm": locating_cavity,
                    "single_side_clearance_mm": tolerance_mm,
                    "locating_lip_height_mm": locating_lip_height,
                    "device_corner_radius_mm": mac_corner_radius,
                    "cavity_corner_radius_mm": (
                        mac_corner_radius + tolerance_mm
                    ),
                    "lead_in_radius_mm": locating_lip_edge_radius,
                    "support_shelf_edge_radius_mm": (
                        support_shelf_edge_radius
                    ),
                    "chassis_overhang_per_side_mm": (
                        (cradle_length - frame_outer) / 2
                    ),
                    "reference_3mf_measured_opening_mm": 114.9,
                },
                "locating_interface": {
                    "pin_count": len(locating_pin_positions),
                    "keyed": True,
                    "keyed_pin_position_mm": keyed_pin_position,
                    "radial_clearance_mm": tolerance_mm,
                    "socket_type": "through",
                    "socket_depth_mm": locating_socket_depth,
                    "socket_overcut_mm": locating_socket_overcut,
                    "through_sockets": True,
                    "top_skin_mm": 0.0,
                    "pin_tip_recess_below_support_plane_mm": (
                        locating_pin_tip_recess
                    ),
                    "minimum_outer_ligament_mm": (
                        locating_socket_minimum_outer_ligament
                    ),
                    "minimum_device_cover_mm": (
                        locating_socket_minimum_device_cover
                    ),
                    "vertical_load_path": (
                        "planar cradle/chassis mating faces; locating pins "
                        "carry lateral and anti-rotation loads only"
                    ),
                    "integrated_into_continuous_ring": True,
                },
                "device": "Apple Mac mini M4",
                "device_dimensions_mm": (
                    mac_length,
                    mac_width,
                    mac_height,
                ),
                "airflow_strategy": (
                    "115mm circular opening aligned with the bottom vent ring"
                ),
                "airflow_open_area_mm2": (
                    math.pi * (airflow_opening / 2) ** 2
                ),
                "visual_radius_mm": 14.0,
                "exterior_continuity": {
                    "closed_outer_ring": True,
                    "outer_edge_notch_count": 0,
                    "corner_radius_mm": 14.0,
                    "service_access_without_edge_cut": True,
                    "through_locating_sockets": True,
                    "locating_sockets_break_outer_edge": False,
                    "continuous_side_rail_count": 0,
                    "continuous_annular_cradle": True,
                    "curved_landing_surfaces": True,
                },
            },
        )
        plunger_shaft_diameter = 4.0
        plunger_shaft_length = 58.0
        # The Mac reference underside has a 0.017 mm modeled crown at the
        # Keep the calibrated head length tied directly to the 34.1 mm
        # reference envelope.  The underside crown is already represented in
        # the Mac reference solid; additional axial compensation creates an
        # oversized rest gap in the installed OpenCascade placement.
        plunger_head_end_compensation = 0.0
        plunger_head_length = (
            plunger_length
            - plunger_shaft_length
            - plunger_head_end_compensation
        )
        # The planned width/height describe the complete actuator envelope,
        # including its rear-access paddle. Keep the calibrated button head
        # independent from that envelope.
        plunger_head_diameter = 13.5
        plunger_head_offset_y = (
            power_button_center[1] - power_button_shaft_center[1]
        )
        plunger_head_offset_z = (
            power_button_center[0] - power_button_shaft_center[0]
        )
        plunger_shaft = (
            cq.Workplane("YZ")
            .circle(plunger_shaft_diameter / 2)
            .extrude(-plunger_shaft_length)
        )
        shaft_flat_cut = (
            cq.Workplane("XY")
            .box(
                plunger_shaft_length + 1.0,
                plunger_shaft_diameter + 2.0,
                2.0,
                centered=(False, True, False),
            )
            .translate((-plunger_shaft_length - 0.5, 0.0, -3.6))
        )
        shaft_top_cut = (
            cq.Workplane("XY")
            .box(
                plunger_shaft_length + 1.0,
                plunger_shaft_diameter + 2.0,
                2.0,
                centered=(False, True, False),
            )
            .translate((-plunger_shaft_length - 0.5, 0.0, 1.6))
        )
        plunger_shaft = (
            plunger_shaft
            .cut(shaft_flat_cut)
            .cut(shaft_top_cut)
        )
        plunger_head = (
            cq.Workplane("YZ")
            .center(plunger_head_offset_y, plunger_head_offset_z)
            .circle(plunger_head_diameter / 2)
            .extrude(-plunger_head_length)
            .translate((-plunger_shaft_length, 0.0, 0.0))
        )
        plunger_head_flat_cut = (
            cq.Workplane("XY")
            .box(
                plunger_head_length + 1.0,
                plunger_head_diameter + 2.0,
                plunger_head_diameter,
                centered=(False, True, False),
            )
            .translate(
                (
                    -plunger_length - 0.5,
                    plunger_head_offset_y,
                    -plunger_head_diameter - 1.6,
                )
            )
        )
        plunger_head = plunger_head.cut(plunger_head_flat_cut)
        # A single-piece rear-access paddle removes the V42 requirement to
        # tip the entire dock for power-button access. The V44 arm is a
        # constant-width capsule instead of a faceted tapered plate: 4 mm
        # thickness cuts elastic finger-pad deflection while 2.75 mm round
        # ends blend the arm into both shaft and pad. In the installed
        # orientation it lies at Z=14.5..18.5 mm immediately behind the
        # existing rear air portal. It never crosses the 134 mm footprint,
        # adds no exterior notch, and translates vertically with the plunger.
        finger_lift_delta_y = 9.25
        finger_lift_delta_z = 25.5
        finger_lift_arm_width = 5.5
        finger_lift_arm_thickness = 4.0
        finger_lift_arm_length = math.hypot(
            finger_lift_delta_y,
            finger_lift_delta_z,
        )
        finger_lift_arm_angle = -math.degrees(
            math.atan2(finger_lift_delta_y, finger_lift_delta_z)
        )
        finger_lift_arm = (
            cq.Workplane("YZ")
            .rect(
                finger_lift_arm_width,
                finger_lift_arm_length,
            )
            .extrude(-finger_lift_arm_thickness)
            .rotate(
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                finger_lift_arm_angle,
            )
            .translate(
                (
                    -13.5,
                    finger_lift_delta_y / 2,
                    finger_lift_delta_z / 2,
                )
            )
        )
        for cap_y, cap_z in (
            (0.0, 0.0),
            (finger_lift_delta_y, finger_lift_delta_z),
        ):
            finger_lift_arm = finger_lift_arm.union(
                cq.Workplane("YZ")
                .center(cap_y, cap_z)
                .circle(finger_lift_arm_width / 2)
                .extrude(-finger_lift_arm_thickness)
                .translate((-13.5, 0.0, 0.0))
            )
        # The root circle would otherwise extend 1.15 mm below the existing
        # shaft flat and lift the 58 mm shaft off the build plate. Clip only
        # the arm root to the shared Z=-1.6 mm datum so OrcaSlicer does not
        # interpret the shaft as a 41 mm bridge.
        finger_lift_print_flat_z = -1.6
        finger_lift_print_flat_cut = (
            cq.Workplane("XY")
            .box(
                100.0,
                100.0,
                20.0,
                centered=(True, True, False),
            )
            .translate((0.0, 0.0, finger_lift_print_flat_z - 20.0))
        )
        finger_lift_arm = finger_lift_arm.cut(
            finger_lift_print_flat_cut
        )
        finger_lift_pad = (
            cq.Workplane("YZ")
            .center(finger_lift_delta_y, finger_lift_delta_z)
            .ellipse(3.75, 7.0)
            .extrude(-finger_lift_arm_thickness)
            .translate((-13.5, 0.0, 0.0))
        )
        power_button_plunger_shape = (
            plunger_shaft
            .union(plunger_head)
            .union(finger_lift_arm)
            .union(finger_lift_pad)
        )
        # Validate the actual D-shaped end face, including its print-flat,
        # against the stated ±2 mm coordinate uncertainty. Sixteen radial
        # samples measure both the full Ø8 button overlap and a conservative
        # Ø4 actuation core. This avoids claiming tolerance from nominal
        # diameters alone.
        contact_probe_length = 0.2
        contact_end_x = -plunger_shaft_length - plunger_head_length
        button_contact_area = math.pi * (power_button_diameter / 2) ** 2
        actuation_core_diameter = 4.0
        actuation_core_area = math.pi * (actuation_core_diameter / 2) ** 2
        button_contact_coverage_ratios = []
        actuation_core_coverage_ratios = []
        for sample_index in range(16):
            angle_degrees = sample_index * 360.0 / 16
            angle_radians = math.radians(angle_degrees)
            offset_y = (
                power_button_coordinate_uncertainty
                * math.cos(angle_radians)
            )
            offset_z = (
                power_button_coordinate_uncertainty
                * math.sin(angle_radians)
            )
            full_button_probe = (
                cq.Workplane("YZ")
                .center(
                    plunger_head_offset_y + offset_y,
                    plunger_head_offset_z + offset_z,
                )
                .circle(power_button_diameter / 2)
                .extrude(contact_probe_length)
                .translate((contact_end_x, 0.0, 0.0))
            )
            core_probe = (
                cq.Workplane("YZ")
                .center(
                    plunger_head_offset_y + offset_y,
                    plunger_head_offset_z + offset_z,
                )
                .circle(actuation_core_diameter / 2)
                .extrude(contact_probe_length)
                .translate((contact_end_x, 0.0, 0.0))
            )
            button_contact_coverage_ratios.append(
                float(
                    power_button_plunger_shape
                    .intersect(full_button_probe)
                    .val()
                    .Volume()
                )
                / contact_probe_length
                / button_contact_area
            )
            actuation_core_coverage_ratios.append(
                float(
                    power_button_plunger_shape
                    .intersect(core_probe)
                    .val()
                    .Volume()
                )
                / contact_probe_length
                / actuation_core_area
            )
        minimum_button_contact_coverage = min(
            button_contact_coverage_ratios
        )
        minimum_actuation_core_coverage = min(
            actuation_core_coverage_ratios
        )
        head_bore_radial_clearance = (
            power_button_access_diameter - plunger_head_diameter
        ) / 2
        plunger_bounds = power_button_plunger_shape.val().BoundingBox()
        plunger_actual_dimensions = (
            round(float(plunger_bounds.xlen), 3),
            round(float(plunger_bounds.ylen), 3),
            round(float(plunger_bounds.zlen), 3),
        )
        petg_elastic_modulus_mpa = 1500.0
        conservative_second_moment_mm4 = (
            plunger_shaft_diameter
            * (plunger_shaft_diameter - 0.8) ** 3
            / 12
        )
        euler_buckling_load_n = (
            math.pi**2
            * petg_elastic_modulus_mpa
            * conservative_second_moment_mm4
            / plunger_shaft_length**2
        )
        assumed_button_force_n = 3.0
        conservative_petg_yield_mpa = 30.0
        finger_lift_second_moment_mm4 = (
            finger_lift_arm_width
            * finger_lift_arm_thickness**3
            / 12
        )
        finger_lift_bending_stress_mpa = (
            assumed_button_force_n
            * finger_lift_arm_length
            * (finger_lift_arm_thickness / 2)
            / finger_lift_second_moment_mm4
        )
        finger_lift_tip_deflection_mm = (
            assumed_button_force_n
            * finger_lift_arm_length**3
            / (
                3
                * petg_elastic_modulus_mpa
                * finger_lift_second_moment_mm4
            )
        )
        finger_lift_yield_safety_factor = (
            conservative_petg_yield_mpa
            / finger_lift_bending_stress_mpa
        )
        power_button_plunger = CADPart(
            "power_button_plunger",
            power_button_plunger_shape,
            {
                "dimensions_mm": plunger_actual_dimensions,
                "wall_thickness_mm": plunger_shaft_diameter,
                "material": material,
                "joint": "captured sliding plunger through fan mount bore",
                "tolerance_mm": tolerance_mm,
                "print_orientation": "horizontal on build plate",
                "support_strategy": "none",
                "shaft_diameter_mm": plunger_shaft_diameter,
                "shaft_flat_mm": 0.4,
                "head_diameter_mm": plunger_head_diameter,
                "head_width_mm": plunger_head_diameter,
                "head_thickness_mm": plunger_head_diameter,
                "head_height_mm": plunger_head_length,
                "shaft_center_mm": power_button_shaft_center,
                "head_center_mm": power_button_center,
                "head_center_offset_mm": round(button_path_length, 3),
                "head_end_compensation_mm": (
                    plunger_head_end_compensation
                ),
                "uncertainty_tolerant_contact": {
                    "modeled_from_actual_end_face": True,
                    "button_diameter_mm": power_button_diameter,
                    "actuation_core_diameter_mm": (
                        actuation_core_diameter
                    ),
                    "coordinate_uncertainty_mm": (
                        power_button_coordinate_uncertainty
                    ),
                    "angular_sample_count": len(
                        button_contact_coverage_ratios
                    ),
                    "minimum_full_button_coverage_ratio": (
                        minimum_button_contact_coverage
                    ),
                    "minimum_actuation_core_coverage_ratio": (
                        minimum_actuation_core_coverage
                    ),
                    "head_access_bore_diameter_mm": (
                        power_button_access_diameter
                    ),
                    "head_bore_radial_clearance_mm": (
                        head_bore_radial_clearance
                    ),
                    "print_flat_included_in_measurement": True,
                },
                "rear_access_finger_lift": {
                    "modeled_as_geometry": True,
                    "integrated_single_piece": True,
                    "input_method": (
                        "lift upward through existing rear-left air portal"
                    ),
                    "installed_pad_center_mm": (-27.0, 61.75, 16.5),
                    "installed_pad_envelope_mm": (14.0, 7.5, 4.0),
                    "arm_profile": "constant-width rounded capsule",
                    "arm_length_mm": round(finger_lift_arm_length, 3),
                    "arm_width_mm": finger_lift_arm_width,
                    "arm_thickness_mm": finger_lift_arm_thickness,
                    "arm_end_radius_mm": finger_lift_arm_width / 2,
                    "root_print_flat_z_mm": finger_lift_print_flat_z,
                    "shares_shaft_build_plane": True,
                    "conservative_petg_modulus_mpa": (
                        petg_elastic_modulus_mpa
                    ),
                    "conservative_petg_yield_mpa": (
                        conservative_petg_yield_mpa
                    ),
                    "assumed_finger_force_n": assumed_button_force_n,
                    "conservative_bending_stress_mpa": round(
                        finger_lift_bending_stress_mpa,
                        3,
                    ),
                    "conservative_tip_deflection_mm": round(
                        finger_lift_tip_deflection_mm,
                        3,
                    ),
                    "conservative_yield_safety_factor": round(
                        finger_lift_yield_safety_factor,
                        2,
                    ),
                    "minimum_finger_corridor_width_mm": 15.0,
                    "chassis_edge_inset_mm": 0.5,
                    "cradle_edge_inset_mm": 1.5,
                    "required_actuation_travel_mm": 1.25,
                    "mechanical_motion_ratio": 1.0,
                    "additional_exterior_openings": 0,
                    "lateral_footprint_extension_mm": 0.0,
                    "return_method": (
                        "Mac mini button spring returns the captured plunger "
                        "to its modeled shoulder"
                    ),
                },
                "assembled_bottom_recess_mm": 1.0,
                "assembled_top_gap_mm": 0.25,
                "available_upward_travel_mm": (
                    cradle_height
                    - power_button_shoulder_z
                    - plunger_head_length
                ),
                "fan_mount_bore_diameter_mm": fan_mount_hole_diameter,
                "conservative_euler_buckling_load_n": round(
                    euler_buckling_load_n,
                    2,
                ),
                "assumed_button_force_n": assumed_button_force_n,
                "buckling_safety_factor": round(
                    euler_buckling_load_n / assumed_button_force_n,
                    1,
                ),
                "service_method": (
                    "operate through rear portal; for removal lift Mac mini, "
                    "withdraw plunger upward, then release fan"
                ),
            },
        )
        sealed_portal_control_shape = chassis_shape
        for filler in air_portal_fillers:
            sealed_portal_control_shape = (
                sealed_portal_control_shape.union(
                    filler,
                    clean=True,
                )
            )
        sealed_portal_control_shape = sealed_portal_control_shape.clean()
        self.manufacturing_control_parts = [
            CADPart(
                "fan_chassis_sealed_portal_control_DO_NOT_PRINT",
                sealed_portal_control_shape,
                {
                    "dimensions_mm": (
                        chassis_length,
                        chassis_width,
                        fan_deck_height,
                    ),
                    "material": material,
                    "control_kind": "sealed_main_air_portals",
                    "production_part": "fan_chassis",
                    "do_not_print": True,
                    "purpose": (
                        "real-slice A/B control that restores only the four "
                        "main lateral airflow portal wall volumes"
                    ),
                    "restored_portal_count": len(air_portal_fillers),
                    "excluded_from_assembly": True,
                    "excluded_from_production_totals": True,
                },
            )
        ]
        return [
            chassis,
            controller_cover,
            fan_guard,
            mac_mini_cradle,
            power_button_plunger,
        ]
