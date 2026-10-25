"""Historical minutes scoring rules, copied verbatim (before the parser fix).

These are the four functions the historical benchmark scorer used for the
60-meeting task: N-1 tolerance, first date-bearing line and last-number index
parsing included. They are not importable on their own: the shared helpers
(_read, _check, _result, MONTHS_EN) are supplied by
minutes_strict.legacy_score_minutes(), which selects these functions by AST,
as the original regrade did.

Source file sha256 (unchanged original): f88ce12e4290a4e477de24e04c1289aed4dcf009dd6a0b9a5ba99f83fa98e36c
"""

def _date_forms(iso: str) -> list[str]:
    y, m, d = (int(x) for x in iso.split("-"))
    mon = MONTHS_EN[m - 1]
    return [iso, f"{y}/{m:02d}/{d:02d}", f"{y}/{m}/{d}", f"{m}月{d}日", f"{m}月{d}号", f"{y}年{m}月{d}日", f"{m}/{d}", f"{m:02d}/{d:02d}",
            f"{mon} {d}", f"{mon[:3]} {d}", f"{d} {mon}", f"{d} {mon[:3]}", f"{m:02d}-{d:02d}"]


def _has_date(text: str, iso: str) -> bool:
    low = text.casefold()
    for form in _date_forms(iso):
        f = form.casefold()
        if re.search(rf"(?<![\d]){re.escape(f)}(?![\d])", low):
            return True
    return False


def _within(ok: int, n: int, slack: int) -> bool:
    return ok >= n - slack


def score_minutes(out: Path, exp: dict) -> dict:
    lang, items = exp["lang"], exp["items"]
    n = len(items)
    d = out / "minutes"
    texts = {it["stem"]: _read(d / f"{it['stem']}.md") for it in items}
    missing = [s for s, t in texts.items() if not t]
    checks = [_check(f"minutes: one per meeting ({n})", not missing, missing[:5])]
    facts_ok, sections_ok, bad = 0, 0, []
    for it in items:
        t = texts[it["stem"]] or ""
        ok = (_has_date(t, it["date"]) and all(a in t for a in it["attendees"]) and it["decision_token"] in t
              and all(a["owner"] in t and _has_date(t, a["due"]) for a in it["actions"]))
        facts_ok += ok
        if not ok and t:
            bad.append(it["stem"])
        low = t.casefold()
        sections_ok += bool(("决定" in t and "待办" in t) if lang == "zh" else ("decision" in low and "action" in low))
    checks.append(_check("each minutes file: date, attendees, decision, owners and due dates (N-1)", _within(facts_ok, n, 1), f"{facts_ok}/{n} {bad[:3]}"))
    checks.append(_check("each minutes file: decision and action sections (N-1)", _within(sections_ok, n, 1), f"{sections_ok}/{n}"))
    index = _read(d / "index.md") or ""
    lines = index.splitlines()
    rows, count_ok = 0, 0
    for it in items:
        row = next((ln for ln in lines if _has_date(ln, it["date"])), None)
        if row is not None:
            rows += 1
            rest = row
            for form in _date_forms(it["date"]):
                rest = rest.replace(form, " ")
            cells = [c.strip() for c in rest.split("|")]
            nums = [c for c in cells if re.fullmatch(r"\d+", c)]
            if not nums:
                nums = re.findall(r"(?<![\w-])(\d+)(?![\w-])", rest)
            count_ok += bool(nums) and int(nums[-1]) == len(it["actions"])
    checks.append(_check("index.md: a row per meeting", rows == n, f"{rows}/{n}"))
    checks.append(_check("index.md: action counts (N-1)", _within(count_ok, n, 1), f"{count_ok}/{n}"))
    return _result(checks, items_done=n - len(missing), items_total=n)
