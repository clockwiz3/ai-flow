import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from forgeloop.agent_loop import AgentConfig, AgentLoop, AgentResult
from forgeloop.tools import ExecResult, Workspace, default_toolbox
from llmcore import LLMClient, Meter, Tracer

Turn = dict[str, Any]


def text(t: str) -> Turn:
    return {"content": t}


def tool(name: str, **args: Any) -> Turn:
    return {
        "content": "",
        "tool_calls": [{"id": f"c_{name}", "function": {"name": name, "arguments": json.dumps(args)}}],
    }


class Script:
    """A fake model: answers with the next scripted turn and records what it was sent."""

    def __init__(self, turns: list[Turn], cost: float = 0.01) -> None:
        self.turns: Iterator[Turn] = iter(turns)
        self.requests: list[dict[str, Any]] = []
        self.cost = cost

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.requests.append(payload)
        last = payload["messages"][-1]
        if last["role"] == "user" and "Summarise the work so far" in json.dumps(last):
            msg: Turn = text("Summary: read main.py, the bug is the minus sign.")
        else:
            msg = next(self.turns)
        finish = "tool_calls" if msg.get("tool_calls") else "stop"
        body = {
            "model": "m",
            "choices": [{"message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "cost": self.cost},
        }
        return httpx.Response(200, json=body)


class NullSandbox:
    async def exec(self, argv: list[str], timeout_s: float) -> ExecResult:
        return ExecResult(0, "ok")

    async def close(self) -> None:
        return None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    return root


def run(repo: Path, script: Script, tracer: Tracer | None = None, **cfg: Any) -> AgentResult:
    async def go() -> AgentResult:
        client = LLMClient(api_key="k", transport=httpx.MockTransport(script), meter=Meter(), tracer=tracer)
        loop = AgentLoop(
            client,
            default_toolbox(Workspace(repo), NullSandbox()),
            AgentConfig(model="m", system="be precise", **cfg),
            tracer=tracer,
        )
        try:
            return await loop.run("fix add()", context="PLAN: change app/main.py", name="implementer")
        finally:
            await client.aclose()

    return asyncio.run(go())


def test_solves_a_task_end_to_end(repo: Path) -> None:
    script = Script(
        [
            tool("read_file", path="app/main.py"),
            tool("apply_patch", path="app/main.py", old="a - b", new="a + b"),
            tool("run_tests"),
            text("Fixed: add() now adds."),
        ]
    )
    result = run(repo, script)
    assert result.status == "done" and result.steps == 4
    assert "a + b" in (repo / "app" / "main.py").read_text(encoding="utf-8")
    assert result.cost_usd == pytest.approx(0.04)
    assert result.usage.input_tokens == 4000
    # the tool result of step 1 is what the model saw on step 2
    tool_msgs = [m for m in script.requests[1]["messages"] if m["role"] == "tool"]
    assert "return a - b" in tool_msgs[0]["content"]
    # system prompt and plan are sent as the stable prefix
    assert [p["text"] for p in script.requests[0]["messages"][0]["content"]] == [
        "be precise",
        "PLAN: change app/main.py",
    ]


def test_tool_errors_are_returned_to_the_model_not_raised(repo: Path) -> None:
    script = Script([tool("read_file", path="../../etc/passwd"), text("cannot")])
    result = run(repo, script)
    assert result.status == "done"
    err = next(m for m in script.requests[1]["messages"] if m["role"] == "tool")
    assert err["content"].startswith("ERROR: path escapes")


def test_repeated_identical_calls_get_a_hint_then_a_stop(repo: Path) -> None:
    script = Script([tool("list_dir", path=".")] * 10)
    result = run(repo, script)
    assert result.status == "loop" and result.loop_hints == 1 and result.steps == 4
    hinted = script.requests[3]["messages"][-1]
    assert hinted["role"] == "user" and "same tool call 3 times" in hinted["content"][0]["text"]


def test_step_and_dollar_budgets_are_hard_stops(repo: Path) -> None:
    calls = [tool("read_file", path="app/main.py", start_line=i) for i in range(1, 30)]
    assert run(repo, Script(calls), max_steps=5).status == "max_steps"
    assert run(repo, Script(calls, cost=0.2), max_usd=0.5).status == "max_usd"
    assert run(repo, Script(calls), max_tokens=2500).status == "max_tokens"


def test_ambiguous_ticket_escalates(repo: Path) -> None:
    script = Script([tool("ask_human", question="Round half up or to even?")])
    result = run(repo, script)
    assert result.status == "escalated" and result.question == "Round half up or to even?"


def test_long_history_is_compacted_without_breaking_tool_pairs(repo: Path) -> None:
    turns = [tool("read_file", path="app/main.py", start_line=1 + i % 2) for i in range(6)]
    script = Script([*turns, text("done")])
    result = run(repo, script, context_tokens=250, keep_recent=2)
    assert result.status == "done" and result.compactions >= 1
    first_user = result.messages[0].text
    assert "Progress so far (summary)" in first_user and "minus sign" in first_user
    # every tool message the model receives follows an assistant turn that issued it
    for req in script.requests:
        ids: set[str] = set()
        for m in req["messages"]:
            if m["role"] == "assistant":
                ids = {c["id"] for c in m.get("tool_calls") or []}
            if m["role"] == "tool":
                assert m["tool_call_id"] in ids


def test_agent_run_is_traced(repo: Path, tmp_path: Path) -> None:
    tracer = Tracer(tmp_path / "trace.sqlite")
    with tracer.span("run", "task-1", run_id="r1"):
        run(repo, Script([tool("read_file", path="app/main.py"), text("ok")]), tracer=tracer)
    kinds = [s["kind"] for s in tracer.spans("r1")]
    assert kinds.count("llm") == 2 and kinds.count("tool") == 1 and "agent" in kinds


def test_finish_tool_gets_a_deadline_reminder(repo: Path) -> None:
    from forgeloop.agent_loop import FinishTool
    from llmcore import ToolSpec

    finish = FinishTool(ToolSpec(name="submit", description="d", input_schema={"type": "object"}), lambda _: None)
    script = Script([tool("read_file", path="app/main.py", start_line=i) for i in range(1, 4)] + [tool("submit")])
    result = run(repo, script, max_steps=5, finish=finish)
    assert result.status == "done" and result.output == {}
    reminded = json.dumps(script.requests[2]["messages"][-1])
    assert "steps left" in reminded and "submit" in reminded
