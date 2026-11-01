from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from code_squad._common.sandbox.errors import SandboxError

_HOST: Final = re.compile(r"^[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?$")
_CREDENTIAL_SCHEMES: Final = frozenset({"https", "http"})

ASKPASS_SCRIPT: Final = (
    "#!/bin/sh\n"
    'case "$1" in\n'
    '  *sername*) printf "%s" "$SQUAD_GIT_USERNAME" ;;\n'
    '  *) IFS= read -r token < "$SQUAD_GIT_TOKEN_FILE" && printf "%s" "$token" ;;\n'
    "esac\n"
)


@dataclass(frozen=True, repr=False)
class GitCredentials:
    username: str
    token: str
    host: str

    def __post_init__(self) -> None:
        if not self.username or "\n" in self.username or len(self.username) > 256:
            raise ValueError("invalid git username")
        if (
            not self.token
            or len(self.token) > 4096
            or any(ch in self.token for ch in ("\n", "\r", "\x00"))
        ):
            raise ValueError("invalid git token")
        if not _HOST.match(self.host):
            raise ValueError("credentials host must be host or host:port")

    def __repr__(self) -> str:
        return (
            f"GitCredentials(username={self.username!r}, "
            f"host={self.host!r}, token='***')"
        )

    __str__ = __repr__


def check_credentials_for_url(
    credentials: GitCredentials, url: str, allowed_schemes: tuple[str, ...]
) -> None:
    parts = urlsplit(url)
    if parts.scheme not in _CREDENTIAL_SCHEMES or parts.scheme not in allowed_schemes:
        raise SandboxError("credentials are only sent to http or https remotes")
    if parts.netloc.lower() != credentials.host.lower():
        raise SandboxError(
            f"credentials are issued for {credentials.host}, not {parts.netloc}"
        )


def token_file_content(token: str) -> bytes:
    return f"{token}\n".encode()


def askpass_environment(
    credentials: GitCredentials, askpass_path: str, token_path: str
) -> dict[str, str]:
    """Only paths and the username enter the environment, never the token."""
    return {
        "GIT_ASKPASS": askpass_path,
        "SQUAD_GIT_USERNAME": credentials.username,
        "SQUAD_GIT_TOKEN_FILE": token_path,
    }
