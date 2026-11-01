from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from code_squad._common.config.errors import ConfigError
from code_squad._common.config.loader import ConfigSources
from code_squad._common.config.reload import ConfigWatcher, install_sighup_handler
from code_squad._common.observability import REGISTRY
from tests.config.support import write

GOOD = "review:\n  max_findings: 12\n"
BAD = "review:\n  max_findings: 0\n"


def _failures() -> float:
    value = REGISTRY.get_sample_value("squad_config_reload_failures_total")
    return value or 0.0


def _touch(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))


@pytest.fixture
def org_path(tmp_path: Path) -> Path:
    return write(tmp_path, "squad.yaml", GOOD)


@pytest.fixture
def watcher(org_path: Path) -> ConfigWatcher:
    return ConfigWatcher(ConfigSources(org_path, {}, None, None))


def test_initial_load_reads_the_org_file(watcher: ConfigWatcher) -> None:
    assert watcher.current().org == {"review": {"max_findings": 12}}
    assert watcher.current().generation == 1


def test_no_change_means_no_reload(watcher: ConfigWatcher) -> None:
    assert watcher.check_reload() is False
    assert watcher.current().generation == 1


def test_good_change_is_applied(watcher: ConfigWatcher, org_path: Path) -> None:
    _touch(org_path, "review:\n  max_findings: 20\n")
    assert watcher.check_reload() is True
    assert watcher.current().org == {"review": {"max_findings": 20}}
    assert watcher.current().generation == 2


def test_bad_change_keeps_the_previous_config_and_counts_a_failure(
    watcher: ConfigWatcher, org_path: Path
) -> None:
    errors: list[Exception] = []
    watcher._on_error = errors.append
    before = _failures()
    _touch(org_path, BAD)
    assert watcher.check_reload() is False
    assert watcher.current().org == {"review": {"max_findings": 12}}
    assert watcher.current().generation == 1
    assert _failures() == before + 1
    assert len(errors) == 1
    assert isinstance(errors[0], ConfigError)


def test_a_broken_file_is_reported_once_not_on_every_poll(
    watcher: ConfigWatcher, org_path: Path
) -> None:
    before = _failures()
    _touch(org_path, BAD)
    watcher.check_reload()
    watcher.check_reload()
    watcher.check_reload()
    assert _failures() == before + 1


def test_fixing_the_file_recovers(watcher: ConfigWatcher, org_path: Path) -> None:
    _touch(org_path, BAD)
    assert watcher.check_reload() is False
    _touch(org_path, "review:\n  max_findings: 15\n")
    assert watcher.check_reload() is True
    assert watcher.current().org["review"]["max_findings"] == 15


def test_force_reload_reloads_without_a_change(
    watcher: ConfigWatcher, org_path: Path
) -> None:
    org_path.write_text("review:\n  max_findings: 9\n", encoding="utf-8")
    assert watcher.force_reload() is True
    assert watcher.current().org["review"]["max_findings"] == 9


def test_registry_directory_changes_are_seen(tmp_path: Path, org_path: Path) -> None:
    registry_dir = tmp_path / "projects"
    registry_dir.mkdir()
    watcher = ConfigWatcher(ConfigSources(org_path, {}, registry_dir, None))
    assert watcher.current().registry.entries == []
    write(registry_dir, "web.yaml", "match: acme/web-shop\nprovider: github\n")
    assert watcher.check_reload() is True
    assert [entry.match for entry in watcher.current().registry.entries] == [
        "acme/web-shop"
    ]


def test_initial_load_failure_raises(tmp_path: Path) -> None:
    bad = write(tmp_path, "squad.yaml", BAD)
    with pytest.raises(ConfigError):
        ConfigWatcher(ConfigSources(bad, {}, None, None))


@pytest.fixture
def restore_sighup() -> Iterator[None]:
    previous = signal.getsignal(signal.SIGHUP)
    yield
    signal.signal(signal.SIGHUP, previous)


def test_sighup_forces_a_reload(
    watcher: ConfigWatcher, org_path: Path, restore_sighup: None
) -> None:
    assert install_sighup_handler(watcher) is True
    org_path.write_text("review:\n  max_findings: 77\n", encoding="utf-8")
    os.kill(os.getpid(), signal.SIGHUP)
    deadline = time.monotonic() + 3
    while watcher.current().org["review"]["max_findings"] != 77:
        assert time.monotonic() < deadline, "SIGHUP did not reload the config"
        time.sleep(0.01)


def test_sighup_with_a_bad_file_keeps_the_previous_config(
    watcher: ConfigWatcher, org_path: Path, restore_sighup: None
) -> None:
    install_sighup_handler(watcher)
    before = _failures()
    org_path.write_text(BAD, encoding="utf-8")
    os.kill(os.getpid(), signal.SIGHUP)
    deadline = time.monotonic() + 3
    while _failures() == before:
        assert time.monotonic() < deadline, "failure was not recorded"
        time.sleep(0.01)
    assert watcher.current().org == {"review": {"max_findings": 12}}


def test_sighup_is_not_installed_from_a_worker_thread(watcher: ConfigWatcher) -> None:
    results: list[bool] = []
    worker = threading.Thread(
        target=lambda: results.append(install_sighup_handler(watcher))
    )
    worker.start()
    worker.join()
    assert results == [False]
