"""Deterministic offline controls: every mutation changes exactly one obligation."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("minutes_strict", PACKAGE / "scoring/minutes_strict.py")
MINUTES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MINUTES)
CORPUS = PACKAGE


def make_fixture(out: Path, expected: dict, *, equivalent_dates: bool = False) -> None:
    directory = out / "minutes"
    directory.mkdir()

    def date(iso: str) -> str:
        if equivalent_dates:
            year, month, day = map(int, iso.split("-"))
            return f"{year}/{month}/{day}"
        return iso

    rows = ["| Date | Topic | Action items |", "| --- | --- | --- |"]
    for item in expected["items"]:
        text = (f"# {item['title']}\nDate: {date(item['date'])}\n"
                f"Attendees: {', '.join(item['attendees'])}\n\n## Decisions\n"
                f"Option {item['decision_token']}\n\n## Action items\n")
        text += "\n".join(f"- {a['owner']}: {a['what']}; due {date(a['due'])}" for a in item["actions"])
        if expected["lang"] == "zh":
            text = text.replace("## Decisions", "## 决定事项").replace("## Action items", "## 待办事项")
        (directory / (item["stem"] + ".md")).write_text(text + "\n", encoding="utf-8")
        rows.append(f"| {date(item['date'])} | {item['title']} | {len(item['actions'])} |")
    (directory / "index.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


class MinutesStrictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.expected = json.loads((CORPUS / "expected/minutes__en__r2.json").read_text())
        self.assertEqual(60, len(self.expected["items"]))
        make_fixture(self.out, self.expected)
        self.item = self.expected["items"][0]
        self.file = self.out / "minutes" / (self.item["stem"] + ".md")
        self.index = self.out / "minutes/index.md"

    def score(self):
        return MINUTES.score_minutes(self.out, self.expected)

    def legacy(self):
        return MINUTES.legacy_score_minutes(self.out, self.expected, CORPUS / "scoring/legacy_minutes_rules.py")

    def reasons(self, result):
        return [failure["reason"] for failure in result["per_item_failures"]]

    def test_complete_60_file_fixture(self):
        result = self.score()
        self.assertTrue(result["completed"])
        self.assertEqual((5, 5, 60), (result["passed"], result["total"], result["items_done"]))
        self.assertEqual([], result["parseuncertainties"])

    def test_one_wrong_count_fails_zero_slack_and_records_numeric_value(self):
        self.index.write_text(self.index.read_text().replace("| 4 |", "| 9 |", 1))
        result = self.score()
        self.assertFalse(result["completed"])
        wrong = [x for x in result["per_item_failures"] if x["reason"] == "wrong_index_action_count"]
        self.assertEqual(1, len(wrong))
        self.assertEqual((4, 9), (wrong[0]["expected"], wrong[0]["observed"]))
        self.assertEqual([], result["parseuncertainties"])
        self.assertTrue(self.legacy()["completed"])  # Historical N-1 tolerates this defect.

    def test_one_missing_attendee_is_not_tolerated(self):
        # Fifth attendee has no assigned action, so only the attendee obligation changes.
        attendee = self.item["attendees"][-1]
        self.file.write_text(self.file.read_text().replace(attendee, ""))
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertEqual(["missing_attendee"], self.reasons(result))
        self.assertTrue(self.legacy()["completed"])

    def test_duplicate_index_row_does_not_pass_first_match(self):
        self.index.write_text(self.index.read_text() + self.index.read_text().splitlines()[2] + "\n")
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertIn("duplicate_index_rows", self.reasons(result))
        self.assertTrue(self.legacy()["completed"])

    def test_one_missing_file_fails(self):
        self.file.unlink()
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertEqual(59, result["items_done"])
        self.assertIn("missing_file", self.reasons(result))

    def test_missing_index_is_confirmed_absence_not_parser_uncertainty(self):
        self.index.unlink()
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertIn("missing_index_file", self.reasons(result))
        self.assertEqual([], result["parseuncertainties"])

    def test_missing_section_is_not_incidental_keyword_match(self):
        text = self.file.read_text().replace("## Decisions", "## Discussion")
        self.file.write_text(text + "This prose mentions decisions.\n")
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertIn("missing_decision_section", self.reasons(result))

    def test_swapped_owner_due_pairs_fail_even_with_all_tokens_present(self):
        actions = self.item["actions"]
        first, second = actions[0]["due"], actions[1]["due"]
        self.file.write_text(self.file.read_text().replace(first, "SWAP").replace(second, first).replace("SWAP", second))
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertEqual(2, self.reasons(result).count("missing_owner_due_pair"))

    def test_empty_or_unrelated_action_description_fails(self):
        self.file.write_text(self.file.read_text().replace(self.item["actions"][0]["what"], "do something else"))
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertIn("missing_source_action_description", self.reasons(result))

    def test_non_numeric_count_is_uncertainty_not_wrong_number(self):
        self.index.write_text(self.index.read_text().replace("| 4 |", "| four |", 1))
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertNotIn("wrong_index_action_count", self.reasons(result))
        self.assertEqual(["non_integer_action_count"], [u["reason"] for u in result["parseuncertainties"]])

    def test_ambiguous_count_column_is_not_guessed_from_last_number(self):
        self.index.write_text(self.index.read_text().replace("Action items", "Total", 1))
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertIn("unrecognized_or_ambiguous_table_columns", [u["reason"] for u in result["parseuncertainties"]])

    def test_malformed_index_row_is_parser_uncertainty(self):
        self.index.write_text(self.index.read_text().replace("| 4 |", "| 4 | unexpected cell |", 1))
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertNotIn("wrong_index_action_count", self.reasons(result))
        self.assertIn("malformed_table_row", [u["reason"] for u in result["parseuncertainties"]])

    def test_summary_date_cannot_replace_a_missing_index_row(self):
        lines = self.index.read_text().splitlines()
        del lines[2]
        self.index.write_text("Period: 2026-07-01 to 2026-09-27; 60 meetings\n" + "\n".join(lines))
        result = self.score()
        self.assertFalse(result["completed"])
        self.assertIn("missing_index_row", self.reasons(result))

    def test_valid_prose_date_range_reproduces_legacy_false_negative(self):
        self.index.write_text("Period: 2026-07-01 to 2026-09-27; 60 meetings\n" + self.index.read_text())
        self.assertFalse(self.legacy()["completed"])
        self.assertTrue(self.score()["completed"])

    def test_equivalent_full_year_date_formats_and_case_pass(self):
        for path in (self.out / "minutes").iterdir():
            text = path.read_text()
            import re
            text = re.sub(r"(2026)-(\d{2})-(\d{2})", lambda m: f"{m[1]}/{int(m[2])}/{int(m[3])}", text)
            path.write_text(text.upper())
        self.assertTrue(self.score()["completed"])
        self.assertTrue(MINUTES._has_date("jUlY 1, 2026", "2026-07-01"))
        self.assertTrue(MINUTES._has_date("2026年7月1日", "2026-07-01"))
        self.assertFalse(MINUTES._has_date("July 1, 2025", "2026-07-01"))
        self.assertFalse(MINUTES._has_date("July 1, 20260", "2026-07-01"))

    def test_explicit_total_footer_and_auxiliary_table_are_not_meetings(self):
        self.index.write_text(self.index.read_text() + "| **Total** | **60 meetings** | **180** |\n\n"
                              "| Owner | Count |\n| --- | --- |\n| Mei | 7 |\n")
        self.assertTrue(self.score()["completed"])

    def test_chinese_source_fixture(self):
        for path in (self.out / "minutes").iterdir():
            path.unlink()
        (self.out / "minutes").rmdir()
        self.expected = json.loads((CORPUS / "expected/minutes__zh__r2.json").read_text())
        make_fixture(self.out, self.expected, equivalent_dates=True)
        self.assertTrue(self.score()["completed"])


if __name__ == "__main__":
    unittest.main()
