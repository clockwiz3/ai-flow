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
