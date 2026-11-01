from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from code_squad._common.contract import (
    Attachment,
    Confidence,
    Finding,
    FinishPayload,
    InvocationRequest,
    ProjectConfigOverride,
    Severity,
    SkillPayload,
    Verdict,
    finding_id,
    severity_rank,
)
from tests.support import finding_dict


def _finding(**overrides: Any) -> Finding:
    return Finding.model_validate(finding_dict(**overrides))


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def test_finding_id_is_stable_and_sixteen_hex_chars() -> None:
    first = finding_id("jim", "a.tsx", 1, 2, "R1", "sha")
    second = finding_id("jim", "a.tsx", 1, 2, "R1", "sha")
    assert first == second
    assert len(first) == 16
    int(first, 16)


def test_finding_id_changes_with_each_anchor_component() -> None:
    base = finding_id("jim", "a.tsx", 1, 2, "R1", "sha")
    variants = [
        finding_id("angela", "a.tsx", 1, 2, "R1", "sha"),
        finding_id("jim", "b.tsx", 1, 2, "R1", "sha"),
        finding_id("jim", "a.tsx", 2, 2, "R1", "sha"),
        finding_id("jim", "a.tsx", 1, 3, "R1", "sha"),
        finding_id("jim", "a.tsx", 1, 2, "R2", "sha"),
        finding_id("jim", "a.tsx", 1, 2, "R1", "other"),
    ]
    assert base not in variants
    assert len(set(variants)) == len(variants)


def test_with_id_fills_empty_id_once() -> None:
    finding = _finding()
    assigned = finding.with_id()
    assert assigned.id == finding_id(
        "michael", "src/app.py", 10, 12, "TEST-001", "a" * 40
    )
    assert assigned.with_id() is assigned
    assert finding.id == ""


def test_blocker_requires_medium_or_high_confidence() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        _finding(severity="blocker", confidence="low", failure_scenario="x")


def test_blocker_requires_concrete_failure_scenario() -> None:
    with pytest.raises(ValidationError, match="failure_scenario"):
        _finding(severity="blocker", confidence="high")
    with pytest.raises(ValidationError, match="failure_scenario"):
        _finding(severity="blocker", confidence="medium", failure_scenario="   ")


def test_blocker_with_scenario_and_confidence_is_accepted() -> None:
    finding = _finding(
        severity="blocker", confidence="medium", failure_scenario="Requests leak."
    )
    assert finding.severity is Severity.BLOCKER
    assert finding.confidence is Confidence.MEDIUM


def test_line_end_must_not_precede_line_start() -> None:
    with pytest.raises(ValidationError, match="line_end"):
        _finding(line_start=9, line_end=8)


def test_line_numbers_start_at_one() -> None:
    with pytest.raises(ValidationError):
        _finding(line_start=0, line_end=0)


def test_finding_title_is_limited_to_200_characters() -> None:
    with pytest.raises(ValidationError):
        _finding(title="x" * 201)


def test_finding_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError, match="extra"):
        _finding(unexpected="value")


def test_request_rejects_extra_keys_and_string_post() -> None:
    with pytest.raises(ValidationError):
        InvocationRequest.model_validate({"prompt": "x", "bogus": 1})
    with pytest.raises(ValidationError):
        InvocationRequest.model_validate({"prompt": "x", "post": "false"})
    with pytest.raises(ValidationError):
        InvocationRequest.model_validate({"prompt": "x", "post": 0})


def test_request_accepts_real_booleans_and_absent_post() -> None:
    assert (
        InvocationRequest.model_validate({"prompt": "x", "post": False}).post is False
    )
    assert InvocationRequest.model_validate({"prompt": "x"}).post is None


def test_attachment_digest_must_match_data() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        Attachment(
            type="text",
            name="log.txt",
            media_type="text/plain",
            data="hello",
            sha256="0" * 64,
        )


def test_attachment_with_matching_digest_is_accepted() -> None:
    attachment = Attachment(
        type="text",
        name="log.txt",
        media_type="text/plain",
        data="hello",
        sha256=_sha("hello"),
    )
    assert attachment.sha256 == _sha("hello")


def test_attachment_digest_must_be_lowercase_hex() -> None:
    with pytest.raises(ValidationError):
        Attachment(
            type="text",
            name="log.txt",
            media_type="text/plain",
            data="hello",
            sha256=_sha("hello").upper(),
        )


@pytest.mark.parametrize(
    "name",
    [
        "glpat-fake-only",
        "ghp_abcdefghijklmnopqrstuvwxyz",
        "gitlab-token/prod",
        "Has Upper",
        "with space",
        "trailing/slash",
    ],
)
def test_secret_fields_reject_token_like_or_unsafe_values(name: str) -> None:
    with pytest.raises(ValidationError):
        ProjectConfigOverride(vcs_token_secret=name)


def test_secret_fields_accept_secret_names() -> None:
    config = ProjectConfigOverride(
        vcs_token_secret="gitlab-token-acme", llm_api_key_secret="litellm.key"
    )
    assert config.vcs_token_secret == "gitlab-token-acme"


def test_base_url_is_normalised_and_credentials_are_refused() -> None:
    config = ProjectConfigOverride(vcs_base_url="https://gitlab.example.com")
    assert config.vcs_base_url is not None
    assert config.vcs_base_url.startswith("https://gitlab.example.com")
    with pytest.raises(ValidationError, match="credentials"):
        ProjectConfigOverride(vcs_base_url="https://user:secret@gitlab.example.com")
    with pytest.raises(ValidationError):
        ProjectConfigOverride(vcs_base_url="not a url")


def test_litellm_tags_must_be_key_value_and_at_most_twenty() -> None:
    assert InvocationRequest(prompt="x", litellm_tags=["team:platform"]).litellm_tags
    with pytest.raises(ValidationError):
        InvocationRequest(prompt="x", litellm_tags=["novalue"])
    with pytest.raises(ValidationError):
        InvocationRequest(prompt="x", litellm_tags=[f"k{i}:v" for i in range(21)])


def test_skill_name_and_source_are_constrained() -> None:
    assert (
        SkillPayload(name="react-hooks.1", description="d", body="b").source
        == "payload"
    )
    with pytest.raises(ValidationError):
        SkillPayload(name="Bad Name", description="d", body="b")
    with pytest.raises(ValidationError):
        SkillPayload.model_validate(
            {"name": "ok", "description": "d", "body": "b", "source": "remote"}
        )


def test_finish_payload_rejects_runtime_reserved_incomplete_verdict() -> None:
    with pytest.raises(ValidationError, match="incomplete"):
        FinishPayload(verdict=Verdict.INCOMPLETE, summary="s")


def test_severity_rank_orders_blocker_first() -> None:
    ranks = [
        severity_rank(s)
        for s in (Severity.BLOCKER, Severity.MAJOR, Severity.MINOR, Severity.NIT)
    ]
    assert ranks == sorted(ranks, reverse=True)
    assert len(set(ranks)) == 4
