"""Render chart-data.json as an SVG (and an HTML wrapper for a headless-Chrome PNG). Standard library only."""
import json
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
data = json.loads((here / "chart-data.json").read_text())
out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else here

W, H = 1200, 740
left, right, top, bottom = 118, 1150, 150, 590
x_max, y_max = 80, 1100
FG, MUTED, GRID = "#1f2328", "#59636e", "#d1d9e0"
POINT = "#0969da"
BUDGETS = [  # value, colour, label, tool calls that fit
    (1000, "#1a7f37", "1000: web UI today, scheduled runs, #7367 default", 75),
    (250, "#9a6700", "250: GitHub channel floor", 17),
    (100, "#cf222e", "100: IM runs today (hard-coded)", 6),
]
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def sx(x):
    return left + (right - left) * x / x_max


def sy(y):
    return bottom - (bottom - top) * y / y_max


parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">',
    f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
    f'<text x="{left - 70}" y="52" font-size="30" font-weight="600" fill="{FG}">How many tool-calling turns fit in a run\'s step budget</text>',
    f'<text x="{left - 70}" y="88" font-size="19" fill="{MUTED}">Smallest recursion_limit at which a lead-agent run finishes. One setup: base 00678f06, default lead-agent</text>',
    f'<text x="{left - 70}" y="114" font-size="19" fill="{MUTED}">middleware, scripted model. These counts change when the middleware chain changes.</text>',
]
for y in range(0, y_max + 1, 200):
    parts.append(f'<line x1="{left}" y1="{sy(y):.1f}" x2="{right}" y2="{sy(y):.1f}" stroke="{GRID}" stroke-width="1"/>')
    parts.append(f'<text x="{left - 14}" y="{sy(y) + 6:.1f}" font-size="18" fill="{MUTED}" text-anchor="end">{y}</text>')
for x in range(0, x_max + 1, 10):
    parts.append(f'<line x1="{sx(x):.1f}" y1="{bottom}" x2="{sx(x):.1f}" y2="{bottom + 7}" stroke="{MUTED}" stroke-width="1"/>')
    parts.append(f'<text x="{sx(x):.1f}" y="{bottom + 30}" font-size="18" fill="{MUTED}" text-anchor="middle">{x}</text>')
parts.append(f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{MUTED}" stroke-width="1.5"/>')
parts.append(f'<text x="{(left + right) / 2:.1f}" y="{bottom + 66}" font-size="20" fill="{FG}" text-anchor="middle">Tool-calling turns before the final answer</text>')
parts.append(f'<text transform="translate({left - 78},{(top + bottom) / 2:.1f}) rotate(-90)" font-size="20" fill="{FG}" text-anchor="middle">Smallest recursion_limit that finishes</text>')

for value, colour, label, fits in BUDGETS:
    y = sy(value)
    parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{colour}" stroke-width="2.5"/>')
    # The run that still finishes within this budget, dropped to the axis.
    need = 22 + 13 * fits
    parts.append(f'<line x1="{sx(fits):.1f}" y1="{sy(need):.1f}" x2="{sx(fits):.1f}" y2="{bottom}" stroke="{colour}" stroke-width="1.5" stroke-dasharray="4 5"/>')
    # Labels sit where no data is: 1000 on the left, the low budgets on the right.
    anchor, label_x = ("start", left + 8) if value >= 1000 else ("end", right - 6)
    parts.append(f'<text x="{label_x}" y="{y - 10:.1f}" font-size="19" font-weight="600" fill="{colour}" text-anchor="{anchor}">{label}</text>')
    parts.append(f'<text x="{sx(fits) + 8:.1f}" y="{bottom - 12}" font-size="18" font-weight="600" fill="{colour}">{fits}</text>')

xs = [p["tool_calling_turns"] for p in data["points"]]
line = f'M {sx(0):.1f} {sy(22):.1f} L {sx(x_max):.1f} {sy(22 + 13 * x_max):.1f}'
parts.append(f'<path d="{line}" stroke="{POINT}" stroke-width="2" stroke-dasharray="7 6" fill="none"/>')
for p in data["points"]:
    parts.append(f'<circle cx="{sx(p["tool_calling_turns"]):.1f}" cy="{sy(p["min_recursion_limit"]):.1f}" r="5.5" fill="{POINT}"/>')
parts.append(f'<text x="{sx(36):.1f}" y="{sy(22 + 13 * 36) - 16:.1f}" font-size="19" fill="{POINT}" transform="rotate(-27.6 {sx(36):.1f} {sy(22 + 13 * 36) - 16:.1f})">measured: 22 + 13 per turn</text>')
parts.append(f'<text x="{left - 70}" y="{H - 44}" font-size="16" fill="{MUTED}">Each dot is a run that finishes at exactly that limit and fails one step lower '
             f'({len(xs)} turn counts, {min(xs)} to {max(xs)}).</text>')
parts.append(f'<text x="{left - 70}" y="{H - 20}" font-size="16" fill="{MUTED}">Dashed drops mark the most turns each budget allows. Parallel calls in one turn share its steps.</text>')
parts.append("</svg>")
svg = "\n".join(parts)
(out_dir / "im-step-budget.svg").write_text(svg, encoding="utf-8")
(out_dir / "im-step-budget.html").write_text(
    f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:#fff}}</style></head><body>{svg}</body></html>',
    encoding="utf-8")
print("wrote", out_dir / "im-step-budget.svg")
