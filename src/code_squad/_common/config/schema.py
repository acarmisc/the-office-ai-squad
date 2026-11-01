"""Single source of truth for every configuration key (brief section 4.8).

Every field has a default and a description; every model forbids unknown keys.
Merge policy lives on the fields (see ``meta.py``). ``SquadFields`` holds the
sections and is used for partial overlays; ``SquadConfig`` adds cross-field checks
for the effective config; ``RepoConfig`` adds ``extends`` for repository files.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from code_squad._common.config.meta import ceiling_violations
from code_squad._common.registry import AGENT_IDS

DEFAULT_SECRET_PATTERNS: Final[tuple[str, ...]] = ("^[a-z0-9][a-z0-9._-]*$",)
SECRET_NAME_PATTERN: Final[str] = r"^[a-z0-9][a-z0-9._-]{0,252}$"
EXTRA_AGENT_ID_PATTERN: Final[str] = r"^[a-z][a-z0-9]{1,30}$"

TriggerEvent = Literal[
    "change_request_opened",
    "change_request_updated",
    "change_request_ready",
    "review_requested",
    "comment",
    "issue_assigned",
]
SkillSource = Literal["payload", "repo", "builtin"]
ToolPreset = Literal["review_readonly", "review_publish"]
ApproveMode = Literal["none", "comment", "approve"]
APPROVE_ORDER: Final[tuple[str, ...]] = ("none", "comment", "approve")
ReviewSeverity = Literal["nit", "minor", "major", "blocker"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _field(
    description: str,
    *,
    merge: Literal["free", "tighten_only", "org_only"] = "free",
    mergeable: bool = False,
    tighten: Literal["le", "subset", "true", "false"] | None = None,
    order: list[str] | None = None,
    ceiling: str | None = None,
    secret: bool = False,
    tool_names: bool = False,
    **kwargs: Any,
) -> Any:
    extra: dict[str, Any] = {}
    if merge != "free":
        extra["x-merge"] = merge
    if mergeable:
        extra["x-mergeable-set"] = True
    if tighten is not None:
        extra["x-tighten"] = tighten
    if order is not None:
        extra["x-order"] = order
    if ceiling is not None:
        extra["x-ceiling"] = ceiling
    if secret:
        extra["x-secret-ref"] = True
    if tool_names:
        extra["x-tool-names"] = True
    return Field(description=description, json_schema_extra=extra or None, **kwargs)


def _secret_field(description: str, **kwargs: Any) -> Any:
    return _field(
        description,
        secret=True,
        pattern=SECRET_NAME_PATTERN,
        **kwargs,
    )


# ---------------------------------------------------------------- vcs


class VcsAuth(_Base):
    token_secret: str | None = _secret_field(
        "Secret name holding the VCS access token.", default=None
    )
    app_id: int | None = _field("GitHub App id (numeric).", default=None, ge=1)
    installation_id: int | None = _field(
        "GitHub App installation id (numeric).", default=None, ge=1
    )
    private_key_secret: str | None = _secret_field(
        "Secret name holding the GitHub App private key (PEM).", default=None
    )


class VcsConfig(_Base):
    provider: Literal["gitlab", "github", "auto"] = _field(
        "VCS provider. 'auto' infers it from base_url for github.com and gitlab.com. "
        "Org-only: set it in the org config or the project registry.",
        default="auto",
        merge="org_only",
    )
    base_url: str | None = _field(
        "API base URL for self-managed or enterprise hosts. Org-only.",
        default=None,
        merge="org_only",
    )
    auth: VcsAuth = _field(
        "Credentials as secret names, matched against secrets.allowed_patterns.",
        default_factory=VcsAuth,
        merge="org_only",
    )
    bot_username: str | None = _field(
        "Login of the bot identity, used for loop prevention.", default=None
    )
    status_context_template: str = _field(
        "Commit status or check name template; {agent} is the agent id.",
        default="ai-review/{agent}",
        max_length=128,
    )
    approve_mode: ApproveMode = _field(
        "Whether a positive verdict may approve the change request. Can only "
        "become stricter below the org layer (none < comment < approve).",
        default="none",
        merge="tighten_only",
        tighten="le",
        order=list(APPROVE_ORDER),
    )
    labels: dict[str, str] = _field(
        "Label name overrides, keyed by logical label name.", default_factory=dict
    )
    comment_style: Literal["inline", "summary", "both"] = _field(
        "Publish inline discussions, a summary note, or both.", default="both"
    )
    protected_branches: list[str] = _field(
        "Branches the squad must never write to. Lower layers may only add.",
        default_factory=list,
        mergeable=True,
    )


# ---------------------------------------------------------------- trigger


class TriggerConfig(_Base):
    events: list[TriggerEvent] = _field(
        "Events that start a review.",
        default_factory=lambda: [
            "change_request_opened",
            "change_request_ready",
            "review_requested",
            "comment",
            "issue_assigned",
        ],
    )
    on_push: bool = _field(
        "Also react to new pushes (change_request_updated).", default=False
    )
    allowed_commenters: list[str] = _field(
        "Users whose comments may trigger the squad. Empty means nobody. "
        "Lower layers may only shrink the list.",
        default_factory=list,
        merge="tighten_only",
        tighten="subset",
    )
    debounce_seconds: int = _field(
        "Quiet period before a burst of events starts one run.",
        default=30,
        ge=0,
        le=3600,
    )
    skip_draft: bool = _field("Skip draft change requests.", default=True)
    skip_labels: list[str] = _field(
        "Change requests carrying any of these labels are skipped.",
        default_factory=lambda: ["skip-squad"],
    )
    skip_wip_titles: bool = _field(
        "Skip change requests whose title starts with WIP or Draft.", default=True
    )
    skip_bot_authors: bool = _field(
        "Skip change requests and comments authored by other bots. The bot's own "
        "events are always ignored.",
        default=False,
    )
    allowed_assigners: list[str] = _field(
        "Users who may assign an issue to the bot to start a pam run. Empty means "
        "nobody. Lower layers may only shrink the list.",
        default_factory=list,
        merge="tighten_only",
        tighten="subset",
    )


# ---------------------------------------------------------------- agents


class Budgets(_Base):
    wall_clock_seconds: int = _field(
        "Maximum wall-clock seconds per invocation. Lower layers may only lower it.",
        default=900,
        ge=1,
        merge="tighten_only",
        tighten="le",
        ceiling="limits.max_wall_clock_seconds",
    )
    tool_calls: int = _field(
        "Maximum tool calls per invocation. Lower layers may only lower it.",
        default=100,
        ge=1,
        merge="tighten_only",
        tighten="le",
    )


class AgentConfig(_Base):
    enabled: bool = _field("Whether this agent runs at all.", default=True)
    model: str | None = _field(
        "Model alias for this agent. Defaults to the agent's built-in alias.",
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$",
    )
    fallback_model: str | None = _field(
        "Model alias used once after a truncation or overload.",
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$",
    )
    temperature: float | None = _field(
        "Sampling temperature between 0 and 1.", default=None, ge=0, le=1
    )
    max_tokens: int | None = _field(
        "Model output token cap per call. Cannot exceed limits.max_tokens.",
        default=None,
        ge=1,
        merge="tighten_only",
        tighten="le",
        ceiling="limits.max_tokens",
    )
    max_iterations: int | None = _field(
        "Model turns per invocation. Cannot exceed limits.max_iterations.",
        default=None,
        ge=1,
        merge="tighten_only",
        tighten="le",
        ceiling="limits.max_iterations",
    )
    budgets: Budgets = _field(
        "Per-invocation budgets. Each is capped by the matching limits.* value.",
        default_factory=Budgets,
    )
    prompt_extra: str | None = _field(
        "Extra guidance appended to the agent prompt. Untrusted guidance: it cannot "
        "override system rules. Length is capped by limits.max_prompt_extra_chars.",
        default=None,
        max_length=20000,
        merge="tighten_only",
        ceiling="limits.max_prompt_extra_chars",
    )
    knowledge_extra_dirs: list[str] = _field(
        "Additional knowledge directories the agent may read. Org-only.",
        default_factory=list,
        merge="org_only",
    )
    tool_allowlist: list[str] | None = _field(
        "Restrict the agent to these tools. Lower layers may only pick a subset of "
        "the base list; null means the agent's full tool set. External-write tools "
        "cannot be listed below the org layer.",
        default=None,
        merge="tighten_only",
        tighten="subset",
        tool_names=True,
    )


# ---------------------------------------------------------------- routing


class Route(_Base):
    glob: str = _field(
        "Changed-file glob. '**' crosses directories, '*' does not.",
        min_length=1,
        max_length=256,
    )
    agents: list[str] = _field("Agents to run when the glob matches.", min_length=1)
    requires: list[str] = _field(
        "Manifest hints the repository must satisfy, for example 'react'.",
        default_factory=list,
    )


class SizeThresholds(_Base):
    medium: int = _field(
        "Changed lines at or above which the risk tier is medium.",
        default=300,
        ge=1,
        merge="tighten_only",
        tighten="le",
    )
    high: int = _field(
        "Changed lines at or above which the risk tier is high.",
        default=1000,
        ge=1,
        merge="tighten_only",
        tighten="le",
    )


def _default_routes() -> list[Route]:
    return [
        Route(glob="**/*.tsx", agents=["jim"], requires=["react"]),
        Route(glob="**/*.jsx", agents=["jim"], requires=["react"]),
        Route(glob="**/*.ts", agents=["jim"], requires=["react"]),
        Route(glob="**/*.js", agents=["jim"], requires=["react"]),
        Route(glob="**/*.java", agents=["angela"]),
        Route(glob="**/*.kt", agents=["angela"]),
        Route(glob="**/pom.xml", agents=["angela"]),
        Route(glob="**/build.gradle*", agents=["angela"]),
        Route(glob=".gitlab-ci.yml", agents=["darryl"]),
        Route(glob=".github/workflows/**", agents=["darryl"]),
        Route(glob="**/Dockerfile*", agents=["darryl"]),
        Route(glob="**/*.tf", agents=["darryl"]),
        Route(glob="**/Chart.yaml", agents=["darryl"]),
        Route(glob="**/values*.yaml", agents=["darryl"]),
        Route(glob="deploy/**", agents=["darryl"]),
    ]


class RoutingConfig(_Base):
    routes: list[Route] = _field(
        "Changed-file glob to agent table. Lower layers may only add routes.",
        default_factory=_default_routes,
        mergeable=True,
    )
    sensitive_paths: list[str] = _field(
        "Paths that raise the risk tier. Lower layers may only add patterns.",
        default_factory=lambda: [
            "**/auth/**",
            "**/payment*/**",
            "**/security/**",
            "infra/**",
            ".gitlab-ci.yml",
            ".github/workflows/**",
            "**/Dockerfile*",
            "**/*.tf",
        ],
        mergeable=True,
    )
    size_thresholds: SizeThresholds = _field(
        "Changed-line thresholds for the risk tier. Lower layers may only lower them.",
        default_factory=SizeThresholds,
        merge="tighten_only",
    )
    always_run: list[str] = _field(
        "Agents that run on every review. Lower layers may only add agents.",
        default_factory=lambda: ["dwight"],
        mergeable=True,
    )
    specialist_urls: dict[str, str] = _field(
        "Base URL per specialist agent for HTTP fan-out. Org-only.",
        default_factory=dict,
        merge="org_only",
    )
    timeouts_seconds: dict[str, int] = _field(
        "Seconds per specialist call. The key 'default' applies to unlisted agents.",
        default_factory=lambda: {"default": 600},
    )
    fan_out_concurrency: int = _field(
        "Specialists called in parallel.", default=4, ge=1, le=32
    )
    specialists_post: bool = _field(
        "Let specialists publish directly instead of returning findings to michael. "
        "Lower layers may only keep it false.",
        default=False,
        merge="tighten_only",
        tighten="false",
    )


# ---------------------------------------------------------------- review


class VerdictPolicy(_Base):
    major_threshold: int = _field(
        "Number of major findings at or above which the verdict becomes 'comment' "
        "instead of 'approve' (default 1: any major prevents approve).",
        default=1,
        ge=0,
    )


class ReviewConfig(_Base):
    ignore_globs: list[str] = _field(
        "Files excluded from review: generated, vendored, lockfiles, snapshots. "
        "Lower layers may only add globs.",
        default_factory=lambda: [
            "**/package-lock.json",
            "**/pnpm-lock.yaml",
            "**/yarn.lock",
            "**/poetry.lock",
            "**/Cargo.lock",
            "dist/**",
            "build/**",
            "vendor/**",
            "**/__snapshots__/**",
            "**/*.min.js",
            "**/generated/**",
        ],
        mergeable=True,
    )
    max_diff_bytes: int = _field(
        "Diffs larger than this are chunked or truncated.",
        default=400000,
        ge=1000,
    )
    min_confidence_to_publish: Literal["low", "medium", "high"] = _field(
        "Findings below this confidence are not published.", default="medium"
    )
    min_severity_inline: ReviewSeverity = _field(
        "Findings below this severity are summarised, not posted inline.",
        default="minor",
    )
    max_findings: int = _field(
        "Maximum findings published per run.", default=30, ge=1, le=500
    )
    verdict: VerdictPolicy = _field(
        "Verdict thresholds.", default_factory=VerdictPolicy
    )


# ---------------------------------------------------------------- skills


class SkillsConfig(_Base):
    paths: list[str] = _field(
        "Candidate skill directories in precedence order.",
        default_factory=lambda: [".agents/skills", ".claude/skills", ".squad/skills"],
    )
    ref: Literal["base", "head"] = _field(
        "Branch skills are read from. 'head' lets a change request edit its own "
        "review rules, so it is org-only.",
        default="base",
        merge="org_only",
    )
    max_skills: int = _field(
        "Maximum skills loaded per run. Lower layers may only lower it.",
        default=20,
        ge=1,
        merge="tighten_only",
        tighten="le",
        ceiling="limits.max_skills",
    )
    max_skill_bytes: int = _field(
        "Maximum bytes per skill body; larger bodies are truncated with a warning. "
        "Lower layers may only lower it.",
        default=20480,
        ge=1,
        merge="tighten_only",
        tighten="le",
        ceiling="limits.max_skill_bytes",
    )
    max_total_bytes: int = _field(
        "Maximum total skill bytes per run. Lower layers may only lower it.",
        default=81920,
        ge=1,
        merge="tighten_only",
        tighten="le",
        ceiling="limits.max_total_skill_bytes",
    )
    allowed_sources: list[SkillSource] = _field(
        "Skill sources in use. Lower layers may only pick a subset.",
        default_factory=lambda: ["payload", "repo", "builtin"],
        merge="tighten_only",
        tighten="subset",
    )


# ---------------------------------------------------------------- security


class SecuritySources(_Base):
    osv: bool = _field("Query OSV for known vulnerabilities.", default=True)
    nvd: bool = _field("Query the NVD for CVSS data.", default=True)
    ghsa: bool = _field("Query GitHub advisories.", default=True)
    kev: bool = _field("Query the CISA KEV catalogue.", default=True)
    epss: bool = _field("Query FIRST EPSS scores.", default=True)


class SeverityMapping(_Base):
    kev_is_blocker: bool = _field(
        "A KEV-listed vulnerability is a blocker.",
        default=True,
        merge="tighten_only",
        tighten="true",
    )
    epss_major: float = _field(
        "EPSS score at or above which a finding is major.",
        default=0.1,
        ge=0,
        le=1,
        merge="tighten_only",
        tighten="le",
    )
    cvss_blocker: float = _field(
        "CVSS score at or above which a finding is a blocker.",
        default=9.0,
        ge=0,
        le=10,
        merge="tighten_only",
        tighten="le",
    )
    cvss_major: float = _field(
        "CVSS score at or above which a finding is major.",
        default=7.0,
        ge=0,
        le=10,
        merge="tighten_only",
        tighten="le",
    )


class AcceptedRisk(_Base):
    id: str = _field(
        "Advisory or rule id being accepted.", min_length=1, max_length=128
    )
    reason: str = _field("Why the risk is accepted. Required.", min_length=1)
    expires: date = _field(
        "Date after which the acceptance is ignored with a warning.",
    )
    package: str | None = _field(
        "Package name the acceptance is limited to. The finding must name it.",
        default=None,
        min_length=1,
        max_length=214,
    )
    path: str | None = _field(
        "Glob of changed files the acceptance is limited to.",
        default=None,
        min_length=1,
        max_length=256,
    )


class SecurityConfig(_Base):
    sources: SecuritySources = _field(
        "Intelligence sources switched on.", default_factory=SecuritySources
    )
    allowed_hosts: list[str] = _field(
        "Hosts intelligence clients may contact. Org-only.",
        default_factory=lambda: [
            "api.osv.dev",
            "services.nvd.nist.gov",
            "api.github.com",
            "www.cisa.gov",
            "api.first.org",
        ],
        merge="org_only",
    )
    cache_ttl_seconds: int = _field("Advisory cache lifetime.", default=21600, ge=0)
    severity_mapping: SeverityMapping = _field(
        "Thresholds mapping advisory data to severity. Lower layers may only lower "
        "the numeric thresholds.",
        default_factory=SeverityMapping,
    )
    offline_mode: Literal["fail_incomplete", "low_confidence"] = _field(
        "When advisory sources are unreachable: mark the run incomplete, or keep "
        "going with low-confidence findings.",
        default="low_confidence",
    )
    accepted_risks: list[AcceptedRisk] = _field(
        "Accepted advisories, applied before publication. Expired entries are "
        "ignored with a warning. Org-only.",
        default_factory=list,
        merge="org_only",
    )


# ---------------------------------------------------------------- ops


class OpsConfig(_Base):
    allowed_namespaces: list[str] = _field(
        "Kubernetes namespaces darryl may read. Org-only.",
        default_factory=list,
        merge="org_only",
    )
    prometheus_url: str | None = _field(
        "Prometheus endpoint. Org-only (egress).", default=None, merge="org_only"
    )
    loki_url: str | None = _field(
        "Loki endpoint. Org-only (egress).", default=None, merge="org_only"
    )
    argocd_url: str | None = _field(
        "Argo CD endpoint. Org-only (egress).", default=None, merge="org_only"
    )
    redaction_patterns: list[str] = _field(
        "Regular expressions redacted from tool output. Lower layers may only add.",
        default_factory=list,
        mergeable=True,
    )
    max_log_lines: int = _field(
        "Maximum log lines returned per query.", default=500, ge=1, le=10000
    )
    max_query_points: int = _field(
        "Maximum points per metrics range query.", default=11000, ge=1
    )


# ---------------------------------------------------------------- implementer


class SandboxConfig(_Base):
    timeout_seconds: int = _field(
        "Wall-clock limit for one implementation run. Lower layers may only lower it; "
        "cannot exceed limits.max_wall_clock_seconds.",
        default=1800,
        ge=1,
        merge="tighten_only",
        tighten="le",
        ceiling="limits.max_wall_clock_seconds",
    )


class GitIdentity(_Base):
    name: str = _field(
        "Commit author name.", default="pam (code-squad)", min_length=1, max_length=128
    )
    email: str = _field(
        "Commit author email.",
        default="pam@code-squad.invalid",
        min_length=3,
        max_length=254,
    )


class ImplementerConfig(_Base):
    branch_template: str = _field(
        "Branch name template; {task_key} and {slug} are filled in.",
        default="pam/{task_key}-{slug}",
        min_length=1,
        max_length=200,
    )
    commit_template: str = _field(
        "Commit message template; {summary} is filled in.",
        default="feat: {summary}",
        max_length=200,
    )
    mr_title_template: str = _field(
        "Change request title template.",
        default="{task_key}: {summary}",
        max_length=200,
    )
    mr_body_template: str = _field(
        "Change request body template with what, why, how tested and risks sections.",
        default=(
            "## What\n{summary}\n\n## Why\n{why}\n\n## How tested\n{tests}\n\n"
            "## Risks\n{risks}\n"
        ),
        max_length=8000,
    )
    labels: list[str] = _field(
        "Labels added to every change request.",
        default_factory=lambda: ["ai-generated"],
    )
    reviewers: list[str] = _field(
        "Reviewers requested on every change request.", default_factory=list
    )
    assignees: list[str] = _field(
        "Assignees set on every change request.", default_factory=list
    )
    mr_draft: bool = _field("Open change requests as drafts.", default=False)
    check_commands: list[str] | None = _field(
        "Commands run in the sandbox to verify the change. Null means detect them "
        "from the repository.",
        default=None,
        max_length=20,
    )
    sandbox: SandboxConfig = _field("Sandbox settings.", default_factory=SandboxConfig)
    git_identity: GitIdentity = _field(
        "Git author for implementer commits.", default_factory=GitIdentity
    )
    protected_paths: list[str] = _field(
        "Paths the implementer must not touch. Lower layers may only add.",
        default_factory=lambda: [
            ".gitlab-ci.yml",
            ".github/**",
            "**/package-lock.json",
            "**/pnpm-lock.yaml",
            "**/yarn.lock",
        ],
        mergeable=True,
    )
    extra_executables: list[str] = _field(
        "Executables added to the sandbox allow-list. Org-only.",
        default_factory=list,
        merge="org_only",
    )
    allowed_protected_paths: list[str] = _field(
        "Globs pam may change although protected_paths matches them. Org-only; a "
        "repository cannot allow a protected path for itself.",
        default_factory=list,
        merge="org_only",
    )


# ---------------------------------------------------------------- llm and platform


class LlmConfig(_Base):
    base_url: str | None = _field(
        "LiteLLM gateway URL. Org-only (egress).", default=None, merge="org_only"
    )
    allowed_models: list[str] = _field(
        "Model aliases a run may use, including per-agent and fallback models. Empty "
        "means any. Org-only.",
        default_factory=list,
        merge="org_only",
    )


class Limits(_Base):
    max_tokens: int = _field(
        "Platform ceiling for tokens per invocation.",
        default=200000,
        ge=1,
        merge="org_only",
    )
    max_iterations: int = _field(
        "Platform ceiling for model turns.", default=50, ge=1, merge="org_only"
    )
    max_wall_clock_seconds: int = _field(
        "Platform ceiling for wall-clock seconds.", default=1800, ge=1, merge="org_only"
    )
    max_skills: int = _field(
        "Platform ceiling for skills per run.", default=50, ge=1, merge="org_only"
    )
    max_skill_bytes: int = _field(
        "Platform ceiling for bytes per skill.", default=65536, ge=1, merge="org_only"
    )
    max_total_skill_bytes: int = _field(
        "Platform ceiling for total skill bytes.",
        default=262144,
        ge=1,
        merge="org_only",
    )
    max_prompt_extra_chars: int = _field(
        "Platform ceiling for prompt_extra length.",
        default=4000,
        ge=1,
        merge="org_only",
    )
    max_request_bytes: int = _field(
        "Largest request body the API accepts, in bytes.",
        default=1_000_000,
        ge=1,
        merge="org_only",
    )
    max_run_tokens: int = _field(
        "Hard ceiling on model tokens for one run, across all turns.",
        default=400_000,
        ge=1,
        merge="org_only",
    )


class SecretsConfig(_Base):
    provider: Literal["k8s_files", "env", "file", "vault"] = _field(
        "Where secret values come from. Org-only.",
        default="k8s_files",
        merge="org_only",
    )
    allowed_patterns: list[str] = _field(
        "Regular expressions a secret name must fully match. Org-only.",
        default_factory=lambda: list(DEFAULT_SECRET_PATTERNS),
        merge="org_only",
    )

    @field_validator("allowed_patterns")
    @classmethod
    def _patterns_compile(cls, value: list[str]) -> list[str]:
        for pattern in value:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid secret pattern {pattern!r}: {exc}") from exc
        return value


class PostingConfig(_Base):
    force_dry_run: bool = _field(
        "When true, no lower layer can enable external writes. Org-only.",
        default=False,
        merge="org_only",
    )


class RepoConfigSource(_Base):
    allow_head_ref: bool = _field(
        "Allow a request to read .squad/config.yml from the change request head. "
        "Org-only; off by default.",
        default=False,
        merge="org_only",
    )


class ExtraAgent(_Base):
    id: str = _field(
        "Agent id: a lowercase single token, not a built-in id.",
        pattern=EXTRA_AGENT_ID_PATTERN,
    )
    description: str = _field(
        "One-line role description.", min_length=1, max_length=200
    )
    prompt_path: str = _field(
        "Path to the agent prompt markdown file.", min_length=1, max_length=512
    )
    knowledge_dirs: list[str] = _field(
        "Knowledge directories readable through read_knowledge.",
        default_factory=list,
    )
    tool_preset: ToolPreset = _field(
        "Tool set: review_readonly, or review_publish which adds publish_review.",
        default="review_readonly",
    )
    model: str | None = _field(
        "Model alias. Defaults to the platform default.",
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$",
    )
    routes: list[str] = _field(
        "Changed-file globs that route to this agent.", default_factory=list
    )


# ---------------------------------------------------------------- sections


class SquadFields(_Base):
    """Every configuration section. Used for overlays, where all keys are optional."""

    vcs: VcsConfig = _field("Version control settings.", default_factory=VcsConfig)
    trigger: TriggerConfig = _field(
        "When and from whom reviews start.", default_factory=TriggerConfig
    )
    agents: dict[str, AgentConfig] = _field(
        "Per-agent settings keyed by agent id.", default_factory=dict
    )
    routing: RoutingConfig = _field(
        "Routing, risk tiers and fan-out.", default_factory=RoutingConfig
    )
    review: ReviewConfig = _field("Review policy.", default_factory=ReviewConfig)
    skills: SkillsConfig = _field(
        "Runtime skill loading.", default_factory=SkillsConfig
    )
    security: SecurityConfig = _field(
        "Vulnerability intelligence and accepted risks.",
        default_factory=SecurityConfig,
    )
    ops: OpsConfig = _field("Operations (darryl) settings.", default_factory=OpsConfig)
    implementer: ImplementerConfig = _field(
        "Implementation settings (pam).", default_factory=ImplementerConfig
    )
    llm: LlmConfig = _field("LLM gateway settings.", default_factory=LlmConfig)
    limits: Limits = _field(
        "Platform ceilings no lower layer can exceed. Org-only.",
        default_factory=Limits,
        merge="org_only",
    )
    secrets: SecretsConfig = _field(
        "Secret provider and allowed names. Org-only.",
        default_factory=SecretsConfig,
        merge="org_only",
    )
    posting: PostingConfig = _field(
        "External write policy.", default_factory=PostingConfig
    )
    repo_config: RepoConfigSource = _field(
        "Where repository config is read from.", default_factory=RepoConfigSource
    )
    extra_agents: list[ExtraAgent] = _field(
        "Additional agents declared in configuration. Org-only.",
        default_factory=list,
        merge="org_only",
    )

    @field_validator("extra_agents")
    @classmethod
    def _unique_extra_ids(cls, value: list[ExtraAgent]) -> list[ExtraAgent]:
        seen: set[str] = set()
        for agent in value:
            if agent.id in AGENT_IDS:
                raise ValueError(
                    f"extra agent id {agent.id!r} collides with a built-in"
                )
            if agent.id in seen:
                raise ValueError(f"duplicate extra agent id {agent.id!r}")
            seen.add(agent.id)
        return value


class SquadConfig(SquadFields):
    """Effective or org-level configuration. Adds cross-field ceiling checks."""

    @model_validator(mode="after")
    def _within_platform_limits(self) -> SquadConfig:
        dumped = self.model_dump(mode="json")
        problems = ceiling_violations(SquadFields, dumped, dumped)
        if problems:
            raise ValueError("; ".join(problems))
        return self


class RepoConfig(SquadFields):
    """Repository file: a partial config that may extend a named profile."""

    extends: str | None = _field(
        "Profile to apply before this file's own keys (built-in or registry profile).",
        default=None,
        min_length=1,
        max_length=64,
    )


# ---------------------------------------------------------------- registry


class ProjectEntry(_Base):
    match: str = _field(
        "Project key or glob. '*' stays within one path segment, '**' crosses them.",
        min_length=1,
        max_length=256,
    )
    key: str | None = _field(
        "Canonical project label used in tags and logs. Defaults to the request key.",
        default=None,
        min_length=1,
        max_length=256,
    )
    provider: Literal["gitlab", "github", "auto"] | None = _field(
        "VCS provider for this project.", default=None
    )
    base_url: str | None = _field("API base URL for this project's host.", default=None)
    auth: VcsAuth | None = _field("Credential secret names.", default=None)
    extends: str | None = _field(
        "Profile applied before this entry's own overrides.",
        default=None,
        min_length=1,
        max_length=64,
    )
    overrides: SquadFields = _field(
        "Configuration overrides for matching projects.",
        default_factory=SquadFields,
    )


class ProjectsFile(_Base):
    profiles: dict[str, SquadFields] = _field(
        "Named profiles: reusable bundles of overrides.", default_factory=dict
    )
    projects: list[ProjectEntry] = _field(
        "Project registry entries, least to most specific by match.",
        default_factory=list,
    )
