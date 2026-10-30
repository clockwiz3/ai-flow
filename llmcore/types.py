"""Provider-neutral conversation model, shaped like the Messages API: content blocks, tool_use, tool_result.

Providers translate to and from their wire format; everything above llmcore only sees these types.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str
    cache: bool = False  # ask the provider to cache the prompt prefix ending at this block


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]
    parse_error: str | None = None  # the model emitted arguments that are not a JSON object


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


Block = Annotated[TextBlock | ToolUseBlock | ToolResultBlock, Field(discriminator="type")]


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[Block]

    @classmethod
    def user(cls, text: str, *, cache: bool = False) -> Message:
        return cls(role="user", content=[TextBlock(text=text, cache=cache)])

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    @property
    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


StopReason = Literal["end_turn", "tool_use", "max_tokens", "other"]


class Usage(BaseModel):
    input_tokens: int = 0  # all prompt tokens, including the cached ones
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(**{k: getattr(self, k) + getattr(other, k) for k in Usage.model_fields})


class Response(BaseModel):
    message: Message
    stop_reason: StopReason
    model: str
    usage: Usage
    cost_usd: float
    latency_s: float
    cached: bool = False  # served from the local response cache, cost was not paid again
