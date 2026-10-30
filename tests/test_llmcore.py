import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from llmcore import (
    BudgetExceeded,
    CacheMiss,
    CacheMode,
    LLMClient,
    LLMError,
    Message,
    Meter,
    Price,
    PriceTable,
    ResponseCache,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Tracer,
    Usage,
    parse_json,
)
from llmcore.openrouter import from_wire, to_wire

Handler = Any


def _body(text: str = "", cost: float | None = 0.001, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage: dict[str, Any] = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": 60},
    }
    if cost is not None:
        usage["cost"] = cost
    finish = "tool_calls" if tool_calls else "stop"
    return {"model": "vendor/m", "choices": [{"message": message, "finish_reason": finish}], "usage": usage}


def _client(tmp_path: Path, handler: Handler, mode: CacheMode = CacheMode.RECORD_MISSING, **kw: Any) -> LLMClient:
    return LLMClient(
        api_key="test",
        cache=ResponseCache(tmp_path / "c.sqlite"),
        mode=mode,
        transport=httpx.MockTransport(handler),
        **kw,
    )


async def _instant(_: float) -> None:
    return None


def test_parse_json_variants() -> None:
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_tool_conversation_round_trips_through_wire_format() -> None:
    messages = [
        Message.user("fix the bug", cache=True),
        Message(
            role="assistant",
            content=[TextBlock(text="looking"), ToolUseBlock(id="c1", name="read_file", input={"path": "a.py"})],
        ),
        Message(role="user", content=[ToolResultBlock(tool_use_id="c1", content="boom", is_error=True)]),
    ]
    wire = to_wire("anthropic/claude-x", [TextBlock(text="sys", cache=True)], messages)
    assert wire[0] == {
        "role": "system",
        "content": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
    }
    assert wire[2]["tool_calls"][0]["function"] == {"name": "read_file", "arguments": '{"path": "a.py"}'}
    assert wire[3] == {"role": "tool", "tool_call_id": "c1", "content": "ERROR: boom"}
    # vendors without explicit cache breakpoints never see the marker
    assert "cache_control" not in to_wire("qwen/q", [TextBlock(text="sys", cache=True)], [])[0]["content"][0]


def test_tool_calls_are_parsed_and_bad_arguments_flagged() -> None:
    body = _body(
        "",
        tool_calls=[
            {"id": "a", "function": {"name": "grep", "arguments": '{"pattern": "x"}'}},
            {"id": "b", "function": {"name": "grep", "arguments": "{not json"}},
        ],
    )
    r = from_wire(body, 0.0, 0.1, cached=False)
    assert r.stop_reason == "tool_use"
    good, bad = r.message.tool_uses
    assert good.input == {"pattern": "x"} and good.parse_error is None
    assert bad.input == {} and bad.parse_error is not None
    assert r.usage.cache_read_tokens == 60


def test_client_caches_replays_and_meters(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=_body("ok"))

    tools = [ToolSpec(name="t", description="d", input_schema={"type": "object"})]

    async def scenario() -> None:
        client = _client(tmp_path, handler)
        first = await client.create("m", [Message.user("hi")], system="s", tools=tools)
        second = await client.create("m", [Message.user("hi")], system="s", tools=tools)
        assert not first.cached and second.cached
        assert client.meter.spent_usd == pytest.approx(0.001)
        assert client.meter.saved_usd == pytest.approx(0.001)
        assert client.meter.usage.input_tokens == 100
        await client.create("m", [Message.user("hi")], system="s", tools=tools, variant=1)  # a fresh sample
        await client.aclose()

        offline = _client(tmp_path, handler, CacheMode.REPLAY)
        assert (await offline.create("m", [Message.user("hi")], system="s", tools=tools)).message.text == "ok"
        with pytest.raises(CacheMiss):
            await offline.create("m", [Message.user("something else")])
        await offline.aclose()

    asyncio.run(scenario())
    assert len(calls) == 2
    assert calls[0]["tools"][0]["function"]["name"] == "t"


def test_retries_transient_errors_then_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _instant)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "primary":
            return httpx.Response(503, text="overloaded")
        return httpx.Response(200, json=_body("from backup"))

    async def scenario() -> str:
        client = _client(tmp_path, handler, attempts=2)
        r = await client.create("primary", [Message.user("x")], fallback_models=["backup"])
        await client.aclose()
        return r.message.text

    assert asyncio.run(scenario()) == "from backup"
    assert seen == ["primary", "primary", "backup"]


def test_client_errors_are_not_retried(tmp_path: Path) -> None:
    seen: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(400, text="bad request")

    async def scenario() -> None:
        client = _client(tmp_path, handler)
        with pytest.raises(LLMError):
            await client.create("m", [Message.user("x")])
        await client.aclose()

    asyncio.run(scenario())
    assert seen == [1]


def test_budget_is_a_hard_stop(tmp_path: Path) -> None:
    async def scenario() -> None:
        client = _client(tmp_path, lambda _: httpx.Response(200, json=_body("ok", cost=0.5)), meter=Meter(1.0))
        await client.create("m", [Message.user("a")])
        await client.create("m", [Message.user("b")])
        with pytest.raises(BudgetExceeded):
            await client.create("m", [Message.user("c")])
        assert (await client.create("m", [Message.user("a")])).cached  # cached answers stay free and allowed
        await client.aclose()

    asyncio.run(scenario())


def test_cost_falls_back_to_price_table(tmp_path: Path) -> None:
    prices = PriceTable({"vendor/m": Price(prompt=1e-6, completion=2e-6, cache_read=1e-7)})

    async def scenario() -> float:
        client = _client(tmp_path, lambda _: httpx.Response(200, json=_body("ok", cost=None)), prices=prices)
        r = await client.create("m", [Message.user("a")])
        await client.aclose()
        return r.cost_usd

    # 40 fresh prompt tokens + 60 cache reads + 20 completion tokens
    assert asyncio.run(scenario()) == pytest.approx(40e-6 + 60e-7 + 40e-6)


def test_price_table_from_catalogue() -> None:
    table = PriceTable.from_catalogue(
        {"data": [{"id": "a/b", "pricing": {"prompt": "0.000001", "completion": "0.000002"}}, {"id": "x"}]}
    )
    price = table.get("a/b")
    assert price is not None and price.cost(Usage(input_tokens=10, output_tokens=5)) == pytest.approx(2e-5)
    assert table.get("x") is None


def test_llm_calls_nest_under_the_current_span(tmp_path: Path) -> None:
    tracer = Tracer(tmp_path / "t.sqlite")

    async def scenario() -> None:
        client = _client(tmp_path, lambda _: httpx.Response(200, json=_body("ok")), tracer=tracer)
        with tracer.span("agent", "implementer", run_id="r1"):
            await client.create("m", [Message.user("a")], name="step-1")
        await client.aclose()

    asyncio.run(scenario())
    spans = {s["name"]: s for s in tracer.spans("r1")}
    assert spans["step-1"]["parent_id"] == spans["implementer"]["id"]
    assert spans["step-1"]["attrs"]["cost_usd"] == pytest.approx(0.001)
    assert spans["step-1"]["attrs"]["cache_read_tokens"] == 60
