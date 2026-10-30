"""Scoring by hidden tests: they are copied into a separate copy of the result, never into the agent's workspace."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from forgeloop.tools.sandbox import DockerSandbox

HIDDEN_DIR = "tests/hidden"


@dataclass(frozen=True)
class Grade:
    passed: bool
    output: str


async def grade(workspace: Path, hidden_tests: Path, *, timeout_s: int = 300) -> Grade:
    with tempfile.TemporaryDirectory(prefix="forgeloop-grade-") as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(workspace, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        shutil.copytree(hidden_tests, copy / HIDDEN_DIR, dirs_exist_ok=True)
        box = await DockerSandbox.start(copy)
        try:
            r = await box.exec(["pytest", "-q", "--tb=short", "-p", "no:cacheprovider", HIDDEN_DIR], timeout_s)
        finally:
            await box.close()
        return Grade(passed=r.exit_code == 0 and not r.timed_out, output=r.output)
