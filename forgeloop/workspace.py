"""Per-run copy of the target repo on its own branch. Hidden tests and secrets never enter it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

EXCLUDE = (".git", ".env", "hidden", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv")
GIT_IDENTITY = ["-c", "user.name=forgeloop", "-c", "user.email=forgeloop@localhost", "-c", "commit.gpgsign=false"]


def git(ws: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *GIT_IDENTITY, *args], cwd=ws, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return out.stdout


def prepare(source: Path, dest: Path, branch: str) -> Path:
    """Copy `source` into `dest`, commit it as the baseline on `main`, switch to `branch` for the agent's work."""
    if dest.exists():
        raise FileExistsError(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*EXCLUDE))
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "baseline")
    git(dest, "switch", "-q", "-c", branch)
    return dest


def commit_all(ws: Path, message: str) -> str | None:
    """Commit whatever the agent changed; None when there was nothing to commit."""
    git(ws, "add", "-A")
    if not git(ws, "status", "--porcelain").strip():
        return None
    git(ws, "commit", "-q", "-m", message)
    return git(ws, "rev-parse", "--short", "HEAD").strip()


def diff(ws: Path, base: str = "main") -> str:
    return git(ws, "diff", f"{base}...HEAD")
