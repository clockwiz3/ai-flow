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


def test_gate_contribution_is_read_from_the_hidden_test_timeline() -> None:
    from forgeloop.eval import Checkpoint
    from forgeloop.report import gates_table

    def tl(*events: tuple[str, bool]) -> list[Checkpoint]:
        return [Checkpoint(event=e, hidden_passed=p) for e, p in events]

    records = [
        # test gate turned a failing implementation into a passing one; reviewer approved
        _rec("a", "full", True, test_rounds=1, timeline=tl(("implemented", False), ("test_fix", True),
             ("reviewed:approve", True), ("final", True))),
        # reviewer caught a real defect and the fix made it pass
        _rec("b", "full", True, review_rounds=1, timeline=tl(("implemented", False),
             ("reviewed:request_changes", False), ("review_fix", True), ("reviewed:approve", True), ("final", True))),
        # reviewer complained about working code and the "fix" broke it; then approved the broken result
        _rec("c", "full", False, review_rounds=1, timeline=tl(("implemented", True),
             ("reviewed:request_changes", True), ("review_fix", False), ("reviewed:approve", False),
             ("final", False))),
        # working code escalated
        _rec("d", "full", False, status="escalated", hidden_passed=True, timeline=tl(("final", True))),
    ]  # fmt: skip
    row = gates_table(records).splitlines()[-1]
    assert row.startswith("| full | 1 | 1 | 1 / 1 | 1 | 1 | 1 |"), row
