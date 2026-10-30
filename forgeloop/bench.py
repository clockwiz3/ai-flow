"""Benchmark tasks: ticket, metadata, hidden tests, optional setup patch and a reference solution.

Layout of one task directory:
    ticket.md        what the agent gets
    meta.yaml        id, kind, difficulty, expected (solve | escalate), tags
    hidden/          hidden tests (never shown to the agent)
    setup.patch      optional: changes the starting state (e.g. plants an injection payload)
    reference.patch  a known-good solution; validation proves the hidden tests need it
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from forgeloop import workspace
from forgeloop.grading import grade
from forgeloop.tools.sandbox import DockerSandbox

BENCH = Path("bench")
REPO = BENCH / "bench-repo"
TASKS = BENCH / "tasks"


class TaskMeta(BaseModel):
    id: str
    title: str
    kind: Literal["bug", "feature", "refactor"]
    difficulty: Literal["easy", "medium", "hard"]
    expected: Literal["solve", "escalate"] = "solve"
    tags: list[str] = []


@dataclass(frozen=True)
class BenchTask:
    dir: Path
    meta: TaskMeta

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def ticket(self) -> str:
        return (self.dir / "ticket.md").read_text(encoding="utf-8")

    @property
    def hidden(self) -> Path | None:
        path = self.dir / "hidden"
        return path if path.is_dir() else None

    @property
    def setup(self) -> Path | None:
        path = self.dir / "setup.patch"
        return path if path.exists() else None

    @property
    def reference(self) -> Path | None:
        path = self.dir / "reference.patch"
        return path if path.exists() else None


def load_tasks(root: Path = TASKS, ids: list[str] | None = None) -> list[BenchTask]:
    tasks = []
    for meta_file in sorted(root.glob("*/meta.yaml")):
        meta = TaskMeta.model_validate(yaml.safe_load(meta_file.read_text(encoding="utf-8")))
        if meta.id != meta_file.parent.name:
            raise ValueError(f"{meta_file}: id {meta.id!r} does not match the directory name")
        if ids is None or meta.id in ids:
            tasks.append(BenchTask(meta_file.parent, meta))
    if ids:
        missing = set(ids) - {t.id for t in tasks}
        if missing:
            raise ValueError(f"unknown tasks: {sorted(missing)}")
    return tasks


@dataclass(frozen=True)
class Validation:
    task_id: str
    ok: bool
    problems: list[str]


async def _visible_ok(ws: Path) -> tuple[bool, str]:
    box = await DockerSandbox.start(ws)
    try:
        tests = await box.exec(["pytest", "-q", "-p", "no:cacheprovider"], 300)
        lint = await box.exec(["ruff", "check", "."], 60)
    finally:
        await box.close()
    return tests.exit_code == 0 and lint.exit_code == 0, tests.output[-1500:] + lint.output[-500:]


async def validate(task: BenchTask, repo: Path = REPO, *, repeats: int = 3) -> Validation:
    problems: list[str] = []
    if not task.ticket.strip():
        problems.append("empty ticket")
    if task.meta.expected == "escalate":
        return Validation(task.id, not problems, problems)
    if task.hidden is None or task.reference is None:
        return Validation(task.id, False, ["a solvable task needs hidden/ and reference.patch"])
    with tempfile.TemporaryDirectory(prefix="forgeloop-validate-") as tmp:
        ws = workspace.prepare(repo, Path(tmp) / "ws", "validate", setup=task.setup)
        before = await grade(ws, task.hidden)
        if before.passed:
            problems.append("hidden tests already pass without the fix")
        try:
            workspace.apply_patch(ws, task.reference)
        except Exception as exc:
            return Validation(task.id, False, [*problems, f"reference.patch does not apply: {exc}"])
        for i in range(repeats):
            after = await grade(ws, task.hidden)
            if not after.passed:
                problems.append(f"hidden tests fail with the reference (run {i + 1}):\n{after.output[-1500:]}")
                break
        ok, output = await _visible_ok(ws)
        if not ok:
            problems.append(f"visible tests or ruff fail with the reference:\n{output}")
    return Validation(task.id, not problems, problems)


async def validate_all(tasks: list[BenchTask], concurrency: int = 4) -> list[Validation]:
    sem = asyncio.Semaphore(concurrency)

    async def one(t: BenchTask) -> Validation:
        async with sem:
            return await validate(t)

    return list(await asyncio.gather(*(one(t) for t in tasks)))
