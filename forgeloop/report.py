"""Tables from eval records: pass@1, cost, iterations and escalations per configuration."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from forgeloop.eval import RunRecord

CONFIG_ORDER = ["baseline", "plan", "test-gate", "full"]


def _pct(xs: list[bool]) -> str:
    return f"{100 * mean(xs):.0f}%" if xs else "-"


def summary_table(records: list[RunRecord]) -> str:
    by_config: dict[str, list[RunRecord]] = defaultdict(list)
    for r in records:
        by_config[r.config].append(r)
    configs = sorted(by_config, key=lambda c: (CONFIG_ORDER.index(c) if c in CONFIG_ORDER else 99, c))
    lines = [
        "| config | runs | pass@1 (solvable) | ambiguous: escalated | wrong escalations | $ / run | steps | $ total |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in configs:
        rs = by_config[c]
        solvable = [r for r in rs if r.expected == "solve"]
        ambiguous = [r for r in rs if r.expected == "escalate"]
        total = sum(r.cost_usd for r in rs)
        lines.append(
            f"| {c} | {len(rs)} | {_pct([r.passed for r in solvable])} | {_pct([r.passed for r in ambiguous])} | "
            f"{_pct([r.status == 'escalated' for r in solvable])} | ${total / len(rs):.4f} | "
            f"{mean(r.steps for r in rs):.1f} | ${total:.3f} |"
        )
    return "\n".join(lines)


def per_task_table(records: list[RunRecord]) -> str:
    by_task: dict[str, dict[str, list[RunRecord]]] = defaultdict(lambda: defaultdict(list))
    meta: dict[str, RunRecord] = {}
    for r in records:
        by_task[r.task_id][r.config].append(r)
        meta[r.task_id] = r
    configs = sorted({r.config for r in records}, key=lambda c: CONFIG_ORDER.index(c) if c in CONFIG_ORDER else 99)
    lines = [
        "| task | kind | difficulty | " + " | ".join(configs) + " |",
        "| --- | --- | --- | " + " | ".join("---" for _ in configs) + " |",
    ]
    for task_id in sorted(by_task):
        m = meta[task_id]
        cells = []
        for c in configs:
            rs = by_task[task_id][c]
            if not rs:
                cells.append("-")
                continue
            failures = sorted({r.status for r in rs if not r.passed})
            cells.append(f"{sum(r.passed for r in rs)}/{len(rs)}" + (f" ({', '.join(failures)})" if failures else ""))
        tag = f" ({', '.join(m.tags)})" if m.tags else ""
        lines.append(f"| {task_id}{tag} | {m.kind} | {m.difficulty} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _gate_counts(r: RunRecord) -> dict[str, int]:
    """What each gate did in one run, read off the hidden-test timeline."""
    c = {"test_saves": 0, "review_saves": 0, "review_true_rc": 0, "review_false_rc": 0, "review_missed": 0,
         "review_broke": 0, "false_escalations": 0}  # fmt: skip
    tl = r.timeline
    first_review = next((i for i, cp in enumerate(tl) if cp.event.startswith("reviewed")), len(tl))
    implemented = next((cp.hidden_passed for cp in tl if cp.event == "implemented"), None)
    before_review = [cp.hidden_passed for cp in tl[:first_review] if cp.event in ("implemented", "test_fix")]
    if implemented is False and before_review and before_review[-1] is True and r.test_rounds:
        c["test_saves"] = 1
    for i, cp in enumerate(tl):
        if cp.event == "reviewed:request_changes":
            c["review_true_rc" if cp.hidden_passed is False else "review_false_rc"] += 1
            after = next((x.hidden_passed for x in tl[i + 1 :] if x.event == "review_fix"), None)
            if cp.hidden_passed is True and after is False:
                c["review_broke"] += 1
        elif cp.event == "reviewed:approve" and cp.hidden_passed is False:
            c["review_missed"] += 1
    at_first_review = tl[first_review].hidden_passed if first_review < len(tl) else None
    if at_first_review is False and r.passed and r.review_rounds:
        c["review_saves"] = 1
    if r.expected == "solve" and r.status == "escalated" and r.hidden_passed:
        c["false_escalations"] = 1
    return c


def gates_table(records: list[RunRecord]) -> str:
    """Per configuration: runs rescued by each gate, review accuracy, and escalations of already-correct work."""
    by_config: dict[str, list[RunRecord]] = defaultdict(list)
    for r in records:
        by_config[r.config].append(r)
    configs = sorted(by_config, key=lambda c: (CONFIG_ORDER.index(c) if c in CONFIG_ORDER else 99, c))
    lines = [
        "| config | test-gate saves | review saves | request_changes right / wrong | approved broken code |"
        " review broke working code | escalated working code | avg test rounds | avg review rounds |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in configs:
        rs = [r for r in by_config[c] if r.expected == "solve"]
        if not rs:
            continue
        totals: dict[str, int] = defaultdict(int)
        for r in rs:
            for k, v in _gate_counts(r).items():
                totals[k] += v
        lines.append(
            f"| {c} | {totals['test_saves']} | {totals['review_saves']} | "
            f"{totals['review_true_rc']} / {totals['review_false_rc']} | {totals['review_missed']} | "
            f"{totals['review_broke']} | {totals['false_escalations']} | "
            f"{mean(r.test_rounds for r in rs):.2f} | {mean(r.review_rounds for r in rs):.2f} |"
        )
    return "\n".join(lines)
