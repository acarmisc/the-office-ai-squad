from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from code_squad._common.sandbox.errors import SandboxError

SAFE_PATH: Final = "/usr/local/bin:/usr/bin:/bin"
_ENV_NAME: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SECRET_LIKE: Final = re.compile(
    r"TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|CREDENTIAL|PRIVATE"
    r"|^(LLM|VCS|GITHUB|GITLAB|AWS|AZURE|GOOGLE|SQUAD|SANDBOX|KUBE|OTEL|SESSION)_"
)
_IDENTITY_FORBIDDEN: Final = re.compile(r"[\x00-\x1f<>]")


@dataclass(frozen=True)
class GitIdentity:
    name: str
    email: str

    def __post_init__(self) -> None:
        for value in (self.name, self.email):
            if not value or len(value) > 200 or _IDENTITY_FORBIDDEN.search(value):
                raise ValueError("invalid git identity value")


def scrubbed_env(
    *,
    home: str,
    tmp: str,
    path: str = SAFE_PATH,
    allowed_schemes: Sequence[str] = ("https",),
    identity: GitIdentity | None = None,
) -> dict[str, str]:
    """The only environment a sandboxed process sees; never built from os.environ."""
    env: dict[str, str] = {
        "PATH": path,
        "HOME": home,
        "TMPDIR": tmp,
        "LANG": "C.UTF-8",
        "CI": "true",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "GIT_EDITOR": "/bin/false",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": "/dev/null",
        "GIT_CONFIG_KEY_1": "core.fsmonitor",
        "GIT_CONFIG_VALUE_1": "false",
        "GIT_ALLOW_PROTOCOL": ":".join(allowed_schemes),
        # Environment settings beat repository .npmrc files, so a repository cannot pick
        # the script shell. The user file is empty; the global file is a path npm must
        # not see twice, and it lies in the sandbox home, outside the repository.
        "NPM_CONFIG_USERCONFIG": os.devnull,
        "NPM_CONFIG_GLOBALCONFIG": posixpath.join(home, ".npmrc-global"),
        "npm_config_script_shell": "/bin/sh",
    }
    if identity is not None:
        env.update(
            {
                "GIT_AUTHOR_NAME": identity.name,
                "GIT_AUTHOR_EMAIL": identity.email,
                "GIT_COMMITTER_NAME": identity.name,
                "GIT_COMMITTER_EMAIL": identity.email,
            }
        )
    return env


def validate_env_name(name: str) -> None:
    if not _ENV_NAME.match(name):
        raise SandboxError(f"environment variable name not allowed: {name!r}")
    if _SECRET_LIKE.search(name):
        raise SandboxError(f"environment variable looks like a secret: {name!r}")


def env_from_allowlist(
    names: Sequence[str],
    provided: Mapping[str, str],
    base: Mapping[str, str],
) -> dict[str, str]:
    env = dict(base)
    for name in names:
        validate_env_name(name)
        if name in base:
            raise SandboxError(f"environment variable is set by the sandbox: {name}")
        if name in provided:
            env[name] = provided[name]
    return env
