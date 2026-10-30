"""Translation between llmcore messages and OpenRouter's OpenAI-compatible chat completions format."""

from __future__ import annotations

import json
from typing import Any

from llmcore.types import Message, Response, StopReason, TextBlock, ToolResultBlock, ToolSpec, ToolUseBlock, Usage

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"

# Explicit cache breakpoints are honoured by these vendors; others cache prefixes automatically or not at all,
# and some upstreams reject unknown fields, so the marker is only sent where it means something.
_CACHE_CONTROL_PREFIXES = ("anthropic/", "google/gemini")

_FINISH: dict[str, StopReason] = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}


def supports_cache_control(model: str) -> bool:
    return model.startswith(_CACHE_CONTROL_PREFIXES)


def _text_part(block: TextBlock, cache: bool) -> dict[str, Any]:
    part: dict[str, Any] = {"type": "text", "text": block.text}
    if cache and block.cache:
        part["cache_control"] = {"type": "ephemeral"}
    return part


def to_wire(model: str, system: list[TextBlock], messages: list[Message]) -> list[dict[str, Any]]:
    """Messages in chat completions shape; tool results become separate `tool` role messages."""
    cache = supports_cache_control(model)
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": [_text_part(b, cache) for b in system]})
    for msg in messages:
        if msg.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": msg.text or None}
            calls = [
                {
                    "id": b.id,
                    "type": "function",
                    "function": {"name": b.name, "arguments": json.dumps(b.input, ensure_ascii=False)},
                }
                for b in msg.tool_uses
            ]
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        texts: list[dict[str, Any]] = []
        for block in msg.content:
            if isinstance(block, ToolResultBlock):
                content = f"ERROR: {block.content}" if block.is_error else block.content
                wire: str | list[dict[str, Any]] = content
                if cache and block.cache:
                    wire = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                out.append({"role": "tool", "tool_call_id": block.tool_use_id, "content": wire})
            elif isinstance(block, TextBlock):
                texts.append(_text_part(block, cache))
        if texts:
            out.append({"role": "user", "content": texts})
    return out


def tools_to_wire(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
        for t in tools
    ]


def usage_from(body: dict[str, Any]) -> Usage:
    usage = body.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    return Usage(
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        cache_read_tokens=int(prompt_details.get("cached_tokens") or 0),
        cache_write_tokens=int(prompt_details.get("cache_write_tokens") or 0),
        reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
    )


def from_wire(body: dict[str, Any], cost: float, latency: float, *, cached: bool) -> Response:
    choice = body["choices"][0]
    raw = choice.get("message") or {}
    blocks: list[TextBlock | ToolUseBlock | ToolResultBlock] = []
    text = raw.get("content") or ""
    if isinstance(text, list):  # some providers return content parts
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    if text:
        blocks.append(TextBlock(text=str(text)))
    for i, call in enumerate(raw.get("tool_calls") or []):
        fn = call.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        args: Any
        error = None
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        except json.JSONDecodeError as exc:
            args, error = {}, f"arguments are not valid JSON: {exc.msg}"
        if not isinstance(args, dict):
            args, error = {}, "arguments must be a JSON object"
        blocks.append(
            ToolUseBlock(id=call.get("id") or f"call_{i}", name=fn.get("name", ""), input=args, parse_error=error)
        )
    stop = _FINISH.get(choice.get("finish_reason") or "", "other")
    if any(isinstance(b, ToolUseBlock) for b in blocks):
        stop = "tool_use"  # some providers report "stop" even when they return tool calls
    return Response(
        message=Message(role="assistant", content=blocks),
        stop_reason=stop,
        model=str(body.get("model", "")),
        usage=usage_from(body),
        cost_usd=cost,
        latency_s=latency,
        cached=cached,
    )
