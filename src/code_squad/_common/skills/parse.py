from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

import yaml

from code_squad._common.contract import SkillPayload
from code_squad._common.skills.model import SKILL_NAME_PATTERN, Skill

_NAME: Final = re.compile(SKILL_NAME_PATTERN)
_FENCE: Final = "---"
_DESCRIPTION_MAX: Final = 1024
_PATTERN_MAX: Final = 256
_AUTHORITY_KEYS: Final = frozenset(
    {
        "tools",
        "allowed_tools",
        "dry_run",
        "post",
        "policy",
        "output_schema",
        "system",
        "permissions",
    }
)
_KNOWN_KEYS: Final = frozenset(
    {"name", "description", "applies_to", "agents", "priority", "always"}
)


@dataclass(frozen=True)
class _Options:
    applies_to: tuple[str, ...]
    agents: tuple[str, ...]
    priority: int
    always: bool


def parse_skill_md(
    text: str, *, path: str, source: Literal["repo", "builtin"] = "repo"
) -> tuple[Skill | None, list[str]]:
    front, body = _split_frontmatter(text)
    if front is None:
        return None, [f"{path}: missing YAML frontmatter; skipped"]
    meta = _mapping(front)
    if meta is None:
        return None, [f"{path}: frontmatter is not a valid YAML mapping; skipped"]
    name = meta.get("name")
    if not isinstance(name, str) or not _NAME.match(name):
        return None, [f"{path}: name must match {SKILL_NAME_PATTERN}; skipped"]
    warnings = _key_warnings(name, meta)
    description = _description(name, meta.get("description"), warnings)
    if description is None:
        warnings.append(
            f"skill {name}: description must be a non-empty string; skipped"
        )
        return None, warnings
    text_body = body.strip()
    if not text_body:
        warnings.append(f"skill {name}: body is empty; skipped")
        return None, warnings
    options = _options(name, meta, warnings)
    skill = Skill(
        name=name,
        description=description,
        body=text_body,
        source=source,
        applies_to=options.applies_to,
        agents=options.agents,
        priority=options.priority,
        always=options.always,
        path=path,
    )
    return skill, warnings


def skill_from_payload(payload: SkillPayload) -> Skill:
    return Skill(
        name=payload.name,
        description=" ".join(payload.description.split()),
        body=payload.body.strip(),
        source="payload",
    )


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != _FENCE:
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == _FENCE:
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    return None, text


def _mapping(front: str) -> dict[str, Any] | None:
    try:
        data: Any = yaml.safe_load(front)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return {str(key): value for key, value in data.items()}


def _key_warnings(name: str, meta: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for key in sorted(meta):
        if key in _KNOWN_KEYS:
            continue
        if key in _AUTHORITY_KEYS:
            warnings.append(f"skill {name} tried to set '{key}'; ignored")
        else:
            warnings.append(
                f"skill {name} has unknown frontmatter key '{key}'; ignored"
            )
    return warnings


def _description(name: str, value: Any, warnings: list[str]) -> str | None:
    if not isinstance(value, str):
        return None
    flat = " ".join(value.split())
    if not flat:
        return None
    if len(flat) > _DESCRIPTION_MAX:
        warnings.append(
            f"skill {name}: description truncated to {_DESCRIPTION_MAX} characters"
        )
        flat = flat[:_DESCRIPTION_MAX]
    return flat


def _options(name: str, meta: dict[str, Any], warnings: list[str]) -> _Options:
    return _Options(
        applies_to=_string_list(name, "applies_to", meta.get("applies_to"), warnings),
        agents=_string_list(name, "agents", meta.get("agents"), warnings),
        priority=_priority(name, meta.get("priority"), warnings),
        always=_flag(name, meta.get("always"), warnings),
    )


def _string_list(
    name: str, key: str, value: Any, warnings: list[str]
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list) and all(_is_pattern(item) for item in value):
        return tuple(str(item).strip() for item in value)
    warnings.append(
        f"skill {name}: '{key}' must be a list of non-empty strings; ignored"
    )
    return ()


def _is_pattern(item: Any) -> bool:
    return isinstance(item, str) and 0 < len(item.strip()) <= _PATTERN_MAX


def _priority(name: str, value: Any, warnings: list[str]) -> int:
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    warnings.append(f"skill {name}: 'priority' must be an integer; ignored")
    return 0


def _flag(name: str, value: Any, warnings: list[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    warnings.append(f"skill {name}: 'always' must be true or false; ignored")
    return False
