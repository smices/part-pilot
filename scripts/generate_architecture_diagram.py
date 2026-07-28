"""Generate the implementation-aligned AI CAD architecture diagram."""

from pathlib import Path


OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "architecture.svg"


def node(
    lines: list[str],
    node_id: str,
    x: int,
    y: int,
    width: int,
    height: int,
    title: str,
    subtitle: str,
    fill: str,
    stroke: str,
    *,
    dashed: bool = False,
) -> None:
    dash = ' stroke-dasharray="7,4"' if dashed else ""
    lines.append(
        f'  <g id="{node_id}" data-graph-role="node">'
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>'
    )
    lines.append(
        f'    <text x="{x + width / 2:g}" y="{y + 31}" text-anchor="middle" '
        f'class="node-title">{title}</text>'
    )
    lines.append(
        f'    <text x="{x + width / 2:g}" y="{y + 53}" text-anchor="middle" '
        f'class="node-subtitle">{subtitle}</text></g>'
    )


def edge(
    lines: list[str],
    edge_id: str,
    path: str,
    label: str,
    label_x: int,
    label_y: int,
    color: str,
    marker: str,
    *,
    dashed: bool = False,
) -> None:
    dash = ' stroke-dasharray="6,4"' if dashed else ""
    lines.append(
        f'  <path id="{edge_id}" data-graph-role="edge" d="{path}" '
        f'fill="none" stroke="{color}" stroke-width="2" '
        f'marker-end="url(#{marker})"{dash}/>'
    )
    lines.append(
        f'  <text x="{label_x}" y="{label_y}" text-anchor="middle" '
        f'class="edge-label" fill="{color}">{label}</text>'
    )


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 700" '
        'width="1200" height="700" role="img" '
        'aria-labelledby="diagram-title diagram-description">'
    )
    lines.append(
        "  <title id=\"diagram-title\">AI industrial design engineering workflow</title>"
    )
    lines.append(
        '  <desc id="diagram-description">Natural language requirements flow through '
        "local Codex or compatible API planning, parametric CAD, OpenCascade validation, "
        "exports, FreeCAD, and OrcaSlicer. Computer vision is implemented; CAD memory is "
        "a future interface.</desc>"
    )
    lines.append("  <style>")
    lines.append(
        "    text { font-family: 'Helvetica Neue', Helvetica, Arial, 'PingFang SC', "
        "'Microsoft YaHei', sans-serif; fill: #111827; }"
    )
    lines.append("    .title { font-size: 22px; font-weight: 600; }")
    lines.append("    .subtitle { font-size: 13px; fill: #6b7280; }")
    lines.append("    .lane-title { font-size: 12px; font-weight: 600; fill: #6b7280; }")
    lines.append("    .node-title { font-size: 15px; font-weight: 600; }")
    lines.append("    .node-subtitle { font-size: 12px; fill: #6b7280; }")
    lines.append("    .edge-label { font-size: 12px; font-weight: 500; }")
    lines.append("  </style>")
    lines.append("  <defs>")
    for marker_id, color in (
        ("arrow-blue", "#2563eb"),
        ("arrow-green", "#16a34a"),
        ("arrow-purple", "#9333ea"),
    ):
        lines.append(
            f'    <marker id="{marker_id}" markerWidth="10" markerHeight="7" '
            'refX="9" refY="3.5" orient="auto">'
            f'<polygon points="0 0, 10 3.5, 0 7" fill="{color}"/></marker>'
        )
    lines.append("  </defs>")
    lines.append('  <rect width="1200" height="700" fill="#ffffff"/>')
    lines.append(
        '  <text x="48" y="42" class="title">AI CAD Industrial Design Workstation</text>'
    )
    lines.append(
        '  <text x="48" y="66" class="subtitle">'
        "LLM/Codex -> Engineering Reasoning -> Parametric CAD -> Assembly -> Manufacturing"
        "</text>"
    )
    lines.append(
        '  <rect x="40" y="92" width="1120" height="210" rx="12" '
        'fill="#f8fafc" stroke="#d1d5db" stroke-dasharray="6,4"/>'
    )
    lines.append('  <text x="58" y="116" class="lane-title">WORKING PROTOTYPE</text>')
    lines.append(
        '  <rect x="40" y="340" width="1120" height="190" rx="12" '
        'fill="#faf5ff" stroke="#e9d5ff" stroke-dasharray="6,4"/>'
    )
    lines.append(
        '  <text x="58" y="364" class="lane-title">'
        "VISION, REVIEW AND MANUFACTURING</text>"
    )

    node(
        lines,
        "request",
        70,
        155,
        180,
        82,
        "CLI + Local GUI",
        "Text / hardware photos",
        "#eff6ff",
        "#93c5fd",
    )
    node(
        lines,
        "design-agent",
        300,
        135,
        190,
        122,
        "Engineering Agent",
        "Codex · API · schema",
        "#fff7ed",
        "#fdba74",
    )
    node(
        lines,
        "parametric-cad",
        550,
        135,
        190,
        122,
        "Parametric CAD",
        "CadQuery · build123d",
        "#f0fdfa",
        "#5eead4",
    )
    node(
        lines,
        "validation",
        800,
        135,
        170,
        122,
        "Geometry + Print",
        "OCP · OCC · Mesh",
        "#f0fdf4",
        "#86efac",
    )
    node(
        lines,
        "exports",
        1030,
        155,
        130,
        82,
        "Manufacturing",
        "STEP · STL",
        "#eff6ff",
        "#93c5fd",
    )
    node(
        lines,
        "vision",
        80,
        405,
        180,
        82,
        "Computer Vision",
        "Hardware recognition",
        "#faf5ff",
        "#c4b5fd",
    )
    node(
        lines,
        "memory",
        330,
        405,
        180,
        82,
        "CAD Memory",
        "Design preferences (future)",
        "#ffffff",
        "#c4b5fd",
        dashed=True,
    )
    node(
        lines,
        "freecad",
        720,
        405,
        170,
        82,
        "FreeCAD",
        "Review / edit / assemble",
        "#eff6ff",
        "#93c5fd",
    )
    node(
        lines,
        "orcaslicer",
        970,
        405,
        170,
        82,
        "OrcaSlicer",
        "Slice / G-code",
        "#f0fdf4",
        "#86efac",
    )

    edge(lines, "e1", "M 250 196 H 300", "Brief", 275, 185, "#2563eb", "arrow-blue")
    edge(lines, "e2", "M 490 196 H 550", "Part plan", 520, 185, "#2563eb", "arrow-blue")
    edge(lines, "e3", "M 740 196 H 800", "B-Rep", 770, 185, "#16a34a", "arrow-green")
    edge(lines, "e4", "M 970 196 H 1030", "Valid", 1000, 185, "#16a34a", "arrow-green")
    edge(
        lines,
        "e5",
        "M 1085 237 V 320 H 805 V 405",
        "STEP",
        946,
        309,
        "#2563eb",
        "arrow-blue",
    )
    edge(
        lines,
        "e6",
        "M 1105 237 V 405",
        "STL",
        1125,
        330,
        "#16a34a",
        "arrow-green",
    )
    edge(
        lines,
        "e7",
        "M 260 446 H 275 V 278 H 350 V 257",
        "Detected parts",
        315,
        293,
        "#9333ea",
        "arrow-purple",
    )
    edge(
        lines,
        "e8",
        "M 420 405 V 286 H 410 V 257",
        "Preferences",
        458,
        324,
        "#9333ea",
        "arrow-purple",
        dashed=True,
    )

    lines.append('  <g transform="translate(70,592)">')
    lines.append('    <text x="0" y="-18" class="lane-title">LEGEND</text>')
    for index, (color, marker, label, dash) in enumerate(
        (
            ("#2563eb", "arrow-blue", "Engineering flow", ""),
            ("#16a34a", "arrow-green", "Validation / output", ""),
            ("#9333ea", "arrow-purple", "Vision / optional input", ""),
        )
    ):
        x = index * 190
        lines.append(
            f'    <line x1="{x}" y1="0" x2="{x + 42}" y2="0" '
            f'stroke="{color}" stroke-width="2" marker-end="url(#{marker})"{dash}/>'
        )
        lines.append(
            f'    <text x="{x + 55}" y="4" class="subtitle">{label}</text>'
        )
    lines.append("  </g>")
    lines.append(
        '  <text x="1135" y="670" text-anchor="end" class="subtitle">'
        "Implementation: ai_cad_designer v0.2</text>"
    )
    lines.append("</svg>")
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
