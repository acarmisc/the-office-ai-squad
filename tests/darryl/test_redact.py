from __future__ import annotations

import pytest

from code_squad.darryl.redact import EmailPolicy, redact

FAKE_GH = "ghp_" + "F" * 36
FAKE_GITLAB = "glpat-" + "x" * 20
FAKE_AWS = "AKIA" + "X" * 16
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlZmFrZQ"


@pytest.mark.parametrize(
    ("raw", "must_not_contain", "must_contain"),
    [
        (
            "Authorization: Bearer fake-token-for-tests",
            "fake-token-for-tests",
            "<redacted>",
        ),
        ('{"Authorization": "Basic dXNlcjpwYXNz"}', "dXNlcjpwYXNz", "<redacted>"),
        ("Bearer fake-token-for-tests", "fake-token-for-tests", "Bearer <redacted>"),
        ('{"password": "hunter2", "user": "x"}', "hunter2", '"password": "<redacted>"'),
        ("password: hunter2", "hunter2", "password: <redacted>"),
        ("DB_PASSWORD=hunter2 LOG=info", "hunter2", "DB_PASSWORD=<redacted> LOG=info"),
        ("export API_KEY=abcd1234", "abcd1234", "API_KEY=<redacted>"),
        ("https://x.test/a?token=abc123&page=2", "abc123", "token=<redacted>&page=2"),
        ("client_secret: s3cr3t", "s3cr3t", "client_secret: <redacted>"),
        ('MY_SECRET="top secret value"', "top secret", 'MY_SECRET="<redacted>"'),
        ("aws_secret_access_key = wJalrXUtnFEMI", "wJalrXUtnFEMI", "<redacted>"),
        ("passwd=pw123", "pw123", "passwd=<redacted>"),
        ("GITHUB_TOKEN_FILE=/run/secrets/x", "", "GITHUB_TOKEN_FILE=/run/secrets/x"),
        (f"token {FAKE_GH} used", FAKE_GH, "<redacted:github-token>"),
        (f"clone with {FAKE_GITLAB}", FAKE_GITLAB, "<redacted:gitlab-token>"),
        (f"key {FAKE_AWS} leaked", FAKE_AWS, "<redacted:aws-access-key-id>"),
        (f"session {FAKE_JWT}", FAKE_JWT, "<redacted:jwt>"),
        (
            "postgres://app:s3cret@db.internal:5432/x",
            "s3cret",
            "postgres://app:***@db.internal",
        ),
        ("redis://:hunter2@cache:6379", "hunter2", "redis://:***@cache:6379"),
    ],
)
def test_each_pattern_masks_its_secret(
    raw: str, must_not_contain: str, must_contain: str
) -> None:
    out = redact(raw)
    assert must_contain in out
    if must_not_contain:
        assert must_not_contain not in out


def test_pem_private_key_block_is_removed_whole() -> None:
    block = (
        "before\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"  # secret-scan: allow
        "MIIFAKEKEYBODY\n"
        "-----END RSA PRIVATE KEY-----\nafter"
    )
    out = redact(block)
    assert "MIIFAKEKEYBODY" not in out
    assert out == "before\n<redacted:private-key>\nafter"


def test_unterminated_pem_block_is_removed_to_end() -> None:
    out = redact("-----BEGIN PRIVATE KEY-----\nMIIFAKE")  # secret-scan: allow
    assert "MIIFAKE" not in out


def test_connection_string_keeps_user_and_host() -> None:
    out = redact("mysql://reporting:pw-fake@db.shop.svc:3306/app")
    assert out == "mysql://reporting:***@db.shop.svc:3306/app"


def test_ordinary_text_is_unchanged() -> None:
    text = "max_tokens: 4096 pod=checkout-7d9f8c6b5-abcde restartCount=14"
    assert redact(text) == text


def test_key_names_that_only_contain_a_keyword_are_not_masked() -> None:
    text = "max_tokens: 4096\ntoken_count=5\nsecret_name: checkout"
    assert redact(text) == text


def test_json_escaped_annotation_values_are_masked() -> None:
    raw = 'last-applied: {\\"password\\":\\"hunter2\\"}'
    out = redact(raw)
    assert "hunter2" not in out


def test_extra_patterns_from_configuration_are_applied() -> None:
    out = redact("ticket ACME-123456 failed", [r"ACME-[0-9]{6}"])
    assert "ACME-123456" not in out
    assert "<redacted:custom>" in out


def test_invalid_extra_pattern_raises_value_error() -> None:
    with pytest.raises(ValueError, match="invalid redaction pattern"):
        redact("text", ["("])


def test_empty_extra_pattern_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        redact("text", [""])


def test_email_addresses_are_kept_by_default_and_masked_on_request() -> None:
    text = "user alice@example.com failed"
    assert redact(text) == text
    masked = redact(text, emails=EmailPolicy.MASK)
    assert "alice@example.com" not in masked
    assert "<redacted:email>" in masked
