from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Ecosystem = Literal["npm", "Maven", "PyPI", "Docker"]
ECOSYSTEMS: tuple[Ecosystem, ...] = ("npm", "Maven", "PyPI", "Docker")


@dataclass(frozen=True)
class Package:
    ecosystem: Ecosystem
    name: str
    version: str | None
    pinned: bool
    source_file: str
    line: int | None
    direct: bool | None


@dataclass(frozen=True)
class ParseResult:
    packages: tuple[Package, ...]
    warnings: tuple[str, ...]
