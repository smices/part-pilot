"""Low-cost physical fit coupons derived from production CAD parameters."""

from __future__ import annotations

import math

import cadquery as cq

from ai_cad_designer.core import CADPart


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
    return shape.edges("|Z").fillet(
        min(radius_mm, length_mm / 2 - 0.1, width_mm / 2 - 0.1)
    )


class CalibrationAgent:
    """Generate test pieces that validate uncertain interfaces before a full print."""

    def smart_fan(
        self,
        production_parts: list[CADPart],
        reference_parts: list[CADPart],
    ) -> list[CADPart]:
        by_name = {part.name: part for part in production_parts}
        chassis = by_name["fan_chassis"]
        cover = by_name["controller_cover"]
        cradle = by_name["mac_mini_cradle"]
        tolerance = float(cradle.metadata["tolerance_mm"])
        parameters = cradle.metadata["engineering_parameters"]
        mac_reference = next(
            part
            for part in reference_parts
            if part.name == "mac_mini_m4_fit_reference"
        )

        cradle_length, cradle_width, cradle_height = (
            float(value) for value in cradle.metadata["dimensions_mm"]
        )
        coupon_size = 40.0
        coupon_center = (
            -cradle_length / 2 + coupon_size / 2,
            cradle_width / 2 - coupon_size / 2,
        )
        coupon_cutter = (
            cq.Workplane("XY")
            .box(
                coupon_size,
                coupon_size,
                cradle_height + 1.0,
                centered=(True, True, False),
            )
            .translate((*coupon_center, -0.25))
        )
        corner_coupon_shape = cradle.shape.intersect(coupon_cutter).translate(
            (-coupon_center[0], -coupon_center[1], 0.0)
        )
        corner_coupon = CADPart(
            "mac_corner_button_fit_coupon",
            corner_coupon_shape,
            {
                "dimensions_mm": (
                    coupon_size,
                    coupon_size,
                    cradle_height,
                ),
                "wall_thickness_mm": float(
                    cradle.metadata["wall_thickness_mm"]
                ),
                "material": cradle.metadata["material"],
                "tolerance_mm": tolerance,
                "print_orientation": "production interface on build plate",
                "support_strategy": "none",
                "display_name": "Mac 后左角与电源键试片",
                "calibration_kind": "正式托架几何原位裁切",
                "source_part": cradle.name,
                "interfaces": [
                    "Mac rear-left rounded locating corner",
                    "underside power-button access bore",
                    "rear-left silicone support-pad recess",
                ],
                "engineering_parameters": {
                    key: parameters[key]
                    for key in (
                        "mac_length_mm",
                        "mac_width_mm",
                        "mac_corner_radius_mm",
                        "mac_foot_height_mm",
                        "power_button_x_mm",
                        "power_button_y_mm",
                        "power_button_diameter_mm",
                    )
                },
                "test_method": (
                    "将断电后的 Mac 后左角放入试片，确认圆弧定位面贴合且"
                    "无翘动，再检查按钮孔与临时推杆是否对准。"
                ),
            },
        )

        fan_size = float(parameters["fan_size_mm"])
        fan_spacing = float(parameters["fan_mount_spacing_mm"])
        fan_hole = float(parameters["fan_mount_hole_diameter_mm"])
        base_outer = 123.0
        base_height = 1.6
        wall_height = 5.0
        fan_gauge_shape = _rounded_box(
            123.0,
            123.0,
            wall_height,
            5.0,
        ).cut(
                _rounded_box(
                    fan_size + 2 * tolerance,
                    fan_size + 2 * tolerance,
                    wall_height + 0.4,
                    4.0 + tolerance,
                ).translate((0.0, 0.0, -0.1))
        )
        for x_pos in (-fan_spacing / 2, fan_spacing / 2):
            for y_pos in (-fan_spacing / 2, fan_spacing / 2):
                fan_gauge_shape = fan_gauge_shape.union(
                    cq.Workplane("XY")
                    .center(x_pos, y_pos)
                    .circle(5.5)
                    .extrude(base_height)
                )
                connector_angle = 45.0 if x_pos * y_pos > 0 else -45.0
                connector_center = (
                    x_pos + (2.5 if x_pos > 0 else -2.5),
                    y_pos + (2.5 if y_pos > 0 else -2.5),
                )
                fan_gauge_shape = fan_gauge_shape.union(
                    cq.Workplane("XY")
                    .box(
                        14.0,
                        4.0,
                        base_height,
                        centered=(True, True, False),
                    )
                    .rotate(
                        (0.0, 0.0, 0.0),
                        (0.0, 0.0, 1.0),
                        connector_angle,
                    )
                    .translate((*connector_center, 0.0))
                )
                fan_gauge_shape = fan_gauge_shape.cut(
                    cq.Workplane("XY")
                    .center(x_pos, y_pos)
                    .circle(fan_hole / 2)
                    .extrude(wall_height + 0.5)
                    .translate((0.0, 0.0, -0.1))
                )
        fan_gauge = CADPart(
            "fan_mount_fit_gauge",
            fan_gauge_shape,
            {
                "dimensions_mm": (base_outer, base_outer, wall_height),
                "wall_thickness_mm": 1.25,
                "material": chassis.metadata["material"],
                "tolerance_mm": tolerance,
                "print_orientation": "flat",
                "support_strategy": "none",
                "display_name": "120 mm 风扇外框与孔距检具",
                "calibration_kind": "风扇外包络与四孔位检具",
                "source_part": chassis.name,
                "fan_envelope_mm": (
                    fan_size,
                    fan_size,
                    float(parameters["fan_thickness_mm"]),
                ),
                "fan_cavity_mm": fan_size + 2 * tolerance,
                "mount_spacing_mm": (fan_spacing, fan_spacing),
                "mount_hole_diameter_mm": fan_hole,
                "test_method": (
                    "把实际风扇放入薄壁定位框，并用四根临时销检查孔位；"
                    "打印完整机架前记录过紧、晃量或孔位偏差。"
                ),
            },
        )

        clearances = (
            round(max(0.1, tolerance - 0.1), 3),
            round(tolerance, 3),
            round(tolerance + 0.1, 3),
        )
        nominal_pin = 6.0
        socket_height = 4.0
        socket_shape = _rounded_box(56.0, 20.0, socket_height, 2.0)
        for index, (x_pos, clearance) in enumerate(
            zip((-18.0, 0.0, 18.0), clearances, strict=True),
            start=1,
        ):
            socket_shape = socket_shape.cut(
                cq.Workplane("XY")
                .center(x_pos, 0.0)
                .rect(
                    nominal_pin + 2 * clearance,
                    nominal_pin + 2 * clearance,
                )
                .extrude(socket_height + 0.4)
                .translate((0.0, 0.0, -0.2))
            )
            for dot in range(index):
                socket_shape = socket_shape.cut(
                    cq.Workplane("XY")
                    .center(
                        x_pos + (dot - (index - 1) / 2) * 2.2,
                        -7.0,
                    )
                    .circle(0.6)
                    .extrude(socket_height + 0.4)
                    .translate((0.0, 0.0, -0.2))
                )
        socket_gauge = CADPart(
            "petg_clearance_socket_gauge",
            socket_shape,
            {
                "dimensions_mm": (56.0, 20.0, socket_height),
                "wall_thickness_mm": socket_height,
                "material": cradle.metadata["material"],
                "tolerance_mm": tolerance,
                "print_orientation": "flat",
                "support_strategy": "none",
                "display_name": "PETG 三档间隙插孔板",
                "calibration_kind": "三档单边间隙阶梯",
                "nominal_pin_mm": nominal_pin,
                "clearance_per_side_mm": clearances,
                "identification": "one, two and three dots from tight to loose",
                "test_method": (
                    "冷却后依次插入配套测试销，选择能够反复拆装、无发白"
                    "且不过度晃动的最小间隙。"
                ),
            },
        )

        pin_shape = _rounded_box(18.0, 14.0, 3.0, 2.0).union(
            cq.Workplane("XY")
            .rect(nominal_pin, nominal_pin)
            .extrude(8.0)
            .translate((0.0, 0.0, 3.0))
        )
        test_pin = CADPart(
            "petg_clearance_test_pin",
            pin_shape,
            {
                "dimensions_mm": (18.0, 14.0, 11.0),
                "wall_thickness_mm": nominal_pin,
                "material": cradle.metadata["material"],
                "tolerance_mm": tolerance,
                "print_orientation": "handle on build plate",
                "support_strategy": "none",
                "display_name": "PETG 标准测试销",
                "calibration_kind": "6 mm 标准间隙探针",
                "nominal_pin_mm": nominal_pin,
                "test_method": (
                    "必须与插孔板使用和正式外壳相同的方向、材料、层高及"
                    "打印机配置打印。"
                ),
            },
        )

        probe_retention = cover.metadata["ds18b20_probe_retention"]
        probe_coupon_length = 18.0
        probe_coupon_width = 14.0
        probe_coupon_center_y = 18.5
        probe_coupon_cutter = (
            cq.Workplane("XY")
            .box(
                probe_coupon_length,
                probe_coupon_width,
                30.0,
                centered=(True, True, False),
            )
            .translate((0.0, probe_coupon_center_y, -0.1))
        )
        probe_coupon_shape = (
            cover.shape
            .intersect(probe_coupon_cutter)
            .translate((0.0, -probe_coupon_center_y, 0.0))
        )
        probe_coupon_bounds = probe_coupon_shape.val().BoundingBox()
        probe_coupon = CADPart(
            "ds18b20_snap_fit_coupon",
            probe_coupon_shape,
            {
                "dimensions_mm": (
                    round(float(probe_coupon_bounds.xlen), 3),
                    round(float(probe_coupon_bounds.ylen), 3),
                    round(float(probe_coupon_bounds.zlen), 3),
                ),
                "wall_thickness_mm": float(
                    cover.metadata["wall_thickness_mm"]
                ),
                "material": cover.metadata["material"],
                "tolerance_mm": tolerance,
                "print_orientation": "production outer face on build plate",
                "support_strategy": "none",
                "display_name": "DS18B20 探头双卡座试片",
                "calibration_kind": "正式载架探头卡座原位裁切",
                "source_part": cover.name,
                "probe_diameter_mm": probe_retention[
                    "probe_diameter_mm"
                ],
                "bore_diameter_mm": probe_retention[
                    "bore_diameter_mm"
                ],
                "entry_slot_width_mm": probe_retention[
                    "entry_slot_width_mm"
                ],
                "snap_interference_per_side_mm": probe_retention[
                    "snap_interference_per_side_mm"
                ],
                "bearing_count": probe_retention["bearing_count"],
                "engineering_parameters": {
                    key: parameters[key]
                    for key in (
                        "ds18b20_probe_diameter_mm",
                        "ds18b20_snap_interference_per_side_mm",
                    )
                },
                "test_method": (
                    "使用实际 Ø6 mm 金属探头，沿与正式载架相同方向压入"
                    "两个 C 形卡座；连续拆装 10 次，确认无发白、裂纹或"
                    "松脱，并记录实测探头直径及合适的单边卡扣干涉量。"
                ),
            },
        )

        exterior = chassis.metadata["exterior_continuity"]
        service_access = chassis.metadata["controller_service_access"]
        coupon_wall = float(chassis.metadata["wall_thickness_mm"])
        bridge_base_length = 88.0
        bridge_base_width = 8.0
        bridge_base_height = 1.2
        bridge_panel_height = 24.0

        def arch_panel(
            *,
            center_x: float,
            panel_width: float,
            opening_width: float,
            bottom_z: float,
            roof_start_z: float,
            top_z: float,
            crown_half_width: float,
            fillet_radius: float,
        ) -> cq.Workplane:
            half_width = opening_width / 2
            points = (
                (center_x - half_width, bottom_z),
                (center_x + half_width, bottom_z),
                (center_x + half_width, roof_start_z),
                (center_x + crown_half_width, top_z),
                (center_x - crown_half_width, top_z),
                (center_x - half_width, roof_start_z),
            )
            profile_wire = cq.Workplane("XZ").polyline(points).close().val()
            rounded_wire = profile_wire.fillet2D(
                fillet_radius,
                profile_wire.Vertices(),
            )
            cutter = (
                cq.Workplane("XZ")
                .add(rounded_wire)
                .toPending()
                .extrude(coupon_wall / 2 + 0.5, both=True)
            )
            return (
                cq.Workplane("XY")
                .box(
                    panel_width,
                    coupon_wall,
                    bridge_panel_height,
                    centered=(True, True, False),
                )
                .translate((center_x, 0.0, 0.0))
                .cut(cutter)
            )

        main_portal_slope = float(exterior["minimum_roof_slope_deg"])
        main_opening_width = 48.0
        main_crown_half_width = (
            float(exterior["crown_bridge_mm"]) / 2
        )
        main_bottom_z = bridge_base_height
        main_roof_start_z = 8.0
        main_top_z = main_roof_start_z + math.tan(
            math.radians(main_portal_slope)
        ) * (main_opening_width / 2 - main_crown_half_width)
        main_panel = arch_panel(
            center_x=-15.0,
            panel_width=54.0,
            opening_width=main_opening_width,
            bottom_z=main_bottom_z,
            roof_start_z=main_roof_start_z,
            top_z=main_top_z,
            crown_half_width=main_crown_half_width,
            fillet_radius=float(exterior["profile_fillet_radius_mm"]),
        )

        usb_opening_width = float(
            service_access["usb_port_dimensions_mm"][0]
        )
        usb_crown_half_width = float(
            service_access["port_crown_half_width_mm"]
        )
        usb_bottom_z = bridge_base_height
        usb_roof_start_z = 6.5
        usb_top_z = usb_roof_start_z + (
            usb_opening_width / 2 - usb_crown_half_width
        )
        usb_panel = arch_panel(
            center_x=29.0,
            panel_width=26.0,
            opening_width=usb_opening_width,
            bottom_z=usb_bottom_z,
            roof_start_z=usb_roof_start_z,
            top_z=usb_top_z,
            crown_half_width=usb_crown_half_width,
            fillet_radius=0.6,
        )
        bridge_coupon_shape = (
            _rounded_box(
                bridge_base_length,
                bridge_base_width,
                bridge_base_height,
                2.0,
            )
            .union(main_panel)
            .union(usb_panel)
            .clean()
        )
        bridge_coupon_bounds = bridge_coupon_shape.val().BoundingBox()
        bridge_coupon = CADPart(
            "portal_bridge_support_coupon",
            bridge_coupon_shape,
            {
                "dimensions_mm": (
                    round(float(bridge_coupon_bounds.xlen), 3),
                    round(float(bridge_coupon_bounds.ylen), 3),
                    round(float(bridge_coupon_bounds.zlen), 3),
                ),
                "wall_thickness_mm": coupon_wall,
                "material": chassis.metadata["material"],
                "tolerance_mm": tolerance,
                "print_orientation": (
                    "upright portals on the integrated base"
                ),
                "support_strategy": "none",
                "display_name": "主风口与 USB 自支撑桥接试片",
                "calibration_kind": "正式风口拱冠与屋肩等效截面",
                "source_part": chassis.name,
                "features": {
                    "main_portal_crown_bridge_mm": float(
                        exterior["crown_bridge_mm"]
                    ),
                    "main_portal_minimum_roof_slope_deg": (
                        main_portal_slope
                    ),
                    "main_portal_profile_fillet_radius_mm": float(
                        exterior["profile_fillet_radius_mm"]
                    ),
                    "usb_effective_bridge_mm": float(
                        service_access["port_effective_bridge_mm"]
                    ),
                    "usb_minimum_roof_slope_deg": float(
                        service_access["port_minimum_roof_slope_deg"]
                    ),
                },
                "acceptance": {
                    "maximum_crown_sag_mm": 0.5,
                    "layer_separation_allowed": False,
                    "support_material_allowed": False,
                    "required_material": chassis.metadata["material"],
                    "required_layer_height_mm": 0.2,
                },
                "test_method": (
                    "使用与正式机架相同的 PETG、喷嘴、层高、桥接流量与"
                    "冷却设置，保持当前方向且关闭支撑打印。冷却后测量两"
                    "个拱冠最低点下垂；任一处超过 0.5 mm、出现分层或"
                    "拉丝堵塞开口时，不应直接打印完整机架，应先调整桥接"
                    "流量/速度/冷却或在切片器中只对失败位置添加局部支撑。"
                ),
            },
        )

        io_gauge_length = float(
            mac_reference.metadata["dimensions_mm"][0]
        )
        mac_body_bottom_z = float(
            mac_reference.metadata["engineering_parameters"][
                "mac_foot_height_mm"
            ]
        )
        io_gauge_top_z = 20.0
        io_gauge_height = io_gauge_top_z - mac_body_bottom_z
        io_gauge_thickness = 1.2

        def io_alignment_gauge(face: str) -> CADPart:
            markers = [
                marker
                for marker in mac_reference.metadata["interface_markers"]
                if marker["face"] == face
            ]
            gauge_shape = _rounded_box(
                io_gauge_length,
                io_gauge_height,
                io_gauge_thickness,
                2.0,
            )
            gauge_vertical_center_z = (
                mac_body_bottom_z + io_gauge_top_z
            ) / 2
            calibrated_markers = []
            for marker in markers:
                opening_width = float(marker["opening_width_mm"])
                opening_height = float(marker["opening_height_mm"])
                center_z = float(marker["center_z_mm"])
                clipped_bottom_z = max(
                    mac_body_bottom_z,
                    center_z - opening_height / 2,
                )
                clipped_top_z = min(
                    io_gauge_top_z,
                    center_z + opening_height / 2,
                )
                clipped_height = clipped_top_z - clipped_bottom_z
                cutter = (
                    cq.Workplane("XY")
                    .box(
                        opening_width + 2 * tolerance,
                        clipped_height + 2 * tolerance,
                        io_gauge_thickness + 0.4,
                        centered=(True, True, False),
                    )
                    .translate(
                        (
                            float(marker["center_x_mm"]),
                            (
                                clipped_bottom_z
                                + clipped_top_z
                            )
                            / 2
                            - gauge_vertical_center_z,
                            -0.2,
                        )
                    )
                )
                gauge_shape = gauge_shape.cut(cutter)
                calibrated_markers.append(
                    {
                        **marker,
                        "gauge_window_width_mm": (
                            opening_width + 2 * tolerance
                        ),
                        "gauge_window_height_mm": (
                            clipped_height + 2 * tolerance
                        ),
                        "gauge_local_y_mm": (
                            center_z - gauge_vertical_center_z
                        ),
                    }
                )
            material_relief_windows = []
            if face == "front":
                for center_x, window_width in (
                    (-38.0, 36.0),
                    (43.0, 26.0),
                ):
                    relief = _rounded_box(
                        window_width,
                        12.0,
                        io_gauge_thickness + 0.4,
                        2.0,
                    ).translate((center_x, 0.0, -0.2))
                    gauge_shape = gauge_shape.cut(relief)
                    material_relief_windows.append(
                        {
                            "center_x_mm": center_x,
                            "width_mm": window_width,
                            "height_mm": 12.0,
                            "corner_radius_mm": 2.0,
                        }
                    )
            identification_dot_count = 1 if face == "front" else 2
            for index in range(identification_dot_count):
                dot_x = (
                    -io_gauge_length / 2
                    + 5.0
                    + index * 3.0
                )
                gauge_shape = gauge_shape.cut(
                    cq.Workplane("XY")
                    .center(dot_x, io_gauge_height / 2 - 3.0)
                    .circle(0.8)
                    .extrude(io_gauge_thickness + 0.4)
                    .translate((0.0, 0.0, -0.2))
                )
            gauge_shape = gauge_shape.clean()
            display_face = "前面" if face == "front" else "后面"
            return CADPart(
                f"mac_{face}_io_alignment_gauge",
                gauge_shape,
                {
                    "dimensions_mm": (
                        io_gauge_length,
                        io_gauge_height,
                        io_gauge_thickness,
                    ),
                    "wall_thickness_mm": io_gauge_thickness,
                    "material": cradle.metadata["material"],
                    "tolerance_mm": tolerance,
                    "print_orientation": "flat on broad face",
                    "support_strategy": "none",
                    "display_name": (
                        f"Mac {display_face} I/O 对位检具"
                    ),
                    "calibration_kind": (
                        "Mac 机身底边基准平面接口模板"
                    ),
                    "source_part": mac_reference.name,
                    "face": face,
                    "body_bottom_datum_z_mm": mac_body_bottom_z,
                    "gauge_top_z_mm": io_gauge_top_z,
                    "identification_dot_count": (
                        identification_dot_count
                    ),
                    "interface_markers": calibrated_markers,
                    "material_relief_windows": (
                        material_relief_windows
                    ),
                    "coordinate_offsets_mm": (
                        mac_reference.metadata[
                            "interface_coordinate_offsets_mm"
                        ][face]
                    ),
                    "acceptance": {
                        "maximum_group_center_error_mm": 0.5,
                        "all_ports_visible_inside_windows": True,
                        "support_material_allowed": False,
                    },
                    "test_method": (
                        f"将检具底边对齐 Mac 机身本体底边并贴合{display_face}；"
                        "确认全部接口完整落入窗口，测量整组接口相对模板的 "
                        "X/Z 偏移。前面检具为一个识别孔，后面为两个识别孔。"
                    ),
                },
            )

        front_io_gauge = io_alignment_gauge("front")
        rear_io_gauge = io_alignment_gauge("rear")
        return [
            corner_coupon,
            front_io_gauge,
            rear_io_gauge,
            fan_gauge,
            socket_gauge,
            test_pin,
            probe_coupon,
            bridge_coupon,
        ]
