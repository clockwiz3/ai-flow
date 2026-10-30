"""The tool-use loop: model turn -> tool calls -> results -> next turn, under hard budgets.

Hand-written on purpose: every guard here (budgets, loop detection, context compaction, caching breakpoints)
is something an agent SDK would hide, and something the eval needs to see and count.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from forgeloop.tools import Toolbox, truncate
from llmcore import (
    BudgetExceeded,
    LLMClient,
    LLMError,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Tracer,
    Usage,
)

Status = Literal["done", "escalated", "max_steps", "max_tokens", "max_usd", "loop", "error"]

ASK_HUMAN = "ask_human"
LOOP_HINT = (
    "You have made the same tool call {n} times in a row with identical arguments and got the same result. "
    "It will not change. Try a different approach, or finish if the work is done."
)
COMPACT_PROMPT = (
    "Summarise the work so far for yourself, to continue it without the full history. Keep: files read and what "
    "matters in them, changes made (file and what changed), commands run and their outcome, open problems. "
    "Plain text, at most 300 words."
)


class AskHumanArgs(BaseModel):
    question: str = Field(description="What is unclear and what you need decided. Ask only when truly blocked.")


ASK_HUMAN_SPEC = ToolSpec(
    name=ASK_HUMAN,
    description="Stop and escalate to a human when the ticket is ambiguous or contradictory. Do not guess instead.",
    input_schema={k: v for k, v in AskHumanArgs.model_json_schema().items() if k != "title"},
)


@dataclass
class AgentConfig:
    model: str
    system: str
    fallback_models: list[str] = field(default_factory=list)
    max_steps: int = 30
    max_tokens: int = 400_000  # prompt + completion over the whole run
    max_usd: float = 0.50
    max_output_tokens: int = 4096
    temperature: float = 0.0
    variant: int = 0
    tool_result_chars: int = 8_000
    context_tokens: int = 48_000  # compact history above this estimated prompt size
    keep_recent: int = 6  # messages kept verbatim when compacting
    loop_hint_after: int = 3
    allow_escalation: bool = True


@dataclass
class AgentResult:
    status: Status
    final_text: str
    steps: int
    usage: Usage
    cost_usd: float
    messages: list[Message]
    question: str | None = None
    error: str | None = None
    compactions: int = 0
    loop_hints: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "done"


def estimate_tokens(messages: list[Message]) -> int:
    """Rough size of the conversation (4 chars per token); good enough to decide when to compact."""
    return sum(len(json.dumps(m.model_dump(), ensure_ascii=False)) for m in messages) // 4


class AgentLoop:
    def __init__(self, client: LLMClient, toolbox: Toolbox, config: AgentConfig, *, tracer: Tracer | None = None):
        self.client = client
        self.toolbox = toolbox
        self.config = config
        self.tracer = tracer

    async def run(self, task: str, *, context: str | None = None, name: str = "agent") -> AgentResult:
        """`context` (e.g. the plan) is stable across turns and goes into the cached prefix with the system prompt."""
        if self.tracer:
            with self.tracer.span("agent", name, model=self.config.model) as span:
                result = await self._run(task, context, name)
                span.set(status=result.status, steps=result.steps, cost_usd=result.cost_usd)
                return result
        return await self._run(task, context, name)

    async def _run(self, task: str, context: str | None, name: str) -> AgentResult:
        cfg = self.config
        system = [TextBlock(text=cfg.system, cache=context is None)]
        if context:
            system.append(TextBlock(text=context, cache=True))
        specs = self.toolbox.specs + ([ASK_HUMAN_SPEC] if cfg.allow_escalation else [])
        messages: list[Message] = [Message.user(task)]
        usage, cost = Usage(), 0.0
        last_call: str | None = None
        repeats = 0
        result = AgentResult("error", "", 0, usage, cost, messages)

        def finish(status: Status, **kw: object) -> AgentResult:
            result.status, result.usage, result.cost_usd = status, usage, cost
            for k, v in kw.items():
                setattr(result, k, v)
            return result

        for step in range(1, cfg.max_steps + 1):
            result.steps = step
            if usage.input_tokens + usage.output_tokens >= cfg.max_tokens:
                return finish("max_tokens")
            if cost >= cfg.max_usd:
                return finish("max_usd")
            if estimate_tokens(messages) > cfg.context_tokens:
                try:
                    messages, extra_usage, extra_cost = await self._compact(system, messages, name)
                except BudgetExceeded:
                    raise
                except LLMError as exc:
                    return finish("error", error=f"compaction failed: {exc}")
                usage, cost = usage + extra_usage, cost + extra_cost
                result.messages = messages
                result.compactions += 1
            try:
                response = await self.client.create(
                    cfg.model,
                    messages,
                    system=system,
                    tools=specs,
                    fallback_models=cfg.fallback_models,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_output_tokens,
                    variant=cfg.variant,
                    name=f"{name}.step{step}",
                )
            except BudgetExceeded:
                raise  # the client-wide budget: stop everything, this is not the agent's failure
            except LLMError as exc:
                return finish("error", error=str(exc))
            usage, cost = usage + response.usage, cost + response.cost_usd
            reply = response.message
            if not reply.content:
                reply = Message(role="assistant", content=[TextBlock(text="(empty reply)")])
            messages.append(reply)

            calls = reply.tool_uses
            if not calls:
                if response.stop_reason == "max_tokens":
                    messages.append(Message.user("Your reply was cut off. Continue, using tools for any edits."))
                    continue
                return finish("done", final_text=reply.text)

            results: list[TextBlock | ToolUseBlock | ToolResultBlock] = []
            for call in calls:
                if call.name == ASK_HUMAN and cfg.allow_escalation:
                    question = str(call.input.get("question", "")).strip() or reply.text
                    return finish("escalated", final_text=reply.text, question=question)
                output, is_error = await self._execute(call)
                results.append(ToolResultBlock(tool_use_id=call.id, content=output, is_error=is_error))

                signature = json.dumps([call.name, call.input], sort_keys=True)
                repeats = repeats + 1 if signature == last_call else 1
                last_call = signature
            messages.append(Message(role="user", content=results))

            if repeats > cfg.loop_hint_after:
                return finish("loop", error=f"repeated {calls[-1].name} after a hint")
            if repeats == cfg.loop_hint_after:
                messages[-1].content.append(TextBlock(text=LOOP_HINT.format(n=repeats)))
                result.loop_hints += 1

        return finish("max_steps")

    async def _execute(self, call: ToolUseBlock) -> tuple[str, bool]:
        if call.parse_error:
            return f"could not run {call.name}: {call.parse_error}. Send the arguments as a JSON object.", True
        started = time.perf_counter()
        output, is_error = await self.toolbox.call(call.name, call.input)
        elapsed = time.perf_counter() - started
        output = truncate(output, self.config.tool_result_chars)
        if self.tracer:
            self.tracer.event(
                "tool", call.name, duration_s=elapsed, args=call.input, is_error=is_error, output_chars=len(output)
            )
        return output, is_error

    async def _compact(
        self, system: list[TextBlock], messages: list[Message], name: str
    ) -> tuple[list[Message], Usage, float]:
        """Replace everything between the task and the recent tail with a model-written summary.

        The tail starts at an assistant turn, so no tool_result is separated from its tool_use.
        """
        cut = max(1, len(messages) - self.config.keep_recent)
        while cut < len(messages) and messages[cut].role != "assistant":
            cut += 1
        if cut <= 1 or cut >= len(messages):
            return messages, Usage(), 0.0
        head, middle, tail = messages[0], messages[1:cut], messages[cut:]
        # middle ends with the user turn (tool results) answering the last summarised assistant turn
        ask = Message(role="user", content=[*middle[-1].content, TextBlock(text=COMPACT_PROMPT)])
        response = await self.client.create(
            self.config.model,
            [head, *middle[:-1], ask],
            system=system,
            tools=self.toolbox.specs,
            fallback_models=self.config.fallback_models,
            max_tokens=1024,
            variant=self.config.variant,
            name=f"{name}.compact",
        )
        summary = response.message.text.strip() or "(no summary)"
        new_head = Message(
            role="user", content=[*head.content, TextBlock(text=f"\n\nProgress so far (summary):\n{summary}")]
        )
        return [new_head, *tail], response.usage, response.cost_usd
