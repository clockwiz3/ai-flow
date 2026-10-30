"""Model client: retries with backoff, fallback models, a hard $ budget, the response cache and tracing."""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from llmcore import openrouter
from llmcore.cache import CacheMiss, CacheMode, ResponseCache, cache_key
from llmcore.pricing import PriceTable
from llmcore.trace import Tracer
from llmcore.types import Message, Response, TextBlock, ToolSpec, Usage


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    pass


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


@dataclass
class Meter:
    """Spend and tokens of everything that went through one client. `limit_usd` is a hard stop."""

    limit_usd: float | None = None
    spent_usd: float = 0.0
    saved_usd: float = 0.0  # cost of responses served from the local cache
    calls: int = 0
    cached_calls: int = 0
    usage: Usage = field(default_factory=Usage)

    def add(self, response: Response) -> None:
        self.calls += 1
        if response.cached:
            self.cached_calls += 1
            self.saved_usd += response.cost_usd
            return
        self.spent_usd += response.cost_usd
        self.usage = self.usage + response.usage

    def check(self) -> None:
        if self.limit_usd is not None and self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(f"budget of ${self.limit_usd:.2f} exhausted (spent ${self.spent_usd:.4f})")


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        cache: ResponseCache | None = None,
        mode: CacheMode = CacheMode.RECORD_MISSING,
        meter: Meter | None = None,
        tracer: Tracer | None = None,
        prices: PriceTable | None = None,
        concurrency: int = 8,
        timeout_s: float = 180.0,
        attempts: int = 6,
        transport: httpx.AsyncBaseTransport | None = None,
        app_name: str = "ForgeLoop",
    ) -> None:
        self._key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self.cache = cache
        self.mode = mode
        self.meter = meter or Meter()
        self.tracer = tracer
        self.prices = prices
        self.attempts = attempts
        self._app_name = app_name
        self._sem = asyncio.Semaphore(concurrency)
        self._http = httpx.AsyncClient(timeout=timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create(
        self,
        model: str,
        messages: list[Message],
        *,
        system: str | list[TextBlock] | None = None,
        tools: list[ToolSpec] | None = None,
        fallback_models: list[str] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        variant: int = 0,  # separate cache entries for repeated sampling of the same conversation
        name: str = "llm",
    ) -> Response:
        system_blocks = [TextBlock(text=system)] if isinstance(system, str) else list(system or [])
        tools = tools or []
        key = cache_key(
            {
                "model": model,
                "fallback": fallback_models or [],
                "system": [b.model_dump() for b in system_blocks],
                "messages": [m.model_dump() for m in messages],
                "tools": [t.model_dump() for t in tools],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "variant": variant,
            }
        )
        if self.cache and self.mode is not CacheMode.LIVE:
            hit = self.cache.get(key)
            if hit is not None:
                body, cost, latency = hit
                response = openrouter.from_wire(body, cost, latency, cached=True)
                self._account(response, name)
                return response
            if self.mode is CacheMode.REPLAY:
                raise CacheMiss(f"no cached response for {model} ({name})")

        self.meter.check()
        errors: list[str] = []
        for candidate in [model, *(fallback_models or [])]:
            payload: dict[str, Any] = {
                "model": candidate,
                "messages": openrouter.to_wire(candidate, system_blocks, messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "usage": {"include": True},
            }
            if tools:
                payload["tools"] = openrouter.tools_to_wire(tools)
            try:
                body, latency = await self._post(payload)
            except BudgetExceeded:
                raise
            except LLMError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            response = openrouter.from_wire(body, 0.0, latency, cached=False)
            cost = self._cost(body, response)
            response.cost_usd = cost
            if self.cache:
                self.cache.put(key, response.model or candidate, body, cost, latency)
            self._account(response, name)
            return response
        raise LLMError("all models failed: " + " | ".join(errors))

    def _cost(self, body: dict[str, Any], response: Response) -> float:
        reported = (body.get("usage") or {}).get("cost")
        if reported is not None:
            return float(reported)
        price = self.prices.get(response.model) if self.prices else None
        return price.cost(response.usage) if price else 0.0

    def _account(self, response: Response, name: str) -> None:
        self.meter.add(response)
        if self.tracer:
            self.tracer.event(
                "llm",
                name,
                duration_s=0.0 if response.cached else response.latency_s,
                model=response.model,
                cached=response.cached,
                cost_usd=response.cost_usd,
                stop_reason=response.stop_reason,
                **response.usage.model_dump(),
            )

    async def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        if not self._key:
            raise LLMError("OPENROUTER_API_KEY is not set (put it into .env)")
        headers = {"Authorization": f"Bearer {self._key}", "X-Title": self._app_name}
        delay = 2.0
        last = ""
        for attempt in range(self.attempts):
            wait = delay
            async with self._sem:
                started = time.perf_counter()
                try:
                    r = await self._http.post(openrouter.API_URL, json=payload, headers=headers)
                except httpx.TransportError as exc:
                    last = f"transport: {exc!r}"
                else:
                    latency = time.perf_counter() - started
                    if r.status_code == 200:
                        body: dict[str, Any] = r.json()
                        if "error" in body:
                            last = f"provider error: {body['error']}"
                        elif body.get("choices"):
                            return body, latency
                        else:
                            last = "empty choices"
                    elif r.status_code in (408, 429) or r.status_code >= 500:
                        last = f"HTTP {r.status_code}: {r.text[:300]}"
                        retry_after = r.headers.get("retry-after", "")
                        if retry_after.replace(".", "", 1).isdigit():
                            wait = max(wait, float(retry_after))
                    else:
                        raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
            if attempt < self.attempts - 1:
                # Jitter spreads retries of concurrent calls hitting the same upstream limit.
                await asyncio.sleep(wait * (0.75 + random.random() / 2))
                delay = min(delay * 2, 60.0)
        raise LLMError(f"giving up after {self.attempts} attempts: {last}")
