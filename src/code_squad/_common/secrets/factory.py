"""Build the secret provider from configuration and resolve VCS settings."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from code_squad._common.config.errors import ConfigError
from code_squad._common.config.loader import EffectiveConfig
from code_squad._common.config.schema import SecretsConfig, SquadConfig
from code_squad._common.secrets.base import (
    LLM_API_KEY_SECRET,
    VCS_TOKEN_SECRET,
    SecretProvider,
)
from code_squad._common.secrets.env import EnvSecretProvider
from code_squad._common.secrets.k8s_files import K8sFilesSecretProvider
from code_squad._common.secrets.vault import VaultSecretProvider

DEFAULT_SECRETS_DIR: str = "/var/run/secrets/squad"


class LayeredSecretProvider:
    """Bootstrap values (VCS_TOKEN, LLM_API_KEY, ...) take precedence over the base."""

    def __init__(self, overrides: Mapping[str, str], base: SecretProvider) -> None:
        self._overrides = dict(overrides)
        self._base = base

    def get(self, name: str) -> str:
        if name in self._overrides:
            return self._overrides[name]
        return self._base.get(name)


def _read_file_value(path_text: str) -> str:
    try:
        return Path(path_text).read_text(encoding="utf-8").rstrip("\r\n")
    except OSError as exc:
        raise ConfigError(f"cannot read bootstrap secret file {path_text!r}") from exc


def bootstrap_secret_values(env: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for var, file_var, secret_name in (
        ("VCS_TOKEN", "VCS_TOKEN_FILE", VCS_TOKEN_SECRET),
        ("LLM_API_KEY", "LLM_API_KEY_FILE", LLM_API_KEY_SECRET),
    ):
        if env.get(var):
            values[secret_name] = env[var]
        elif env.get(file_var):
            values[secret_name] = _read_file_value(env[file_var])
    return values


def build_secret_provider(
    config: SecretsConfig, env: Mapping[str, str]
) -> SecretProvider:
    patterns = tuple(config.allowed_patterns)
    base: SecretProvider
    if config.provider == "k8s_files":
        directory = Path(env.get("SECRETS_DIR") or DEFAULT_SECRETS_DIR)
        base = K8sFilesSecretProvider(directory, patterns)
    elif config.provider == "env":
        base = EnvSecretProvider(env, patterns)
    elif config.provider == "vault":
        base = VaultSecretProvider()
    else:
        raise ConfigError(f"secrets provider {config.provider!r} is not implemented")
    overrides = bootstrap_secret_values(env)
    return LayeredSecretProvider(overrides, base) if overrides else base


_DEFAULT_BASE_URL: dict[str, str] = {
    "github": "https://api.github.com",
    "gitlab": "https://gitlab.com",
}
_HOST_PROVIDER: dict[str, Literal["gitlab", "github"]] = {
    "api.github.com": "github",
    "github.com": "github",
    "gitlab.com": "gitlab",
}


def resolve_vcs_settings_dict(
    effective: EffectiveConfig | SquadConfig, secrets: SecretProvider
) -> dict[str, Any]:
    """Keys match the M2 ``VcsSettings`` fields; values come from secret names."""
    config = effective.config if isinstance(effective, EffectiveConfig) else effective
    vcs = config.vcs
    provider: Literal["gitlab", "github"]
    if vcs.provider == "auto":
        host = urlsplit(vcs.base_url).hostname if vcs.base_url else None
        if host is None or host not in _HOST_PROVIDER:
            raise ConfigError(
                "cannot infer vcs.provider from vcs.base_url; "
                "set vcs.provider explicitly"
            )
        provider = _HOST_PROVIDER[host]
    else:
        provider = vcs.provider
    base_url = vcs.base_url or _DEFAULT_BASE_URL[provider]
    token = secrets.get(vcs.auth.token_secret) if vcs.auth.token_secret else None
    key = (
        secrets.get(vcs.auth.private_key_secret)
        if vcs.auth.private_key_secret
        else None
    )
    return {
        "provider": provider,
        "base_url": base_url,
        "token": token,
        "app_id": None if vcs.auth.app_id is None else str(vcs.auth.app_id),
        "app_private_key": key,
        "installation_id": (
            None if vcs.auth.installation_id is None else str(vcs.auth.installation_id)
        ),
    }
