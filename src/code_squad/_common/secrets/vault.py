"""Vault provider stub. It needs the optional ``hvac`` package (not a dependency)."""

from __future__ import annotations

import importlib.util


class VaultSecretProvider:
    def __init__(self) -> None:
        if importlib.util.find_spec("hvac") is None:
            raise NotImplementedError(
                "secrets.provider 'vault' needs the optional 'hvac' package, "
                "which is not installed; use 'k8s_files' or 'env'"
            )

    def get(self, name: str) -> str:
        raise NotImplementedError(
            "secrets.provider 'vault' is not implemented in this version"
        )
