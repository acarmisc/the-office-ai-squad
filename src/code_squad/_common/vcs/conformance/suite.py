"""Reusable provider checks. Every backend must pass every check in ALL_CHECKS."""

from __future__ import annotations

from collections.abc import Callable

from code_squad._common.vcs.base import (
    Capability,
    CapabilityError,
    InlineComment,
    StaleHeadError,
    StatusState,
    VcsProvider,
)
from code_squad._common.vcs.conformance import scenario as s
from code_squad._common.vcs.diff import line_in_changed_hunk

Check = Callable[[VcsProvider], None]


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_whoami(p: VcsProvider) -> None:
    _expect(p.whoami().username == s.BOT, "bot identity mismatch")


def check_change_request(p: VcsProvider) -> None:
    cr = p.get_change_request(s.REF)
    _expect(cr.ref == s.REF, "ref mismatch")
    _expect(cr.title == s.TITLE, "title mismatch")
    _expect(cr.head_sha == s.HEAD, "head sha mismatch")
    _expect(cr.base_sha == s.BASE, "base sha mismatch")
    _expect(cr.source_branch == s.SOURCE and cr.target_branch == s.TARGET, "branches")
    _expect(not cr.draft and not cr.is_fork, "draft/fork flags")
    _expect(cr.author == s.AUTHOR, "author mismatch")
    _expect(cr.labels == ("frontend",), "labels mismatch")


def check_fork_flag(p: VcsProvider) -> None:
    _expect(p.get_change_request(s.FORK_REF).is_fork, "fork PR must set is_fork")


def check_diff_refs(p: VcsProvider) -> None:
    refs = p.get_diff_refs(s.REF)
    _expect(refs.head_sha == s.HEAD and refs.base_sha == s.BASE, "diff refs mismatch")


def check_diff_and_hunks(p: VcsProvider) -> None:
    files = {f.path: f for f in p.get_diff(s.REF, s.HEAD)}
    _expect(set(files) == {s.APP_PATH, s.LOGO_PATH}, f"unexpected files {set(files)}")
    app = files[s.APP_PATH]
    _expect(app.status == "modified" and not app.truncated, "app file flags")
    _expect(len(app.hunks) == 1, "app file should have one hunk")
    hunk = app.hunks[0]
    _expect((hunk.new_start, hunk.new_lines) == (1, 4), "hunk range mismatch")
    _expect(hunk.added_lines == frozenset({2}), "added lines mismatch")
    _expect(line_in_changed_hunk(app, 2, 2), "line 2 must be inside the hunk")
    _expect(not line_in_changed_hunk(app, 40, 42), "line 40 must be outside")
    logo = files[s.LOGO_PATH]
    _expect(
        logo.truncated and logo.binary and logo.hunks == (), "logo must be truncated"
    )


def check_stale_head(p: VcsProvider) -> None:
    try:
        p.get_diff(s.REF, "c" * 40)
    except StaleHeadError:
        return
    raise AssertionError("expected StaleHeadError for an old head sha")


def check_changed_files_paginated(p: VcsProvider) -> None:
    paths = sorted(p.list_changed_files(s.REF))
    _expect(paths == sorted([s.APP_PATH, s.LOGO_PATH]), f"changed files {paths}")


def check_read_file(p: VcsProvider) -> None:
    _expect(p.read_file(s.PROJECT, s.APP_PATH, s.HEAD) == s.FILE_TEXT, "file text")


def check_list_tree(p: VcsProvider) -> None:
    _expect(p.list_tree(s.PROJECT, "src", s.HEAD) == [s.APP_PATH], "tree listing")


def check_search_repo(p: VcsProvider) -> None:
    hits = p.search_repo(s.PROJECT, "greet", s.HEAD)
    expected = [(s.APP_PATH, 2, 'import { greet } from "./greet";')]
    _expect(hits == expected, f"search hits {hits}")


def check_default_branch(p: VcsProvider) -> None:
    _expect(p.get_default_branch(s.PROJECT) == s.TARGET, "default branch")


def check_list_comments(p: VcsProvider) -> None:
    by_id = {c.id: c for c in p.list_comments(s.REF)}
    _expect(s.EXISTING_ID in by_id, "existing comment missing")
    existing = by_id[s.EXISTING_ID]
    _expect(existing.author == s.BOT, "existing comment author")
    _expect(s.EXISTING_MARKER in existing.body, "marker missing from body")


def check_post_inline_comments(p: VcsProvider) -> None:
    comment = InlineComment(s.APP_PATH, 2, "Consider memoising the greeting.")
    ids = p.post_inline_comments(s.REF, s.HEAD, [comment], p.get_diff_refs(s.REF))
    _expect(len(ids) == 1 and all(ids), "one inline comment should yield one id")


def check_inline_anchoring(p: VcsProvider) -> None:
    comments = [
        InlineComment(s.APP_PATH, 2, "added line"),
        InlineComment(s.APP_PATH, 1, "context line"),
        InlineComment(s.APP_PATH, 40, "outside the hunk"),
    ]
    ids = p.post_inline_comments(s.REF, s.HEAD, comments, p.get_diff_refs(s.REF))
    _expect(len(ids) == 3, f"one result per comment, got {ids}")
    _expect(bool(ids[0]), "added line must be posted")
    _expect(ids[1] == "" and ids[2] == "", f"unanchorable lines must be rejected {ids}")


def check_multi_line_range(p: VcsProvider) -> None:
    comment = InlineComment(s.APP_PATH, 2, "range", start_line=2)
    ids = p.post_inline_comments(s.REF, s.HEAD, [comment], p.get_diff_refs(s.REF))
    _expect(len(ids) == 1 and bool(ids[0]), "multi-line range must be posted")


def check_renamed_file_comment(p: VcsProvider) -> None:
    comment = InlineComment(s.APP_PATH, 2, "renamed", old_path=s.APP_PATH)
    ids = p.post_inline_comments(s.REF, s.HEAD, [comment], p.get_diff_refs(s.REF))
    _expect(len(ids) == 1 and bool(ids[0]), "comment with old_path must be posted")


def check_upsert_updates_existing(p: VcsProvider) -> None:
    body = f"Updated summary.\n{s.EXISTING_MARKER}"
    first = p.upsert_comment(s.REF, s.EXISTING_MARKER, body)
    second = p.upsert_comment(s.REF, s.EXISTING_MARKER, body)
    _expect(first == second == s.EXISTING_ID, "upsert must reuse the existing comment")


def check_upsert_creates_new(p: VcsProvider) -> None:
    _expect(bool(p.upsert_comment(s.REF, s.NEW_MARKER, "Fresh summary.")), "new id")


def check_set_status(p: VcsProvider) -> None:
    sid = p.set_status(
        s.PROJECT,
        s.HEAD,
        StatusState.SUCCESS,
        "ai-review/jim",
        "ok",
        "https://ci.example.test",
    )
    _expect(bool(sid), "status id")


def check_submit_verdict(p: VcsProvider) -> None:
    _expect(
        bool(p.submit_review_verdict(s.REF, s.HEAD, "COMMENT", "Summary")), "verdict id"
    )


def check_resolve_thread(p: VcsProvider) -> None:
    if Capability.RESOLVE_THREAD in p.capabilities:
        p.resolve_thread(s.REF, s.THREAD_ID)
        return
    try:
        p.resolve_thread(s.REF, s.THREAD_ID)
    except CapabilityError:
        return
    raise AssertionError("unsupported resolve_thread must raise CapabilityError")


def check_ci_runs_and_jobs(p: VcsProvider) -> None:
    runs = p.list_ci_runs(s.PROJECT, s.HEAD)
    _expect([r.id for r in runs] == [s.RUN_ID], f"runs {runs}")
    _expect(runs[0].status == "success", "run status")
    jobs = p.list_ci_jobs(s.PROJECT, s.RUN_ID)
    _expect([(j.id, j.status) for j in jobs] == [(s.JOB_ID, "failed")], "jobs")


def check_job_log_truncated(p: VcsProvider) -> None:
    log = p.get_job_log(s.PROJECT, s.JOB_ID, 40)
    _expect(len(log.encode("utf-8")) <= 40, "log must respect max_bytes")
    _expect(log.endswith(s.LOG_ENDING), "log tail must keep the last line")


def check_create_branch(p: VcsProvider) -> None:
    _expect(p.create_branch(s.PROJECT, s.BRANCH, s.HEAD) == s.BRANCH, "branch name")


def check_create_draft_change_request(p: VcsProvider) -> None:
    cr = p.create_change_request(
        s.PROJECT, s.BRANCH, s.TARGET, "Fix greeting", "Body", True, (), (), ()
    )
    _expect(cr.draft, "created change request must be a draft")
    _expect(cr.target_branch == s.TARGET, "target branch")


def check_protected_branch(p: VcsProvider) -> None:
    _expect(p.is_protected(s.PROJECT, s.PROTECTED), "main must be protected")
    _expect(not p.is_protected(s.PROJECT, s.UNPROTECTED), "develop is not protected")


def check_issues(p: VcsProvider) -> None:
    issue = p.get_issue(s.PROJECT, s.ISSUE_NUMBER)
    _expect(issue.title == s.ISSUE_TITLE and issue.state == "open", "issue fields")
    _expect(
        bool(p.comment_on_issue(s.PROJECT, s.ISSUE_NUMBER, "Looking.")), "issue note"
    )


def check_rate_limit(p: VcsProvider) -> None:
    rate = p.rate_limit()
    _expect(rate is None or rate.limit > 0, "rate limit shape")


def check_clone_and_credentials(p: VcsProvider) -> None:
    _expect(p.clone_url(s.PROJECT).endswith("acme/web.git"), "clone url")
    _expect(bool(p.git_credentials(s.PROJECT)[1]), "git token")


ALL_CHECKS: tuple[Check, ...] = (
    check_whoami,
    check_change_request,
    check_fork_flag,
    check_diff_refs,
    check_diff_and_hunks,
    check_stale_head,
    check_changed_files_paginated,
    check_read_file,
    check_list_tree,
    check_search_repo,
    check_default_branch,
    check_list_comments,
    check_post_inline_comments,
    check_inline_anchoring,
    check_multi_line_range,
    check_renamed_file_comment,
    check_upsert_updates_existing,
    check_upsert_creates_new,
    check_set_status,
    check_submit_verdict,
    check_resolve_thread,
    check_ci_runs_and_jobs,
    check_job_log_truncated,
    check_create_branch,
    check_create_draft_change_request,
    check_protected_branch,
    check_issues,
    check_rate_limit,
    check_clone_and_credentials,
)
