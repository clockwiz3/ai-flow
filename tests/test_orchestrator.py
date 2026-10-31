import asyncio
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import httpx
import pytest

from forgeloop.intake import Task, from_markdown
from forgeloop.orchestrator import Orchestrator, PipelineConfig, RunState, Stage
from forgeloop.store import RunStore
from forgeloop.tools import ExecResult, Sandbox
from llmcore import LLMClient, Meter

Turn = dict[str, Any]

PLAN = {
    "summary": "Make add() add.",
    "files": [{"path": "app/main.py", "action": "modify", "why": "the bug"}],
    "checkpoints": [
        {"title": "Fix add", "steps": ["change minus to plus"], "done_when": "add(2, 2) == 4"},
        {"title": "Test it", "steps": ["add a test"], "done_when": "test passes"},
    ],
    "acceptance": ["add returns the sum"],
}
APPROVE = {"verdict": "approve", "summary": "looks right"}
CHANGES = {
    "verdict": "request_changes",
    "summary": "missing test",
    "issues": [{"severity": "major", "file": "tests/test_main.py", "comment": "add a test for negatives"}],
}


def call(name: str, **args: Any) -> Turn:
    return {
        "content": "",
        "tool_calls": [{"id": f"c_{name}", "function": {"name": name, "arguments": json.dumps(args)}}],
    }


def say(text: str) -> Turn:
    return {"content": text}


class Models:
    """Fake OpenRouter: answers per role (recognised by the system prompt) from scripted queues."""

    def __init__(self, script: dict[str, list[Turn]]) -> None:
        self.queues = {role: deque(turns) for role, turns in script.items()}
        self.calls: dict[str, int] = defaultdict(int)

    def role(self, payload: dict[str, Any]) -> str:
        system = payload["messages"][0]["content"][0]["text"]
        if "planning a change" in system:
            return "planner"
        if "code reviewer" in system:
            return "reviewer"
        return "implementer"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        role = self.role(payload)
        self.calls[role] += 1
        turn = self.queues[role].popleft()
        finish = "tool_calls" if turn.get("tool_calls") else "stop"
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "choices": [{"message": turn, "finish_reason": finish}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 20, "cost": 0.001},
            },
        )


class FakeSandbox:
    """pytest results come from a queue; ruff and bandit are clean."""

    def __init__(self, pytest_results: list[int]) -> None:
        self.pytest_results = deque(pytest_results)
        self.commands: list[list[str]] = []

    async def exec(self, argv: list[str], timeout_s: float) -> ExecResult:
        self.commands.append(argv)
        if argv[0] == "pytest":
            code = self.pytest_results.popleft() if self.pytest_results else 0
            return ExecResult(code, "1 failed: test_add" if code else "3 passed")
        if argv[0] == "bandit":
            return ExecResult(0, '{"results": []}')
        return ExecResult(0, "All checks passed!")

    async def close(self) -> None:
        return None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "main.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "tests" / "test_main.py").write_text("from app.main import add\n", encoding="utf-8")
    return root


def implementer_edits(n: int) -> list[Turn]:
    """n implementer runs, each making a distinct edit and finishing."""
    turns: list[Turn] = []
    for i in range(n):
        turns += [call("write_file", path=f"app/step{i}.py", content=f"X = {i}\n"), say(f"done {i}")]
    return turns


def run_pipeline(
    tmp_path: Path,
    repo: Path,
    models: Models,
    config: PipelineConfig,
    pytest_results: list[int] | None = None,
    observer: Any = None,
) -> tuple[RunState, Orchestrator, FakeSandbox]:
    sandbox = FakeSandbox(pytest_results or [])

    async def factory(_: Path) -> Sandbox:
        return sandbox

    async def go() -> tuple[RunState, Orchestrator]:
        client = LLMClient(api_key="k", transport=httpx.MockTransport(models), meter=Meter())
        orch = Orchestrator(
            client, RunStore(tmp_path / "runs.sqlite"), observer=observer, runs_dir=tmp_path / "runs",
            sandbox_factory=factory,
        )  # fmt: skip
        task = Task(id="t1", title="Fix add", body="add() subtracts", source="file")
        state = orch.new_run(task, repo, config)
        try:
            return await orch.run(state), orch
        finally:
            await client.aclose()

    state, orch = asyncio.run(go())
    return state, orch, sandbox


def test_full_pipeline_delivers_with_plan_gates_and_pr(tmp_path: Path, repo: Path) -> None:
    models = Models(
        {
            "planner": [call("read_file", path="app/main.py"), call("submit_plan", **PLAN)],
            "implementer": implementer_edits(2),
            "reviewer": [call("submit_review", **APPROVE)],
        }
    )
    state, _, sandbox = run_pipeline(tmp_path, repo, models, PipelineConfig.preset("full"))
    assert state.stage == Stage.DELIVERED, state.escalation
    assert state.checkpoints_done == 2
    assert [g.gate for g in state.gates] == ["plan", "test", "review"]
    assert [a.role for a in state.agents] == ["planner", "implementer.cp1", "implementer.cp2", "reviewer"]
    assert state.cost_usd == pytest.approx(0.001 * sum(models.calls.values()))
    pr = (tmp_path / "runs" / state.run_id / "PR.md").read_text(encoding="utf-8")
    assert "## Plan" in pr and "| review | pass | approve |" in pr and "+X = 1" in pr
    assert any(c[0] == "ruff" for c in sandbox.commands)


def test_failing_tests_go_back_to_the_implementer(tmp_path: Path, repo: Path) -> None:
    models = Models(
        {
            "planner": [call("submit_plan", **PLAN)],
            "implementer": implementer_edits(3),
        }
    )
    state, _, _ = run_pipeline(tmp_path, repo, models, PipelineConfig.preset("test-gate"), pytest_results=[1, 0])
    assert state.stage == Stage.DELIVERED
    assert state.test_rounds == 1
    assert [g.passed for g in state.gates if g.gate == "test"] == [False, True]
    assert state.agents[-1].role == "implementer.fix-test-gate"


def test_tests_that_never_pass_escalate(tmp_path: Path, repo: Path) -> None:
    models = Models({"implementer": implementer_edits(4)})
    config = PipelineConfig.preset("test-gate", plan=False, max_test_rounds=2)
    state, _, _ = run_pipeline(tmp_path, repo, models, config, pytest_results=[1, 1, 1, 1])
    assert state.stage == Stage.ESCALATED and "after 2 fix rounds" in (state.escalation or "")


def test_review_changes_are_fixed_and_retested(tmp_path: Path, repo: Path) -> None:
    models = Models(
        {
            "planner": [call("submit_plan", **PLAN)],
            "implementer": implementer_edits(3),
            "reviewer": [call("submit_review", **CHANGES), call("submit_review", **APPROVE)],
        }
    )
    state, _, _ = run_pipeline(tmp_path, repo, models, PipelineConfig.preset("full"))
    assert state.stage == Stage.DELIVERED
    assert [g.gate for g in state.gates] == ["plan", "test", "review", "test", "review"]
    assert [r.verdict for r in state.reviews] == ["request_changes", "approve"]


def test_invalid_plan_is_sent_back_once(tmp_path: Path, repo: Path) -> None:
    bad = {**PLAN, "files": [{"path": "app/nope.py", "action": "modify", "why": "x"}]}
    models = Models(
        {
            "planner": [call("submit_plan", **bad), call("submit_plan", **PLAN)],
            "implementer": implementer_edits(2),
        }
    )
    state, _, _ = run_pipeline(tmp_path, repo, models, PipelineConfig.preset("plan"))
    assert state.stage == Stage.DELIVERED and state.plan_attempts == 2
    assert [g.passed for g in state.gates] == [False, True]


def test_plan_touching_protected_paths_escalates(tmp_path: Path, repo: Path) -> None:
    sneaky = {**PLAN, "files": [{"path": "tests/hidden/test_x.py", "action": "create", "why": "x"}]}
    models = Models({"planner": [call("submit_plan", **sneaky), call("submit_plan", **sneaky)]})
    state, _, _ = run_pipeline(tmp_path, repo, models, PipelineConfig.preset("plan"))
    assert state.stage == Stage.ESCALATED and "plan gate" in (state.escalation or "")


def test_ambiguous_ticket_escalates_with_the_question(tmp_path: Path, repo: Path) -> None:
    models = Models({"planner": [call("ask_human", question="Round half up or half even?")]})
    state, _, _ = run_pipeline(tmp_path, repo, models, PipelineConfig.preset("full"))
    assert state.stage == Stage.ESCALATED and state.question == "Round half up or half even?"
    assert models.calls["implementer"] == 0


def test_baseline_skips_planner_and_gates(tmp_path: Path, repo: Path) -> None:
    models = Models({"implementer": implementer_edits(1)})
    state, _, sandbox = run_pipeline(tmp_path, repo, models, PipelineConfig.preset("baseline"))
    assert state.stage == Stage.DELIVERED and state.gates == [] and models.calls["planner"] == 0
    assert sandbox.commands == []


def test_run_budget_escalates(tmp_path: Path, repo: Path) -> None:
    models = Models({"planner": [call("submit_plan", **PLAN)], "implementer": implementer_edits(2)})
    config = PipelineConfig.preset("full", max_usd_per_run=0.0025)
    state, _, _ = run_pipeline(tmp_path, repo, models, config)
    assert state.stage == Stage.ESCALATED and "budget" in (state.escalation or "")


def test_resume_continues_after_a_crash(tmp_path: Path, repo: Path) -> None:
    models = Models(
        {
            "planner": [call("submit_plan", **PLAN)],
            "implementer": implementer_edits(2),
            "reviewer": [call("submit_review", **APPROVE)],
        }
    )
    crashed = {"done": False}

    async def crash_once(event: str, _: RunState) -> None:
        if event == "implemented" and not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError("power cut")

    with pytest.raises(RuntimeError):
        run_pipeline(tmp_path, repo, models, PipelineConfig.preset("full"), observer=crash_once)

    async def resume() -> RunState:
        async def factory(_: Path) -> Sandbox:
            return FakeSandbox([])

        client = LLMClient(api_key="k", transport=httpx.MockTransport(models), meter=Meter())
        store = RunStore(tmp_path / "runs.sqlite")
        orch = Orchestrator(
            client, store, observer=crash_once, runs_dir=tmp_path / "runs", sandbox_factory=factory
        )  # fmt: skip
        (run,) = store.runs()
        state = orch.load(run["id"])
        assert state.stage == Stage.IMPLEMENT and state.checkpoints_done == 2
        try:
            return await orch.run(state)
        finally:
            await client.aclose()

    state = asyncio.run(resume())
    assert state.stage == Stage.DELIVERED
    assert models.calls["planner"] == 1 and models.calls["implementer"] == 4  # nothing was redone


def test_markdown_intake(tmp_path: Path) -> None:
    (tmp_path / "bug-9").mkdir()
    ticket = tmp_path / "bug-9" / "ticket.md"
    ticket.write_text("# Search ignores case\n\nSearching 'tent' finds nothing.\n", encoding="utf-8")
    task = from_markdown(ticket)
    assert task.id == "bug-9" and task.title == "Search ignores case"
    assert task.ticket.startswith("# Search ignores case\n\nSearching")
