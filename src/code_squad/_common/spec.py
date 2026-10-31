from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from strands.types.tools import AgentTool


class ContentCapture(StrEnum):
    FULL = "full"
    METADATA = "metadata"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    role: str
    system_prompt: str
    task_template: str
    tools: tuple[Callable[..., Any] | AgentTool, ...]
    model_id: str
    max_tokens: int = 8192
    temperature: float = 0.0
    max_iterations: int = 25
    retry_model_id: str | None = None
    content_capture: ContentCapture = ContentCapture.METADATA
    accepts_attachments: bool = False
    telemetry_factory: Callable[[], Any] | None = None
    input_key: str = "prompt"
    modes: tuple[str, ...] = ("review",)

    def render_task(
        self, target: str | None, action: str | None, project: str | None
    ) -> str:
        return self.task_template.format(
            target=target or "",
            action=action or "",
            project=project or "",
        )
