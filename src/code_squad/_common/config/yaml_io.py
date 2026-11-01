"""YAML loading for configuration files, hardened for repository-supplied input.

Repository files come from change requests' target branches, so they are treated as
untrusted: capped in size, and YAML aliases are refused because they expand
exponentially (the "billion laughs" pattern) and no configuration needs them.
"""

from __future__ import annotations

from typing import Any, Final

import yaml

from code_squad._common.config.errors import ConfigError

MAX_DOCUMENT_BYTES: Final[int] = 256 * 1024


def load_yaml(text: str, what: str) -> Any:
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ConfigError(f"{what} is larger than {MAX_DOCUMENT_BYTES // 1024} KiB")
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.AliasEvent):
                raise ConfigError(f"{what} uses YAML aliases, which are not supported")
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{what} is not valid YAML: {exc}") from exc
