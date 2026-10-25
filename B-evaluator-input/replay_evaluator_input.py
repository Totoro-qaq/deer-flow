"""Rebuild the Goal evaluator input with DeerFlow's unchanged native code. No provider call.

The native evaluator (runtime/goal.py, evaluate_goal_completion) is called with a
stand-in model whose ainvoke() records the messages it receives and stops. That
is exactly the input the evaluator model would get. Nothing else is patched.

Needs a bytedance/deer-flow checkout at 505c33c793389451f2ce7183bdbd4f3465f22f66
and a Python environment with that checkout's backend dependencies installed.

Usage: python replay_evaluator_input.py --deerflow-src /path/to/deer-flow [--out DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
NATIVE_GOAL_SHA256 = "342d27728b626859b85380a2b8130a6b0a18314aed4ed3ba2b19ab4a30372ef9"
CASES = {"observed-A-deepseek": "observed-A-deepseek.evaluator-input.json",
         "observed-B-glm": "observed-B-glm.evaluator-input.json"}


class _Captured(BaseException):
    pass


class _CaptureOnly:
    """Stand-in model: records the evaluator input and stops before any provider call."""

    def __init__(self) -> None:
        self.messages = None

    async def ainvoke(self, messages, config=None):
        self.messages = [{"role": "system" if m.type == "system" else "user", "content": m.content} for m in messages]
        raise _Captured()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deerflow-src", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "rebuilt")
    args = parser.parse_args()
    src = args.deerflow_src.resolve()
    goal_py = src / "backend/packages/harness/deerflow/runtime/goal.py"
    if hashlib.sha256(goal_py.read_bytes()).hexdigest() != NATIVE_GOAL_SHA256:
        sys.exit("runtime/goal.py does not match commit 505c33c7; check out that commit first")
    for path in (src / "backend", src / "backend/packages/harness", src / "backend/packages/extension-api"):
        sys.path.insert(0, str(path))
    os.environ.setdefault("LANGSMITH_TRACING", "false")

    from langchain_core.messages import convert_to_messages
    from deerflow.agents.interaction_policy import resolve_run_interaction_policy
    from deerflow.config.pii_redaction_config import PiiRedactionConfig
    from deerflow.runtime.goal import (MAX_GOAL_CONVERSATION_CHARS, _evidence_window, _is_visible_message,
                                       _message_type, evaluate_goal_completion, format_visible_conversation)
    from deerflow.utils.messages import message_to_text

    pii = PiiRedactionConfig()  # the trial configs set nothing, so redaction is off (the default)
    policy = resolve_run_interaction_policy({})
    assert not pii.enabled and policy.allows_clarification

    async def evaluator_input(goal: dict, messages: list[dict]) -> list[dict]:
        capture = _CaptureOnly()
        try:
            await evaluate_goal_completion(goal, convert_to_messages(messages), model=capture,
                                           app_config=SimpleNamespace(pii_redaction=pii), interaction_policy=policy)
        except _Captured:
            pass
        assert capture.messages is not None
        return capture.messages

    def counts(messages: list[dict]) -> dict:
        visible = [m for m in _evidence_window(messages) if _is_visible_message(m)]
        assert [_message_type(m) for m in visible] == ["human", "ai"]
        user, answer = [message_to_text(m).strip() for m in visible]
        formatted = format_visible_conversation(messages)
        return {"source_user_chars": len(user), "answer_chars": len(answer),
                "uncapped_evidence_chars": len(f"User: {user}\n\nAssistant: {answer}"),
                "formatted_evidence_chars": len(formatted), "cap_chars": MAX_GOAL_CONVERSATION_CHARS,
                "unused_cap_chars": MAX_GOAL_CONVERSATION_CHARS - len(formatted),
                "document_5_source_offset": user.index("Document 5:"),
                "source_document_ids": re.findall(r"(?m)^Document (\d+):", user),
                "formatted_document_ids": re.findall(r"(?m)^Document (\d+):", formatted),
                "document_5_kept": "Document 5:" in formatted, "formatted_evidence_sha256": _digest(formatted)}

    args.out.mkdir(parents=True, exist_ok=True)
    report = {"source_commit": "505c33c793389451f2ce7183bdbd4f3465f22f66", "provider_calls": 0, "cases": []}
    inputs = {}
    for case, published in CASES.items():
        data = json.loads((HERE / "inputs" / f"{case}.formatter-input.json").read_text(encoding="utf-8"))
        inputs[case] = data
        rebuilt = await evaluator_input(data["goal"], data["messages"])
        same = rebuilt == json.loads((HERE / published).read_text(encoding="utf-8"))
        (args.out / published).write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["cases"].append({"case": case, "matches_published_input": same, **counts(data["messages"])})

    # Boundary control: the DeepSeek answer padded with internal spaces only. Words,
    # facts, citations and the user message stay identical; no model is involved.
    base = inputs["observed-A-deepseek"]
    answer = next(m for m in base["messages"] if _message_type(m) == "ai")["content"]
    at = re.search(r"(?<=\w) (?=\w)", answer).start()
    room = MAX_GOAL_CONVERSATION_CHARS - counts(base["messages"])["uncapped_evidence_chars"]
    for extra in (room, room + 1):
        variant = copy.deepcopy(base["messages"])
        padded = answer[:at] + " " * extra + answer[at:]
        assert padded.split() == answer.split()
        next(m for m in variant if _message_type(m) == "ai")["content"] = padded
        rebuilt = await evaluator_input(base["goal"], variant)
        name = f"boundary-{MAX_GOAL_CONVERSATION_CHARS + (extra - room)}.evaluator-input.json"
        (args.out / name).write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["cases"].append({"case": name.removesuffix(".evaluator-input.json"), "extra_internal_spaces": extra,
                                "hypothetical_formatter_input": True, **counts(variant)})
    (args.out / "replay-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in report["cases"]:
        print(f"{row['case']:22} evidence {row['uncapped_evidence_chars']:>6} -> {row['formatted_evidence_chars']:>6} "
              f"unused {row['unused_cap_chars']:>5}  Document 5 kept: {row['document_5_kept']}"
              + (f"  matches published: {row['matches_published_input']}" if "matches_published_input" in row else ""))


if __name__ == "__main__":
    asyncio.run(main())
