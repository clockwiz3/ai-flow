"""Command tools. Arguments are argv lists, never shell strings, and the program must be on the allowlist."""

from __future__ import annotations

from pydantic import BaseModel, Field

from forgeloop.tools.base import Tool, ToolError, Workspace
from forgeloop.tools.sandbox import Sandbox

ALLOWED_PROGRAMS = frozenset({"pytest", "python", "ruff"})
_SHELL_CHARS = set(";|&<>`$\n")


class RunCmdArgs(BaseModel):
    argv: list[str] = Field(
        min_length=1,
        description=f"Program and arguments, e.g. ['ruff', 'check', 'app']. Allowed: {sorted(ALLOWED_PROGRAMS)}",
    )
    timeout_s: int = Field(60, ge=1, le=300)


class RunTestsArgs(BaseModel):
    path: str = Field("tests", description="Test file, directory or node id")
    keyword: str | None = Field(None, description="pytest -k expression")


def check_argv(argv: list[str], ws: Workspace) -> list[str]:
    program = argv[0]
    if program not in ALLOWED_PROGRAMS:
        raise ToolError(f"program {program!r} is not allowed; allowed: {sorted(ALLOWED_PROGRAMS)}")
    for arg in argv:
        if _SHELL_CHARS & set(arg):
            raise ToolError("shell syntax is not supported: pass one program with plain arguments")
    if program == "python" and len(argv) > 1 and argv[1] == "-c":
        raise ToolError("python -c is not allowed; write a file and run it, or use pytest")
    for arg in argv[1:]:
        # Anything that looks like a path must stay inside the workspace and outside denied areas.
        if "/" in arg or "\\" in arg or arg.startswith("."):
            ws.resolve(arg.split("::", 1)[0].split("=", 1)[-1])
    return argv


def exec_tools(ws: Workspace, sandbox: Sandbox, *, test_timeout_s: int = 180) -> list[Tool]:
    async def run_cmd(a: RunCmdArgs) -> str:
        argv = check_argv(a.argv, ws)
        r = await sandbox.exec(argv, a.timeout_s)
        status = "timed out" if r.timed_out else f"exit code {r.exit_code}"
        return f"$ {' '.join(argv)}\n{r.output}\n[{status}]"

    async def run_tests(a: RunTestsArgs) -> str:
        argv = ["pytest", "-q", "--tb=short", "-p", "no:cacheprovider", a.path]
        if a.keyword:
            argv += ["-k", a.keyword]
        check_argv(argv, ws)
        r = await sandbox.exec(argv, test_timeout_s)
        status = "timed out" if r.timed_out else ("passed" if r.exit_code == 0 else f"failed (exit {r.exit_code})")
        return f"{r.output}\n[tests {status}]"

    return [
        Tool("run_tests", "Run pytest in the sandbox.", RunTestsArgs, run_tests, read_only=False),
        Tool("run_cmd", "Run an allowed program in the sandbox (no network).", RunCmdArgs, run_cmd, read_only=False),
    ]
