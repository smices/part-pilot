"""Render generated CAD parts to lightweight SVG previews."""

from pathlib import Path

import cadquery as cq

from ai_cad_designer.agents.joint_agent import JointAgent
from ai_cad_designer.agents.assembly_agent import AssemblyAgent


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs"


def translated(part, x: float, y: float = 0, z: float = 0) -> cq.Shape:
    return part.solid().moved(cq.Location(cq.Vector(x, y, z)))


def export_preview(name: str, shapes: list[cq.Shape]) -> None:
    compound = cq.Compound.makeCompound(shapes)
    cq.exporters.export(
        compound,
        str(OUTPUT / f"{name}.svg"),
        exportType="SVG",
        opt={
            "width": 1000,
            "height": 600,
            "marginLeft": 30,
            "marginTop": 30,
            "showAxes": False,
            "projectionDir": (1.0, -1.0, 0.75),
            "strokeWidth": 0.8,
            "strokeColor": (20, 30, 45),
            "hiddenColor": (150, 160, 175),
            "showHidden": False,
        },
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    agent = JointAgent()
    base, lid = agent.two_piece_snap_enclosure()
    export_preview(
        "two_piece_enclosure_preview",
        [translated(base, -48), translated(lid, 48)],
    )

    robot = agent.desktop_robot_parts()
    offsets = (-135, -45, 55, 135)
    export_preview(
        "desktop_robot_preview",
        [translated(part, offset) for part, offset in zip(robot, offsets, strict=True)],
    )
    smart_fan = agent.smart_fan_parts()
    assembly = AssemblyAgent().smart_fan(smart_fan)
    assembled = [
        part.solid().moved(assembly.placements[part.name])
        for part in smart_fan
    ]
    mac_reference = (
        cq.Workplane("XY")
        .box(127.0, 127.0, 50.0, centered=(True, True, False))
        .edges("|Z")
        .fillet(9.0)
        .val()
        .moved(cq.Location(cq.Vector(0, 0, 36.0)))
    )
    export_preview(
        "mac_mini_m4_floating_halo_assembled",
        assembled + [mac_reference],
    )
    exploded = []
    for index, part in enumerate(smart_fan):
        location = assembly.placements[part.name]
        translation, rotation = location.toTuple()
        exploded_location = cq.Location(
            cq.Vector(
                translation[0],
                translation[1],
                translation[2] + index * 18.0,
            ),
            cq.Vector(1, 0, 0),
            rotation[0],
        )
        exploded.append(part.solid().moved(exploded_location))
    export_preview("mac_mini_m4_floating_halo_exploded", exploded)
    print(OUTPUT / "two_piece_enclosure_preview.svg")
    print(OUTPUT / "desktop_robot_preview.svg")
    print(OUTPUT / "mac_mini_m4_floating_halo_assembled.svg")
    print(OUTPUT / "mac_mini_m4_floating_halo_exploded.svg")


if __name__ == "__main__":
    main()
