from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from code_squad._common.contract import InvocationRequest

POST_WHEN_ABSENT: Final = True


class DryRunError(PermissionError):
    pass


@dataclass
class PostingGate:
    post_allowed: bool
    blocked: list[str] = field(default_factory=list)

    @classmethod
    def from_request(cls, req: InvocationRequest) -> PostingGate:
        allowed = req.post if req.post is not None else POST_WHEN_ABSENT
        return cls(post_allowed=allowed)

    def require_write(self, name: str) -> None:
        if self.post_allowed:
            return
        self.blocked.append(name)
        raise DryRunError(
            f"tool '{name}' is an external write and posting is disabled (dry-run)"
        )
