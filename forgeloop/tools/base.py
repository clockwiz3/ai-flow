"""Tool plumbing: typed arguments, a registry the agent loop dispatches through, and the path policy.

Every restriction lives here, in code. Prompts may describe the rules, but nothing depends on the model obeying them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError

from llmcore import ToolSpec

MAX_OUTPUT_CHARS = 20_000


class ToolError(Exception):
    """A failure the agent should see and can react to (bad path, denied write, failed command)."""


@dataclass(frozen=True)
class PathPolicy:
    """Workspace-relative prefixes the agent may not read or write. Compared case-insensitively."""

    read_deny: tuple[str, ...] = (".git", "tests/hidden", ".env")
    write_deny: tuple[str, ...] = (".git", "tests/hidden", ".env", ".github")

    @staticmethod
    def _matches(rel: PurePosixPath, prefixes: tuple[str, ...]) -> bool:
        parts = [p.lower() for p in rel.parts]
        for prefix in prefixes:
            pre = [p.lower() for p in PurePosixPath(prefix).parts]
            if parts[: len(pre)] == pre:
                return True
        return False


@dataclass
class Workspace:
    root: Path
    policy: PathPolicy = field(default_factory=PathPolicy)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()

    def resolve(self, path: str, *, write: bool = False) -> Path:
        """Workspace path for an agent-supplied one. Symlinks are resolved before the containment check."""
        raw = path.strip().replace("\\", "/")
        if not raw or raw == ".":
            raw = "."
        candidate = PurePosixPath(raw)
        if candidate.is_absolute() or (len(raw) > 1 and raw[1] == ":"):
            raise ToolError(f"absolute paths are not allowed: {path!r}; use a path relative to the repo root")
        target = (self.root / candidate).resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise ToolError(f"path escapes the repository: {path!r}")
        rel = PurePosixPath(target.relative_to(self.root).as_posix())
        if self.policy._matches(rel, self.policy.read_deny):
            raise ToolError(f"access denied: {rel}")
        if write and self.policy._matches(rel, self.policy.write_deny):
            raise ToolError(f"write denied: {rel}")
        return target

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


Handler = Callable[[Any], Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler
    read_only: bool

    @property
    def spec(self) -> ToolSpec:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, input_schema=schema)


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Keep head and tail: errors tend to be at the end, context at the start."""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]}\n... [{len(text) - limit} chars truncated] ...\n{text[-tail:]}"


class Toolbox:
    def __init__(self, tools: list[Tool]) -> None:
        self.tools = {t.name: t for t in tools}

    def subset(self, *, read_only: bool) -> Toolbox:
        return Toolbox([t for t in self.tools.values() if t.read_only or not read_only])

    @property
    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self.tools.values()]

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """(output, is_error). Never raises for agent mistakes: they come back as error results."""
        tool = self.tools.get(name)
        if tool is None:
            return f"unknown tool {name!r}; available: {', '.join(self.tools)}", True
        try:
            args = tool.args.model_validate(arguments)
        except ValidationError as exc:
            return f"invalid arguments for {name}: {exc.errors(include_url=False)}", True
        try:
            return truncate(await tool.handler(args)), False
        except ToolError as exc:
            return str(exc), True
