"""Secrets mounted as files, as Kubernetes Secret volumes do.

Kubernetes places each key as a symlink to ``..data/<key>``, so symlinks are followed.
The resolved target must still lie inside the resolved directory.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from code_squad._common.secrets.base import (
    DEFAULT_ALLOWED_PATTERNS,
    SecretNameError,
    SecretNotFoundError,
    check_secret_name,
)


class K8sFilesSecretProvider:
    def __init__(
        self,
        directory: Path,
        allowed_patterns: Sequence[str] = DEFAULT_ALLOWED_PATTERNS,
    ) -> None:
        self._directory = directory
        self._patterns = tuple(allowed_patterns)

    def get(self, name: str) -> str:
        check_secret_name(name, self._patterns)
        root = self._directory.resolve()
        target = (root / name).resolve()
        if not target.is_relative_to(root):
            raise SecretNameError(
                f"secret {name!r} resolves outside the secrets directory"
            )
        if not target.is_file():
            raise SecretNotFoundError(name)
        value = target.read_text(encoding="utf-8").rstrip("\r\n")
        if not value:
            raise SecretNotFoundError(name)
        return value
