"""Deterministic checks of a plan before any money is spent on implementing it."""

from __future__ import annotations

from forgeloop.gates import GateResult
from forgeloop.roles.planner import Plan
from forgeloop.tools import ToolError, Workspace


def check_plan(plan: Plan, ws: Workspace) -> GateResult:
    problems: list[str] = []
    seen: set[str] = set()
    for change in plan.files:
        if change.path in seen:
            problems.append(f"{change.path}: listed twice")
        seen.add(change.path)
        try:
            target = ws.resolve(change.path, write=True)
        except ToolError as exc:
            problems.append(f"{change.path}: {exc}")
            continue
        if change.action == "modify" and not target.is_file():
            problems.append(f"{change.path}: marked modify but does not exist")
        if change.action == "create" and target.exists():
            problems.append(f"{change.path}: marked create but already exists")
    if problems:
        return GateResult(
            gate="plan",
            passed=False,
            summary=f"{len(problems)} problem(s) in the plan",
            feedback="\n".join(f"- {p}" for p in problems),
            data={"problems": problems},
        )
    return GateResult(
        gate="plan",
        passed=True,
        summary=f"{len(plan.files)} files, {len(plan.checkpoints)} checkpoints",
    )
