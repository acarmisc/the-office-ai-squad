"""Shared bearer token for ``/invocations``, ``/jobs/{id}`` and specialists.

``SQUAD_API_TOKEN`` holds the token. ``SQUAD_API_TOKEN_FILE`` names a file that holds it
and is read at start-up. When neither is set those endpoints refuse every request unless
``SQUAD_ALLOW_UNAUTHENTICATED=1`` is set explicitly. Webhook routes use their own
signature checks.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from pathlib import Path
from typing import Final

API_TOKEN_ENV: Final = "SQUAD_API_TOKEN"
API_TOKEN_FILE_ENV: Final = "SQUAD_API_TOKEN_FILE"
ALLOW_UNAUTHENTICATED_ENV: Final = "SQUAD_ALLOW_UNAUTHENTICATED"
_SCHEME: Final = "bearer"


def load_api_token(env: Mapping[str, str]) -> str | None:
    direct = env.get(API_TOKEN_ENV, "").strip()
    if direct:
        return direct
    path = env.get(API_TOKEN_FILE_ENV, "").strip()
    if not path:
        return None
    token = Path(path).read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(f"{API_TOKEN_FILE_ENV} names an empty file")
    return token


def unauthenticated_allowed(env: Mapping[str, str]) -> bool:
    return env.get(ALLOW_UNAUTHENTICATED_ENV, "").strip() == "1"


def bearer_matches(authorization: str | None, expected: str) -> bool:
    if authorization is None:
        return False
    scheme, _, presented = authorization.strip().partition(" ")
    if scheme.lower() != _SCHEME or not presented.strip():
        return False
    return hmac.compare_digest(
        presented.strip().encode("utf-8"), expected.encode("utf-8")
    )
