"""Intake: a ticket from a markdown file or a GitHub issue becomes a `Task`."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Task(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,80}$")
    title: str
    body: str
    source: Literal["file", "github"]
    url: str | None = None

    @property
    def ticket(self) -> str:
        return f"# {self.title}\n\n{self.body.strip()}\n"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:60] or "task"


def from_markdown(path: Path, task_id: str | None = None) -> Task:
    text = path.read_text(encoding="utf-8")
    first, _, rest = text.lstrip().partition("\n")
    title = first.lstrip("# ").strip() if first.startswith("#") else path.stem
    body = rest if first.startswith("#") else text
    return Task(id=task_id or _slug(path.parent.name if path.name == "ticket.md" else path.stem), title=title,
                body=body, source="file")  # fmt: skip


def from_github(repo: str, number: int) -> Task:
    """Reads an issue through the GitHub CLI (uses the user's existing `gh` login)."""
    out = subprocess.run(
        ["gh", "issue", "view", str(number), "--repo", repo, "--json", "title,body,url"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    issue = json.loads(out.stdout)
    return Task(
        id=f"{_slug(repo.split('/')[-1])}-{number}",
        title=issue["title"],
        body=issue.get("body") or "",
        source="github",
        url=issue.get("url"),
    )
