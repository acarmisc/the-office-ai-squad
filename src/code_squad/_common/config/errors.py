from __future__ import annotations

from pydantic import ValidationError


class ConfigError(Exception):
    """A configuration source is unusable; the message lists every problem."""

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        self.problems: list[str] = list(problems or [])
        detail = "; ".join(self.problems)
        super().__init__(f"{message}: {detail}" if detail else message)


class ConfigUnreadableError(ConfigError):
    """A configuration file exists but cannot be read; no earlier copy may stand in."""


def problems_of(exc: ValidationError) -> list[str]:
    """Render pydantic errors as ``dotted.path: message`` strings."""
    out: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        out.append(f"{location}: {error['msg']}" if location else error["msg"])
    return out
