"""Quality gates. A gate is a state-machine transition: the pipeline cannot reach delivery around it."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class GateResult(BaseModel):
    gate: str
    passed: bool
    summary: str
    feedback: str = ""  # what goes back to the agent when the gate fails
    data: dict[str, Any] = {}
