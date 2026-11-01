"""Masks secrets in text before any darryl tool output leaves the agent.

Every tool output passes through ``redact`` and then ``wrap_untrusted``. Rules run in
a fixed order: PEM blocks, authorization headers, connection strings, JWTs, token
prefixes (including Stripe and Slack webhook URLs), signed URL signatures, JSON
name/value secrets, JSON private keys, environment-style secret pairs, key-value
secrets, configured extra patterns, then optional e-mail addresses.

Environment-style names are matched case-sensitively (``DB_PASS=`` and ``API_KEY:``), so
lower-case config keys such as ``max_tokens`` keep their values.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from enum import StrEnum
from functools import lru_cache
from typing import Final

Replacer = Callable[[re.Match[str]], str]
_Rule = tuple[re.Pattern[str], Replacer]

_KEYWORDS: Final = (
    r"(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key"
    r"|private[_-]?key|client[_-]?secret|credentials?)"
)
_EXTRA_MARK: Final = "<redacted:custom>"


class EmailPolicy(StrEnum):
    KEEP = "keep"
    MASK = "mask"


def _fixed(marker: str) -> Replacer:
    return lambda _match: marker


def _keep_group(group: int, marker: str) -> Replacer:
    return lambda match: match.group(group) + marker


def _mask_key_value(match: re.Match[str]) -> str:
    value = match.group("value")
    if value.startswith('\\"'):
        quote = '\\"'
    elif value[:1] in ('"', "'"):
        quote = value[0]
    else:
        quote = ""
    return f"{match.group('key')}{quote}<redacted>{quote}"


def _mask_connection(match: re.Match[str]) -> str:
    return f"{match.group('scheme')}{match.group('user')}:***@"


def _mask_env_pair(match: re.Match[str]) -> str:
    value = match.group("value")
    quote = value[0] if value[:1] in ('"', "'") else ""
    return f"{match.group('key')}{match.group('sep')}{quote}<redacted>{quote}"


def _mask_json_name_value(match: re.Match[str]) -> str:
    if _SECRET_NAME.search(match.group("name")) is None:
        return match.group(0)
    return f'{match.group("pre")}"<redacted>"'


_PEM_BLOCK: Final = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_AUTH_HEADER: Final = re.compile(
    r"(?i)(\bauthorization[\"']?[ \t]*[:=][ \t]*[\"']?)"
    r"(?:(?:bearer|basic|token)[ \t]+)?[^\s\"',;]+"
)
_BEARER: Final = re.compile(r"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/=-]+")
_CONNECTION: Final = re.compile(
    r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.\-]*://)"
    r"(?P<user>[^\s/:@]*):(?P<password>[^\s/@]+)@"
)
_JWT: Final = re.compile(
    r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"
)
_KEY_VALUE: Final = re.compile(
    r"(?P<key>\\?[\"']?[A-Za-z0-9_.\-]*" + _KEYWORDS + r"\\?[\"']?[ \t]*[:=][ \t]*)"
    r"(?P<value>\\?\"[^\"\n]*?\\?\"|'[^'\n]*'|[^\s&,;}\]\"'\\]+)",
    re.IGNORECASE,
)
_EMAIL: Final = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_SECRET_NAME: Final = re.compile(
    r"[A-Z0-9_]*(?:PASS|PASSWD|PASSWORD|PWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY"
    r"|CREDENTIALS?)[A-Z0-9_]*",
    re.IGNORECASE,
)
_ENV_SECRET_PAIR: Final = re.compile(
    r"(?<![A-Za-z0-9_])(?P<key>[A-Z][A-Z0-9_]*(?:PASS|PASSWD|PASSWORD|PWD|SECRET|TOKEN"
    r"|API_?KEY|PRIVATE_?KEY|CREDENTIALS?)[A-Z0-9_]*)"
    r"(?P<sep>[ \t]*[:=][ \t]*)"
    r"(?P<value>\"[^\"\n]*\"|'[^'\n]*'|[^\s\"',;&}\]]+)"
)
_JSON_NAME_VALUE: Final = re.compile(
    r'(?P<pre>\{\s*"name"\s*:\s*"(?P<name>[^"\n]{1,200})"\s*,\s*"value"\s*:\s*)'
    r'"(?:[^"\\\n]|\\.)*"',
    re.IGNORECASE,
)
_JSON_PRIVATE_KEY: Final = re.compile(
    r'("private_key"\s*:\s*)"(?:[^"\\]|\\.)*"', re.IGNORECASE
)
_STRIPE_KEY: Final = re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}\b")
_SLACK_WEBHOOK: Final = re.compile(
    r"https://hooks\.slack\.com/services/[A-Za-z0-9_/\-]+"
)
_SAS_SIGNATURE: Final = re.compile(r"(?i)\bsig=[^&\s\"',;]+")

_BUILTIN_RULES: Final[tuple[_Rule, ...]] = (
    (_PEM_BLOCK, _fixed("<redacted:private-key>")),
    (_AUTH_HEADER, _keep_group(1, "<redacted>")),
    (_BEARER, _fixed("Bearer <redacted>")),
    (_CONNECTION, _mask_connection),
    (_JWT, _fixed("<redacted:jwt>")),
    (_STRIPE_KEY, _fixed("<redacted:stripe-key>")),
    (_SLACK_WEBHOOK, _fixed("<redacted:slack-webhook>")),
    (_SAS_SIGNATURE, _fixed("sig=<redacted>")),
    (
        re.compile(
            r"\b(?:gh[pousr]_[A-Za-z0-9]{20,255}|github_pat_[A-Za-z0-9_]{20,255})\b"
        ),
        _fixed("<redacted:github-token>"),
    ),
    (
        re.compile(r"\bgl(?:pat|ptt|rt|dt|cbt|oas|soat)-[A-Za-z0-9_\-]{20,}"),
        _fixed("<redacted:gitlab-token>"),
    ),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), _fixed("<redacted:slack-token>")),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), _fixed("<redacted:api-key>")),
    (
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        _fixed("<redacted:aws-access-key-id>"),
    ),
    (_JSON_NAME_VALUE, _mask_json_name_value),
    (_JSON_PRIVATE_KEY, _keep_group(1, '"<redacted>"')),
    (_ENV_SECRET_PAIR, _mask_env_pair),
    (_KEY_VALUE, _mask_key_value),
)


@lru_cache(maxsize=32)
def _compile_extra(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if not pattern:
            raise ValueError("redaction patterns must not be empty")
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"invalid redaction pattern: {exc}") from exc
    return tuple(compiled)


def redact(
    text: str,
    extra_patterns: Sequence[str] = (),
    *,
    emails: EmailPolicy = EmailPolicy.KEEP,
) -> str:
    """Return ``text`` with secrets masked. Raises ValueError for a bad pattern."""
    out = text
    for pattern, replacer in _BUILTIN_RULES:
        out = pattern.sub(replacer, out)
    for pattern in _compile_extra(tuple(extra_patterns)):
        out = pattern.sub(_EXTRA_MARK, out)
    if emails is EmailPolicy.MASK:
        out = _EMAIL.sub("<redacted:email>", out)
    return out
