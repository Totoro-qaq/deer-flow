"""Classify how recorded bench runs ended and whether they delivered the files they created.

Each batch directory holds one folder per run with the run's event log in
``step-*/events.json`` (the Gateway's run events, as the bench recorded them).

    python scan_bench_runs.py "Compaction threshold A/B=<dir>" "Lead effort A/B=<dir>" ... --out chart-data.json
"""

import argparse
import json
from pathlib import Path


def classify(run: dict) -> str:
    if run["produced"] == 0:
        return "no_outputs"
    if run["presented"] > 0:
        return "delivered"
    if run["error_type"] == "GraphRecursionError":
        return "step_limit"
    if run["loop_warnings"] > 0:
        return "after_loop_warning"
    return "other"


def scan_run(run_dir: Path) -> dict:
    events = []
    for path in sorted(run_dir.glob("step-*/events.json")):
        events.extend(json.loads(path.read_text(encoding="utf-8")))
    errors = [e for e in events if e["event_type"] == "run.error"]
    loop = [e.get("content") or {} for e in events if e["event_type"] == "middleware:loop_detection"]
    deliveries = [e.get("content") or {} for e in events if e["event_type"] == "run.delivery"]
    receipt = deliveries[-1] if deliveries else {}
    run = {
        "run": run_dir.name,
        "error_type": (errors[-1].get("metadata") or {}).get("error_type", "") if errors else "",
        "loop_warnings": sum(item.get("action") == "warn" for item in loop),
        "loop_hard_stops": sum(item.get("action") not in (None, "warn") for item in loop),
        # Outputs the run created, and how many of them it presented with present_files.
        "produced": len(receipt.get("produced_paths") or []),
        "presented": len(receipt.get("matched_paths") or []),
    }
    run["outcome"] = classify(run)
    return run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batches", nargs="+", help="LABEL=DIR, one per bench batch")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    batches = []
    for spec in args.batches:
        label, _, directory = spec.partition("=")
        runs = [scan_run(path) for path in sorted(Path(directory).iterdir()) if path.is_dir()]
        batches.append({"label": label, "runs": runs})
    outcomes: dict[str, int] = {}
    for batch in batches:
        for run in batch["runs"]:
            outcomes[run["outcome"]] = outcomes.get(run["outcome"], 0) + 1
    warned = [run for batch in batches for run in batch["runs"] if run["loop_warnings"]]
    data = {
        "runs": sum(len(batch["runs"]) for batch in batches),
        "outcomes": outcomes,
        "runs_with_loop_warning": len(warned),
        "runs_with_loop_warning_delivered": sum(run["outcome"] == "delivered" for run in warned),
        "batches": batches,
    }
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in data.items() if k != "batches"}, indent=2))


if __name__ == "__main__":
    main()
