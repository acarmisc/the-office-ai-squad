"""Built-in profiles. Files in the profiles directory override them by name."""

from __future__ import annotations

from typing import Any, Final

BUILTIN_PROFILES: Final[dict[str, dict[str, Any]]] = {
    "strict": {
        "vcs": {"approve_mode": "none"},
        "review": {
            "min_confidence_to_publish": "low",
            "min_severity_inline": "nit",
            "verdict": {"major_threshold": 1, "request_changes_on_blocker": True},
        },
        "security": {
            "severity_mapping": {
                "cvss_blocker": 7.0,
                "cvss_major": 4.0,
                "epss_major": 0.05,
            },
            "offline_mode": "fail_incomplete",
        },
        "skills": {"allowed_sources": ["payload", "builtin"]},
        "routing": {"size_thresholds": {"medium": 150, "high": 500}},
    },
    "balanced": {},
    "lenient": {
        "review": {
            "min_confidence_to_publish": "high",
            "min_severity_inline": "major",
            "verdict": {"major_threshold": 5},
        },
        "trigger": {"skip_draft": True},
    },
}
