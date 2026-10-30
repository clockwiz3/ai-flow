"""Shared model access: OpenRouter client, response cache, prices, token and cost accounting, tracing.

Extracted from MenuBench (github.com/clockwiz3/menubench) and extended with multi-turn tool use.
"""

from __future__ import annotations

import json
import re
from typing import Any

from llmcore.cache import CacheMiss, CacheMode, ResponseCache
from llmcore.client import BudgetExceeded, LLMClient, LLMError, Meter, load_dotenv
from llmcore.pricing import Price, PriceTable
from llmcore.trace import Span, Tracer, current_span
from llmcore.types import (
    Message,
    Response,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Usage,
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json(text: str) -> Any:
    """Models wrap JSON in fences or prose; take the fenced block or the outermost object/array."""
    m = _FENCE.search(text)
    candidate = (m.group(1) if m else text).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON found in model output")
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    return json.loads(candidate[min(starts) : end + 1])


__all__ = [
    "BudgetExceeded",
    "CacheMiss",
    "CacheMode",
    "LLMClient",
    "LLMError",
    "Message",
    "Meter",
    "Price",
    "PriceTable",
    "Response",
    "ResponseCache",
    "Span",
    "StopReason",
    "TextBlock",
    "ToolResultBlock",
    "ToolSpec",
    "ToolUseBlock",
    "Tracer",
    "Usage",
    "current_span",
    "load_dotenv",
    "parse_json",
]
