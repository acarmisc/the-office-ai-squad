from __future__ import annotations


class SandboxError(Exception):
    pass


class CommandNotAllowedError(SandboxError):
    pass


class PathEscapeError(SandboxError):
    pass


class LoopDetectedError(SandboxError):
    pass


class BudgetExceededError(SandboxError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"budget exceeded: {reason}")
        self.reason = reason
