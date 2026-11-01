from __future__ import annotations

import math
from typing import Final

_AV: Final = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC: Final = {"L": 0.77, "H": 0.44}
_PR_UNCHANGED: Final = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_CHANGED: Final = {"N": 0.85, "L": 0.68, "H": 0.5}
_UI: Final = {"N": 0.85, "R": 0.62}
_CIA: Final = {"H": 0.56, "L": 0.22, "N": 0.0}


def cvss3_base_score(vector: str) -> float | None:
    """CVSS v3.0/v3.1 base score from a vector string, or None if malformed."""
    if not vector.startswith(("CVSS:3.0/", "CVSS:3.1/")):
        return None
    try:
        metrics = dict(part.split(":", 1) for part in vector.split("/")[1:])
        changed = metrics["S"] == "C"
        av = _AV[metrics["AV"]]
        ac = _AC[metrics["AC"]]
        pr = (_PR_CHANGED if changed else _PR_UNCHANGED)[metrics["PR"]]
        ui = _UI[metrics["UI"]]
        conf = _CIA[metrics["C"]]
        integ = _CIA[metrics["I"]]
        avail = _CIA[metrics["A"]]
    except (KeyError, ValueError):
        return None
    iss = 1 - (1 - conf) * (1 - integ) * (1 - avail)
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    exploitability = 8.22 * av * ac * pr * ui
    if impact <= 0:
        return 0.0
    if changed:
        return _roundup(min(1.08 * (impact + exploitability), 10.0))
    return _roundup(min(impact + exploitability, 10.0))


def _roundup(value: float) -> float:
    scaled = round(value * 100000)
    if scaled % 10000 == 0:
        return scaled / 100000.0
    return (math.floor(scaled / 10000) + 1) / 10.0


def severity_band(score: float) -> str:
    if score == 0:
        return "NONE"
    if score < 4.0:
        return "LOW"
    if score < 7.0:
        return "MEDIUM"
    if score < 9.0:
        return "HIGH"
    return "CRITICAL"
