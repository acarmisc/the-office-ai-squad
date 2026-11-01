from __future__ import annotations

from pathlib import Path

import pytest

from code_squad._common.auth import bearer_matches, load_api_token

_TOKEN = "fake-token-for-tests"


def test_token_comes_from_the_direct_variable_first(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("fake-token-from-file\n", encoding="utf-8")
    env = {"SQUAD_API_TOKEN": f" {_TOKEN} ", "SQUAD_API_TOKEN_FILE": str(token_file)}
    assert load_api_token(env) == _TOKEN


def test_token_file_is_stripped_and_used_when_no_direct_value(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(f"{_TOKEN}\n", encoding="utf-8")
    assert load_api_token({"SQUAD_API_TOKEN_FILE": str(token_file)}) == _TOKEN


def test_no_token_when_nothing_is_configured() -> None:
    assert load_api_token({}) is None
    assert load_api_token({"SQUAD_API_TOKEN": "  "}) is None


def test_empty_token_file_fails_closed(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_api_token({"SQUAD_API_TOKEN_FILE": str(token_file)})


def test_missing_token_file_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_api_token({"SQUAD_API_TOKEN_FILE": str(tmp_path / "absent")})


@pytest.mark.parametrize(
    "header",
    [
        f"Bearer {_TOKEN}",
        f"bearer {_TOKEN}",
        f"BEARER   {_TOKEN}",
    ],
)
def test_bearer_header_with_the_token_matches(header: str) -> None:
    assert bearer_matches(header, _TOKEN)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Bearer fake-token-for-other",
        f"Basic {_TOKEN}",
        _TOKEN,
    ],
)
def test_anything_else_does_not_match(header: str | None) -> None:
    assert not bearer_matches(header, _TOKEN)
