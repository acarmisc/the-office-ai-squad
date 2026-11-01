from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from code_squad._common.config.errors import ConfigError
from code_squad._common.config.loader import EffectiveConfig, resolve
from code_squad._common.config.projects import ProjectRegistry
from code_squad._common.config.schema import SecretsConfig, SquadConfig
from code_squad._common.secrets.base import (
    SecretNameError,
    SecretNotFoundError,
    check_secret_name,
)
from code_squad._common.secrets.env import EnvSecretProvider, env_var_name
from code_squad._common.secrets.factory import (
    LayeredSecretProvider,
    build_secret_provider,
    resolve_vcs_settings_dict,
)
from code_squad._common.secrets.k8s_files import K8sFilesSecretProvider
from code_squad._common.secrets.vault import VaultSecretProvider

FAKE = "fake-token-for-tests"


@pytest.fixture
def secrets_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "secrets"
    directory.mkdir()
    (directory / "vcs-token").write_text(FAKE + "\n", encoding="utf-8")
    (directory / "plain").write_text(FAKE, encoding="utf-8")
    (directory / "empty").write_text("\n", encoding="utf-8")
    return directory


# ---------------------------------------------------------------- k8s files


def test_k8s_files_reads_and_strips_the_trailing_newline(secrets_dir: Path) -> None:
    provider = K8sFilesSecretProvider(secrets_dir)
    assert provider.get("vcs-token") == FAKE
    assert provider.get("plain") == FAKE


def test_missing_secret_is_not_found(secrets_dir: Path) -> None:
    with pytest.raises(SecretNotFoundError):
        K8sFilesSecretProvider(secrets_dir).get("absent")


def test_empty_secret_is_treated_as_not_found(secrets_dir: Path) -> None:
    with pytest.raises(SecretNotFoundError):
        K8sFilesSecretProvider(secrets_dir).get("empty")


@pytest.mark.parametrize(
    "name", ["../x", "../../etc/passwd", "a/b", "..", "a..b", "/etc/passwd", "x\\y"]
)
def test_path_like_names_are_refused(secrets_dir: Path, name: str) -> None:
    with pytest.raises(SecretNameError):
        K8sFilesSecretProvider(secrets_dir).get(name)


def test_symlink_escaping_the_directory_is_refused(
    tmp_path: Path, secrets_dir: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text(FAKE, encoding="utf-8")
    (secrets_dir / "leak").symlink_to(outside)
    with pytest.raises(SecretNameError, match="outside the secrets directory"):
        K8sFilesSecretProvider(secrets_dir).get("leak")


def test_kubernetes_style_data_symlink_inside_the_directory_is_followed(
    secrets_dir: Path,
) -> None:
    generation = secrets_dir / "..2026_10_31_00_00_00.1"
    generation.mkdir()
    (generation / "api-key").write_text(FAKE, encoding="utf-8")
    (secrets_dir / "..data").symlink_to(generation.name)
    (secrets_dir / "api-key").symlink_to("..data/api-key")
    assert K8sFilesSecretProvider(secrets_dir).get("api-key") == FAKE


def test_names_outside_allowed_patterns_are_refused(secrets_dir: Path) -> None:
    provider = K8sFilesSecretProvider(secrets_dir, ["^team-[a-z]+$"])
    with pytest.raises(SecretNameError, match="allowed_patterns"):
        provider.get("vcs-token")


def test_name_shape_is_checked_before_patterns() -> None:
    with pytest.raises(SecretNameError):
        check_secret_name("UPPER", ["^.*$"])
    assert check_secret_name("ok-name", ["^.*$"]) == "ok-name"


# ---------------------------------------------------------------- env


def test_env_provider_maps_names_to_squad_secret_variables() -> None:
    assert (
        env_var_name("gitlab-payments.token/v2")
        == "SQUAD_SECRET_GITLAB_PAYMENTS_TOKEN_V2"
    )
    provider = EnvSecretProvider({"SQUAD_SECRET_VCS_TOKEN": FAKE})
    assert provider.get("vcs-token") == FAKE


def test_env_provider_missing_and_empty_are_not_found() -> None:
    provider = EnvSecretProvider({"SQUAD_SECRET_VCS_TOKEN": ""})
    with pytest.raises(SecretNotFoundError):
        provider.get("vcs-token")
    with pytest.raises(SecretNotFoundError):
        EnvSecretProvider({}).get("vcs-token")


def test_env_provider_refuses_bad_names() -> None:
    with pytest.raises(SecretNameError):
        EnvSecretProvider({"SQUAD_SECRET_X": FAKE}).get("../x")


# ---------------------------------------------------------------- vault stub


def test_vault_stub_explains_the_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(NotImplementedError, match="hvac"):
        VaultSecretProvider()


def test_vault_stub_refuses_to_read_even_with_the_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    provider = VaultSecretProvider()
    with pytest.raises(NotImplementedError, match="not implemented"):
        provider.get("vcs-token")


# ---------------------------------------------------------------- factory


def test_factory_builds_the_k8s_provider_from_secrets_dir(secrets_dir: Path) -> None:
    provider = build_secret_provider(
        SecretsConfig(provider="k8s_files"), {"SECRETS_DIR": str(secrets_dir)}
    )
    assert provider.get("plain") == FAKE


def test_factory_builds_the_env_provider() -> None:
    provider = build_secret_provider(
        SecretsConfig(provider="env"), {"SQUAD_SECRET_PLAIN": FAKE}
    )
    assert provider.get("plain") == FAKE


def test_factory_refuses_vault_without_the_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(NotImplementedError):
        build_secret_provider(SecretsConfig(provider="vault"), {})


def test_bootstrap_token_overrides_the_base_provider(secrets_dir: Path) -> None:
    provider = build_secret_provider(
        SecretsConfig(provider="k8s_files"),
        {"SECRETS_DIR": str(secrets_dir), "VCS_TOKEN": "other-fake-token"},
    )
    assert isinstance(provider, LayeredSecretProvider)
    assert provider.get("vcs-token") == "other-fake-token"
    assert provider.get("plain") == FAKE


def test_bootstrap_token_file_is_read_and_trimmed(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(FAKE + "\n", encoding="utf-8")
    provider = build_secret_provider(
        SecretsConfig(provider="env"), {"VCS_TOKEN_FILE": str(token_file)}
    )
    assert provider.get("vcs-token") == FAKE


def test_bootstrap_llm_key_file_is_read(tmp_path: Path) -> None:
    key_file = tmp_path / "llm"
    key_file.write_text(FAKE, encoding="utf-8")
    provider = build_secret_provider(
        SecretsConfig(provider="env"), {"LLM_API_KEY_FILE": str(key_file)}
    )
    assert provider.get("llm-api-key") == FAKE


def test_unreadable_bootstrap_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read bootstrap secret file"):
        build_secret_provider(
            SecretsConfig(provider="env"), {"VCS_TOKEN_FILE": str(tmp_path / "missing")}
        )


# ---------------------------------------------------------------- VCS settings


class _Recorder:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.asked: list[str] = []

    def get(self, name: str) -> str:
        self.asked.append(name)
        if name not in self._values:
            raise SecretNotFoundError(name)
        return self._values[name]


def _effective(vcs: dict[str, object]) -> EffectiveConfig:
    return resolve(
        "acme/web-shop",
        org={"vcs": vcs},
        registry=ProjectRegistry(),
        repo_config_text=None,
        call_overrides=None,
    )


def test_vcs_settings_for_gitlab_use_the_token_secret() -> None:
    effective = _effective(
        {
            "provider": "gitlab",
            "base_url": "https://gitlab.example.com",
            "auth": {"token_secret": "gl-token"},
        }
    )
    settings = resolve_vcs_settings_dict(effective, _Recorder({"gl-token": FAKE}))
    assert settings == {
        "provider": "gitlab",
        "base_url": "https://gitlab.example.com",
        "token": FAKE,
        "app_id": None,
        "app_private_key": None,
        "installation_id": None,
    }


def test_vcs_settings_for_a_github_app_read_the_key_and_ids() -> None:
    effective = _effective(
        {
            "provider": "github",
            "auth": {
                "app_id": 12345,
                "installation_id": 67890,
                "private_key_secret": "gh-key",
            },
        }
    )
    recorder = _Recorder({"gh-key": "-----fake-pem-----"})
    settings = resolve_vcs_settings_dict(effective, recorder)
    assert settings["base_url"] == "https://api.github.com"
    assert settings["app_id"] == "12345"
    assert settings["installation_id"] == "67890"
    assert settings["app_private_key"] == "-----fake-pem-----"
    assert settings["token"] is None
    assert recorder.asked == ["gh-key"]


def test_auto_provider_is_inferred_from_public_hosts() -> None:
    effective = _effective({"provider": "auto", "base_url": "https://gitlab.com"})
    assert resolve_vcs_settings_dict(effective, _Recorder({}))["provider"] == "gitlab"


def test_auto_provider_on_an_enterprise_host_needs_an_explicit_provider() -> None:
    effective = _effective(
        {"provider": "auto", "base_url": "https://ghes.example.com/api/v3"}
    )
    with pytest.raises(ConfigError, match=r"set vcs\.provider explicitly"):
        resolve_vcs_settings_dict(effective, _Recorder({}))


def test_settings_accept_a_plain_config_too() -> None:
    settings = resolve_vcs_settings_dict(
        SquadConfig.model_validate({"vcs": {"provider": "github"}}),
        _Recorder({}),
    )
    assert settings["provider"] == "github"
