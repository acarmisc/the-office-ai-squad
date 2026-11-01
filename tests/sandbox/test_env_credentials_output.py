from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from code_squad._common.sandbox.credentials import (
    ASKPASS_SCRIPT,
    GitCredentials,
    askpass_environment,
    check_credentials_for_url,
)
from code_squad._common.sandbox.env import (
    SAFE_PATH,
    GitIdentity,
    env_from_allowlist,
    scrubbed_env,
    validate_env_name,
)
from code_squad._common.sandbox.errors import SandboxError
from code_squad._common.sandbox.output import (
    OutputCapture,
    capture_file,
    redact_secrets,
)

FAKE_SECRET_NAMES = ("LLM_API_KEY", "VCS_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN")


def test_scrubbed_env_never_reads_the_host_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in FAKE_SECRET_NAMES:
        monkeypatch.setenv(name, "fake-token-for-tests")
    env = scrubbed_env(home="/w/.home", tmp="/w/.tmp")
    assert env["PATH"] == SAFE_PATH
    assert env["HOME"] == "/w/.home"
    assert not set(FAKE_SECRET_NAMES) & set(env)
    assert all("fake-token-for-tests" not in value for value in env.values())


def test_scrubbed_env_pins_git_configuration_and_protocols() -> None:
    env = scrubbed_env(home="/h", tmp="/t", allowed_schemes=("https",))
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_KEY_0"] == "core.hooksPath"
    assert env["GIT_CONFIG_VALUE_0"] == os.devnull
    assert env["GIT_ALLOW_PROTOCOL"] == "https"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_identity_is_added_only_when_given() -> None:
    env = scrubbed_env(
        home="/h",
        tmp="/t",
        identity=GitIdentity("Squad Bot", "squad@example.test"),
    )
    assert env["GIT_AUTHOR_NAME"] == "Squad Bot"
    assert env["GIT_COMMITTER_EMAIL"] == "squad@example.test"
    assert "GIT_AUTHOR_NAME" not in scrubbed_env(home="/h", tmp="/t")


def test_identity_rejects_header_injection() -> None:
    with pytest.raises(ValueError):
        GitIdentity("Bot\nX: y", "bot@example.test")


def test_env_allowlist_takes_only_named_values_and_refuses_secret_names() -> None:
    base = scrubbed_env(home="/h", tmp="/t")
    provided = {"FEATURE_FLAG": "on", "VCS_TOKEN": "fake-token-for-tests"}
    env = env_from_allowlist(["FEATURE_FLAG"], provided, base)
    assert env["FEATURE_FLAG"] == "on"
    with pytest.raises(SandboxError):
        env_from_allowlist(["VCS_TOKEN"], provided, base)
    with pytest.raises(SandboxError):
        env_from_allowlist(["PATH"], provided, base)
    with pytest.raises(SandboxError):
        validate_env_name("lowercase")


def test_credentials_repr_never_shows_the_token() -> None:
    creds = GitCredentials("squad-bot", "fake-token-for-tests", "git.example.test")
    assert "fake-token-for-tests" not in repr(creds)
    assert "fake-token-for-tests" not in str(creds)
    assert "fake-token-for-tests" not in f"{creds!r}"


def test_credentials_are_only_for_their_host_over_http_schemes() -> None:
    creds = GitCredentials("squad-bot", "fake-token-for-tests", "git.example.test")
    check_credentials_for_url(creds, "https://git.example.test/o/r.git", ("https",))
    with pytest.raises(SandboxError):
        check_credentials_for_url(
            creds, "https://evil.example.test/o/r.git", ("https",)
        )
    with pytest.raises(SandboxError):
        check_credentials_for_url(creds, "file:///tmp/r.git", ("file",))


def test_askpass_environment_carries_paths_and_username_not_the_token() -> None:
    creds = GitCredentials("squad-bot", "fake-token-for-tests", "git.example.test")
    env = askpass_environment(creds, "/tmp/c/askpass.sh", "/tmp/c/token")
    assert env == {
        "GIT_ASKPASS": "/tmp/c/askpass.sh",
        "SQUAD_GIT_USERNAME": "squad-bot",
        "SQUAD_GIT_TOKEN_FILE": "/tmp/c/token",
    }


def test_askpass_script_answers_git_prompts_from_the_token_file(tmp_path: Path) -> None:
    script = tmp_path / "askpass.sh"
    script.write_text(ASKPASS_SCRIPT)
    script.chmod(0o700)
    token = tmp_path / "token"
    token.write_text("fake-token-for-tests\n")
    env = {
        "PATH": SAFE_PATH,
        "SQUAD_GIT_USERNAME": "squad-bot",
        "SQUAD_GIT_TOKEN_FILE": str(token),
    }

    def answer(prompt: str) -> str:
        done = subprocess.run(
            [str(script), prompt],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout

    assert answer("Username for 'https://git.example.test': ") == "squad-bot"
    assert answer("Password for 'https://squad-bot@git.example.test': ") == (
        "fake-token-for-tests"
    )


def test_output_keeps_small_streams_whole() -> None:
    capture = OutputCapture(limit=100)
    capture.feed("hello ")
    capture.feed(b"world")
    assert capture.render() == ("hello world", False)


def test_output_keeps_head_and_tail_of_large_streams_with_a_marker() -> None:
    capture = OutputCapture(limit=64)
    capture.feed("H" * 16)
    capture.feed("M" * 1000)
    capture.feed("T" * 48)
    text, truncated = capture.render()
    assert truncated
    assert text.startswith("H" * 16)
    assert text.endswith("T" * 48)
    assert "bytes truncated" in text
    assert len(text) < 200


def test_capture_file_reads_head_and_tail_without_loading_everything(
    tmp_path: Path,
) -> None:
    path = tmp_path / "out"
    path.write_bytes(b"a" * 10 + b"b" * 5000 + b"c" * 100)
    with path.open("rb") as handle:
        text, truncated = capture_file(handle, limit=200)
    assert truncated
    assert text.startswith("a" * 10)
    assert text.endswith("c" * 100)


def test_redaction_replaces_every_secret_value_longest_first() -> None:
    text = "token fake-token-for-tests and fake-token"
    assert redact_secrets(text, ["fake-token", "fake-token-for-tests", ""]) == (
        "token *** and ***"
    )
