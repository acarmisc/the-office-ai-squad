from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

from strands.models.model import Model
from strands.models.openai import OpenAIModel

ModelFactory = Callable[[str, int, float, Sequence[str]], Model]

_DEFAULT_BASE_URL: Final = "http://localhost:4000/v1"
RESERVED_TAG_NAMESPACES: Final = ("squad", "project", "agent")
_factory_override: ModelFactory | None = None


def set_model_factory(factory: ModelFactory | None) -> None:
    global _factory_override
    _factory_override = factory


def get_model_factory() -> ModelFactory:
    return _factory_override or build_model


def build_model(
    model_id: str,
    max_tokens: int,
    temperature: float,
    tags: Sequence[str] = (),
) -> Model:
    return OpenAIModel(
        client_args={"base_url": _base_url(), "api_key": _api_key()},
        model_id=model_id,
        params=_params(max_tokens, temperature, tags),
    )


def litellm_tags(agent: str, project: str | None, extra: Sequence[str]) -> list[str]:
    tags = ["squad:code-squad", f"agent:{agent}"]
    if project:
        tags.append(f"project:{project}")
    tags.extend(tag for tag in extra if _reserved_namespace(tag) is None)
    return tags


def dropped_caller_tags(extra: Sequence[str]) -> list[str]:
    """Reserved namespaces that caller tags tried to use, in order, without repeats."""
    dropped: list[str] = []
    for tag in extra:
        namespace = _reserved_namespace(tag)
        if namespace is not None and namespace not in dropped:
            dropped.append(namespace)
    return dropped


def _reserved_namespace(tag: str) -> str | None:
    for namespace in RESERVED_TAG_NAMESPACES:
        if tag.startswith(f"{namespace}:"):
            return namespace
    return None


def _base_url() -> str:
    return os.environ.get("LLM_BASE_URL") or _DEFAULT_BASE_URL


def _api_key() -> str:
    direct = os.environ.get("LLM_API_KEY")
    if direct:
        return direct
    key_file = os.environ.get("LLM_API_KEY_FILE")
    if key_file:
        key = Path(key_file).read_text(encoding="utf-8").strip()
        if key:
            return key
    raise RuntimeError("LLM_API_KEY or LLM_API_KEY_FILE must be set")


def _params(max_tokens: int, temperature: float, tags: Sequence[str]) -> dict[str, Any]:
    params: dict[str, Any] = {"max_tokens": max_tokens, "temperature": temperature}
    if tags:
        params["extra_body"] = {"metadata": {"tags": list(tags)}}
    return params
