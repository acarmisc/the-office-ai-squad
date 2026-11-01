from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from code_squad._common.context import InvocationContext
from code_squad._common.posting import PostingGate
from tests.support import request

SHA_BASE = "a" * 40
SHA_HEAD = "b" * 40
FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class FakeReader:
    """Repository reader over per-ref file maps that records every request."""

    files_by_ref: dict[str, dict[str, str]]
    requests: list[tuple[str, str]] = field(default_factory=list)

    def list_tree(self, path: str, ref: str) -> list[str]:
        self.requests.append(("list_tree", ref))
        files = self.files_by_ref.get(ref, {})
        matches = sorted(p for p in files if p.startswith(f"{path}/"))
        if not matches:
            raise FileNotFoundError(path)
        return matches

    def read_file(self, path: str, ref: str) -> str:
        self.requests.append(("read_file", ref))
        files = self.files_by_ref.get(ref, {})
        if path not in files:
            raise FileNotFoundError(path)
        return files[path]

    def refs_requested(self) -> set[str]:
        return {ref for _op, ref in self.requests}

    def calls(self, op: str) -> int:
        return sum(1 for name, _ref in self.requests if name == op)


def skill_md(
    name: str,
    description: str = "Does something useful.",
    body: str = "Follow the convention.",
    extra: str = "",
) -> str:
    front = f"name: {name}\ndescription: {description}\n{extra}"
    return f"---\n{front}---\n\n{body}\n"


def context_with(services: dict[str, object]) -> InvocationContext:
    req = request()
    return InvocationContext(
        agent="jim",
        request=req,
        gate=PostingGate.from_request(req),
        services=dict(services),
    )
