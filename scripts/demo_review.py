"""Run one dry-run review of a sample change request with jim, and print the report.

Usage: uv run python -m scripts.demo_review

Everything is offline and deterministic: the model is a scripted model, the VCS is the
in-memory fake, and the request sets post=false. The report uses the same formatter as
scripts/trial_review.sh. The demo exits 1 when the external-write check fails.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any, Final

from fastapi.testclient import TestClient
from strands.models.model import Model

from code_squad._common.config.loader import ConfigSources
from code_squad._common.fake_model import ScriptedModel, ToolCall, Turn
from code_squad._common.services import ServiceBuilder
from code_squad._common.session import MemorySessionStore
from code_squad._common.vcs.base import ChangeRequest, ChangeRequestRef
from code_squad._common.vcs.fake import FakeVcsProvider
from code_squad.server import create_app
from scripts.trial_report import render

PROJECT: Final = "acme/storefront"
NUMBER: Final = 7
HEAD: Final = "c" * 40
BASE: Final = "d" * 40
PATH: Final = "src/features/profile/ProfileCard.tsx"
TOKEN: Final = "fake-token-for-tests"
TEXT: Final = "\n".join(
    [
        'import { useState } from "react";',
        "",
        "type Props = { bio: string };",
        "",
        "export function ProfileCard({ bio }: Props) {",
        "  const [open, setOpen] = useState(false);",
        "  return (",
        "    <section onClick={() => setOpen(!open)}>",
        "      <div dangerouslySetInnerHTML={{ __html: bio }} />",
        "    </section>",
        "  );",
        "}",
        "",
    ]
)


def _patch(text: str) -> str:
    lines = text.rstrip("\n").split("\n")
    body = "\n".join(f"+{line}" for line in lines)
    return f"@@ -0,0 +1,{len(lines)} @@\n{body}"


def _line_of(needle: str) -> int:
    for number, line in enumerate(TEXT.split("\n"), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


def _provider() -> FakeVcsProvider:
    fake = FakeVcsProvider(name="github")
    change = ChangeRequest(
        ref=ChangeRequestRef(PROJECT, NUMBER),
        title="Show the profile bio in ProfileCard",
        description="Sample change for the offline demo.",
        author="dev-user",
        source_branch="feature/profile-bio",
        target_branch="main",
        head_sha=HEAD,
        base_sha=BASE,
        draft=False,
        is_fork=False,
        web_url=f"https://fake.invalid/{PROJECT}/-/pull/{NUMBER}",
        labels=(),
        state="opened",
    )
    fake.add_change_request(
        change,
        files={PATH: _patch(TEXT)},
        file_contents={PATH: TEXT},
    )
    fake.set_files(PROJECT, {"package.json": '{"dependencies": {"react": "^18.3.1"}}'})
    fake.set_default_branch(PROJECT, "main")
    return fake


def _finding() -> dict[str, Any]:
    line = _line_of("dangerouslySetInnerHTML")
    return {
        "agent": "jim",
        "rule_id": "REACT-SEC-001",
        "category": "security",
        "severity": "blocker",
        "confidence": "high",
        "file": PATH,
        "line_start": line,
        "line_end": line,
        "head_sha": HEAD,
        "title": "Unsanitised HTML from the profile bio",
        "rationale": "The bio is rendered with dangerouslySetInnerHTML, unsanitised.",
        "failure_scenario": "A bio containing a script runs in every viewer's session.",
    }


def _script() -> ScriptedModel:
    turns = [
        Turn((ToolCall("get_review_context", {}),)),
        Turn((ToolCall("read_file", {"path": PATH, "start": 1, "end": 20}),)),
        Turn(
            (
                ToolCall(
                    "finish",
                    {
                        "verdict": "request_changes",
                        "summary": "One blocker: unsanitised HTML from the bio.",
                        "findings": [_finding()],
                    },
                ),
            )
        ),
    ]
    return ScriptedModel(turns)


def _factory(model: Model) -> Callable[..., Model]:
    def build(*_args: object) -> Model:
        return model

    return build


def _post(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/invocations",
        headers={"authorization": f"Bearer {TOKEN}"},
        json={
            "prompt": f"review change request {NUMBER}",
            "project": PROJECT,
            "target": str(NUMBER),
            "mode": "review",
            "post": False,
        },
    )
    if response.status_code != 200:
        raise SystemExit(f"error: POST /invocations returned {response.status_code}")
    result: dict[str, Any] = response.json()
    return result


def _client(fake: FakeVcsProvider, model: Model) -> TestClient:
    builder = ServiceBuilder(
        provider_factory=lambda _settings: fake,
        secret_provider=_NoSecrets(),
        config_sources=ConfigSources(
            org_file=None, env={}, projects_dir=None, profiles_dir=None
        ),
        env={"VCS_PROVIDER": "github", "VCS_BASE_URL": "https://api.github.com"},
    )
    app = create_app(
        "jim",
        model_factory=_factory(model),
        services_factory=builder.build,
        session_store=MemorySessionStore(),
    )
    return TestClient(app)


class _NoSecrets:
    def get(self, name: str) -> str:
        return TOKEN if name == "vcs-token" else ""


def main(_argv: Sequence[str] = ()) -> int:
    os.environ["SQUAD_API_TOKEN"] = TOKEN
    os.environ["LOG_LEVEL"] = "ERROR"
    fake = _provider()
    client = _client(fake, _script())
    print("dry run: post=false, nothing is written to the VCS.")
    result = _post(client)
    print(render(result, None))
    writes = len(fake.writes)
    print(f"external writes recorded by the fake VCS: {writes}")
    return 0 if writes == 0 and result.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
