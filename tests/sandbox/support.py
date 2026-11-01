from __future__ import annotations

import base64
import os
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from kubernetes.client import V1Pod, V1PodStatus
from kubernetes.client.exceptions import ApiException
from kubernetes.stream.ws_client import V5_CHANNEL_PROTOCOL

FAKE_TOKEN = "fake-token-for-tests"
FAKE_USER = "squad-bot"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.test",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.test",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def run_git(args: Sequence[str], cwd: Path) -> str:
    env = {**os.environ, **GIT_ENV}
    done = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )
    return done.stdout


def make_bare_repo(root: Path) -> Path:
    """A bare repository with one commit on main, built with plain git fixtures."""
    work = root / "work"
    work.mkdir(parents=True)
    run_git(["init", "-q", "-b", "main"], work)
    (work / "README.md").write_text("hello\n")
    run_git(["add", "."], work)
    run_git(["commit", "-q", "-m", "init"], work)
    bare = root / "bare.git"
    run_git(["clone", "-q", "--bare", str(work), str(bare)], root)
    return bare


def git_head_commit(bare: Path, branch: str) -> str:
    return run_git(["rev-parse", f"refs/heads/{branch}"], bare).strip()


class _GitHandler(BaseHTTPRequestHandler):
    server: _GitServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        expected = base64.b64encode(
            f"{FAKE_USER}:{self.server.token}".encode()
        ).decode()
        return header == f"Basic {expected}"

    def _serve(self) -> None:
        if not self._authorized():
            self.server.auth_failures += 1
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="fixture"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        path, _, query = self.path.partition("?")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            **GIT_ENV,
            "GIT_PROJECT_ROOT": str(self.server.root),
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": path,
            "REQUEST_METHOD": self.command,
            "QUERY_STRING": query,
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(len(body)),
            "REMOTE_USER": FAKE_USER,
            "REMOTE_ADDR": "127.0.0.1",
        }
        done = subprocess.run(
            ["git", "http-backend"],
            input=body,
            env=env,
            capture_output=True,
            check=False,
        )
        self._send_cgi(done.stdout)

    def _send_cgi(self, output: bytes) -> None:
        head, _, payload = output.partition(b"\r\n\r\n")
        if not payload and b"\n\n" in output:
            head, _, payload = output.partition(b"\n\n")
        status = 200
        self.send_response(status)
        for line in head.decode("latin-1").splitlines():
            name, _, value = line.partition(":")
            if name.lower() == "status":
                self.send_response(int(value.strip().split()[0]))
            elif name:
                self.send_header(name.strip(), value.strip())
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _GitServer(ThreadingHTTPServer):
    def __init__(self, root: Path, token: str) -> None:
        super().__init__(("127.0.0.1", 0), _GitHandler)
        self.root = root
        self.token = token
        self.auth_failures = 0


@dataclass
class GitHTTPFixture:
    server: _GitServer
    thread: threading.Thread = field(repr=False)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host!s}:{port}"

    @property
    def host(self) -> str:
        host, port = self.server.server_address[:2]
        return f"{host!s}:{port}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_git_http(root: Path, token: str = FAKE_TOKEN) -> GitHTTPFixture:
    server = _GitServer(root, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return GitHTTPFixture(server=server, thread=thread)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Script:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    hang: bool = False


Responder = Callable[[list[str], str | None], Script]


class FakeExecSession:
    """Stands in for a kubernetes WSClient: serves one scripted exec call."""

    subprotocol: str | None = V5_CHANNEL_PROTOCOL

    def __init__(self, script: Script, clock: FakeClock) -> None:
        self._script = script
        self._clock = clock
        self._pending = {1: script.stdout, 2: script.stderr}
        self._open = True
        self.stdin_received: list[str] = []
        self.closed_channels: list[int] = []
        self._returncode = script.exit_code

    def is_open(self) -> bool:
        return self._open

    def update(self, timeout: float = 0) -> None:
        self._clock.advance(timeout)
        if not self._script.hang:
            self._open = False

    def read_channel(self, channel: int, timeout: float = 0) -> str:
        data = self._pending.get(channel, "")
        self._pending[channel] = ""
        return data

    def write_stdin(self, data: str) -> None:
        self.stdin_received.append(data)

    def close_channel(self, channel: int) -> None:
        self.closed_channels.append(channel)

    def close(self, **kwargs: Any) -> None:
        self._open = False

    @property
    def returncode(self) -> int | None:
        return None if self._open else self._returncode


class FakeKubernetes:
    """Fake CoreV1Api plus exec stream. Records every pod operation and exec command."""

    def __init__(
        self,
        clock: FakeClock,
        responder: Responder | None = None,
        phases: Sequence[str] = ("Running",),
    ) -> None:
        self.clock = clock
        self.responder: Responder = responder or (lambda _c, _s: Script())
        self._phases = list(phases)
        self.created: list[V1Pod] = []
        self.deleted: list[dict[str, Any]] = []
        self.delete_status: int | None = None
        self.commands: list[list[str]] = []
        self.sessions: list[FakeExecSession] = []

    def create_namespaced_pod(self, namespace: str, body: V1Pod) -> V1Pod:
        self.created.append(body)
        return body

    def read_namespaced_pod(self, name: str, namespace: str) -> V1Pod:
        phase = self._phases[0] if len(self._phases) == 1 else self._phases.pop(0)
        return V1Pod(status=V1PodStatus(phase=phase))

    def delete_namespaced_pod(
        self, name: str, namespace: str, grace_period_seconds: int | None = None
    ) -> None:
        if self.delete_status is not None:
            raise ApiException(status=self.delete_status, reason="fake")
        self.deleted.append({"name": name, "grace": grace_period_seconds})

    def connect_get_namespaced_pod_exec(
        self, name: str, namespace: str, **kwargs: Any
    ) -> None:
        return None

    def stream(
        self, api_method: Any, name: str, namespace: str, **kwargs: Any
    ) -> FakeExecSession:
        command = list(kwargs["command"])
        self.commands.append(command)
        script = self.responder(command, None)
        session = FakeExecSession(script, self.clock)
        self.sessions.append(session)
        return session


def inner_command(command: list[str]) -> list[str]:
    """Strips the sandbox wrapper: env -i ... timeout --kill-after=N SECS argv..."""
    marker = command.index("timeout")
    return command[marker + 3 :]
