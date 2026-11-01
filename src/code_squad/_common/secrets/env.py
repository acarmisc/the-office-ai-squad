"""Secrets from ``SQUAD_SECRET_<NAME>`` environment variables (dev and tests)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from code_squad._common.secrets.base import (
    DEFAULT_ALLOWED_PATTERNS,
    SecretNotFoundError,
    check_secret_name,
)

_PREFIX = "SQUAD_SECRET_"


def env_var_name(secret_name: str) -> str:
    return _PREFIX + re.sub(r"[-./]", "_", secret_name).upper()


class EnvSecretProvider:
    def __init__(
        self,
        environ: Mapping[str, str],
        allowed_patterns: Sequence[str] = DEFAULT_ALLOWED_PATTERNS,
    ) -> None:
        self._environ = environ
        self._patterns = tuple(allowed_patterns)

    def get(self, name: str) -> str:
        check_secret_name(name, self._patterns)
        value = self._environ.get(env_var_name(name), "")
        if not value:
            raise SecretNotFoundError(name)
        return value
