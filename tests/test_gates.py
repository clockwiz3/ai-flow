import asyncio
import json
from pathlib import Path

import httpx

from forgeloop import workspace
from forgeloop.gates.plan_gate import check_plan
from forgeloop.gates.test_gate import added_lines, check_dependencies, dependencies, run_bandit
from forgeloop.roles.planner import Plan
from forgeloop.tools import ExecResult, Workspace

DIFF = """\
diff --git a/app/x.py b/app/x.py
--- a/app/x.py
+++ b/app/x.py
@@ -3,0 +4,2 @@ def f():
+    a = 1
+    b = 2
@@ -10 +12 @@ def g():
-    old
+    new
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x
-y
"""


def test_added_lines_follow_hunk_headers() -> None:
    assert added_lines(DIFF) == {"app/x.py": {4, 5, 12}}


def test_dependencies_are_parsed_with_pins() -> None:
    pyproject = '[project]\ndependencies = ["FastAPI==0.115.0", "httpx>=0.27", "uvicorn[standard]==0.30.1"]\n'
    assert dependencies(pyproject) == {"fastapi": "0.115.0", "httpx": None, "uvicorn": "0.30.1"}


def _repo_with_deps(tmp_path: Path, before: list[str], after: list[str]) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "pyproject.toml").write_text(f"[project]\ndependencies = {json.dumps(before)}\n", encoding="utf-8")
    ws = workspace.prepare(src, tmp_path / "ws", "work")
    (ws / "pyproject.toml").write_text(f"[project]\ndependencies = {json.dumps(after)}\n", encoding="utf-8")
    workspace.commit_all(ws, "deps")
    return ws


def test_new_dependencies_must_be_pinned_and_clean(tmp_path: Path) -> None:
    ws = _repo_with_deps(tmp_path, ["fastapi==0.115.0"], ["fastapi==0.115.0", "requests", "pyyaml==5.3", "attrs==24.1"])
    asked: list[str] = []

    def osv(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        asked.append(body["package"]["name"])
        vulns = [{"id": "GHSA-8q59"}] if body["package"]["name"] == "pyyaml" else []
        return httpx.Response(200, json={"vulns": vulns})

    problems = asyncio.run(check_dependencies(ws, "main", transport=httpx.MockTransport(osv)))
    assert sorted(asked) == ["attrs", "pyyaml"]  # unchanged fastapi is not re-checked
    assert any("requests is added without a pinned version" in p for p in problems)
    assert any("pyyaml==5.3 has known vulnerabilities: GHSA-8q59" in p for p in problems)
    assert len(problems) == 2


def test_unreachable_vulnerability_database_fails_closed(tmp_path: Path) -> None:
    ws = _repo_with_deps(tmp_path, [], ["attrs==24.1"])

    def down(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    problems = asyncio.run(check_dependencies(ws, "main", transport=httpx.MockTransport(down)))
    assert problems and "could not be checked" in problems[0]


def test_bandit_reports_only_findings_on_added_lines(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "x.py").write_text("import subprocess\nsubprocess.call('ls', shell=True)\n", encoding="utf-8")
    ws = workspace.prepare(src, tmp_path / "ws", "work")
    with (ws / "app" / "x.py").open("a", encoding="utf-8") as f:
        f.write("eval(input())\n")
    workspace.commit_all(ws, "add eval")
    report = {
        "results": [
            {"filename": "app/x.py", "line_number": 2, "test_id": "B602", "issue_severity": "HIGH",
             "issue_text": "shell=True (pre-existing)"},
            {"filename": "app/x.py", "line_number": 3, "test_id": "B307", "issue_severity": "MEDIUM",
             "issue_text": "Use of eval"},
        ]
    }  # fmt: skip

    class BanditSandbox:
        async def exec(self, argv: list[str], timeout_s: float) -> ExecResult:
            assert argv[0] == "bandit" and "app/x.py" in argv
            return ExecResult(1, json.dumps(report))

        async def close(self) -> None:
            return None

    findings = asyncio.run(run_bandit(BanditSandbox(), ws, "main"))
    assert findings == ["app/x.py:3: [B307 MEDIUM] Use of eval"]


def test_plan_gate_checks_paths_against_the_repository(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("", encoding="utf-8")
    plan = Plan.model_validate(
        {
            "summary": "s",
            "files": [
                {"path": "app/a.py", "action": "modify", "why": "ok"},
                {"path": "app/a.py", "action": "modify", "why": "dup"},
                {"path": "app/new.py", "action": "create", "why": "ok"},
                {"path": "app/a.py", "action": "create", "why": "exists"},
                {"path": "../outside.py", "action": "create", "why": "escape"},
                {"path": ".git/config", "action": "modify", "why": "denied"},
            ],
            "checkpoints": [{"title": "t", "steps": ["s"], "done_when": "d"}],
            "acceptance": ["a"],
        }
    )
    gate = check_plan(plan, Workspace(tmp_path))
    assert not gate.passed
    text = gate.feedback
    assert "listed twice" in text and "already exists" in text and "escapes" in text and "denied" in text
    assert "app/new.py" not in text
