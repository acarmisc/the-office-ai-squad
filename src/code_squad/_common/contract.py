from __future__ import annotations

import hashlib
import hmac
import re
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    TypeAdapter,
    field_validator,
    model_validator,
)

_SECRET_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,252}$")
_TOKEN_LIKE = re.compile(
    r"^(glpat-|ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|xox[baprs]-|sk-)"
)
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MODEL_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$")
_LITELLM_TAG = re.compile(r"^[A-Za-z0-9_.-]{1,64}:\S{1,128}$")
_HTTP_URL: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Verdict(StrEnum):
    APPROVE = "approve"
    COMMENT = "comment"
    REQUEST_CHANGES = "request_changes"
    INCOMPLETE = "incomplete"


class RunStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class Mode(StrEnum):
    REVIEW = "review"
    TROUBLESHOOT = "troubleshoot"
    ADVISOR = "advisor"
    IMPLEMENTER = "implementer"
    QUESTION = "question"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.BLOCKER: 3,
    Severity.MAJOR: 2,
    Severity.MINOR: 1,
    Severity.NIT: 0,
}


def severity_rank(severity: Severity) -> int:
    """Higher is more severe."""
    return _SEVERITY_RANK[severity]


def finding_id(
    agent: str,
    file: str,
    line_start: int,
    line_end: int,
    rule_id: str,
    head_sha: str,
) -> str:
    raw = "|".join([agent, file, str(line_start), str(line_end), rule_id, head_sha])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class Finding(_Contract):
    model_config = ConfigDict(frozen=True)

    id: str = ""
    agent: str
    rule_id: str
    category: str
    severity: Severity
    confidence: Confidence
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    head_sha: str
    title: str = Field(max_length=200)
    rationale: str
    suggestion: str | None = None
    references: list[str] = Field(default_factory=list)
    failure_scenario: str | None = None

    @model_validator(mode="after")
    def _check_rules(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        if self.severity is Severity.BLOCKER:
            if self.confidence is Confidence.LOW:
                raise ValueError("blocker findings require confidence medium or high")
            if not (self.failure_scenario or "").strip():
                raise ValueError("blocker findings require a concrete failure_scenario")
        return self

    def with_id(self) -> Finding:
        if self.id:
            return self
        new_id = finding_id(
            self.agent,
            self.file,
            self.line_start,
            self.line_end,
            self.rule_id,
            self.head_sha,
        )
        return self.model_copy(update={"id": new_id})


class SkillPayload(_Contract):
    name: str = Field(pattern=_SKILL_NAME.pattern)
    description: str = Field(max_length=1024)
    body: str
    source: Literal["payload"] = "payload"


class Attachment(_Contract):
    type: Literal["image", "text"]
    name: str
    media_type: str
    data: str
    sha256: str = Field(pattern=_SHA256_HEX.pattern)

    @model_validator(mode="after")
    def _check_digest(self) -> Self:
        digest = hashlib.sha256(self.data.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(digest, self.sha256):
            raise ValueError("sha256 does not match attachment data")
        return self


def _check_secret_name(value: str) -> str:
    if _TOKEN_LIKE.match(value):
        raise ValueError("secret fields take secret names, not token values")
    if not _SECRET_NAME.match(value):
        raise ValueError("secret name must match ^[a-z0-9][a-z0-9._-]{0,252}$")
    return value


def _check_http_url(value: str) -> str:
    url = _HTTP_URL.validate_python(value)
    if url.username or url.password:
        raise ValueError("vcs_base_url must not contain credentials")
    return str(url)


SecretName = Annotated[str, AfterValidator(_check_secret_name)]
BaseUrl = Annotated[str, AfterValidator(_check_http_url)]


class ProjectConfigOverride(_Contract):
    vcs_provider: Literal["gitlab", "github"] | None = None
    vcs_base_url: BaseUrl | None = None
    vcs_token_secret: SecretName | None = None
    llm_api_key_secret: SecretName | None = None
    skills_repo_path: str | None = None
    skills_ref: Literal["base", "head"] = "base"
    config_ref: Literal["base", "head"] = "base"
    overrides: dict[str, Any] = Field(default_factory=dict)


def _check_tags(tags: list[str]) -> list[str]:
    if len(tags) > 20:
        raise ValueError("at most 20 litellm_tags")
    for tag in tags:
        if not _LITELLM_TAG.match(tag):
            raise ValueError("litellm_tags must be 'key:value' strings")
    return tags


class InvocationRequest(_Contract):
    @field_validator("post", mode="before")
    @classmethod
    def _reject_null_post(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("must be true or false when present")
        return value

    prompt: str = Field(min_length=1, max_length=20000)
    project: str | None = Field(default=None, max_length=256)
    target: str | None = Field(default=None, max_length=256)
    mode: Mode | None = None
    post: StrictBool | None = None
    model: str | None = Field(default=None, pattern=_MODEL_ALIAS.pattern)
    litellm_tags: Annotated[list[str], AfterValidator(_check_tags)] = Field(
        default_factory=list
    )
    project_config: ProjectConfigOverride | None = None
    skills: list[SkillPayload] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=128)


class Stats(_Contract):
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_hint: float | None = None
    config_hash: str | None = None
    skills_applied: list[str] = Field(default_factory=list)
    tool_calls: dict[str, int] = Field(default_factory=dict)


class Posted(_Contract):
    notes: int = 0
    discussions: int = 0
    status: str | None = None
    urls: list[str] = Field(default_factory=list)


class InvocationResult(_Contract):
    agent: str
    status: RunStatus
    verdict: Verdict
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    stats: Stats = Field(default_factory=Stats)
    posted: Posted = Field(default_factory=Posted)
    warnings: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class FinishPayload(_Contract):
    verdict: Verdict
    summary: str = Field(min_length=1, max_length=4000)
    findings: list[Finding] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("verdict")
    @classmethod
    def _reserve_incomplete(cls, value: Verdict) -> Verdict:
        if value is Verdict.INCOMPLETE:
            raise ValueError(
                "verdict 'incomplete' is set by the runtime, not by finish()"
            )
        return value
