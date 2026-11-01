from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from code_squad._common.untrusted import wrap_untrusted

SKILL_NAME_PATTERN: Final = r"^[a-z0-9][a-z0-9._-]{0,63}$"
SkillSource = Literal["payload", "repo", "builtin"]


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    source: SkillSource
    applies_to: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    priority: int = 0
    always: bool = False
    path: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class SkillLimits:
    max_skills: int = 20
    max_skill_bytes: int = 20480
    max_total_bytes: int = 81920


@dataclass(frozen=True)
class RootDiscovery:
    found: bool
    skills: tuple[Skill, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillSet:
    skills: tuple[Skill, ...]
    warnings: tuple[str, ...]
    changed_in_change_request: tuple[str, ...]
    overrides: tuple[str, ...] = ()

    def get(self, name: str) -> Skill | None:
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None

    def index_text(self) -> str:
        if not self.skills:
            return ""
        listing = "\n".join(
            f"- {skill.name}: {skill.description}" for skill in self.skills
        )
        blocks = [wrap_untrusted(listing, "skills:index")]
        blocks.extend(_always_block(skill) for skill in self.skills if skill.always)
        return "\n\n".join(blocks)


def _always_block(skill: Skill) -> str:
    header = f"Always-on skill '{skill.name}' (full instructions):"
    return f"{header}\n{wrap_untrusted(skill.body, f'skill:{skill.name}')}"
