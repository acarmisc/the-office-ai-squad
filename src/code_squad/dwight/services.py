"""Builds dwight's per-invocation security services.

Building is lazy: no request leaves the process here. An optional secret that is missing
or unreadable leaves that source running without the key. The egress proxy is read from
``EGRESS_PROXY_URL`` by the HTTP layer.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Mapping
from datetime import date
from typing import Any, Final

from code_squad._common.config.schema import SecurityConfig
from code_squad._common.context import current
from code_squad._common.findings import VerdictCap
from code_squad._common.secrets.base import SecretProvider
from code_squad.dwight.guard import (
    UNVERIFIED,
    accepted_risk_guard,
    offline_verdict_guard,
    unverified,
)
from code_squad.dwight.intel.cache import TtlCache
from code_squad.dwight.intel.epss import EpssClient
from code_squad.dwight.intel.ghsa import GhsaClient
from code_squad.dwight.intel.http import IntelHttp
from code_squad.dwight.intel.kev import KevCatalog
from code_squad.dwight.intel.nvd import NvdClient
from code_squad.dwight.intel.osv import OsvClient
from code_squad.dwight.intel.service import IntelService
from code_squad.dwight.intel.triage import SeverityThresholds

INTEL_AGENTS: Final = frozenset({"dwight"})
NVD_KEY_SECRET: Final = "nvd-api-key"
GHSA_TOKEN_SECRET: Final = "ghsa-token"
PROXY_ENV: Final = "EGRESS_PROXY_URL"
NVD_HOST: Final = "services.nvd.nist.gov"
NVD_INTERVAL_NO_KEY: Final = 6.0
NVD_INTERVAL_WITH_KEY: Final = 0.6


def security_services(
    agent: str,
    security: SecurityConfig | None,
    secrets: SecretProvider | None,
    *,
    env: Mapping[str, str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    if agent not in INTEL_AGENTS:
        return {}
    cfg = security or SecurityConfig()
    cutoff = today or date.today()
    return {
        "intel": build_intel_service(cfg, secrets, env=env),
        "severity_thresholds": _thresholds(cfg),
        "offline_mode": cfg.offline_mode,
        "accepted_risks": tuple(r for r in cfg.accepted_risks if r.expires >= cutoff),
        "result_guards": [accepted_risk_guard, offline_verdict_guard],
        "publish_verdict_cap": publish_verdict_cap,
    }


def publish_verdict_cap() -> tuple[VerdictCap, str] | None:
    """Withhold approve at publish time when the offline guard would withhold it."""
    ctx = current()
    if not unverified(ctx.services, ctx.tool_calls):
        return None
    return "comment", UNVERIFIED


_INTEL_LOCK: Final = threading.Lock()
_INTEL_SERVICES: dict[str, IntelService] = {}


def reset_intel_services() -> None:
    """Forget the shared intel services; the next build starts with empty caches."""
    with _INTEL_LOCK:
        _INTEL_SERVICES.clear()


def build_intel_service(
    security: SecurityConfig | None,
    secrets: SecretProvider | None,
    *,
    env: Mapping[str, str] | None = None,
) -> IntelService:
    """One intel service per process and configuration, so KEV and caches persist.

    The key covers the security configuration, the egress proxy and whether the NVD and
    GHSA secrets exist. Rotating a secret's value needs a restart to take effect.
    """
    cfg = security or SecurityConfig()
    environ: Mapping[str, str] = os.environ if env is None else env
    proxy = environ.get(PROXY_ENV) or None
    nvd_key = _secret(secrets, NVD_KEY_SECRET)
    ghsa_token = _secret(secrets, GHSA_TOKEN_SECRET)
    key = _service_key(cfg, proxy, nvd_key is not None, ghsa_token is not None)
    with _INTEL_LOCK:
        service = _INTEL_SERVICES.get(key)
        if service is None:
            service = _new_intel_service(cfg, proxy, nvd_key, ghsa_token)
            _INTEL_SERVICES[key] = service
        return service


def _service_key(
    cfg: SecurityConfig, proxy: str | None, has_nvd: bool, has_ghsa: bool
) -> str:
    parts = (cfg.model_dump_json(), proxy or "", str(has_nvd), str(has_ghsa))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _new_intel_service(
    cfg: SecurityConfig,
    proxy: str | None,
    nvd_key: str | None,
    ghsa_token: str | None,
) -> IntelService:
    ttl = float(cfg.cache_ttl_seconds)
    interval = NVD_INTERVAL_WITH_KEY if nvd_key else NVD_INTERVAL_NO_KEY
    http = IntelHttp(
        allowed_hosts=frozenset(cfg.allowed_hosts),
        proxy_url=proxy,
        min_intervals={NVD_HOST: interval},
    )
    return IntelService(
        osv=OsvClient(
            http,
            query_cache=TtlCache(ttl_seconds=ttl),
            vuln_cache=TtlCache(ttl_seconds=ttl),
        ),
        ghsa=GhsaClient(
            http,
            token=ghsa_token,
            cache=TtlCache(ttl_seconds=ttl),
        ),
        nvd=NvdClient(http, api_key=nvd_key, cache=TtlCache(ttl_seconds=ttl)),
        kev=KevCatalog(http, refresh_seconds=ttl),
        epss=EpssClient(http, cache=TtlCache(ttl_seconds=ttl)),
        sources_enabled=_sources(cfg),
        thresholds=_thresholds(cfg),
    )


def _secret(secrets: SecretProvider | None, name: str) -> str | None:
    if secrets is None:
        return None
    try:
        return secrets.get(name) or None
    except (KeyError, ValueError, OSError):
        return None


def _sources(cfg: SecurityConfig) -> dict[str, bool]:
    sources = cfg.sources
    return {
        "osv": sources.osv,
        "ghsa": sources.ghsa,
        "nvd": sources.nvd,
        "kev": sources.kev,
        "epss": sources.epss,
    }


def _thresholds(cfg: SecurityConfig) -> SeverityThresholds:
    mapping = cfg.severity_mapping
    return SeverityThresholds(
        kev_is_blocker=mapping.kev_is_blocker,
        epss_major=mapping.epss_major,
        cvss_blocker=mapping.cvss_blocker,
        cvss_major=mapping.cvss_major,
    )
