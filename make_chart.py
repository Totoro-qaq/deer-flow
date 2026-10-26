"""Render chart-data.json as an SVG (and an HTML wrapper for a headless-Chrome PNG). Standard library only."""

import json
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
data = json.loads((here / "chart-data.json").read_text(encoding="utf-8"))
out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else here

W, H = 1200, 620
FG, MUTED, LINE = "#1f2328", "#59636e", "#d1d9e0"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
STYLE = {  # outcome: fill, text colour, legend
    "delivered": ("#dde3e9", MUTED, "Delivered: presented at least one file it created"),
    "after_loop_warning": ("#bc4c00", "#ffffff", "Answered right after a loop warning, presented nothing, failed the delivery check"),
    "step_limit": ("#cf222e", "#ffffff", "Stopped at the step limit with LangGraph's raw error, presented nothing"),
}
left, label_w, top = 64, 262, 158
cell_w, cell_h, gap, row_gap = 46, 50, 6, 40

parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">',
    f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
    f'<text x="{left}" y="56" font-size="30" font-weight="600" fill="{FG}">{data["runs"] - data["outcomes"]["delivered"]} of {data["runs"]} runs created files and delivered none of them</text>',
    f'<text x="{left}" y="92" font-size="19" fill="{MUTED}">Recorded /goal runs from three DeerFlow bench batches, before this change. One setup: DeepSeek V4.1 Flash,</text>',
    f'<text x="{left}" y="118" font-size="19" fill="{MUTED}">thinking on, recursion_limit 1,000, four office tasks. These counts belong to this setup.</text>',
]
y = top
for batch in data["batches"]:
    runs = batch["runs"]
    parts.append(f'<text x="{left}" y="{y + cell_h / 2 + 7:.0f}" font-size="19" font-weight="600" fill="{FG}">{batch["label"]}</text>')
    parts.append(f'<text x="{left}" y="{y + cell_h / 2 + 30:.0f}" font-size="16" fill="{MUTED}">{len(runs)} runs</text>')
    for index, run in enumerate(runs):
        x = left + label_w + index * (cell_w + gap)
        fill, ink, _ = STYLE[run["outcome"]]
        parts.append(f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="7" fill="{fill}"/>')
        if run["outcome"] != "delivered":
            parts.append(f'<text x="{x + cell_w / 2}" y="{y + 23}" font-size="17" font-weight="700" fill="{ink}" text-anchor="middle">{run["produced"]}</text>')
            parts.append(f'<text x="{x + cell_w / 2}" y="{y + 41}" font-size="12" fill="{ink}" text-anchor="middle">files</text>')
    y += cell_h + row_gap

legend_y = y + 6
for outcome, (fill, _, text) in STYLE.items():
    count = data["outcomes"].get(outcome, 0)
    parts.append(f'<rect x="{left}" y="{legend_y - 17}" width="22" height="22" rx="5" fill="{fill}"/>')
    parts.append(f'<text x="{left + 34}" y="{legend_y}" font-size="19" fill="{FG}"><tspan font-weight="700">{count}</tspan>  {text}</text>')
    legend_y += 36
parts.append(
    f'<text x="{left}" y="{H - 44}" font-size="16" fill="{MUTED}">Numbers in a cell: files the run created in /mnt/user-data/outputs. '
    f'{data["runs_with_loop_warning"]} runs saw a loop warning; {data["runs_with_loop_warning_delivered"]} of them still delivered.</text>'
)
parts.append(f'<text x="{left}" y="{H - 20}" font-size="16" fill="{MUTED}">Each square is one run. All four runs without a delivery had seen a loop warning first.</text>')
parts.append("</svg>")
svg = "\n".join(parts)
(out_dir / "delivery-outcomes.svg").write_text(svg, encoding="utf-8")
(out_dir / "delivery-outcomes.html").write_text(
    f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:#fff}}</style></head><body>{svg}</body></html>',
    encoding="utf-8",
)
print("wrote", out_dir / "delivery-outcomes.svg")
