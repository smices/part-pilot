"""Render the Mac mini M4 dock assembly and airflow architecture diagram."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "mac-mini-m4-floating-halo-architecture.svg"


def main() -> None:
    lines: list[str] = []
    lines.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 720">')
    lines.append("<style>")
    lines.append(
        "text{font-family:'Helvetica Neue',Helvetica,Arial,'PingFang SC',sans-serif}"
    )
    lines.append(".title{font-size:24px;font-weight:700;fill:#111827}")
    lines.append(".subtitle{font-size:13px;fill:#6b7280}")
    lines.append(".label{font-size:15px;font-weight:600;fill:#111827}")
    lines.append(".meta{font-size:12px;fill:#6b7280}")
    lines.append(".flow{font-size:12px;font-weight:600}")
    lines.append("</style>")
    lines.append("<defs>")
    lines.append(
        '<marker id="arrow-blue" markerWidth="10" markerHeight="7" '
        'refX="9" refY="3.5" orient="auto">'
    )
    lines.append('<polygon points="0 0,10 3.5,0 7" fill="#2563eb"/></marker>')
    lines.append(
        '<marker id="arrow-green" markerWidth="10" markerHeight="7" '
        'refX="9" refY="3.5" orient="auto">'
    )
    lines.append('<polygon points="0 0,10 3.5,0 7" fill="#16a34a"/></marker>')
    lines.append(
        '<marker id="arrow-purple" markerWidth="10" markerHeight="7" '
        'refX="9" refY="3.5" orient="auto">'
    )
    lines.append('<polygon points="0 0,10 3.5,0 7" fill="#9333ea"/></marker>')
    lines.append("</defs>")
    lines.append('<rect width="960" height="720" fill="#ffffff"/>')
    lines.append('<text x="48" y="48" class="title">Mac mini M4 Floating Halo V2</text>')
    lines.append(
        '<text x="48" y="72" class="subtitle">'
        "Screwless parametric assembly · 0.25 mm per-side fit · PETG FDM"
        "</text>"
    )

    nodes = [
        (280, 105, 400, 80, "#f3f4f6", "#9ca3af", "Mac mini M4", "127 × 127 × 50 mm reference"),
        (280, 220, 400, 80, "#faf5ff", "#a855f7", "Locating cradle", "127.5 mm cavity · 120 mm central opening"),
        (280, 335, 400, 80, "#f0fdfa", "#14b8a6", "Fan guard", "124 × 124 × 2 mm · removable snap fit"),
        (280, 450, 400, 96, "#f0fdf4", "#22c55e", "Fan chassis", "120.5 mm cavity · lateral intake windows"),
        (720, 458, 190, 80, "#eff6ff", "#3b82f6", "Controller pod", "ESP32 · DC-DC · sensor"),
    ]
    for x, y, width, height, fill, stroke, label, meta in nodes:
        lines.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )
        lines.append(
            f'<text x="{x + width / 2}" y="{y + 33}" '
            f'text-anchor="middle" class="label">{label}</text>'
        )
        lines.append(
            f'<text x="{x + width / 2}" y="{y + 56}" '
            f'text-anchor="middle" class="meta">{meta}</text>'
        )

    for y1, y2 in ((185, 220), (300, 335), (415, 450)):
        lines.append(
            f'<path d="M 410 {y1} L 410 {y2 - 10}" fill="none" '
            'stroke="#2563eb" stroke-width="2.2" marker-end="url(#arrow-blue)"/>'
        )
    lines.append(
        '<text x="388" y="318" text-anchor="end" class="flow" fill="#2563eb">'
        "ASSEMBLY"
        "</text>"
    )

    lines.append(
        '<path d="M 280 498 L 250 498 L 250 145 L 270 145" fill="none" '
        'stroke="#16a34a" stroke-width="3" marker-end="url(#arrow-green)"/>'
    )
    lines.append(
        '<text x="232" y="326" text-anchor="end" class="flow" fill="#16a34a">'
        "BOTTOM AIRFLOW"
        "</text>"
    )
    lines.append(
        '<path d="M 720 498 L 690 498" fill="none" stroke="#9333ea" '
        'stroke-width="2" stroke-dasharray="6,4" marker-end="url(#arrow-purple)"/>'
    )
    lines.append(
        '<text x="700" y="482" text-anchor="middle" class="flow" fill="#9333ea">'
        "SERVICE LINK"
        "</text>"
    )

    lines.append('<text x="68" y="614" class="label">Design gates</text>')
    lines.append(
        '<text x="68" y="640" class="meta">'
        "Front/rear ports open · controller outside airflow keep-out · no screws · minimal supports"
        "</text>"
    )
    lines.append(
        '<line x1="560" y1="615" x2="600" y2="615" stroke="#2563eb" '
        'stroke-width="2.2" marker-end="url(#arrow-blue)"/>'
    )
    lines.append('<text x="610" y="619" class="meta">assembly order</text>')
    lines.append(
        '<line x1="560" y1="642" x2="600" y2="642" stroke="#16a34a" '
        'stroke-width="3" marker-end="url(#arrow-green)"/>'
    )
    lines.append('<text x="610" y="646" class="meta">cooling airflow</text>')
    lines.append(
        '<line x1="748" y1="642" x2="788" y2="642" stroke="#9333ea" '
        'stroke-width="2" stroke-dasharray="6,4" marker-end="url(#arrow-purple)"/>'
    )
    lines.append('<text x="798" y="646" class="meta">service access</text>')
    lines.append("</svg>")
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
