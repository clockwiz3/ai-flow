from pathlib import Path

from forgeloop import workspace


def test_workspace_copy_has_no_hidden_tests_or_secrets(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "tests" / "hidden").mkdir(parents=True)
    (src / "tests" / "hidden" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
    (src / "tests" / "test_y.py").write_text("y = 1\n", encoding="utf-8")
    (src / ".env").write_text("OPENROUTER_API_KEY=sk\n", encoding="utf-8")

    ws = workspace.prepare(src, tmp_path / "ws", "forgeloop/t1")
    assert (ws / "tests" / "test_y.py").exists()
    assert not (ws / "tests" / "hidden").exists() and not (ws / ".env").exists()
    assert workspace.git(ws, "branch", "--show-current").strip() == "forgeloop/t1"

    assert workspace.commit_all(ws, "noop") is None
    (ws / "tests" / "test_y.py").write_text("y = 2\n", encoding="utf-8")
    assert workspace.commit_all(ws, "change") is not None
    assert "+y = 2" in workspace.diff(ws)
