from __future__ import annotations

from code_squad._common.vcs.base import (
    ChangeRequest,
    ChangeRequestRef,
    CiJob,
    CiRun,
    Comment,
    FileDiff,
    Issue,
    RateLimit,
)
from code_squad._common.vcs.fake import FakeVcsProvider

PROJECT = "acme/web"
NUMBER = 42
FORK_NUMBER = 43
HEAD = "a" * 40
BASE = "b" * 40
REF = ChangeRequestRef(PROJECT, NUMBER)
FORK_REF = ChangeRequestRef(PROJECT, FORK_NUMBER)
BOT = "code-squad-bot"
TITLE = "Add greeting"
DESCRIPTION = "Adds a greeting to the app."
AUTHOR = "alice"
SOURCE = "feature/greeting"
TARGET = "main"
APP_PATH = "src/app.tsx"
LOGO_PATH = "assets/logo.png"
APP_PATCH = (
    '@@ -1,3 +1,4 @@\n import React from "react";\n'
    '+import { greet } from "./greet";\n \n'
    " export const App = () => <h1>Hello</h1>;"
)
FILE_TEXT = (
    'import React from "react";\n'
    'import { greet } from "./greet";\n\n'
    "export const App = () => <h1>Hello</h1>;\n"
)
EXISTING_ID = "900"
THREAD_ID = "d1"
EXISTING_MARKER = "<!-- code-squad:summary:jim -->"
EXISTING_BODY = f"Earlier summary.\n{EXISTING_MARKER}"
NEW_MARKER = "<!-- code-squad:summary:fresh -->"
RUN_ID = "5001"
JOB_ID = "7001"
LOG_TEXT = "build line\n" * 20 + "FAILED test_greet\n"
LOG_ENDING = "FAILED test_greet\n"
BRANCH = "code-squad/fix-1"
ISSUE_NUMBER = 12
ISSUE_TITLE = "Greeting broken"
PROTECTED = "main"
UNPROTECTED = "develop"
RATE = RateLimit(limit=5000, remaining=4990, reset_epoch=1_800_000_000)


def seed_fake(fake: FakeVcsProvider) -> None:
    """Load the conformance scenario into an in-memory provider."""
    fake.add_change_request(
        _cr(REF, HEAD, fork=False),
        files={APP_PATH: APP_PATCH},
        file_contents={APP_PATH: FILE_TEXT},
        extra_diffs=(_logo_diff(),),
    )
    fake.add_change_request(_cr(FORK_REF, HEAD, fork=True), files={})
    fake.seed_comment(
        REF, Comment(EXISTING_ID, BOT, EXISTING_BODY, None, None, THREAD_ID, False)
    )
    fake.seed_comment(REF, Comment("901", "bob", "Looks fine", None, None, None, False))
    fake.add_ci_run(
        PROJECT,
        CiRun(RUN_ID, "success", SOURCE, HEAD, "https://ci.example.test/5001", "ci"),
        jobs=(CiJob(JOB_ID, "unit", "failed", "test", "https://ci.example.test/7001"),),
        logs={JOB_ID: LOG_TEXT},
    )
    fake.add_issue(
        Issue(
            PROJECT,
            ISSUE_NUMBER,
            ISSUE_TITLE,
            "Hello never renders",
            ("bug",),
            (AUTHOR,),
            "open",
            "https://fake.invalid/issues/12",
        )
    )
    fake.protect(PROJECT, PROTECTED)
    fake.set_default_branch(PROJECT, TARGET)


def _logo_diff() -> FileDiff:
    return FileDiff(
        path=LOGO_PATH,
        old_path=LOGO_PATH,
        status="modified",
        hunks=(),
        patch="",
        binary=True,
        truncated=True,
    )


def _cr(ref: ChangeRequestRef, head: str, *, fork: bool) -> ChangeRequest:
    return ChangeRequest(
        ref=ref,
        title=TITLE if not fork else "Fork greeting",
        description=DESCRIPTION,
        author=AUTHOR,
        source_branch=SOURCE,
        target_branch=TARGET,
        head_sha=head,
        base_sha=BASE,
        draft=False,
        is_fork=fork,
        web_url=f"https://fake.invalid/{PROJECT}/-/merge_requests/{ref.number}",
        labels=("frontend",),
        state="opened",
    )
