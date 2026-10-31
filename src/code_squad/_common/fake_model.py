"""Scripted model replaying fixed turns, for tests, the eval harness and compose smoke.

JSON script format for ``ScriptedModel.from_json``: a list of entries, one turn each:

- ``{"tool": "<name>", "input": {...}}`` requests one tool call (``tool_use``)
- ``{"text": "..."}`` answers with text (``end_turn``)
- ``{"stop_reason": "max_tokens", "text": "..."}`` answers with text and an explicit
  stop reason (``tool_use``, ``end_turn`` or ``max_tokens``)

When the script is exhausted the model answers "script exhausted" with ``end_turn``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, TypeVar

from pydantic import BaseModel
from strands.agent.agent_metadata import AgentMetadata
from strands.models.model import Model
from strands.types.content import Message, Messages, SystemContentBlock
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

T = TypeVar("T", bound=BaseModel)
StopReasonName = Literal["tool_use", "end_turn", "max_tokens"]

_STOP_REASONS: Final = frozenset({"tool_use", "end_turn", "max_tokens"})
_ENTRY_KEYS: Final = frozenset({"tool", "input", "text", "stop_reason"})
_INPUT_TOKENS: Final = 10
_OUTPUT_TOKENS: Final = 5


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Turn:
    items: tuple[ToolCall | Text, ...]
    stop_reason: StopReasonName | None = None

    def effective_stop_reason(self) -> StopReasonName:
        if self.stop_reason is not None:
            return self.stop_reason
        return (
            "tool_use"
            if any(isinstance(item, ToolCall) for item in self.items)
            else "end_turn"
        )


@dataclass(frozen=True)
class ModelCall:
    message_count: int
    messages: tuple[Message, ...]
    system_prompt: str | None
    tool_names: tuple[str, ...]


class ScriptedModel(Model):
    def __init__(self, turns: Sequence[Turn], *, model_id: str = "scripted") -> None:
        self._turns: list[Turn] = list(turns)
        self._cursor = 0
        self._sequence = 0
        self._config: dict[str, Any] = {"model_id": model_id}
        self.calls: list[ModelCall] = []

    @classmethod
    def from_json(cls, path: Path | str) -> ScriptedModel:
        data: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("a script must be a JSON list")
        return cls([_turn_from_entry(entry, index) for index, entry in enumerate(data)])

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self._config

    def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any], None]:
        raise NotImplementedError("ScriptedModel does not produce structured output")

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
        invocation_state: dict[str, Any] | None = None,
        cancel_signal: threading.Event | None = None,
        agent_metadata: AgentMetadata | None = None,
        structured_output_model: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.calls.append(
            ModelCall(
                message_count=len(messages),
                messages=tuple(messages),
                system_prompt=system_prompt,
                tool_names=tuple(spec["name"] for spec in tool_specs or []),
            )
        )
        for event in self._events(self._next_turn()):
            yield event

    def _next_turn(self) -> Turn:
        if self._cursor >= len(self._turns):
            return Turn((Text("script exhausted"),), stop_reason="end_turn")
        turn = self._turns[self._cursor]
        self._cursor += 1
        return turn

    def _events(self, turn: Turn) -> list[StreamEvent]:
        events: list[StreamEvent] = [{"messageStart": {"role": "assistant"}}]
        for item in turn.items:
            events.extend(self._item_events(item))
        events.append({"messageStop": {"stopReason": turn.effective_stop_reason()}})
        events.append(
            {
                "metadata": {
                    "usage": {
                        "inputTokens": _INPUT_TOKENS,
                        "outputTokens": _OUTPUT_TOKENS,
                        "totalTokens": _INPUT_TOKENS + _OUTPUT_TOKENS,
                    },
                    "metrics": {"latencyMs": 0},
                }
            }
        )
        return events

    def _item_events(self, item: ToolCall | Text) -> list[StreamEvent]:
        if isinstance(item, Text):
            return [
                {"contentBlockStart": {"start": {}}},
                {"contentBlockDelta": {"delta": {"text": item.text}}},
                {"contentBlockStop": {}},
            ]
        self._sequence += 1
        tool_use_id = f"scripted-{self._sequence}"
        return [
            {
                "contentBlockStart": {
                    "start": {"toolUse": {"name": item.name, "toolUseId": tool_use_id}}
                }
            },
            {
                "contentBlockDelta": {
                    "delta": {"toolUse": {"input": json.dumps(item.input)}}
                }
            },
            {"contentBlockStop": {}},
        ]


def _turn_from_entry(entry: Any, index: int) -> Turn:
    if not isinstance(entry, dict):
        raise ValueError(f"script entry {index} must be an object")
    unknown = sorted(set(entry) - _ENTRY_KEYS)
    if unknown:
        raise ValueError(f"script entry {index} has unknown keys: {', '.join(unknown)}")
    stop_reason = entry.get("stop_reason")
    if stop_reason is not None and stop_reason not in _STOP_REASONS:
        raise ValueError(f"script entry {index} has invalid stop_reason")
    if "tool" in entry:
        return _tool_turn(entry, index, stop_reason)
    if isinstance(entry.get("text"), str):
        return Turn((Text(entry["text"]),), stop_reason=stop_reason)
    raise ValueError(f"script entry {index} needs 'tool' or 'text'")


def _tool_turn(entry: dict[Any, Any], index: int, stop_reason: Any) -> Turn:
    name = entry["tool"]
    tool_input = entry.get("input", {})
    if not isinstance(name, str) or not isinstance(tool_input, dict) or "text" in entry:
        raise ValueError(f"script entry {index} has an invalid tool call")
    return Turn((ToolCall(name=name, input=tool_input),), stop_reason=stop_reason)
