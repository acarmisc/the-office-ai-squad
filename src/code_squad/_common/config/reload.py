"""Hot reload of org and registry files: mtime polling and SIGHUP.

A reload that fails keeps the last good configuration, increments
``squad_config_reload_failures_total`` and logs a warning. The failed signature is
remembered, so a broken file is reported once, not on every poll.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_squad._common.config.loader import ConfigSources, load_org, load_registry
from code_squad._common.config.projects import ProjectRegistry
from code_squad._common.observability import CONFIG_RELOAD_FAILURES

_LOG = logging.getLogger(__name__)
Signature = tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class LoadedConfig:
    org: dict[str, Any]
    registry: ProjectRegistry
    generation: int


def _stat(path: Path) -> tuple[str, int, int]:
    try:
        info = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), info.st_mtime_ns, info.st_size)


def _signature(sources: ConfigSources) -> Signature:
    paths: list[Path] = []
    if sources.org_file is not None:
        paths.append(sources.org_file)
    for root in (sources.projects_dir, sources.profiles_dir):
        if root is None:
            continue
        if root.is_dir():
            paths.extend(sorted(root.rglob("*.y*ml")))
        else:
            paths.append(root)
    return tuple(_stat(path) for path in paths)


def _load(sources: ConfigSources, generation: int) -> LoadedConfig:
    return LoadedConfig(
        org=load_org(sources),
        registry=load_registry(sources),
        generation=generation,
    )


class ConfigWatcher:
    def __init__(
        self,
        sources: ConfigSources,
        *,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._sources = sources
        self._on_error = on_error
        self._lock = threading.RLock()
        self._current = _load(sources, generation=1)
        self._signature = _signature(sources)

    def current(self) -> LoadedConfig:
        with self._lock:
            return self._current

    def check_reload(self) -> bool:
        """Reload if a watched file changed; True when a new config is live."""
        signature = _signature(self._sources)
        if signature == self._signature:
            return False
        return self._reload(signature)

    def force_reload(self) -> bool:
        return self._reload(_signature(self._sources))

    def _reload(self, signature: Signature) -> bool:
        with self._lock:
            generation = self._current.generation + 1
            try:
                fresh = _load(self._sources, generation)
            except Exception as exc:
                CONFIG_RELOAD_FAILURES.inc()
                _LOG.warning("config reload rejected, keeping previous: %s", exc)
                self._signature = signature
                if self._on_error is not None:
                    self._on_error(exc)
                return False
            self._current = fresh
            self._signature = signature
            return True


def install_sighup_handler(watcher: ConfigWatcher) -> bool:
    """Reload on SIGHUP. Returns False where signals cannot be installed."""
    if not hasattr(signal, "SIGHUP"):
        return False
    if threading.current_thread() is not threading.main_thread():
        return False

    def _on_hup(signum: int, frame: object) -> None:
        del signum, frame
        watcher.force_reload()

    signal.signal(signal.SIGHUP, _on_hup)
    return True
