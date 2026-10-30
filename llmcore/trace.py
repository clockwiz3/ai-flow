"""Spans in SQLite: what ran, inside what, how long, with which tokens and cost.

The current span lives in a context variable, so model calls made anywhere below an agent step nest under it
without passing a tracer around.
"""

from __future__ import annotations

import contextvars
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """create table if not exists spans (
    id text primary key,
    parent_id text,
    run_id text,
    kind text not null,
    name text not null,
    started_at text not null,
    duration_s real,
    status text,
    attrs text not null default '{}')"""


@dataclass
class Span:
    id: str
    run_id: str | None
    kind: str
    name: str
    attrs: dict[str, Any] = field(default_factory=dict)

    def set(self, **attrs: Any) -> None:
        self.attrs.update(attrs)


_current: contextvars.ContextVar[Span | None] = contextvars.ContextVar("llmcore_span", default=None)


def current_span() -> Span | None:
    return _current.get()


class Tracer:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=60)
        self._db.execute("pragma journal_mode=wal")
        self._db.execute(SCHEMA)
        self._db.execute("create index if not exists spans_run on spans (run_id)")
        self._db.commit()

    @contextmanager
    def span(self, kind: str, name: str, *, run_id: str | None = None, **attrs: Any) -> Iterator[Span]:
        parent = _current.get()
        span = Span(
            id=uuid.uuid4().hex,
            run_id=run_id or (parent.run_id if parent else None),
            kind=kind,
            name=name,
            attrs=dict(attrs),
        )
        started_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()
        token = _current.set(span)
        status = "ok"
        try:
            yield span
        except BaseException as exc:
            status = f"error: {type(exc).__name__}: {exc}"[:500]
            raise
        finally:
            _current.reset(token)
            self._write(span, parent.id if parent else None, started_at, time.perf_counter() - started, status)

    def event(self, kind: str, name: str, duration_s: float = 0.0, **attrs: Any) -> None:
        """A finished span recorded in one go, for example a model call."""
        parent = _current.get()
        span = Span(uuid.uuid4().hex, parent.run_id if parent else None, kind, name, dict(attrs))
        self._write(span, parent.id if parent else None, datetime.now(UTC).isoformat(), duration_s, "ok")

    def _write(self, span: Span, parent_id: str | None, started_at: str, duration: float, status: str) -> None:
        with self._lock:
            self._db.execute(
                "insert into spans (id, parent_id, run_id, kind, name, started_at, duration_s, status, attrs)"
                " values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    span.id,
                    parent_id,
                    span.run_id,
                    span.kind,
                    span.name,
                    started_at,
                    duration,
                    status,
                    json.dumps(span.attrs, ensure_ascii=False, default=str),
                ),
            )
            self._db.commit()

    def spans(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "select id, parent_id, kind, name, started_at, duration_s, status, attrs from spans"
                " where run_id = ? order by started_at",
                (run_id,),
            ).fetchall()
        keys = ("id", "parent_id", "kind", "name", "started_at", "duration_s", "status", "attrs")
        return [{**dict(zip(keys, r, strict=True)), "attrs": json.loads(r[7])} for r in rows]

    def close(self) -> None:
        self._db.close()
