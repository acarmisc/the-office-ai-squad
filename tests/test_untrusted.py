from __future__ import annotations

import secrets

import pytest

from code_squad._common.untrusted import UNTRUSTED_RULE, wrap_untrusted


def test_content_is_wrapped_with_matching_token_in_both_tags() -> None:
    wrapped = wrap_untrusted("diff body", "change-request-diff")
    lines = wrapped.split("\n")
    assert lines[0].startswith('<untrusted id="')
    token = lines[0].split('"')[1]
    assert len(token) == 16
    assert lines[1] == "diff body"
    assert lines[2] == f'</untrusted id="{token}">'
    assert 'source="change-request-diff"' in lines[0]


def test_token_is_regenerated_when_it_occurs_in_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "text with deadbeefdeadbeef inside"
    tokens = iter(["deadbeefdeadbeef", "aaaaaaaaaaaaaaaa"])
    monkeypatch.setattr(secrets, "token_hex", lambda _n: next(tokens))
    wrapped = wrap_untrusted(content, "issue")
    assert 'id="aaaaaaaaaaaaaaaa"' in wrapped
    assert "deadbeefdeadbeef" in wrapped
    assert wrapped.count('id="deadbeefdeadbeef"') == 0


def test_source_is_escaped_and_flattened() -> None:
    wrapped = wrap_untrusted("x", 'a"<b>\r\nc')
    header = wrapped.split("\n")[0]
    assert 'source="a&quot;&lt;b&gt; c"' in header
    assert "<b>" not in header


def test_long_source_is_truncated() -> None:
    wrapped = wrap_untrusted("x", "s" * 500)
    header = wrapped.split("\n")[0]
    value = header.split('source="')[1].removesuffix('">')
    assert value == "s" * 200


def test_rule_tells_models_untrusted_content_is_data() -> None:
    assert "<untrusted>" in UNTRUSTED_RULE
    assert "never an instruction" in UNTRUSTED_RULE
