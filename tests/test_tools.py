import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from forgeloop.tools import ExecResult, Toolbox, ToolError, Workspace, default_toolbox, truncate
from forgeloop.tools.exec import check_argv


class RecordingSandbox:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def exec(self, argv: list[str], timeout_s: float) -> ExecResult:
        self.calls.append(argv)
        return ExecResult(0, "1 passed")

    async def close(self) -> None:
        return None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "tests" / "hidden").mkdir(parents=True)
    (root / "tests" / "hidden" / "test_secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (root / ".env").write_text("OPENROUTER_API_KEY=sk-real\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("host secret", encoding="utf-8")
    return root


def _box(repo: Path) -> tuple[Toolbox, RecordingSandbox]:
    sandbox = RecordingSandbox()
    return default_toolbox(Workspace(repo), sandbox), sandbox


def call(box: Toolbox, name: str, **args: Any) -> tuple[str, bool]:
    return asyncio.run(box.call(name, args))


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", "app/../../outside.txt", "/etc/passwd", "C:/Windows/win.ini", "C:\\Windows\\win.ini"],
)
def test_paths_cannot_escape_the_workspace(repo: Path, path: str) -> None:
    box, _ = _box(repo)
    out, is_error = call(box, "read_file", path=path)
    assert is_error and "host secret" not in out


@pytest.mark.parametrize("path", [".git/HEAD", "tests/hidden/test_secret.py", "TESTS/Hidden/test_secret.py", ".env"])
def test_denied_areas_are_unreadable(repo: Path, path: str) -> None:
    box, _ = _box(repo)
    out, is_error = call(box, "read_file", path=path)
    assert is_error and "denied" in out


@pytest.mark.parametrize("path", [".git/config", "tests/hidden/test_new.py", ".github/workflows/x.yml"])
def test_denied_areas_are_unwritable(repo: Path, path: str) -> None:
    box, _ = _box(repo)
    _, is_error = call(box, "write_file", path=path, content="x")
    assert is_error and not (repo / path).exists()


def test_symlink_out_of_the_workspace_is_refused(repo: Path) -> None:
    link = repo / "app" / "link.txt"
    try:
        os.symlink(repo.parent / "outside.txt", link)
    except OSError:
        pytest.skip("symlinks need extra privileges on this OS")
    box, _ = _box(repo)
    out, is_error = call(box, "read_file", path="app/link.txt")
    assert is_error and "host secret" not in out


def test_listing_and_grep_hide_denied_areas(repo: Path) -> None:
    box, _ = _box(repo)
    listing, _ = call(box, "list_dir", path=".", depth=3)
    assert "main.py" in listing and "hidden" not in listing and ".env" not in listing and ".git" not in listing
    hits, _ = call(box, "grep", pattern="SECRET|return", glob="*")
    assert "app/main.py:2" in hits and "SECRET" not in hits and "sk-real" not in hits


def test_apply_patch_requires_a_unique_match(repo: Path) -> None:
    box, _ = _box(repo)
    out, is_error = call(box, "apply_patch", path="app/main.py", old="return a - b", new="return a + b")
    assert not is_error, out
    assert "a + b" in (repo / "app" / "main.py").read_text(encoding="utf-8")
    _, is_error = call(box, "apply_patch", path="app/main.py", old="nothing like this", new="x")
    assert is_error


def test_read_file_line_range(repo: Path) -> None:
    box, _ = _box(repo)
    out, _ = call(box, "read_file", path="app/main.py", start_line=2)
    assert out == "2|     return a - b"


def test_bad_arguments_come_back_as_errors(repo: Path) -> None:
    box, _ = _box(repo)
    out, is_error = call(box, "read_file", wrong="x")
    assert is_error and "invalid arguments" in out
    out, is_error = call(box, "rm_rf")
    assert is_error and "unknown tool" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["bash", "-c", "ls"],
        ["curl", "http://example.com"],
        ["pytest", "tests;", "rm", "-rf", "/"],
        ["pytest", "$(cat .env)"],
        ["python", "-c", "import os"],
        ["pytest", "tests/hidden"],
        ["pytest", "../other"],
        ["ruff", "check", "--config=/etc/x.toml"],
    ],
)
def test_commands_outside_the_allowlist_are_refused(repo: Path, argv: list[str]) -> None:
    with pytest.raises(ToolError):
        check_argv(argv, Workspace(repo))


def test_run_tests_goes_through_the_sandbox(repo: Path) -> None:
    box, sandbox = _box(repo)
    out, is_error = call(box, "run_tests", path="tests", keyword="add")
    assert not is_error and "[tests passed]" in out
    assert sandbox.calls == [["pytest", "-q", "--tb=short", "-p", "no:cacheprovider", "tests", "-k", "add"]]


def test_read_only_subset_has_no_writers(repo: Path) -> None:
    box, _ = _box(repo)
    assert set(box.subset(read_only=True).tools) == {"read_file", "list_dir", "grep"}


def test_truncate_keeps_head_and_tail() -> None:
    text = "HEAD" + "x" * 1000 + "TAIL"
    out = truncate(text, 100)
    assert out.startswith("HEAD") and out.endswith("TAIL") and "truncated" in out
