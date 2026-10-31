"""Eval runner: task x configuration x repeat. Each run is a full pipeline in its own workspace and sandbox.

Hidden tests are run by the eval (never by the agents) after implementation, after every fix round and at the end.
That timeline is what shows which gate rescued a run, and which review verdicts were wrong.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from forgeloop import workspace
from forgeloop.bench import REPO, BenchTask
from forgeloop.grading import grade
from forgeloop.intake import Task
from forgeloop.orchestrator import Orchestrator, PipelineConfig, RunState, Stage
from forgeloop.store import RunStore
from llmcore import BudgetExceeded, LLMClient, Tracer

RESULTS = Path("evals/results")
CONFIGS = ["baseline", "plan", "test-gate", "full"]


class Checkpoint(BaseModel):
    event: str  # implemented, test_fix, review_fix, reviewed:<verdict>, final
    hidden_passed: bool | None


class RunRecord(BaseModel):
    eval_id: str
    task_id: str
    kind: str
    difficulty: str
    expected: str
    tags: list[str]
    config: str
    repeat: int
    model: str
    status: str  # how the pipeline ended: delivered or escalated
    passed: bool  # the outcome the task wants: delivered and hidden tests pass, or a question on an ambiguous ticket
    hidden_passed: bool | None
    cost_usd: float
    steps: int
    input_tokens: int
    cache_read_tokens: int
    output_tokens: int
    wall_s: float
    question: str | None = None
    error: str | None = None  # escalation reason
    diff: str = ""
    grade_output: str = ""
    reviewer_model: str | None = None
    plan_attempts: int = 0
    test_rounds: int = 0
    review_rounds: int = 0
    timeline: list[Checkpoint] = []
    agents: list[dict[str, object]] = []


@dataclass(frozen=True)
class EvalSettings:
    model: str
    reviewer_model: str = "z-ai/glm-5.3-flash"
    planner_model: str = "anthropic/claude-haiku-5.5"  # fixed across tracks: only the implementer varies
    max_usd_per_run: float = 1.00
    max_usd_per_agent: float = 0.40
    max_steps: int = 40
    temperature: float = 0.2

    def pipeline(self, config: str, repeat: int) -> PipelineConfig:
        return PipelineConfig.preset(
            config,
            implementer_model=self.model,
            planner_model=self.planner_model,
            reviewer_model=self.reviewer_model,
            max_usd_per_run=self.max_usd_per_run,
            max_usd_per_agent=self.max_usd_per_agent,
            max_steps=self.max_steps,
            temperature=self.temperature,
            variant=repeat,
        )


async def run_one(
    client: LLMClient,
    tracer: Tracer,
    store: RunStore,
    eval_id: str,
    task: BenchTask,
    config: str,
    repeat: int,
    settings: EvalSettings,
    work_root: Path,
) -> RunRecord:
    run_id = f"{task.id}-{config}-{repeat}"  # the eval directory already namespaces it
    workspace.remove(work_root / run_id)  # leftovers of an interrupted attempt
    timeline: list[Checkpoint] = []

    async def observe(event: str, state: RunState) -> None:
        if event == "reviewed":
            verdict = state.reviews[-1].verdict
            last = timeline[-1].hidden_passed if timeline else None
            timeline.append(Checkpoint(event=f"reviewed:{verdict}", hidden_passed=last))
            return
        if task.hidden is not None:
            timeline.append(Checkpoint(event=event, hidden_passed=(await grade(state.ws, task.hidden)).passed))

    orch = Orchestrator(client, store, tracer=tracer, observer=observe, runs_dir=work_root)
    ticket = Task(id=task.id, title=task.meta.title, body=task.ticket, source="file")
    started = time.perf_counter()
    state = orch.new_run(ticket, REPO, settings.pipeline(config, repeat), setup=task.setup, run_id=run_id)
    with tracer.span("run", task.id, run_id=run_id, config=config, repeat=repeat):
        state = await orch.run(state)

    workspace.commit_all(state.ws, f"forgeloop: {task.id} final")
    hidden, grade_output = None, ""
    if task.hidden is not None:
        g = await grade(state.ws, task.hidden)
        hidden, grade_output = g.passed, g.output[-3000:]
        timeline.append(Checkpoint(event="final", hidden_passed=hidden))
    delivered = state.stage == Stage.DELIVERED
    if task.meta.expected == "escalate":
        passed = state.stage == Stage.ESCALATED and state.question is not None
    else:
        passed = delivered and bool(hidden)
    patch = workspace.diff(state.ws)
    workspace.remove(work_root / run_id)
    return RunRecord(
        eval_id=eval_id,
        task_id=task.id,
        kind=task.meta.kind,
        difficulty=task.meta.difficulty,
        expected=task.meta.expected,
        tags=task.meta.tags,
        config=config,
        repeat=repeat,
        model=settings.model,
        reviewer_model=settings.reviewer_model if state.config.review_gate else None,
        status=state.stage.value,
        passed=passed,
        hidden_passed=hidden,
        cost_usd=state.cost_usd,
        steps=sum(a.steps for a in state.agents),
        input_tokens=sum(a.input_tokens for a in state.agents),
        cache_read_tokens=sum(a.cache_read_tokens for a in state.agents),
        output_tokens=sum(a.output_tokens for a in state.agents),
        wall_s=time.perf_counter() - started,
        question=state.question,
        error=state.escalation,
        diff=patch[-20_000:],
        grade_output=grade_output,
        plan_attempts=state.plan_attempts,
        test_rounds=state.test_rounds,
        review_rounds=state.review_rounds,
        timeline=timeline,
        agents=[a.model_dump() for a in state.agents],
    )


async def run_eval(
    client: LLMClient,
    tracer: Tracer,
    eval_id: str,
    tasks: list[BenchTask],
    configs: list[str],
    repeats: int,
    settings: EvalSettings,
    *,
    concurrency: int = 4,
    on_record: Callable[[RunRecord], None] | None = None,
) -> list[RunRecord]:
    """Runs every combination; finished runs already in the results file are skipped, so an eval can resume."""
    out_file = RESULTS / f"{eval_id}.jsonl"
    done = {(r.task_id, r.config, r.repeat): r for r in load_records(out_file)}
    work_root = Path("runs") / eval_id
    store = RunStore(work_root / "runs.sqlite")
    sem = asyncio.Semaphore(concurrency)
    records = list(done.values())

    async def one(task: BenchTask, config: str, repeat: int) -> None:
        async with sem:
            client.meter.check()  # raises BudgetExceeded once the whole eval is out of money
            try:
                record = await run_one(client, tracer, store, eval_id, task, config, repeat, settings, work_root)
            except BudgetExceeded:
                raise
            except Exception as exc:  # harness failure (Docker, git): not a result, the run is retried on resume
                print(f"harness error in {task.id}/{config}/{repeat}: {type(exc).__name__}: {exc}")
                return
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with out_file.open("a", encoding="utf-8", newline="\n") as f:
            f.write(record.model_dump_json() + "\n")
        records.append(record)
        if on_record:
            on_record(record)

    jobs = [one(t, c, r) for r in range(repeats) for c in configs for t in tasks if (t.id, c, r) not in done]
    try:
        await asyncio.gather(*jobs)
    finally:
        store.close()
    return records


def load_records(path: Path) -> list[RunRecord]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [RunRecord.model_validate(json.loads(line)) for line in lines if line]
