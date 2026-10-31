"""SQLite persistence of pipeline runs: the full state after every stage, plus an event log for the trace view.

The state is saved at every transition, so `forgeloop resume <run_id>` continues from the stage that was next.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

DEFAULT_PATH = Path("runs/forgeloop.sqlite")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunStore:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=60)
        self._db.execute("pragma journal_mode=wal")
        self._db.executescript(
            """
            create table if not exists runs (
                id text primary key, created_at text not null, updated_at text not null,
                task_id text not null, stage text not null, cost_usd real not null default 0, state text not null);
            create table if not exists events (
                run_id text not null, seq integer not null, ts text not null, stage text not null,
                kind text not null, data text not null, primary key (run_id, seq));
            """
        )
        self._db.commit()

    def save(self, run_id: str, task_id: str, stage: str, cost_usd: float, state: BaseModel) -> None:
        now = _now()
        with self._lock:
            self._db.execute(
                "insert into runs (id, created_at, updated_at, task_id, stage, cost_usd, state)"
                " values (?, ?, ?, ?, ?, ?, ?) on conflict(id) do update set updated_at = excluded.updated_at,"
                " stage = excluded.stage, cost_usd = excluded.cost_usd, state = excluded.state",
                (run_id, now, now, task_id, stage, cost_usd, state.model_dump_json()),
            )
            self._db.commit()

    def load(self, run_id: str) -> str:
        with self._lock:
            row = self._db.execute("select state from runs where id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"no run {run_id}")
        return str(row[0])

    def event(self, run_id: str, stage: str, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            seq = self._db.execute("select coalesce(max(seq), 0) + 1 from events where run_id = ?", (run_id,))
            self._db.execute(
                "insert into events (run_id, seq, ts, stage, kind, data) values (?, ?, ?, ?, ?, ?)",
                (run_id, seq.fetchone()[0], _now(), stage, kind, json.dumps(data, ensure_ascii=False, default=str)),
            )
            self._db.commit()

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "select seq, ts, stage, kind, data from events where run_id = ? order by seq", (run_id,)
            ).fetchall()
        return [{"seq": s, "ts": ts, "stage": st, "kind": k, "data": json.loads(d)} for s, ts, st, k, d in rows]

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "select id, updated_at, task_id, stage, cost_usd from runs order by updated_at desc limit ?", (limit,)
            ).fetchall()
        return [{"id": i, "updated_at": u, "task_id": t, "stage": s, "cost_usd": c} for i, u, t, s, c in rows]

    def close(self) -> None:
        self._db.close()
