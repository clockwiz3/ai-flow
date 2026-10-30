"""File tools. They run on the host against the workspace copy; the path policy decides what is reachable."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from forgeloop.tools.base import Tool, ToolError, Workspace

_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", "node_modules"}
MAX_FILE_BYTES = 200_000


class ReadFileArgs(BaseModel):
    path: str = Field(description="Path relative to the repository root")
    start_line: int = Field(1, ge=1, description="First line to return (1-based)")
    end_line: int | None = Field(None, ge=1, description="Last line to return, inclusive; omit for end of file")


class ListDirArgs(BaseModel):
    path: str = Field(".", description="Directory relative to the repository root")
    depth: int = Field(2, ge=1, le=5, description="How many levels to descend")


class GrepArgs(BaseModel):
    pattern: str = Field(description="Python regular expression")
    path: str = Field(".", description="File or directory to search")
    glob: str = Field("*.py", description="File name pattern, e.g. *.py or *")
    max_results: int = Field(50, ge=1, le=200)


class WriteFileArgs(BaseModel):
    path: str
    content: str = Field(description="Full new content of the file")


class ApplyPatchArgs(BaseModel):
    path: str
    old: str = Field(description="Exact text to replace; must occur exactly once in the file")
    new: str = Field(description="Replacement text")


def _visible(ws: Workspace, rel: str, *, write: bool = False) -> bool:
    try:
        ws.resolve(rel, write=write)
    except ToolError:
        return False
    return True


def fs_tools(ws: Workspace) -> list[Tool]:
    async def read_file(a: ReadFileArgs) -> str:
        p = ws.resolve(a.path)
        if not p.is_file():
            raise ToolError(f"not a file: {a.path}")
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ToolError(f"file too large ({p.stat().st_size} bytes); read a line range or grep it")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        end = a.end_line or len(lines)
        width = len(str(end))
        body = "\n".join(f"{i:>{width}}| {line}" for i, line in enumerate(lines[a.start_line - 1 : end], a.start_line))
        return body or "(empty file)"

    async def list_dir(a: ListDirArgs) -> str:
        base = ws.resolve(a.path)
        if not base.is_dir():
            raise ToolError(f"not a directory: {a.path}")
        out: list[str] = []

        def walk(d: Path, level: int) -> None:
            for child in sorted(d.iterdir(), key=lambda c: (c.is_file(), c.name)):
                if child.name in _SKIP_DIRS or not _visible(ws, ws.rel(child)):
                    continue
                indent = "  " * level
                if child.is_dir():
                    out.append(f"{indent}{child.name}/")
                    if level + 1 < a.depth:
                        walk(child, level + 1)
                else:
                    out.append(f"{indent}{child.name}")

        walk(base, 0)
        return "\n".join(out) or "(empty directory)"

    async def grep(a: GrepArgs) -> str:
        try:
            rx = re.compile(a.pattern)
        except re.error as exc:
            raise ToolError(f"bad regex: {exc}") from exc
        base = ws.resolve(a.path)
        files = [base] if base.is_file() else sorted(base.rglob(a.glob))
        hits: list[str] = []
        for f in files:
            if not f.is_file() or any(part in _SKIP_DIRS for part in f.parts):
                continue
            rel = ws.rel(f.resolve()) if f.resolve().is_relative_to(ws.root) else None
            if rel is None or not _visible(ws, rel):
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{n}: {line.strip()[:200]}")
                    if len(hits) >= a.max_results:
                        return "\n".join(hits) + f"\n(stopped at {a.max_results} matches)"
        return "\n".join(hits) or "no matches"

    async def write_file(a: WriteFileArgs) -> str:
        p = ws.resolve(a.path, write=True)
        if p.is_dir():
            raise ToolError(f"is a directory: {a.path}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a.content, encoding="utf-8", newline="\n")
        return f"wrote {ws.rel(p)} ({len(a.content.splitlines())} lines)"

    async def apply_patch(a: ApplyPatchArgs) -> str:
        p = ws.resolve(a.path, write=True)
        if not p.is_file():
            raise ToolError(f"not a file: {a.path}; use write_file to create it")
        text = p.read_text(encoding="utf-8")
        count = text.count(a.old) if a.old else 0
        if count != 1:
            hint = "not found" if count == 0 else f"found {count} times; include more surrounding lines"
            raise ToolError(f"`old` must occur exactly once in {a.path}: {hint}")
        p.write_text(text.replace(a.old, a.new, 1), encoding="utf-8", newline="\n")
        return f"patched {ws.rel(p)}"

    return [
        Tool("read_file", "Read a text file with line numbers.", ReadFileArgs, read_file, read_only=True),
        Tool("list_dir", "List a directory tree.", ListDirArgs, list_dir, read_only=True),
        Tool("grep", "Search files for a regular expression.", GrepArgs, grep, read_only=True),
        Tool("write_file", "Create or overwrite a file with full content.", WriteFileArgs, write_file, read_only=False),
        Tool(
            "apply_patch",
            "Replace one exact, unique snippet in an existing file. Prefer this over write_file for edits.",
            ApplyPatchArgs,
            apply_patch,
            read_only=False,
        ),
    ]
