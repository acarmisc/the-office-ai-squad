"""Intent classification: deterministic rules first, then an injected classifier."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final, Literal

from code_squad._common.contract import InvocationRequest, Mode

Intent = Literal["mr_review", "incident", "implement", "question"]
INTENTS: Final[tuple[Intent, ...]] = ("mr_review", "incident", "implement", "question")
Classifier = Callable[[str], str]

_MODE_INTENT: Final[dict[Mode, Intent]] = {
    Mode.REVIEW: "mr_review",
    Mode.TROUBLESHOOT: "incident",
    Mode.IMPLEMENTER: "implement",
    Mode.QUESTION: "question",
}
_INCIDENT: Final = re.compile(
    r"\b(incidents?|alerts?|5xx|down|crash ?loop\w*)\b", re.IGNORECASE
)
_IMPLEMENT: Final = re.compile(r"\b(implement|build|add feature)\b", re.IGNORECASE)
_ISSUE_REF: Final = re.compile(r"(#\d+|/issues/\d+|\bissue\s+\d+\b)", re.IGNORECASE)
_NUMBER: Final = re.compile(r"^!?#?\d+$")


def classify_intent(
    request: InvocationRequest, classifier: Classifier | None = None
) -> Intent:
    """Return the intent of a request. The classifier is consulted only when the rules
    cannot decide; without one, a numeric target means a review and anything else a
    question (the safe default: no writes)."""
    if request.mode is not None and request.mode in _MODE_INTENT:
        return _MODE_INTENT[request.mode]
    text = request.prompt
    if _INCIDENT.search(text):
        return "incident"
    if _IMPLEMENT.search(text) and _ISSUE_REF.search(text):
        return "implement"
    if is_numeric_target(request.target):
        return "mr_review"
    if classifier is not None:
        return parse_intent(classifier(text))
    return "question"


def parse_intent(answer: str) -> Intent:
    word = answer.strip().strip(".`'\"").lower()
    if word in INTENTS:
        return word
    return "question"


def is_numeric_target(target: str | None) -> bool:
    return target is not None and _NUMBER.match(target.strip()) is not None
