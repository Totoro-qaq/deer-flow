"""How many tool-calling turns fit in a lead-agent run's recursion_limit. No provider or network call.

Drives the production lead agent (``_make_lead_agent``: default middleware chain, real
sandbox tools on LocalSandboxProvider, default summarization and memory settings) with a
scripted model that takes N turns, each with one distinct write_file / read_file call,
and then answers.

For each N it checks that the run finishes at exactly 22 + 13 * N and fails one step
lower, then checks the 100 / 250 / 1000 budgets directly, and that parallel calls in
one turn share that turn's steps. These counts belong to this setup: adding or removing
graph middleware changes them.

Usage: python measure_step_budget.py /path/to/deer-flow/backend [--out chart-data.json]
(run with that backend's Python environment)
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("backend", type=Path)
parser.add_argument("--out", type=Path, default=Path("chart-data.json"))
args = parser.parse_args()
backend = args.backend.resolve()
for path in (backend, backend / "packages/harness", backend / "packages/extension-api"):
    sys.path.insert(0, str(path))
os.environ["DEER_FLOW_HOME"] = tempfile.mkdtemp(prefix="step-budget-")
os.environ.setdefault("LANGSMITH_TRACING", "false")

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langgraph.errors import GraphRecursionError  # noqa: E402

import deerflow.agents.lead_agent.agent as lead  # noqa: E402
from deerflow.config.app_config import AppConfig  # noqa: E402


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def tool_call(i: int) -> dict:
    # Distinct calls (write, read back, write an index) so loop detection sees progress.
    if i % 3 == 0:
        name, call_args = "write_file", {"description": "draft", "path": f"/mnt/user-data/outputs/part-{i}.md", "content": f"Section {i}\n"}
    elif i % 3 == 1:
        name, call_args = "read_file", {"description": "check", "path": f"/mnt/user-data/outputs/part-{i - 1}.md"}
    else:
        name, call_args = "write_file", {"description": "index", "path": f"/mnt/user-data/outputs/index-{i}.md", "content": f"Index {i}\n"}
    return {"name": name, "args": call_args, "id": f"call-{i}", "type": "tool_call"}


def run(n_calls: int, limit: int, per_turn: int = 1) -> tuple[bool, int, str | None]:
    """Return (finished, tool results seen, final answer) for one scripted run of n_calls turns."""
    turns = [AIMessage(content="", tool_calls=[tool_call(i * per_turn + k) for k in range(per_turn)]) for i in range(n_calls)]
    model = ScriptedModel(responses=turns + [AIMessage(content="done")])
    lead.create_chat_model = lambda **kwargs: model
    lead._resolve_model_name = lambda *a, **k: "scripted"
    lead.build_tracing_callbacks = lambda: []
    config = AppConfig.model_validate({
        "models": [{"name": "scripted", "use": "langchain_openai:ChatOpenAI", "model": "scripted"}],
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
    })
    thread_id = f"t-{n_calls}-{limit}"
    context = {"thread_id": thread_id, "user_id": "u1", "run_id": f"r-{n_calls}-{limit}",
               "thinking_enabled": False, "is_plan_mode": False, "subagent_enabled": False}
    graph = lead._make_lead_agent({"configurable": {"thread_id": thread_id}, "context": context}, app_config=config)
    tools, answer = 0, None
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            for chunk in graph.stream({"messages": [HumanMessage(content="Make the report")]},
                                      config={"recursion_limit": limit, "configurable": {"thread_id": thread_id}},
                                      context=context, stream_mode="updates"):
                for update in chunk.values():
                    for message in (update or {}).get("messages", []) if isinstance(update, dict) else []:
                        if message.type == "tool":
                            tools += 1
                        elif message.type == "ai" and isinstance(message.content, str) and message.content:
                            answer = message.content
        return True, tools, answer
    except GraphRecursionError:
        return False, tools, answer


points = []
for n in (0, 1, 2, 4, 6, 7, 10, 17, 18, 20, 30, 40, 50, 60, 75, 76):
    need = 22 + 13 * n
    assert run(n, need)[0] and not run(n, need - 1)[0], n
    points.append({"tool_calling_turns": n, "min_recursion_limit": need})
    print(f"{n:2} tool-calling turns: finishes at {need}, fails at {need - 1}")
checks = []
for budget, fits in ((100, 6), (250, 17), (1000, 75)):
    good, bad = run(fits, budget), run(fits + 1, budget)
    assert good == (True, fits, "done") and not bad[0], (budget, good, bad)
    checks.append({"budget": budget, "finishes_with": fits, "fails_with": fits + 1, "tool_results_before_failure": bad[1]})
    print(f"budget {budget:4}: {fits} turns finish; {fits + 1} fail with GraphRecursionError after {bad[1]} tool results")
# Parallel calls in one turn share the turn's steps: 6 turns of 3 calls still fit in 100.
parallel = run(6, 100, per_turn=3), run(6, 99, per_turn=3)
assert parallel[0] == (True, 18, "done") and not parallel[1][0], parallel
print("budget  100: 6 turns of 3 parallel calls (18 tool results) finish; fail at 99")
args.out.write_text(json.dumps({
    "base": "00678f06",
    "setup": "default lead-agent middleware chain, LocalSandboxProvider, default summarization and memory, "
             "thinking/plan mode/subagents off, scripted fake model",
    "points": points, "budget_checks": checks,
    "parallel_check": {"turns": 6, "calls_per_turn": 3, "tool_results": 18, "finishes_at": 100, "fails_at": 99}}, indent=2) + "\n")
