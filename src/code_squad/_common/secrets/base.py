"""Secret provider protocol and name validation.

Names are lowercase tokens matched against ``secrets.allowed_patterns`` (org-only).
Path separators and ``..`` are refused before any provider touches the filesystem.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final, Protocol

VCS_TOKEN_SECRET: Final[str] = "vcs-token"
LLM_API_KEY_SECRET: Final[str] = "llm-api-key"
DEFAULT_ALLOWED_PATTERNS: Final[tuple[str, ...]] = ("^[a-z0-9][a-z0-9._-]*$",)
_NAME_SHAPE: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,252}$")


class SecretNotFoundError(KeyError):
    """The secret is not available from the provider."""


class SecretNameError(ValueError):
    """The name is malformed, not allowed, or would escape the provider's scope."""


class SecretProvider(Protocol):
    def get(self, name: str) -> str: ...


def check_secret_name(name: str, allowed_patterns: Sequence[str]) -> str:
    if not _NAME_SHAPE.fullmatch(name) or ".." in name:
        raise SecretNameError(f"invalid secret name {name!r}")
    if not any(re.fullmatch(pattern, name) for pattern in allowed_patterns):
        raise SecretNameError(f"secret name {name!r} is outside allowed_patterns")
    return name
