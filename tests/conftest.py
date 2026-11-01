from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _allow_unauthenticated_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Test clients run without a bearer token; auth tests remove this explicitly."""
    monkeypatch.setenv("SQUAD_ALLOW_UNAUTHENTICATED", "1")
    yield
