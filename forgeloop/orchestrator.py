"""The pipeline as an explicit state machine: intake -> plan -> plan gate -> implement -> test gate -> review gate ->
deliver, or escalate to a human.

Each stage reads and writes `RunState`; the state is persisted after every transition, so a run can be resumed from
the stage it stopped at. Gates are transitions, not suggestions: there is no path to DELIVER that skips an enabled
gate. Stages can be switched off by configuration, which is how the eval measures what each one adds.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from forgeloop import workspace
from forgeloop.agent_loop import AgentConfig, AgentLoop, AgentResult, FinishTool
from forgeloop.gates import GateResult
from forgeloop.gates.plan_gate import check_plan
from forgeloop.gates.test_gate import run_test_gate
from forgeloop.intake import Task
from forgeloop.roles import implementer, planner, reviewer
from forgeloop.roles.planner import Plan
from forgeloop.roles.reviewer import Review
from forgeloop.store import RunStore
from forgeloop.tools import DockerSandbox, Sandbox, Workspace, default_toolbox
from llmcore import LLMClient, Tracer


class Stage(StrEnum):
    PLAN = "plan"
    PLAN_GATE = "plan_gate"
    IMPLEMENT = "implement"
    TEST_GATE = "test_gate"
    REVIEW_GATE = "review_gate"
    DELIVER = "deliver"
    DELIVERED = "delivered"
    ESCALATED = "escalated"


TERMINAL = {Stage.DELIVERED, Stage.ESCALATED}


class PipelineConfig(BaseModel):
    plan: bool = True
    test_gate: bool = True
    review_gate: bool = True
    approve_plan: bool = False
    implementer_model: str = "anthropic/claude-haiku-5.5"
    planner_model: str = "anthropic/claude-haiku-5.5"
    reviewer_model: str = "deepseek/deepseek-v4.1-flash"  # a different model than the implementer
    max_plan_attempts: int = 2
    max_test_rounds: int = 3
    max_review_rounds: int = 2
    max_usd_per_agent: float = 0.40
    max_usd_per_run: float = 1.00
    max_steps: int = 40
    temperature: float = 0.2
    variant: int = 0

    @classmethod
    def preset(cls, name: str, **overrides: Any) -> PipelineConfig:
        flags = {
            "baseline": {"plan": False, "test_gate": False, "review_gate": False},
            "plan": {"plan": True, "test_gate": False, "review_gate": False},
            "test-gate": {"plan": True, "test_gate": True, "review_gate": False},
            "full": {"plan": True, "test_gate": True, "review_gate": True},
        }
        if name not in flags:
            raise ValueError(f"unknown preset {name!r}; available: {sorted(flags)}")
        return cls(**{**flags[name], **overrides})


class AgentSummary(BaseModel):
    role: str
    status: str
    steps: int
    cost_usd: float
    input_tokens: int
    cache_read_tokens: int
    output_tokens: int


class RunState(BaseModel):
    run_id: str
    task: Task
    config: PipelineConfig
    stage: Stage = Stage.PLAN
    workspace: str
    plan: Plan | None = None
    plan_attempts: int = 0
    plan_feedback: str | None = None
    checkpoints_done: int = 0
    test_rounds: int = 0
    review_rounds: int = 0
    gates: list[GateResult] = []
    agents: list[AgentSummary] = []
    reviews: list[Review] = []
    cost_usd: float = 0.0
    escalation: str | None = None  # why a human is needed
    question: str | None = None  # an agent's question for an ambiguous ticket

    @property
    def ws(self) -> Path:
        return Path(self.workspace)


Observer = Callable[[str, RunState], Awaitable[None]]  # (event, state): eval hooks, e.g. grade after each gate
Approver = Callable[[Plan], bool]


@dataclass
class Orchestrator:
    client: LLMClient
    store: RunStore
    tracer: Tracer | None = None
    observer: Observer | None = None
    approver: Approver | None = None
    runs_dir: Path = Path("runs")
    sandbox_factory: Callable[[Path], Awaitable[Sandbox]] = field(default=DockerSandbox.start)

    def new_run(
        self, task: Task, repo: Path, config: PipelineConfig, *, setup: Path | None = None, run_id: str | None = None
    ) -> RunState:
        run_id = run_id or f"{task.id}-{uuid.uuid4().hex[:8]}"
        ws = workspace.prepare(repo, self.runs_dir / run_id / "workspace", f"forgeloop/{run_id}", setup=setup)
        state = RunState(run_id=run_id, task=task, config=config, workspace=str(ws))
        state.stage = Stage.PLAN if config.plan else Stage.IMPLEMENT
        self._save(state, "created", {"task": task.id, "config": config.model_dump()})
        return state

    def load(self, run_id: str) -> RunState:
        return RunState.model_validate_json(self.store.load(run_id))

    async def run(self, state: RunState) -> RunState:
        """Advance until delivered or escalated. Safe to call again on a loaded state (resume)."""
        sandbox = await self.sandbox_factory(state.ws)
        handlers: dict[Stage, Callable[[RunState, Sandbox], Awaitable[None]]] = {
            Stage.PLAN: self._plan,
            Stage.PLAN_GATE: self._plan_gate,
            Stage.IMPLEMENT: self._implement,
            Stage.TEST_GATE: self._test_gate,
            Stage.REVIEW_GATE: self._review_gate,
            Stage.DELIVER: self._deliver,
        }
        try:
            while state.stage not in TERMINAL:
                stage = state.stage
                if stage != Stage.DELIVER and state.cost_usd >= state.config.max_usd_per_run:
                    self._escalate(state, f"run budget of ${state.config.max_usd_per_run:.2f} exhausted")
                    continue
                if self.tracer:
                    with self.tracer.span("stage", stage.value, run_id=state.run_id):
                        await handlers[stage](state, sandbox)
                else:
                    await handlers[stage](state, sandbox)
                self._save(state, "stage_done", {"stage": stage.value, "next": state.stage.value})
        finally:
            await sandbox.close()
        return state

    # --- stages -------------------------------------------------------------------------------------------------

    async def _plan(self, state: RunState, sandbox: Sandbox) -> None:
        cfg = state.config
        state.plan_attempts += 1
        result = await self._agent(
            state,
            sandbox,
            role="planner",
            model=cfg.planner_model,
            system=planner.SYSTEM,
            task=planner.task_prompt(state.task.ticket, state.plan_feedback),
            read_only=True,
            finish=planner.FINISH,
        )
        if result.status == "escalated":
            state.question = result.question
            self._escalate(state, "the planner needs clarification")
        elif result.status != "done" or result.output is None:
            self._escalate(state, f"planning failed: {result.status} {result.error or ''}".strip())
        else:
            state.plan = Plan.model_validate(result.output)
            state.stage = Stage.PLAN_GATE

    async def _plan_gate(self, state: RunState, sandbox: Sandbox) -> None:
        assert state.plan is not None
        gate = check_plan(state.plan, Workspace(state.ws))
        state.gates.append(gate)
        if not gate.passed:
            if state.plan_attempts < state.config.max_plan_attempts:
                state.plan_feedback = gate.feedback
                state.stage = Stage.PLAN
            else:
                self._escalate(state, f"plan rejected by the plan gate: {gate.summary}")
            return
        if state.config.approve_plan and (self.approver is None or not self.approver(state.plan)):
            self._escalate(state, "plan rejected by a human")
            return
        state.stage = Stage.IMPLEMENT

    async def _implement(self, state: RunState, sandbox: Sandbox) -> None:
        cfg = state.config
        if state.plan is None:  # no planner: the ticket goes straight to one implementer run
            result = await self._agent(
                state, sandbox, role="implementer", model=cfg.implementer_model, system=implementer.SYSTEM,
                task=implementer.task_prompt(state.task.ticket),
            )  # fmt: skip
            if result.status == "escalated":
                state.question = result.question
                self._escalate(state, "the implementer needs clarification")
                return
            workspace.commit_all(state.ws, f"forgeloop: {state.task.id}")
        else:
            checkpoints = state.plan.checkpoints
            plan_text = state.plan.render()
            while state.checkpoints_done < len(checkpoints):
                n = state.checkpoints_done
                cp = checkpoints[n]
                result = await self._agent(
                    state, sandbox, role=f"implementer.cp{n + 1}", model=cfg.implementer_model,
                    system=implementer.SYSTEM, context=plan_text,
                    task=implementer.checkpoint_prompt(state.task.ticket, n + 1, len(checkpoints), cp.title,
                                                       cp.steps, cp.done_when),
                )  # fmt: skip
                if result.status == "escalated":
                    state.question = result.question
                    self._escalate(state, f"the implementer needs clarification at checkpoint {n + 1}")
                    return
                workspace.commit_all(state.ws, f"forgeloop: {state.task.id} checkpoint {n + 1}: {cp.title}")
                state.checkpoints_done += 1
                self._save(state, "checkpoint", {"n": n + 1, "title": cp.title, "status": result.status})
                if state.cost_usd >= cfg.max_usd_per_run:
                    break  # the run loop escalates on the budget before the next stage
        await self._notify("implemented", state)
        state.stage = self._after_implement(state)

    def _after_implement(self, state: RunState) -> Stage:
        if state.config.test_gate:
            return Stage.TEST_GATE
        if state.config.review_gate:
            return Stage.REVIEW_GATE
        return Stage.DELIVER

    async def _test_gate(self, state: RunState, sandbox: Sandbox) -> None:
        gate = await run_test_gate(sandbox, state.ws)
        gate.data["round"] = state.test_rounds
        state.gates.append(gate)
        if gate.passed:
            state.stage = Stage.REVIEW_GATE if state.config.review_gate else Stage.DELIVER
            return
        if state.test_rounds >= state.config.max_test_rounds:
            self._escalate(state, f"test gate still failing after {state.test_rounds} fix rounds: {gate.summary}")
            return
        state.test_rounds += 1
        await self._fix(state, sandbox, "test gate", gate.feedback)
        await self._notify("test_fix", state)
        # stay in TEST_GATE: the fix is verified by the same gate

    async def _review_gate(self, state: RunState, sandbox: Sandbox) -> None:
        cfg = state.config
        diff = workspace.diff(state.ws)
        if not diff.strip():
            state.gates.append(GateResult(gate="review", passed=False, summary="empty diff"))
            self._escalate(state, "nothing was changed")
            return
        result = await self._agent(
            state, sandbox, role="reviewer", model=cfg.reviewer_model, system=reviewer.SYSTEM,
            task=reviewer.task_prompt(state.task.ticket, state.plan.render() if state.plan else None, diff[-60_000:]),
            read_only=True, finish=reviewer.FINISH, allow_escalation=False,
        )  # fmt: skip
        if result.status != "done" or result.output is None:
            state.gates.append(GateResult(gate="review", passed=False, summary=f"reviewer failed: {result.status}"))
            self._escalate(state, f"review could not be completed: {result.status}")
            return
        review = Review.model_validate(result.output)
        state.reviews.append(review)
        approved = review.verdict == "approve"
        state.gates.append(
            GateResult(
                gate="review", passed=approved, summary=review.verdict, feedback=review.render(),
                data={"round": state.review_rounds, "issues": len(review.issues)},
            )
        )  # fmt: skip
        if approved:
            state.stage = Stage.DELIVER
            return
        if state.review_rounds >= cfg.max_review_rounds:
            self._escalate(state, f"reviewer still requests changes after {state.review_rounds} rounds")
            return
        state.review_rounds += 1
        await self._fix(state, sandbox, "code review", review.render())
        await self._notify("review_fix", state)
        if state.stage != Stage.ESCALATED:
            state.stage = Stage.TEST_GATE if cfg.test_gate else Stage.REVIEW_GATE

    async def _deliver(self, state: RunState, sandbox: Sandbox) -> None:
        workspace.commit_all(state.ws, f"forgeloop: {state.task.id}")
        pr = self.runs_dir / state.run_id / "PR.md"
        pr.write_text(render_pr(state, workspace.diff(state.ws)), encoding="utf-8", newline="\n")
        state.stage = Stage.DELIVERED

    # --- helpers ------------------------------------------------------------------------------------------------

    async def _fix(self, state: RunState, sandbox: Sandbox, source: str, feedback: str) -> None:
        cfg = state.config
        result = await self._agent(
            state, sandbox, role=f"implementer.fix-{source.replace(' ', '-')}", model=cfg.implementer_model,
            system=implementer.SYSTEM, context=state.plan.render() if state.plan else None,
            task=implementer.fix_prompt(state.task.ticket, source, feedback),
        )  # fmt: skip
        workspace.commit_all(state.ws, f"forgeloop: {state.task.id} fix after {source}")
        if result.status == "escalated":
            state.question = result.question
            self._escalate(state, f"the implementer needs clarification while fixing {source} findings")

    async def _agent(
        self,
        state: RunState,
        sandbox: Sandbox,
        *,
        role: str,
        model: str,
        system: str,
        task: str,
        context: str | None = None,
        read_only: bool = False,
        finish: FinishTool | None = None,
        allow_escalation: bool = True,
    ) -> AgentResult:
        cfg = state.config
        toolbox = default_toolbox(Workspace(state.ws), sandbox)
        if read_only:
            toolbox = toolbox.subset(read_only=True)
        remaining = max(cfg.max_usd_per_run - state.cost_usd, 0.0)
        loop = AgentLoop(
            self.client,
            toolbox,
            AgentConfig(
                model=model,
                system=system,
                max_usd=min(cfg.max_usd_per_agent, remaining),
                max_steps=cfg.max_steps,
                temperature=cfg.temperature,
                variant=cfg.variant,
                allow_escalation=allow_escalation,
                finish=finish,
            ),
            tracer=self.tracer,
        )
        result = await loop.run(task, context=context, name=role)
        state.cost_usd += result.cost_usd
        state.agents.append(
            AgentSummary(
                role=role, status=result.status, steps=result.steps, cost_usd=result.cost_usd,
                input_tokens=result.usage.input_tokens, cache_read_tokens=result.usage.cache_read_tokens,
                output_tokens=result.usage.output_tokens,
            )
        )  # fmt: skip
        self.store.event(state.run_id, state.stage.value, "agent", state.agents[-1].model_dump())
        return result

    def _escalate(self, state: RunState, reason: str) -> None:
        state.escalation = reason
        state.stage = Stage.ESCALATED

    def _save(self, state: RunState, kind: str, data: dict[str, Any]) -> None:
        self.store.save(state.run_id, state.task.id, state.stage.value, state.cost_usd, state)
        self.store.event(state.run_id, state.stage.value, kind, data)

    async def _notify(self, event: str, state: RunState) -> None:
        if self.observer:
            await self.observer(event, state)


def render_pr(state: RunState, diff: str) -> str:
    lines = [f"# {state.task.title}", ""]
    if state.task.url:
        lines += [f"Closes {state.task.url}", ""]
    lines += ["## Ticket", "", state.task.body.strip(), ""]
    if state.plan:
        lines += [state.plan.render().replace("# Plan", "## Plan", 1), ""]
    lines += ["## Gates", "", "| gate | result | details |", "| --- | --- | --- |"]
    for g in state.gates:
        lines.append(f"| {g.gate} | {'pass' if g.passed else 'fail'} | {g.summary} |")
    lines += ["", "## Cost", "", "| agent | status | steps | $ |", "| --- | --- | ---: | ---: |"]
    for a in state.agents:
        lines.append(f"| {a.role} | {a.status} | {a.steps} | {a.cost_usd:.4f} |")
    lines += [f"| **total** | | | **{state.cost_usd:.4f}** |", ""]
    lines += ["<details><summary>Diff</summary>", "", "```diff", diff[-30_000:], "```", "", "</details>", ""]
    return "\n".join(lines)
