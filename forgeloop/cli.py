"""Command line: `forgeloop solve` runs one agent on one ticket end to end."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Annotated

import typer

from forgeloop import workspace
from forgeloop.agent_loop import AgentConfig, AgentLoop, AgentResult
from forgeloop.grading import Grade, grade
from forgeloop.roles import implementer
from forgeloop.tools import DockerSandbox, Workspace, default_toolbox
from forgeloop.tools.sandbox import docker_ready, ensure_image
from llmcore import LLMClient, Meter, PriceTable, ResponseCache, Tracer, load_dotenv

app = typer.Typer(no_args_is_help=True, add_completion=False)

DEFAULT_MODEL = "anthropic/claude-haiku-5.5"
RUNS = Path("runs")


@app.callback()
def main() -> None:
    """ForgeLoop: ticket -> plan -> code -> gates -> PR, with an eval of what each gate buys."""


async def _solve(
    repo: Path, ticket: Path, hidden: Path | None, model: str, max_usd: float, budget_usd: float
) -> tuple[str, AgentResult, Grade | None, Meter]:
    if not await docker_ready():
        raise typer.BadParameter("Docker is not running: agents only execute commands inside the sandbox")
    await ensure_image()
    run_id = uuid.uuid4().hex[:10]
    run_dir = RUNS / run_id
    ws_path = workspace.prepare(repo, run_dir / "workspace", f"forgeloop/{run_id}")
    tracer = Tracer(RUNS / "trace.sqlite")
    meter = Meter(limit_usd=budget_usd)
    client = LLMClient(cache=ResponseCache(), meter=meter, tracer=tracer, prices=PriceTable.load())
    sandbox = await DockerSandbox.start(ws_path)
    try:
        loop = AgentLoop(
            client,
            default_toolbox(Workspace(ws_path), sandbox),
            AgentConfig(model=model, system=implementer.SYSTEM, max_usd=max_usd),
            tracer=tracer,
        )
        with tracer.span("run", "solve", run_id=run_id, ticket=str(ticket)):
            result = await loop.run(implementer.task_prompt(ticket.read_text(encoding="utf-8")), name="implementer")
        workspace.commit_all(ws_path, f"forgeloop: {ticket.stem}")
        verdict = await grade(ws_path, hidden) if hidden else None
    finally:
        await sandbox.close()
        await client.aclose()
    return run_id, result, verdict, meter


@app.command()
def solve(
    repo: Annotated[Path, typer.Option(exists=True, file_okay=False, help="Repository to work on (copied)")],
    ticket: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="Ticket in markdown")],
    hidden: Annotated[Path | None, typer.Option(exists=True, file_okay=False, help="Hidden tests for scoring")] = None,
    model: Annotated[str, typer.Option(help="OpenRouter model id")] = DEFAULT_MODEL,
    max_usd: Annotated[float, typer.Option(help="Budget for this agent run")] = 0.5,
) -> None:
    """One agent, no plan and no gates (the eval baseline): solve a ticket and score it."""
    load_dotenv()
    budget = float(os.environ.get("FORGELOOP_BUDGET_USD", "2.0"))
    run_id, result, verdict, meter = asyncio.run(_solve(repo, ticket, hidden, model, max_usd, budget))
    typer.echo(f"run {run_id}: {result.status} in {result.steps} steps, ${result.cost_usd:.4f}")
    typer.echo(
        f"tokens: in {result.usage.input_tokens} (cache read {result.usage.cache_read_tokens}),"
        f" out {result.usage.output_tokens}; compactions {result.compactions}, loop hints {result.loop_hints}"
    )
    if result.question:
        typer.echo(f"escalated: {result.question}")
    if result.error:
        typer.echo(f"error: {result.error}")
    if result.final_text:
        typer.echo(f"\n{result.final_text.strip()}\n")
    if verdict:
        typer.echo(f"hidden tests: {'PASS' if verdict.passed else 'FAIL'}")
        if not verdict.passed:
            typer.echo(verdict.output[-2000:])
    typer.echo(f"workspace: {RUNS / run_id / 'workspace'}; total spent this process: ${meter.spent_usd:.4f}")
