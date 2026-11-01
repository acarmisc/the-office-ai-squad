"""Starter ``.squad/config.yml`` files for ``squad config init``."""

from __future__ import annotations

from typing import Final

SCHEMA_HINT: Final[str] = (
    "# yaml-language-server: $schema="
    "https://raw.githubusercontent.com/acarmisc/the-office-ai-squad/main/"
    "schemas/squad-config.schema.json"
)

_GENERIC: Final[str] = """\
# Repository configuration for Code Squad.
# Read from the target branch of each change request. Lower layers may only tighten
# settings: a value that loosens an org or profile setting drops this whole file.
#
# extends: balanced

review:
  # Files the reviewers skip: generated, vendored or lock files.
  ignore_globs:
    - "**/generated/**"
  # Findings below this confidence are not published.
  min_confidence_to_publish: medium

trigger:
  # Only start reviews for these comment commands.
  slash_commands: [review, sec, help]
"""

_REACT: Final[str] = """\
# Repository configuration for a React or TypeScript app.
#
# extends: balanced

routing:
  # Changes under these paths also raise the risk tier.
  sensitive_paths:
    - "**/auth/**"
    - "src/payments/**"

review:
  ignore_globs:
    - "**/*.stories.tsx"
    - "src/generated/**"
  min_severity_inline: minor

agents:
  jim:
    # Extra guidance for the React reviewer. Treated as untrusted guidance.
    prompt_extra: "Prefer hooks over class components. Flag direct DOM access."
"""

_JAVA: Final[str] = """\
# Repository configuration for a Java or Spring service.
#
# extends: balanced

routing:
  sensitive_paths:
    - "**/security/**"
    - "**/payment*/**"

review:
  ignore_globs:
    - "**/target/**"
    - "**/generated-sources/**"
  verdict:
    major_threshold: 1

agents:
  angela:
    prompt_extra: "Check JPA queries for N+1 patterns and missing transactions."
"""

_TEMPLATES: Final[dict[str, str]] = {
    "generic": _GENERIC,
    "react": _REACT,
    "java": _JAVA,
}


def scaffold(kind: str) -> str:
    body = _TEMPLATES[kind]
    return f"{SCHEMA_HINT}\n{body}"


def scaffold_kinds() -> tuple[str, ...]:
    return tuple(_TEMPLATES)
