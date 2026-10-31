from __future__ import annotations

import pytest

from code_squad._common.posting import POST_WHEN_ABSENT, DryRunError, PostingGate
from tests.support import request


def test_absent_post_allows_writes() -> None:
    assert POST_WHEN_ABSENT is True
    gate = PostingGate.from_request(request())
    assert gate.post_allowed is True
    gate.require_write("publish_review")
    assert gate.blocked == []


def test_post_false_blocks_writes_and_records_them() -> None:
    gate = PostingGate.from_request(request(post=False))
    assert gate.post_allowed is False
    with pytest.raises(DryRunError, match="publish_review"):
        gate.require_write("publish_review")
    assert gate.blocked == ["publish_review"]


def test_post_true_allows_writes() -> None:
    gate = PostingGate.from_request(request(post=True))
    gate.require_write("publish_review")
    assert gate.blocked == []


def test_dry_run_error_is_a_permission_error() -> None:
    assert issubclass(DryRunError, PermissionError)
