from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _local_sandbox_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """pam tests run on LocalProcessSandbox; the cluster refuses that without this."""
    monkeypatch.setenv("ALLOW_LOCAL_SANDBOX", "1")
