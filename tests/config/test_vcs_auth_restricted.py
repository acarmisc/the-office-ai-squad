from __future__ import annotations

from typing import Any

import pytest

from code_squad._common.config.merge import check_restricted
from code_squad._common.config.schema import SquadConfig


@pytest.mark.parametrize("layer", ["repo", "call"])
@pytest.mark.parametrize(
    "overlay",
    [
        {"vcs": {"provider": "github"}},
        {"vcs": {"auth": {"token_secret": "other-token"}}},
    ],
)
def test_vcs_provider_and_auth_cannot_change_below_org(
    layer: Any, overlay: dict[str, Any]
) -> None:
    base = SquadConfig().model_dump(mode="json")
    assert check_restricted(base, overlay, layer)
