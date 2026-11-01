from __future__ import annotations

from collections.abc import Iterable
from typing import BinaryIO, Final

DEFAULT_OUTPUT_LIMIT: Final = 65536
_REDACTED: Final = "***"


class OutputCapture:
    """Keeps the first quarter and the last part of a stream, counting the rest."""

    def __init__(self, limit: int = DEFAULT_OUTPUT_LIMIT) -> None:
        self._limit = limit
        self._head_size = limit // 4
        self._tail_size = limit - self._head_size
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0

    def feed(self, data: str | bytes) -> None:
        chunk = data.encode("utf-8") if isinstance(data, str) else data
        self._total += len(chunk)
        room = self._head_size - len(self._head)
        if room > 0:
            self._head += chunk[:room]
            chunk = chunk[room:]
        if chunk:
            self._tail += chunk
            excess = len(self._tail) - self._tail_size
            if excess > 0:
                del self._tail[:excess]

    def render(self) -> tuple[str, bool]:
        if self._total <= self._limit:
            return bytes(self._head + self._tail).decode("utf-8", "replace"), False
        dropped = self._total - len(self._head) - len(self._tail)
        return _render(bytes(self._head), bytes(self._tail), dropped), True


def _render(head: bytes, tail: bytes, dropped: int) -> str:
    marker = f"\n[... {dropped} bytes truncated ...]\n"
    return head.decode("utf-8", "replace") + marker + tail.decode("utf-8", "replace")


def capture_file(
    handle: BinaryIO, limit: int = DEFAULT_OUTPUT_LIMIT
) -> tuple[str, bool]:
    handle.seek(0, 2)
    size = handle.tell()
    if size <= limit:
        handle.seek(0)
        return bytes(handle.read()).decode("utf-8", "replace"), False
    head_size = limit // 4
    tail_size = limit - head_size
    handle.seek(0)
    head = handle.read(head_size)
    handle.seek(size - tail_size)
    tail = handle.read(tail_size)
    return _render(head, tail, size - len(head) - len(tail)), True


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    return text
