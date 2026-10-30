"""Model prices from OpenRouter's catalogue, cached on disk: used for estimates and when a response has no cost."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from llmcore.openrouter import MODELS_URL
from llmcore.types import Usage

DEFAULT_PATH = Path(".cache/prices.json")


@dataclass(frozen=True)
class Price:
    """USD per token."""

    prompt: float
    completion: float
    cache_read: float | None = None
    cache_write: float | None = None

    def cost(self, usage: Usage) -> float:
        cache_read = self.cache_read if self.cache_read is not None else self.prompt
        cache_write = self.cache_write if self.cache_write is not None else self.prompt
        fresh = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
        return (
            max(fresh, 0) * self.prompt
            + usage.cache_read_tokens * cache_read
            + usage.cache_write_tokens * cache_write
            + usage.output_tokens * self.completion
        )


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PriceTable:
    def __init__(self, prices: dict[str, Price]) -> None:
        self.prices = prices

    def get(self, model: str) -> Price | None:
        return self.prices.get(model)

    @classmethod
    def from_catalogue(cls, catalogue: dict[str, Any]) -> PriceTable:
        prices: dict[str, Price] = {}
        for item in catalogue.get("data", []):
            p = item.get("pricing") or {}
            prompt, completion = _num(p.get("prompt")), _num(p.get("completion"))
            if prompt is None or completion is None:
                continue
            prices[item["id"]] = Price(
                prompt=prompt,
                completion=completion,
                cache_read=_num(p.get("input_cache_read")),
                cache_write=_num(p.get("input_cache_write")),
            )
        return cls(prices)

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH, *, refresh: bool = False) -> PriceTable:
        """Read the cached catalogue, downloading it once (the catalogue endpoint needs no key)."""
        if refresh or not path.exists():
            body = httpx.get(MODELS_URL, timeout=60).raise_for_status().json()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(body), encoding="utf-8")
        return cls.from_catalogue(json.loads(path.read_text(encoding="utf-8")))
