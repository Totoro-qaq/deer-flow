"""Regrade the eight unchanged output sets with the historical and the fixed minutes rules.

Standard library only. No model, provider or network is used, and the outputs
are read, never modified. For every set the historical rules failed, it also
prints the index line the historical parser picked for each meeting it counted
wrong, next to the actual meeting-table row.

Usage: python regrade.py [--json regrade-results.json]
"""
from __future__ import annotations

import argparse
import ast
import calendar
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("minutes_strict", HERE / "scoring/minutes_strict.py")
strict = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(strict)
LEGACY = HERE / "scoring/legacy_minutes_rules.py"


def _historical_helpers() -> dict:
    """The historical date helpers, loaded the same way the historical rules are."""
    text = LEGACY.read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(text).body
             if isinstance(node, ast.FunctionDef) and node.name in {"_date_forms", "_has_date"}]
    context = {"re": re, "MONTHS_EN": list(calendar.month_name)[1:]}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(LEGACY), "exec"), context)
    return context


def historical_index_misreads(out_dir: Path, expected: dict) -> list[dict]:
    """Meetings whose action count the historical index parser read wrong, with the line it used."""
    old = _historical_helpers()
    lines = (out_dir / "minutes/index.md").read_text(encoding="utf-8").splitlines()
    misreads = []
    for item in expected["items"]:
        first = next(((number, line) for number, line in enumerate(lines, 1) if old["_has_date"](line, item["date"])), None)
        if first is None:
            continue
        rest = first[1]
        for form in old["_date_forms"](item["date"]):
            rest = rest.replace(form, " ")
        numbers = [cell.strip() for cell in rest.split("|") if re.fullmatch(r"\d+", cell.strip())]
        if not numbers:
            numbers = re.findall(r"(?<![\w-])(\d+)(?![\w-])", rest)
        if numbers and int(numbers[-1]) == len(item["actions"]):
            continue
        actual = [{"line": number, "text": line} for number, line in enumerate(lines, 1)
                  if "|" in line and strict._has_date((strict._cells(line) or [""])[0], item["date"])]
        misreads.append({"meeting": item["stem"], "expected_action_count": len(item["actions"]),
                         "historical_line_number": first[0], "historical_line": first[1],
                         "historical_numbers_read": numbers, "actual_meeting_rows": actual})
    return misreads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Also write the full results to this path")
    args = parser.parse_args()
    recorded = json.loads((HERE / "recorded-scores.json").read_text(encoding="utf-8"))
    rows = []
    for record in recorded:
        out_dir = HERE / "outputs" / record["run"]
        expected = json.loads((HERE / "expected" / f"minutes__{record['language']}__r2.json").read_text(encoding="utf-8"))
        legacy = strict.legacy_score_minutes(out_dir, expected, LEGACY)
        fixed = strict.score_minutes(out_dir, expected)
        rows.append({"run": record["run"], "language": record["language"], "recorded": record["recorded"],
                     "historical_rules": legacy, "fixed_rules": fixed,
                     "historical_matches_recorded": all(legacy[k] == record["recorded"][k] for k in ("passed", "total", "completed")),
                     "historical_index_misreads": [] if legacy["completed"] else historical_index_misreads(out_dir, expected)})
    print(f"{'run':5} {'lang':4} {'recorded':>8} {'historical':>10} {'fixed':>6}  historical misreads")
    for row in rows:
        def score(result):
            return f"{result['passed']}/{result['total']}"
        print(f"{row['run']:5} {row['language']:4} {score(row['recorded']):>8} {score(row['historical_rules']):>10} "
              f"{score(row['fixed_rules']):>6}  {len(row['historical_index_misreads'])}")
    summary = {
        "sets": len(rows),
        "recorded_completed": sum(r["recorded"]["completed"] for r in rows),
        "historical_completed": sum(r["historical_rules"]["completed"] for r in rows),
        "fixed_completed": sum(r["fixed_rules"]["completed"] for r in rows),
        "historical_replay_matches_every_recorded_score": all(r["historical_matches_recorded"] for r in rows),
        "fixed_parse_uncertainties": sum(len(r["fixed_rules"]["parse_uncertainties"]) for r in rows),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if args.json:
        args.json.write_text(json.dumps({"summary": summary, "sets": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
