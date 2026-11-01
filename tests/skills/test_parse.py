from __future__ import annotations

from code_squad._common.contract import SkillPayload
from code_squad._common.skills.parse import parse_skill_md, skill_from_payload
from tests.skills.support import skill_md


def test_frontmatter_and_body_are_parsed() -> None:
    text = skill_md(
        "react-query-conventions",
        description="Query keys.",
        body="Use arrays for keys.",
        extra="applies_to: ['src/**/*.tsx']\npriority: 7\nalways: true\n",
    )
    skill, warnings = parse_skill_md(text, path=".agents/skills/x/SKILL.md")
    assert warnings == []
    assert skill is not None
    assert skill.name == "react-query-conventions"
    assert skill.description == "Query keys."
    assert skill.body == "Use arrays for keys."
    assert skill.applies_to == ("src/**/*.tsx",)
    assert skill.priority == 7
    assert skill.always is True
    assert skill.source == "repo"
    assert skill.path == ".agents/skills/x/SKILL.md"


def test_crlf_line_endings_are_accepted() -> None:
    text = skill_md("crlf", body="line").replace("\n", "\r\n")
    skill, warnings = parse_skill_md(text, path="p")
    assert warnings == []
    assert skill is not None and skill.body == "line"


def test_invalid_names_are_skipped_with_warning() -> None:
    for bad in ("Bad_Name", "-leading", "has space", "x" * 65):
        skill, warnings = parse_skill_md(skill_md(bad), path="p")
        assert skill is None
        assert any("name must match" in warning for warning in warnings)


def test_valid_name_edges_are_accepted() -> None:
    for good in ("a", "ok.name-1_x", "9lives", "x" * 64):
        skill, _warnings = parse_skill_md(skill_md(good), path="p")
        assert skill is not None, good


def test_missing_frontmatter_is_skipped() -> None:
    skill, warnings = parse_skill_md("# just markdown\n", path="p")
    assert skill is None
    assert warnings == ["p: missing YAML frontmatter; skipped"]


def test_unterminated_frontmatter_is_skipped() -> None:
    skill, warnings = parse_skill_md("---\nname: abc\n", path="p")
    assert skill is None
    assert "missing YAML frontmatter" in warnings[0]


def test_invalid_yaml_is_skipped() -> None:
    skill, warnings = parse_skill_md("---\nname: [unclosed\n---\nbody\n", path="p")
    assert skill is None
    assert warnings == ["p: frontmatter is not a valid YAML mapping; skipped"]


def test_frontmatter_must_be_a_mapping() -> None:
    skill, warnings = parse_skill_md("---\n- a\n- b\n---\nbody\n", path="p")
    assert skill is None
    assert "not a valid YAML mapping" in warnings[0]


def test_missing_description_or_empty_body_is_skipped() -> None:
    no_description, warnings = parse_skill_md("---\nname: abc\n---\nbody\n", path="p")
    assert no_description is None
    assert "description must be a non-empty string" in warnings[0]

    empty_body, body_warnings = parse_skill_md(skill_md("abc", body="   "), path="p")
    assert empty_body is None
    assert body_warnings == ["skill abc: body is empty; skipped"]


def test_authority_keys_are_stripped_with_warning() -> None:
    extra = "tools: [publish_review]\ndry_run: false\npost: true\n"
    skill, warnings = parse_skill_md(skill_md("hostile", extra=extra), path="p")
    assert skill is not None
    assert "skill hostile tried to set 'tools'; ignored" in warnings
    assert "skill hostile tried to set 'dry_run'; ignored" in warnings
    assert "skill hostile tried to set 'post'; ignored" in warnings
    assert not hasattr(skill, "tools")
    assert not hasattr(skill, "dry_run")


def test_every_authority_key_is_reported() -> None:
    keys = (
        "tools",
        "allowed_tools",
        "dry_run",
        "post",
        "policy",
        "output_schema",
        "system",
        "permissions",
    )
    extra = "".join(f"{key}: x\n" for key in keys)
    skill, warnings = parse_skill_md(skill_md("keys", extra=extra), path="p")
    assert skill is not None
    for key in keys:
        assert f"skill keys tried to set '{key}'; ignored" in warnings


def test_unknown_key_is_ignored_with_warning() -> None:
    skill, warnings = parse_skill_md(skill_md("odd", extra="colour: teal\n"), path="p")
    assert skill is not None
    assert warnings == ["skill odd has unknown frontmatter key 'colour'; ignored"]


def test_wrongly_typed_options_fall_back_to_defaults() -> None:
    extra = "applies_to: 42\nagents: [1, 2]\npriority: high\nalways: 'yes'\n"
    skill, warnings = parse_skill_md(skill_md("typed", extra=extra), path="p")
    assert skill is not None
    assert skill.applies_to == ()
    assert skill.agents == ()
    assert skill.priority == 0
    assert skill.always is False
    assert len(warnings) == 4


def test_boolean_is_not_accepted_as_priority() -> None:
    text = skill_md("flag", extra="priority: true\n")
    skill, warnings = parse_skill_md(text, path="p")
    assert skill is not None
    assert skill.priority == 0
    assert "'priority' must be an integer; ignored" in warnings[0]


def test_long_description_is_flattened_and_capped() -> None:
    text = skill_md("long", description="word " * 400)
    skill, warnings = parse_skill_md(text, path="p")
    assert skill is not None
    assert len(skill.description) == 1024
    assert any("description truncated" in warning for warning in warnings)


def test_payload_becomes_payload_skill_with_flattened_description() -> None:
    payload = SkillPayload(
        name="design-system", description="Line one\nline two", body="  Use tokens.  "
    )
    skill = skill_from_payload(payload)
    assert skill.source == "payload"
    assert skill.description == "Line one line two"
    assert skill.body == "Use tokens."
    assert skill.path is None
