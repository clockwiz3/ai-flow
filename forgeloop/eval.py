"""Eval runner: task x configuration x repeat, each run in its own workspace and sandbox, scored by hidden tests."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from forgeloop import workspace
from forgeloop.agent_loop import AgentConfig, AgentLoop, AgentResult
from forgeloop.bench import REPO, BenchTask
from forgeloop.grading import grade
from forgeloop.roles import implementer
from forgeloop.tools import DockerSandbox, Workspace, default_toolbox
from llmcore import BudgetExceeded, LLMClient, Tracer

RESULTS = Path("evals/results")


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
    status: str  # how the pipeline ended: done, escalated, max_steps, ...
    passed: bool  # the outcome the task wants: hidden tests pass, or an escalation for an ambiguous ticket
    hidden_passed: bool | None
    cost_usd: float
    steps: int
    input_tokens: int
    cache_read_tokens: int
    output_tokens: int
    wall_s: float
    question: str | None = None
    error: str | None = None
    diff: str = ""
    grade_output: str = ""


@dataclass(frozen=True)
class EvalSettings:
    model: str
    max_usd_per_run: float = 0.40
    max_steps: int = 40
    temperature: float = 0.2


Pipeline = Callable[[LLMClient, Tracer, BenchTask, Path, DockerSandbox, EvalSettings, int], Awaitable[AgentResult]]


async def baseline(
    client: LLMClient,
    tracer: Tracer,
    task: BenchTask,
    ws: Path,
    sandbox: DockerSandbox,
    settings: EvalSettings,
    repeat: int,
) -> AgentResult:
    """One agent, no plan, no gates: the ticket goes straight to the implementer."""
    loop = AgentLoop(
        client,
        default_toolbox(Workspace(ws), sandbox),
        AgentConfig(
            model=settings.model,
            system=implementer.SYSTEM,
            max_usd=settings.max_usd_per_run,
            max_steps=settings.max_steps,
            temperature=settings.temperature,
            variant=repeat,
        ),
        tracer=tracer,
    )
    return await loop.run(implementer.task_prompt(task.ticket), name="implementer")


PIPELINES: dict[str, Pipeline] = {"baseline": baseline}


async def run_one(
    client: LLMClient,
    tracer: Tracer,
    eval_id: str,
    task: BenchTask,
    config: str,
    repeat: int,
    settings: EvalSettings,
    work_root: Path,
) -> RunRecord:
    run_id = f"{eval_id}-{task.id}-{config}-{repeat}"
    shutil.rmtree(work_root / run_id, ignore_errors=True)  # leftovers of an interrupted attempt
    ws = workspace.prepare(REPO, work_root / run_id, f"forgeloop/{task.id}", setup=task.setup)
    started = time.perf_counter()
    sandbox = await DockerSandbox.start(ws)
    try:
        with tracer.span("run", task.id, run_id=run_id, config=config, repeat=repeat):
            result = await PIPELINES[config](client, tracer, task, ws, sandbox, settings, repeat)
    finally:
        await sandbox.close()
    workspace.commit_all(ws, f"forgeloop: {task.id}")
    patch = workspace.diff(ws)
    hidden = None
    grade_output = ""
    if task.hidden is not None and result.status != "escalated":
        g = await grade(ws, task.hidden)
        hidden, grade_output = g.passed, g.output[-3000:]
    passed = result.status == "escalated" if task.meta.expected == "escalate" else bool(hidden)
    shutil.rmtree(ws, ignore_errors=True)
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
        status=result.status,
        passed=passed,
        hidden_passed=hidden,
        cost_usd=result.cost_usd,
        steps=result.steps,
        input_tokens=result.usage.input_tokens,
        cache_read_tokens=result.usage.cache_read_tokens,
        output_tokens=result.usage.output_tokens,
        wall_s=time.perf_counter() - started,
        question=result.question,
        error=result.error,
        diff=patch[-20_000:],
        grade_output=grade_output,
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
    sem = asyncio.Semaphore(concurrency)
    records = list(done.values())

    async def one(task: BenchTask, config: str, repeat: int) -> None:
        async with sem:
            client.meter.check()  # raises BudgetExceeded once the whole eval is out of money
            try:
                record = await run_one(client, tracer, eval_id, task, config, repeat, settings, work_root)
            except BudgetExceeded:
                raise
            except Exception as exc:  # harness failure (Docker, git): not a result, the run is retried on resume
                print(f"harness error in {task.id}/{config}/{repeat}: {type(exc).__name__}: {exc}")
                return
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with out_file.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
        records.append(record)
        if on_record:
            on_record(record)

    jobs = [one(t, c, r) for r in range(repeats) for c in configs for t in tasks if (t.id, c, r) not in done]
    await asyncio.gather(*jobs)
    return records


def load_records(path: Path) -> list[RunRecord]:
    if not path.exists():
        return []
    return [
        RunRecord.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line
    ]
