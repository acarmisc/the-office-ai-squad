from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Final, cast

from pydantic import ValidationError
from strands import tool

from code_squad._common.context import current
from code_squad._common.contract import Finding
from code_squad._common.findings import (
    PublishOptions,
    PublishOutcome,
    VerdictCap,
    publish,
)
from code_squad._common.posting import DryRunError
from code_squad._common.untrusted import wrap_untrusted
from code_squad._common.vcs.base import (
    ChangeRequestRef,
    Comment,
    FileDiff,
    NotFoundError,
    VcsError,
    VcsProvider,
)

MAX_CONTEXT_BYTES: Final = 120_000
MAX_COMMENT_CHARS: Final = 4000
MAX_READ_LINES: Final = 400
MAX_READ_BYTES: Final = 65_536
MAX_SEARCH_HITS: Final = 50
MAX_TREE_ENTRIES: Final = 500
MAX_PATTERN_CHARS: Final = 200
MAX_FINDINGS: Final = 100
_REF_TEXT: Final = re.compile(r"^!?#?(\d+)$")
_GIT_REF: Final = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_VERSION: Final = re.compile(r"^[\w.^~<>=*| -]{1,40}$")
_LANGUAGES: Final[dict[str, str]] = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".kt": "kotlin",
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".xml": "xml",
    ".gradle": "groovy",
    ".kts": "kotlin",
    ".tf": "terraform",
    ".sql": "sql",
}


@dataclass(frozen=True)
class ReviewState:
    ref: ChangeRequestRef
    head_sha: str
    diff: tuple[FileDiff, ...]


def _provider() -> VcsProvider:
    return cast(VcsProvider, current().services["vcs"])


def _ref(change_request: str) -> ChangeRequestRef | None:
    ctx = current()
    project = ctx.request.project
    text = change_request or ctx.request.target or ""
    match = _REF_TEXT.match(text.strip())
    if project is None or match is None:
        return None
    return ChangeRequestRef(project, int(match.group(1)))


def _git_ref(provider: VcsProvider, project: str, requested: str) -> str:
    if requested:
        return (
            requested
            if _GIT_REF.match(requested) or re.match(r"^[0-9a-f]{40}$", requested)
            else ""
        )
    state = current().services.get("review_state")
    if isinstance(state, ReviewState):
        return state.head_sha
    return provider.get_default_branch(project)


def _safe_path(path: str) -> bool:
    return (
        bool(path)
        and not path.startswith("/")
        and ".." not in path.split("/")
        and "\n" not in path
    )


@tool
def get_review_context(change_request: str = "") -> str:
    """Return the review context for the change request as JSON in one call.

    Includes change request metadata, head and base sha, changed files with
    language, the diffs, existing comments, latest CI run and framework hints
    read from the target branch. Untrusted text is delimited in untrusted blocks.

    Args:
        change_request: Change request number, for example "42". Empty uses the
            change request of this run.
    """
    ref = _ref(change_request)
    if ref is None:
        return "change request not found in this run"
    provider = _provider()
    cr = provider.get_change_request(ref)
    diff = provider.get_diff(ref, cr.head_sha)
    current().services["review_state"] = ReviewState(ref, cr.head_sha, diff)
    context: dict[str, Any] = {
        "change_request": {
            "number": ref.number,
            "title": wrap_untrusted(cr.title, "change_request:title"),
            "description": wrap_untrusted(cr.description, "change_request:description"),
            "author": cr.author,
            "source_branch": cr.source_branch,
            "target_branch": cr.target_branch,
            "head_sha": cr.head_sha,
            "base_sha": cr.base_sha,
            "draft": cr.draft,
            "is_fork": cr.is_fork,
            "labels": list(cr.labels),
        },
        "files": [_file_entry(item) for item in diff],
        "frameworks": _frameworks(provider, ref.project, cr.target_branch),
        "ci": _latest_ci(provider, ref.project, cr.head_sha),
        "comments": [_comment_entry(item) for item in provider.list_comments(ref)],
        "diffs": [],
        "truncation": [],
    }
    _fill_diffs(context, diff)
    return json.dumps(context, ensure_ascii=False)


def _file_entry(item: FileDiff) -> dict[str, Any]:
    return {
        "path": item.path,
        "status": item.status,
        "language": _language(item.path),
        "truncated": item.truncated,
        "binary": item.binary,
    }


def _language(path: str) -> str:
    dot = path.rfind(".")
    return _LANGUAGES.get(path[dot:].lower(), "other") if dot != -1 else "other"


def _comment_entry(comment: Comment) -> dict[str, Any]:
    return {
        "id": comment.id,
        "author": comment.author,
        "path": comment.path,
        "line": comment.line,
        "body": wrap_untrusted(
            str(comment.body)[:MAX_COMMENT_CHARS], f"comment:{comment.id}"
        ),
    }


def _latest_ci(provider: VcsProvider, project: str, sha: str) -> dict[str, Any] | None:
    try:
        runs = provider.list_ci_runs(project, sha)
    except VcsError:
        return None
    if not runs:
        return None
    latest = runs[0]
    return {"status": latest.status, "name": wrap_untrusted(latest.name, "ci:name")}


def _fill_diffs(context: dict[str, Any], diff: tuple[FileDiff, ...]) -> None:
    budget = MAX_CONTEXT_BYTES - _size(context)
    for item in diff:
        if item.truncated or not item.patch:
            continue
        entry = {
            "path": item.path,
            "patch": wrap_untrusted(item.patch, f"diff:{item.path}"),
        }
        cost = _size(entry)
        if cost > budget:
            context["truncation"].append(
                f"diff omitted for {item.path}: context budget reached"
            )
            continue
        context["diffs"].append(entry)
        budget -= cost


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _frameworks(provider: VcsProvider, project: str, branch: str) -> dict[str, Any]:
    found: dict[str, Any] = {
        "react": None,
        "typescript_strict": None,
        "java_release": None,
    }
    package = _read_optional(provider, project, "package.json", branch)
    if package is not None:
        found["react"] = _react_version(package)
    tsconfig = _read_optional(provider, project, "tsconfig.json", branch)
    if tsconfig is not None:
        found["typescript_strict"] = _tsconfig_strict(tsconfig)
    for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
        text = _read_optional(provider, project, name, branch)
        if text is not None and found["java_release"] is None:
            found["java_release"] = _java_release(text)
    return found


def _read_optional(
    provider: VcsProvider, project: str, path: str, branch: str
) -> str | None:
    try:
        return provider.read_file(project, path, branch)
    except (NotFoundError, VcsError):
        return None


def _react_version(text: str) -> str | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    deps = {
        **dict(data.get("dependencies") or {}),
        **dict(data.get("devDependencies") or {}),
    }
    version = deps.get("react")
    return (
        str(version) if isinstance(version, str) and _VERSION.match(version) else None
    )


def _tsconfig_strict(text: str) -> bool | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    options = data.get("compilerOptions") if isinstance(data, dict) else None
    strict = options.get("strict") if isinstance(options, dict) else None
    return strict if isinstance(strict, bool) else None


def _java_release(text: str) -> str | None:
    patterns = (
        r"<maven\.compiler\.release>\s*(\d+)\s*<",
        r"<java\.version>\s*(\d+)\s*<",
        r"JavaVersion\.VERSION_(\d+)",
        r"(?:sourceCompatibility|targetCompatibility)\s*=\s*['\"]?(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match is not None:
            return match.group(1)
    return None


@tool
def read_file(path: str, ref: str = "", start: int = 1, end: int = 400) -> str:
    """Read a range of lines from a repository file (read only, bounded).

    Args:
        path: Repository-relative path, for example "src/app.tsx".
        ref: Branch, tag or commit sha. Empty uses the change request head.
        start: First line to return, counted from 1.
        end: Last line to return (at most 400 lines per call).
    """
    if not _safe_path(path):
        return "invalid path"
    provider = _provider()
    project = _project()
    resolved = _git_ref(provider, project, ref)
    if not resolved:
        return "invalid ref"
    try:
        text = provider.read_file(project, path, resolved)
    except NotFoundError:
        return f"file not found: {path}"
    raw = text.encode("utf-8")[:MAX_READ_BYTES].decode("utf-8", errors="ignore")
    lines = raw.splitlines()
    first = max(1, start)
    last = min(end, first + MAX_READ_LINES - 1, len(lines))
    numbered = [
        f"{number:>5} | {lines[number - 1]}" for number in range(first, last + 1)
    ]
    header = f"{path} lines {first}-{last} of {len(lines)} at {resolved[:12]}"
    return wrap_untrusted("\n".join([header, *numbered]), f"file:{path}")


@tool
def search_repo(pattern: str) -> str:
    """Search the repository for a literal text pattern (read only, at most 50 hits).

    Args:
        pattern: Literal text to find, at most 200 characters.
    """
    if not pattern or len(pattern) > MAX_PATTERN_CHARS or "\n" in pattern:
        return "invalid pattern"
    provider = _provider()
    project = _project()
    ref = _git_ref(provider, project, "")
    try:
        hits = provider.search_repo(project, pattern, ref)[:MAX_SEARCH_HITS]
    except VcsError as exc:
        return f"search unavailable: {type(exc).__name__}"
    lines = [f"{path}:{line}: {text[:300]}" for path, line, text in hits]
    return wrap_untrusted("\n".join(lines) or "no matches", f"search:{pattern[:80]}")


@tool
def list_tree(path: str = "") -> str:
    """List the entries of a repository directory (read only, at most 500 entries).

    Args:
        path: Directory path. Empty lists the repository root.
    """
    if path and not _safe_path(path):
        return "invalid path"
    provider = _provider()
    project = _project()
    entries = provider.list_tree(project, path, _git_ref(provider, project, ""))
    shown = entries[:MAX_TREE_ENTRIES]
    return wrap_untrusted("\n".join(shown) or "empty", f"tree:{path or '/'}")


@tool
def publish_review(findings: list[dict[str, Any]], summary: str) -> str:
    """Publish findings as inline comments and a summary. External write.

    Findings are validated, anchored to the changed lines, de-duplicated against
    existing comments and published idempotently. Blocked by dry-run.

    Args:
        findings: Finding objects with agent, rule_id, category, severity, confidence,
            file, line_start, line_end, head_sha, title and rationale.
        summary: Short summary for the review.
    """
    ctx = current()
    try:
        ctx.gate.require_write("publish_review")
    except DryRunError:
        return "publish_review refused: posting is disabled for this run (dry-run)"
    parsed = _parse_findings(findings, ctx.agent)
    if isinstance(parsed, str):
        return parsed
    ref = _ref("")
    if ref is None:
        return "change request not found in this run"
    provider = _provider()
    head = _review_head(provider, ref)
    options = _publish_options(ctx.services.get("publish_options"))
    outcome = publish(
        provider,
        ref,
        head,
        parsed,
        summary[:4000],
        agent=ctx.agent,
        gate=ctx.gate,
        options=options,
        journal=ctx.services.get("journal"),
        idempotency_key=ctx.request.idempotency_key,
    )
    return _describe(outcome)


def _publish_options(configured: object) -> PublishOptions:
    base = configured if isinstance(configured, PublishOptions) else PublishOptions()
    cap = _verdict_cap(current().services.get("publish_verdict_cap"))
    if cap is None:
        return base
    return replace(base, verdict_cap=cap[0], verdict_cap_reason=cap[1])


def _verdict_cap(source: object) -> tuple[VerdictCap, str] | None:
    """Run-time verdict cap registered by a service, e.g. dwight's offline guard."""
    if not callable(source):
        return None
    fetch = cast(Callable[[], tuple[VerdictCap, str] | None], source)
    return fetch()


def _review_head(provider: VcsProvider, ref: ChangeRequestRef) -> str:
    state = current().services.get("review_state")
    if isinstance(state, ReviewState) and state.ref == ref:
        return state.head_sha
    return provider.get_change_request(ref).head_sha


def _parse_findings(raw: list[dict[str, Any]], agent: str) -> list[Finding] | str:
    if len(raw) > MAX_FINDINGS:
        return f"too many findings: at most {MAX_FINDINGS} per call"
    parsed: list[Finding] = []
    for index, item in enumerate(raw):
        try:
            finding = Finding.model_validate({**item, "agent": agent, "id": ""})
        except ValidationError as exc:
            first = exc.errors(include_input=False, include_url=False)[0]
            location = ".".join(str(part) for part in first["loc"]) or "finding"
            return f"finding {index} rejected: {location}: {first['msg']}"
        parsed.append(finding.with_id())
    return parsed


def _project() -> str:
    project = current().request.project
    if project is None:
        raise ValueError("a project is required for repository tools")
    return project


def _describe(outcome: PublishOutcome) -> str:
    posted = outcome.posted
    parts = [
        f"verdict={outcome.verdict.value}",
        f"inline={posted.discussions}",
        f"summary_notes={posted.notes}",
        f"status={posted.status or 'none'}",
    ]
    if outcome.warnings:
        parts.append("warnings=" + "; ".join(outcome.warnings))
    return "published: " + ", ".join(parts)
