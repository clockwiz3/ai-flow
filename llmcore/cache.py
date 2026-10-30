"""Local cache of model responses: every experiment can be replayed offline at zero cost."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from enum import StrEnum
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(".cache/llm.sqlite")


class CacheMode(StrEnum):
    RECORD_MISSING = "record-missing"  # reuse what is cached, call the API for the rest
    REPLAY = "replay"  # cache only; a miss is an error (offline, free, reproducible)
    LIVE = "live"  # always call the API and overwrite the cache


class CacheMiss(LookupError):
    pass


def cache_key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ResponseCache:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=60)
        self._db.execute("pragma journal_mode=wal")
        self._db.execute(
            """create table if not exists responses (
                key text primary key, model text, response text, cost_usd real, latency_s real,
                created_at text default current_timestamp)"""
        )
        self._db.commit()

    def get(self, key: str) -> tuple[dict[str, Any], float, float] | None:
        with self._lock:
            row = self._db.execute(
                "select response, cost_usd, latency_s from responses where key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0]), float(row[1]), float(row[2])

    def put(self, key: str, model: str, response: dict[str, Any], cost_usd: float, latency_s: float) -> None:
        with self._lock:
            self._db.execute(
                "insert or replace into responses (key, model, response, cost_usd, latency_s) values (?, ?, ?, ?, ?)",
                (key, model, json.dumps(response, ensure_ascii=False), cost_usd, latency_s),
            )
            self._db.commit()

    def close(self) -> None:
        self._db.close()
