"""Offline, fail-closed structural scorer for the saved 60-meeting benchmark.

Only output artifacts and the supplied expected data are read. No Goal verdict,
model, provider, or production module is used. A parse uncertainty prevents a
completion claim but is reported separately from an observed wrong value.
This is bounded structural/fact validation, not exhaustive semantic assessment.
"""

from __future__ import annotations

import calendar
import datetime as dt
import ast
import hashlib
import json
import re
from pathlib import Path

VERSION = "minutes-strict-v1"


def _normal(text: str) -> str:
    return " ".join(text.casefold().replace("**", "").replace("`", "").split())


def _token(text: str, value: str) -> bool:
    # ASCII boundaries also work beside Chinese text (方案B3).
    return re.search(r"(?<![a-z0-9_])" + re.escape(_normal(value)) +
                     r"(?![a-z0-9_])", _normal(text)) is not None


def _date_forms(iso: str) -> list[str]:
    year, month, day = map(int, iso.split("-"))
    dt.date(year, month, day)  # Reject an invalid expected date.
    full, short = calendar.month_name[month], calendar.month_abbr[month]
    forms = [f"{year}-{month:02d}-{day:02d}", f"{year}-{month}-{day}",
             f"{year}/{month:02d}/{day:02d}", f"{year}/{month}/{day}",
             f"{year}年{month}月{day}日", f"{year}年{month:02d}月{day:02d}日"]
    for name in (full, short):
        forms += [f"{name} {day}, {year}", f"{name} {day} {year}",
                  f"{day} {name} {year}"]
    return forms


def _has_date(text: str, iso: str) -> bool:
    # A year is required: short month/day alone can silently match the wrong year.
    text = _normal(text)
    return any(re.search(r"(?<![a-z0-9])" + re.escape(_normal(form)) +
                         r"(?![a-z0-9])", text) for form in _date_forms(iso))


def _topic(text: str, item: dict) -> bool:
    title = item["title"]
    topic = re.split(r"[:：]", title, maxsplit=1)[-1].strip()
    return _normal(topic) in _normal(text)


def _read(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8-sig"), None
    except FileNotFoundError:
        return None, "missing_file"
    except (OSError, UnicodeError) as exc:
        return None, type(exc).__name__


def _section(text: str, kind: str) -> str | None:
    names = {"decision": r"decisions?|决定(?:事项)?",
             "action": r"action(?: items?)?s?|待办(?:事项)?|todo"}
    lines = text.splitlines()
    # Recognize actual Markdown headings or stand-alone labels, not incidental words.
    label = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:" + names[kind] +
                       r")(?:\*\*)?\s*[:：]?\s*$", re.I)
    for i, line in enumerate(lines):
        if not label.fullmatch(line):
            continue
        end = i + 1
        while end < len(lines) and not re.match(r"^\s*#{1,6}\s+", lines[end]):
            end += 1
        return "\n".join(lines[i + 1:end])
    return None


def _cells(line: str) -> list[str] | None:
    if "|" not in line:
        return None
    # Escaped table pipes are uncommon in this corpus; report rather than mis-split.
    if r"\|" in line:
        return None
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in cells)


def _action_rows(section: str) -> tuple[list[str], str | None]:
    """One physical Markdown table row or list item per action; no prose guessing."""
    rows = []
    lines = section.splitlines()
    for i, line in enumerate(lines):
        cells = _cells(line)
        if cells is not None:
            if _separator(cells):
                continue
            following = _cells(lines[i + 1]) if i + 1 < len(lines) else None
            if following and _separator(following):
                continue  # Table header.
            rows.append(line)
        elif re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line):
            rows.append(line)
        elif line.strip() and not line.lstrip().startswith(">"):
            return [], "unsupported_action_layout"
    return rows, None


def _index_rows(text: str) -> tuple[list[dict], list[dict]]:
    """Read labelled Markdown tables; dates in prose summaries cannot become rows."""
    rows, uncertain = [], []
    lines = text.splitlines()
    i = 0
    date_labels = {"date", "meeting date", "日期", "会议日期"}
    topic_labels = {"topic", "主题", "议题"}
    count_labels = {"action items", "action count", "number of action items",
                    "actions", "待办数量", "待办数", "待办事项数", "待办事项数量"}
    while i < len(lines):
        head = _cells(lines[i])
        sep = _cells(lines[i + 1]) if i + 1 < len(lines) else None
        if not head or not sep or not _separator(sep):
            i += 1
            continue
        names = [_normal(c) for c in head]
        columns = [[j for j, name in enumerate(names) if name in labels]
                   for labels in (date_labels, topic_labels, count_labels)]
        start = i + 2
        end = start
        while end < len(lines) and "|" in lines[end] and lines[end].strip():
            end += 1
        if not columns[0] and not any(re.search(r"\d{4}[-/年]", line) for line in lines[start:end]):
            # Auxiliary tables (e.g. owner totals) are not meeting-index rows.
            i = max(end, i + 2)
            continue
        if any(len(found) != 1 for found in columns) or len(head) != len(sep):
            uncertain.append({"scope": "index", "line": i + 1,
                              "reason": "unrecognized_or_ambiguous_table_columns"})
            i = max(end, i + 2)
            continue
        date_col, topic_col, count_col = [found[0] for found in columns]
        for j in range(start, end):
            cells = _cells(lines[j])
            if cells is None or len(cells) != len(head):
                uncertain.append({"scope": "index", "line": j + 1,
                                  "reason": "malformed_table_row"})
                continue
            if _normal(cells[date_col]) in {"total", "totals", "合计", "总计"}:
                continue  # Explicit aggregate footer; not a meeting.
            value = _normal(cells[count_col])
            count = int(value) if re.fullmatch(r"\d+", value) else None
            row = {"line": j + 1, "date": cells[date_col],
                   "topic": cells[topic_col], "count": count,
                   "count_text": cells[count_col]}
            rows.append(row)
            if count is None:
                uncertain.append({"scope": "index", "line": j + 1,
                                  "reason": "non_integer_action_count",
                                  "observed": cells[count_col]})
        i = max(end, i + 2)
    if not rows and not uncertain:
        uncertain.append({"scope": "index", "reason": "no_recognized_markdown_table"})
    return rows, uncertain


def score_minutes(out_dir: Path, expected: dict) -> dict:
    """Score all supplied expected meetings with zero item slack.

    The registered corpus contains 60 meetings. Small expected sets are accepted
    for mutation tests; n must still agree with items and names/dates be unique.
    checkresults aliases checks for consumers; uncertainties fail completion.
    """
    items = expected["items"]
    n = len(items)
    if not n or expected.get("n", n) != n:
        raise ValueError("expected n must equal a nonempty items list")
    if len({x["stem"] for x in items}) != n or len({x["date"] for x in items}) != n:
        raise ValueError("expected meeting filenames and dates must be unique")
    directory = Path(out_dir) / "minutes"
    failures, uncertainties = [], []
    present, facts_good, sections_good, rows_good, counts_good = 0, 0, 0, 0, 0

    def fail(item: dict, code: str, **detail) -> None:
        failures.append({"stem": item["stem"], "reason": code, **detail})

    for item in items:
        text, error = _read(directory / (item["stem"] + ".md"))
        if text is None or not text.strip():
            fail(item, "missing_file" if error == "missing_file" else "empty_or_unreadable_file")
            if error not in (None, "missing_file"):
                uncertainties.append({"stem": item["stem"], "scope": "minutes", "reason": error})
            continue
        present += 1
        start = len(failures)
        if not _topic(text, item):
            fail(item, "missing_topic", expected=item["title"])
        if not _has_date(text, item["date"]):
            fail(item, "missing_meeting_date", expected=item["date"])
        for attendee in item["attendees"]:
            if not _token(text, attendee):
                fail(item, "missing_attendee", expected=attendee)
        decision, action = _section(text, "decision"), _section(text, "action")
        section_ok = decision is not None and action is not None
        sections_good += section_ok
        if decision is None:
            fail(item, "missing_decision_section")
        if action is None:
            fail(item, "missing_action_section")
        if not _token(decision or "", item["decision_token"]):
            fail(item, "missing_decision_token", expected=item["decision_token"])
        if action is not None:
            action_rows, parse_error = _action_rows(action)
            if parse_error:
                uncertainties.append({"stem": item["stem"], "scope": "actions", "reason": parse_error})
            else:
                if len(action_rows) != len(item["actions"]):
                    fail(item, "wrong_minutes_action_count", expected=len(item["actions"]), observed=len(action_rows))
                for act in item["actions"]:
                    if not any(_token(row, act["owner"]) and _has_date(row, act["due"]) for row in action_rows):
                        fail(item, "missing_owner_due_pair", owner=act["owner"], due=act["due"])
                    elif not any(_token(row, act["owner"]) and _has_date(row, act["due"]) and
                                 _normal(act["what"]) in _normal(row) for row in action_rows):
                        fail(item, "missing_source_action_description", owner=act["owner"], expected=act["what"])
        facts_good += len(failures) == start and not any(u.get("stem") == item["stem"] for u in uncertainties)

    index, error = _read(directory / "index.md")
    if index is None:
        rows = []
        if error == "missing_file":
            failures.append({"stem": "index.md", "reason": "missing_index_file"})
        else:
            uncertainties.append({"scope": "index", "reason": error or "unreadable_file"})
    else:
        rows, issues = _index_rows(index)
        uncertainties.extend(issues)
    matched_lines = set()
    for item in items:
        matches = [row for row in rows if _has_date(row["date"], item["date"])]
        for row in matches:
            matched_lines.add(row["line"])
        if len(matches) != 1:
            fail(item, "missing_index_row" if not matches else "duplicate_index_rows",
                 observed=len(matches), lines=[row["line"] for row in matches])
            continue
        row = matches[0]
        if not _topic(row["topic"], item):
            fail(item, "wrong_or_missing_index_topic", line=row["line"], observed=row["topic"])
        else:
            rows_good += 1
        if row["count"] is None:
            continue  # The parser uncertainty already records this; not a wrong number.
        if row["count"] != len(item["actions"]):
            fail(item, "wrong_index_action_count", line=row["line"],
                 expected=len(item["actions"]), observed=row["count"])
        else:
            counts_good += 1
    unassigned = [row for row in rows if row["line"] not in matched_lines]
    for row in unassigned:
        failures.append({"stem": "index.md", "reason": "unexpected_or_unidentified_index_row", **row})

    checks = [
        {"name": f"minutes: all {n} expected nonempty files", "ok": present == n, "detail": f"{present}/{n}"},
        {"name": "every minutes file: topic, date, attendees, decision, action descriptions, owner/due pairs and action count", "ok": facts_good == n, "detail": f"{facts_good}/{n}"},
        {"name": "every minutes file: decision and action sections", "ok": sections_good == n, "detail": f"{sections_good}/{n}"},
        {"name": "index.md: exactly one row and source topic per meeting", "ok": rows_good == n and len(rows) == n and not unassigned and not any(u["scope"] == "index" and u["reason"] != "non_integer_action_count" for u in uncertainties), "detail": f"{rows_good}/{n}; parsed_rows={len(rows)}"},
        {"name": "index.md: every action count exact and parseable", "ok": counts_good == n and not any(u["scope"] == "index" for u in uncertainties), "detail": f"{counts_good}/{n}"},
    ]
    passed = sum(check["ok"] for check in checks)
    return {"version": VERSION, "completed": passed == len(checks) and not uncertainties,
            "checks": checks, "checkresults": checks, "passed": passed, "total": len(checks),
            "score": passed / len(checks), "items_done": present, "items_total": n,
            "per_item_failures": failures, "parseuncertainties": uncertainties,
            "parse_uncertainties": uncertainties}


def legacy_score_minutes(out_dir: Path, expected: dict, source_path: Path) -> dict:
    """Replay original rules verbatim without importing its dependency tree.

    AST selection preserves the original four functions (including N-1 and
    first-date-line/last-number parsing). The three tiny shared I/O/result
    helpers below have the same semantics as the historical p2_scorers helpers.
    This executes trusted local benchmark source only, never submitted output.
    """
    wanted = {"_date_forms", "_has_date", "_within", "score_minutes"}
    nodes = [node for node in ast.parse(source_path.read_text()).body
             if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if {node.name for node in nodes} != wanted:
        raise ValueError("legacy source does not contain the registered scorer functions")

    def read(path):
        text, _error = _read(path)
        return text

    def check(name, ok, detail=""):
        return {"name": name, "ok": bool(ok), "detail": str(detail)[:200]}

    def result(checks, **extra):
        passed = sum(c["ok"] for c in checks)
        return {"checks": checks, "passed": passed, "total": len(checks),
                "score": round(passed / len(checks), 4) if checks else 0.0,
                "completed": bool(checks) and passed == len(checks), **extra}

    context = {"Path": Path, "re": re, "_read": read, "_check": check,
               "_result": result, "MONTHS_EN": list(calendar.month_name)[1:]}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), context)
    return context["score_minutes"](out_dir, expected)


def regrade_records(corpus_root: Path) -> dict:
    """Regrade the eight original saved final artifacts; never edit old reports."""
    corpus_root = corpus_root.resolve()
    source = corpus_root / "harness/lt_scorers.py"
    inputs = {source, corpus_root / "harness/lt_seeds.py", Path(__file__).resolve(),
              Path(__file__).resolve().parents[1] / "tests/test_minutes_strict.py"}
    units, examples = [], []
    for run in ("live-1", "r3-live-1"):
        records_path = corpus_root / "runs" / run / "units.jsonl"
        inputs.add(records_path)
        # Only scoring metadata is used. Goal verdict fields are never read by a scorer.
        records = [record for record in map(json.loads, records_path.read_text().splitlines())
                   if record["task"] == "lt_minutes"]
        for record in sorted(records, key=lambda record: record["uid"]):
            folder = record["uid"].replace("/", "_") + f"-a{record['attempt']}"
            output = corpus_root / "runs" / run / "evidence" / folder / "outputs"
            expected_path = corpus_root / "expected" / f"minutes__{record['lang']}__r2.json"
            expected = json.loads(expected_path.read_text())
            if record["rung"] != 2 or expected["n"] != 60:
                raise ValueError("unexpected saved minutes corpus size or rung")
            inputs.add(expected_path)
            raw_root = corpus_root / "data" / "meetings" / ("notes_h2" if record["lang"] == "en" else "notes_zh_h2")
            raw_files = [raw_root / (item["stem"] + ".md") for item in expected["items"]]
            inputs.update(raw_files)
            expected_matches_raw = all(
                item["title"] in path.read_text() and item["date"] in path.read_text()
                and item["decision_token"] in path.read_text()
                and all(a in path.read_text() for a in item["attendees"])
                and all(a["owner"] in path.read_text() and a["due"] in path.read_text()
                        and a["what"] in path.read_text() for a in item["actions"])
                for item, path in zip(expected["items"], raw_files))
            inputs.update((output / "minutes").glob("*.md"))
            legacy = legacy_score_minutes(output, expected, source)
            strict = score_minutes(output, expected)
            historical = record["final_score"]
            same_legacy = all(legacy[key] == historical[key] for key in ("completed", "passed", "total", "score"))
            units.append({"run": run, "uid": record["uid"], "output_directory": str(output),
                          "expected_path": str(expected_path), "raw_source_directory": str(raw_root),
                          "expected_matches_raw_source_facts": expected_matches_raw,
                          "registered_rung": record["rung"], "historical_recorded_score": historical,
                          "historical_failing_checks": record["final_failing_checks"],
                          "legacy_replay_matches_recorded_score": same_legacy,
                          "legacy_replayed": legacy, "strict_regrade": strict})
            if not legacy["completed"]:
                lines = (output / "minutes/index.md").read_text().splitlines()
                # Capture the exact first-line error mechanism without changing old rules.
                old_names = {"_date_forms", "_has_date"}
                old_nodes = [node for node in ast.parse(source.read_text()).body
                             if isinstance(node, ast.FunctionDef) and node.name in old_names]
                ctx = {"re": re, "MONTHS_EN": list(calendar.month_name)[1:]}
                exec(compile(ast.Module(body=old_nodes, type_ignores=[]), str(source), "exec"), ctx)
                for item in expected["items"]:
                    first = next(((number, line) for number, line in enumerate(lines, 1)
                                  if ctx["_has_date"](line, item["date"])), None)
                    if first is None:
                        continue
                    rest = first[1]
                    for form in ctx["_date_forms"](item["date"]):
                        rest = rest.replace(form, " ")
                    nums = [c.strip() for c in rest.split("|") if re.fullmatch(r"\d+", c.strip())]
                    if not nums:
                        nums = re.findall(r"(?<![\w-])(\d+)(?![\w-])", rest)
                    if nums and int(nums[-1]) == len(item["actions"]):
                        continue
                    actual = [(number, line) for number, line in enumerate(lines, 1)
                              if "|" in line and _has_date((_cells(line) or [""])[0], item["date"])]
                    examples.append({"run": run, "uid": record["uid"], "stem": item["stem"],
                                     "index_path": str(output / "minutes/index.md"),
                                     "legacy_selected_line_number": first[0], "legacy_selected_line": first[1],
                                     "legacy_extracted_numbers": nums, "expected_action_count": len(item["actions"]),
                                     "actual_meeting_table_rows": [{"line": number, "text": line} for number, line in actual]})
    hashes = [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
              for path in sorted(inputs)]
    return {"schema_version": 1, "scorer_version": VERSION, "mode": "offline_original_final_artifacts",
            "strict_scope": "deterministic structural and registered fact checks; not exhaustive semantic quality",
            "goal_verdict_used_for_scoring": False, "provider_calls": 0,
            "summary": {"units": len(units), "historical_completed": sum(u["historical_recorded_score"]["completed"] for u in units),
                        "legacy_replayed_completed": sum(u["legacy_replayed"]["completed"] for u in units),
                        "strict_completed": sum(u["strict_regrade"]["completed"] for u in units),
                        "all_legacy_replays_match_recorded": all(u["legacy_replay_matches_recorded_score"] for u in units),
                        "strict_parse_uncertainties": sum(len(u["strict_regrade"]["parseuncertainties"]) for u in units)},
            "units": units, "legacy_parser_examples": examples, "input_sha256": hashes}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regrade", required=True, type=Path, help="Original goal-longtask corpus directory")
    parser.add_argument("--output", required=True, type=Path, help="New report path; originals are never overwritten")
    args = parser.parse_args()
    report = regrade_records(args.regrade)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
