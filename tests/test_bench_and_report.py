from pathlib import Path
from typing import Any

import pytest

from forgeloop.bench import load_tasks
from forgeloop.eval import RunRecord
from forgeloop.report import per_task_table, summary_table


def _task(root: Path, task_id: str, **meta: str) -> None:
    d = root / task_id
    d.mkdir(parents=True)
    fields = {"id": task_id, "title": "t", "kind": "bug", "difficulty": "easy", **meta}
    (d / "meta.yaml").write_text("\n".join(f"{k}: {v}" for k, v in fields.items()), encoding="utf-8")
    (d / "ticket.md").write_text("Fix it", encoding="utf-8")


def test_load_tasks_filters_and_checks_ids(tmp_path: Path) -> None:
    _task(tmp_path, "bug-01")
    _task(tmp_path, "feat-01", kind="feature", expected="escalate")
    assert [t.id for t in load_tasks(tmp_path)] == ["bug-01", "feat-01"]
    (only,) = load_tasks(tmp_path, ["feat-01"])
    assert only.meta.expected == "escalate" and only.hidden is None and only.ticket == "Fix it"
    with pytest.raises(ValueError, match="unknown"):
        load_tasks(tmp_path, ["nope"])
    _task(tmp_path, "bad", id="other")
    with pytest.raises(ValueError, match="does not match"):
        load_tasks(tmp_path)


def _rec(task: str, config: str, passed: bool, **kw: Any) -> RunRecord:
    base: dict[str, Any] = dict(
        eval_id="e", task_id=task, kind="bug", difficulty="easy", expected="solve", tags=[], config=config,
        repeat=0, model="m", status="done", passed=passed, hidden_passed=passed, cost_usd=0.01, steps=5,
        input_tokens=1, cache_read_tokens=0, output_tokens=1, wall_s=1.0,
    )  # fmt: skip
    return RunRecord(**{**base, **kw})


def test_summary_separates_solvable_and_ambiguous() -> None:
    records = [
        _rec("a", "baseline", True),
        _rec("b", "baseline", False),
        _rec("c", "baseline", True, expected="escalate", status="escalated"),
        _rec("b", "full", True),
    ]
    table = summary_table(records)
    baseline_row = next(line for line in table.splitlines() if line.startswith("| baseline"))
    assert "| 3 | 50% | 100% | 0% |" in baseline_row
    assert table.index("| baseline") < table.index("| full")
    assert "| b | bug | easy | 0/1 (done) | 1/1 |" in per_task_table(records)
