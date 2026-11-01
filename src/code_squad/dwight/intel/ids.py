from __future__ import annotations

import re
from typing import Final

_CVE: Final = re.compile(r"^CVE-\d{4}-\d{4,}$")
_VULN_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_cve_id(value: str) -> bool:
    return _CVE.match(value) is not None


def is_vuln_id(value: str) -> bool:
    return _VULN_ID.match(value) is not None


def is_iso_date(value: str) -> bool:
    return _DATE.match(value) is not None
