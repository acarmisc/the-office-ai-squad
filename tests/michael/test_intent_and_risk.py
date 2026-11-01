from __future__ import annotations

from typing import Any

import pytest

from code_squad._common.config.schema import RoutingConfig
from code_squad._common.contract import InvocationRequest
from code_squad._common.fake_model import ScriptedModel, Text, Turn
from code_squad._common.vcs.base import FileDiff, Hunk
from code_squad.michael.intent import classify_intent, parse_intent
from code_squad.michael.llm import llm_intent_classifier
from code_squad.michael.risk import risk_tier
from tests.support import factory_of


def _request(**overrides: Any) -> InvocationRequest:
    values: dict[str, Any] = {"prompt": "Look at this."}
    values.update(overrides)
    return InvocationRequest.model_validate(values)


def _no_calls(text: str) -> str:
    raise AssertionError(f"classifier must not run for {text!r}")


# ----- intent ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "intent"),
    [
        ("review", "mr_review"),
        ("troubleshoot", "incident"),
        ("implementer", "implement"),
        ("question", "question"),
    ],
)
def test_mode_decides_the_intent_without_the_classifier(mode: str, intent: str) -> None:
    assert classify_intent(_request(mode=mode, prompt="down"), _no_calls) == intent


@pytest.mark.parametrize(
    "prompt",
    ["The checkout is down", "alert fired on orders", "5xx spike", "crashloop in prod"],
)
def test_incident_keywords_select_an_incident(prompt: str) -> None:
    assert classify_intent(_request(prompt=prompt), _no_calls) == "incident"


def test_implement_with_an_issue_reference_selects_implementation() -> None:
    request = _request(prompt="Implement issue #12 with a settings page")
    assert classify_intent(request, _no_calls) == "implement"


def test_numeric_target_selects_a_review_without_the_classifier() -> None:
    assert (
        classify_intent(_request(target="!42", prompt="thoughts?"), _no_calls)
        == "mr_review"
    )


def test_classifier_decides_only_when_rules_do_not() -> None:
    seen: list[str] = []

    def classifier(text: str) -> str:
        seen.append(text)
        return "implement"

    assert (
        classify_intent(_request(prompt="add a dark mode"), classifier) == "implement"
    )
    assert seen == ["add a dark mode"]


def test_without_classifier_and_target_the_safe_default_is_question() -> None:
    assert classify_intent(_request(prompt="how does retry work?")) == "question"


@pytest.mark.parametrize(
    ("answer", "intent"),
    [
        ("incident", "incident"),
        ("  MR_REVIEW.  ", "mr_review"),
        ("`implement`", "implement"),
        ("please review the MR", "question"),
        ("", "question"),
    ],
)
def test_parse_intent_accepts_one_word_and_defaults_to_question(
    answer: str, intent: str
) -> None:
    assert parse_intent(answer) == intent


def test_llm_classifier_uses_a_scripted_model_and_wraps_the_request() -> None:
    model = ScriptedModel([Turn((Text("incident"),))])
    classify = llm_intent_classifier(factory_of(model))
    assert classify("the api is failing for everyone") == "incident"
    user_text = str(model.calls[0].messages[0]["content"][0]["text"])
    assert "request:prompt" in user_text
    assert "the api is failing" in user_text


def test_llm_classifier_falls_back_to_question_when_the_model_fails() -> None:
    def broken(*_args: Any) -> Any:
        raise RuntimeError("gateway down")

    assert llm_intent_classifier(broken)("anything") == "question"


# ----- risk --------------------------------------------------------------------


def _diff(path: str, added: list[str], removed: int = 0) -> FileDiff:
    body = [f"+{line}" for line in added] + [
        f"-old {index}" for index in range(removed)
    ]
    patch = f"@@ -1,{removed} +1,{len(added)} @@\n" + "\n".join(body)
    return FileDiff(
        path=path,
        old_path=path,
        status="modified",
        hunks=(Hunk(1, removed, 1, len(added), frozenset(range(1, len(added) + 1))),),
        patch=patch,
        binary=False,
        truncated=False,
    )


def test_small_change_is_low_risk() -> None:
    assessment = risk_tier([_diff("src/a.ts", ["const a = 1;"])], RoutingConfig())
    assert assessment.tier == "low"
    assert assessment.reasons == ()
    assert assessment.changed_lines == 1


def test_size_thresholds_drive_medium_and_high() -> None:
    routing = RoutingConfig()
    medium = risk_tier([_diff("src/a.ts", ["x"] * 300)], routing)
    high = risk_tier([_diff("src/a.ts", ["x"] * 1000)], routing)
    assert medium.tier == "medium"
    assert "300 changed lines" in medium.reasons[0]
    assert high.tier == "high"
    assert "1000 changed lines" in high.reasons[0]


def test_removed_lines_count_towards_size() -> None:
    assessment = risk_tier([_diff("src/a.ts", ["x"], removed=299)], RoutingConfig())
    assert assessment.changed_lines == 300
    assert assessment.tier == "medium"


def test_sensitive_path_raises_the_tier_to_medium() -> None:
    assessment = risk_tier([_diff("src/auth/session.ts", ["x"])], RoutingConfig())
    assert assessment.tier == "medium"
    assert assessment.reasons == ("sensitive path changed: src/auth/session.ts",)


def test_dependency_manifest_raises_the_tier_to_medium() -> None:
    assessment = risk_tier([_diff("package-lock.json", ["x"])], RoutingConfig())
    assert assessment.tier == "medium"
    assert assessment.reasons == ("dependency manifest changed: package-lock.json",)


def test_secret_like_added_line_is_high_and_the_value_is_not_reported() -> None:
    value = "fake-password-for-tests"
    diff = _diff("src/config.ts", [f"const password = '{value}';"])
    assessment = risk_tier([diff], RoutingConfig())
    assert assessment.tier == "high"
    assert assessment.reasons == (
        "secret-like value added (hard-coded password) in src/config.ts",
    )
    assert value not in " ".join(assessment.reasons)


def test_secret_pattern_in_removed_line_is_not_counted() -> None:
    diff = FileDiff(
        path="src/config.ts",
        old_path="src/config.ts",
        status="modified",
        hunks=(),
        patch="@@ -1 +1 @@\n-const api_key = 'fake-token-for-tests';\n+const x = 1;",
        binary=False,
        truncated=False,
    )
    assert risk_tier([diff], RoutingConfig()).tier == "low"


def test_api_key_assignment_is_detected() -> None:
    diff = _diff("src/client.ts", ["api_key: 'fake-token-for-tests'"])
    assert risk_tier([diff], RoutingConfig()).tier == "high"


def test_high_tier_outranks_medium_reasons() -> None:
    diffs = [
        _diff("src/auth/a.ts", ["x"]),
        _diff("src/b.ts", ["const passwd = 'fake-password-for-tests'"]),
    ]
    assessment = risk_tier(diffs, RoutingConfig())
    assert assessment.tier == "high"
    assert assessment.reasons[0].startswith("secret-like value added")
    assert any(reason.startswith("sensitive path") for reason in assessment.reasons)
