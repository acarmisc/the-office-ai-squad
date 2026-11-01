"""Record real project command output as asciinema casts and animated SVG terminals.

Usage: uv run python scripts/record_demos.py [--only NAME ...]

Each demo runs the project's own commands, strips ANSI codes, normalises volatile values
(durations, log timestamps, temporary paths) and writes two files from one timeline:

  docs/assets/casts/<name>.cast   asciinema v2 (play with: asciinema play <file>)
  docs/assets/demos/<name>.svg    self-contained animated SVG: CSS keyframes only, no
                                  scripts, no external fonts or images

Typing and output delays are fixed constants, so the same output always gives the same
files. A demo whose prerequisite is missing (the compose stack for the smoke test) is
skipped and reported. A command that exits non-zero stops the run: the demos must show
success.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
CAST_DIR: Final = REPO_ROOT / "docs" / "assets" / "casts"
SVG_DIR: Final = REPO_ROOT / "docs" / "assets" / "demos"

TYPE_DELAY: Final = 0.045
OUTPUT_DELAY: Final = 0.12
PROMPT_PAUSE: Final = 0.35
COMMAND_PAUSE: Final = 1.2
TAIL_PAUSE: Final = 3.0
FIXED_TIMESTAMP: Final = 1767225600
COLUMNS: Final = 100
CHAR_WIDTH: Final = 8.4
LINE_HEIGHT: Final = 19
TITLE_HEIGHT: Final = 34
PADDING: Final = 16

_ANSI: Final = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_DURATION: Final = re.compile(r"\bin \d+(?:\.\d+)?s\b")
_SECONDS: Final = re.compile(r"\bin \d+(?:\.\d+)? seconds\b")
_LOG_TS: Final = re.compile(r'"ts": "[^"]*", ')


class RecordError(RuntimeError):
    """A demo command failed or a prerequisite was not met."""


@dataclass(frozen=True)
class Step:
    """One demo command. ``keep`` output lines are shown, from the end when ``tail``."""

    display: str
    argv: tuple[str, ...]
    keep: int = 12
    tail: bool = False
    drop_prefixes: tuple[str, ...] = ()
    if_empty: str = ""
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TermLine:
    """One visible terminal line, shown at ``at`` seconds into the loop."""

    at: float
    text: str
    prompt: bool = False


@dataclass(frozen=True)
class Transcript:
    """A recorded terminal session, ready to render as a cast or an SVG."""

    name: str
    title: str
    lines: tuple[TermLine, ...]
    duration: float


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text).replace("\r", "")


def normalise(text: str, replacements: Mapping[str, str]) -> str:
    """Remove volatile values so reruns produce the same output."""
    out = strip_ansi(text)
    for old, new in replacements.items():
        out = out.replace(old, new)
    out = _DURATION.sub("in N.NNs", out)
    out = _SECONDS.sub("in N.NN seconds", out)
    return _LOG_TS.sub("", out)


def select_lines(lines: Sequence[str], keep: int, tail: bool) -> list[str]:
    """Keep ``keep`` lines and say how many were left out."""
    if len(lines) <= keep:
        return list(lines)
    hidden = len(lines) - keep
    chosen = lines[-keep:] if tail else lines[:keep]
    note = f"... ({hidden} more lines not shown)"
    return [note, *chosen] if tail else [*chosen, note]


def build_transcript(
    name: str, title: str, runs: Sequence[tuple[str, Sequence[str]]]
) -> Transcript:
    """Lay out prompts and output on one timeline with fixed pauses."""
    lines: list[TermLine] = []
    clock = 0.6
    for display, output in runs:
        prompt = f"$ {display}"
        lines.append(TermLine(at=clock, text=prompt, prompt=True))
        clock += len(prompt) * TYPE_DELAY + PROMPT_PAUSE
        for text in output:
            lines.append(TermLine(at=clock, text=text))
            clock += OUTPUT_DELAY
        clock += COMMAND_PAUSE
    lines.append(TermLine(at=clock, text="$ ", prompt=True))
    return Transcript(
        name=name,
        title=title,
        lines=tuple(lines),
        duration=round(clock + TAIL_PAUSE, 3),
    )


def render_cast(transcript: Transcript) -> str:
    """asciinema v2: a JSON header line, then ``[time, "o", data]`` events."""
    widest = max((len(line.text) for line in transcript.lines), default=COLUMNS)
    width = max(COLUMNS, widest + 2)
    height = len(transcript.lines) + 2
    header = {
        "version": 2,
        "width": width,
        "height": height,
        "timestamp": FIXED_TIMESTAMP,
        "title": transcript.title,
        "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"},
    }
    events: list[tuple[float, str]] = []
    for line in transcript.lines:
        if not line.prompt:
            events.append((line.at, line.text + "\r\n"))
            continue
        for index, char in enumerate(line.text):
            events.append((round(line.at + index * TYPE_DELAY, 3), char))
        typed_end = line.at + len(line.text) * TYPE_DELAY
        events.append((round(typed_end + 0.1, 3), "\r\n"))
    events.sort(key=lambda item: item[0])
    rows = [json.dumps(header, separators=(",", ":"))]
    rows.extend(json.dumps([at, "o", data]) for at, data in events)
    return "\n".join(rows) + "\n"


def render_svg(transcript: Transcript) -> str:
    """A dark terminal in pure SVG. Each line fades in at its time, then loops."""
    lines = transcript.lines
    cols = max((len(line.text) for line in lines), default=60)
    width = round(max(cols, 60) * CHAR_WIDTH + PADDING * 2)
    height = round(TITLE_HEIGHT + PADDING * 2 + len(lines) * LINE_HEIGHT)
    duration = transcript.duration
    rules: list[str] = []
    rows: list[str] = []
    for index, line in enumerate(lines):
        share = round(line.at / duration * 100, 3)
        fade = round(min(share + 0.25, 100.0), 3)
        rules.append(
            f"@keyframes r{index}{{0%,{share}%{{opacity:0}}{fade}%,100%{{opacity:1}}}}"
            f".l{index}{{animation:r{index} {duration}s linear infinite}}"
        )
        y = TITLE_HEIGHT + PADDING + (index + 1) * LINE_HEIGHT - 5
        css_class = "p" if line.prompt else "o"
        rows.append(
            f'<text class="{css_class} l{index}" x="{PADDING}" y="{y}" '
            f'xml:space="preserve">{escape(line.text)}</text>'
        )
    style = "".join(rules)
    title = escape(transcript.title)
    label = escape(transcript.title, {'"': "&quot;"})
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{label}">'
        f"<title>{title}</title>"
        "<style>"
        ".bg{fill:#0d1117}.bar{fill:#161b22}.ttl{fill:#8b949e;font:12px ui-monospace,"
        "Menlo,Consolas,monospace}"
        "text{font:14px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        "fill:#c9d1d9}.p{fill:#7ee787}"
        f"{style}"
        "@media (prefers-reduced-motion:reduce){"
        "text{animation:none!important;opacity:1}}"
        "</style>"
        f'<rect class="bg" width="{width}" height="{height}" rx="8"/>'
        f'<rect class="bar" width="{width}" height="{TITLE_HEIGHT}" rx="8"/>'
        '<circle cx="18" cy="17" r="6" fill="#ff5f56"/>'
        '<circle cx="38" cy="17" r="6" fill="#ffbd2e"/>'
        '<circle cx="58" cy="17" r="6" fill="#27c93f"/>'
        f'<text class="ttl" x="{width // 2}" y="22" text-anchor="middle">'
        f"{title}</text>" + "".join(rows) + "</svg>\n"
    )


def _env() -> dict[str, str]:
    base = dict(os.environ)
    base.update(
        {
            "NO_COLOR": "1",
            "TERM": "dumb",
            "LOG_LEVEL": "ERROR",
            "NO_MKDOCS_2_WARNING": "1",
            "COLUMNS": str(COLUMNS),
        }
    )
    return base


def run_step(step: Step, replacements: Mapping[str, str]) -> list[str]:
    env = _env()
    env.update(step.env)
    completed = subprocess.run(
        list(step.argv),
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RecordError(
            f"`{step.display}` exited {completed.returncode}:\n"
            f"{completed.stdout[-800:]}"
        )
    raw = normalise(completed.stdout, replacements).splitlines()
    kept = [line for line in raw if not line.startswith(step.drop_prefixes)]
    if not kept and step.if_empty:
        return [step.if_empty]
    return select_lines(kept, step.keep, step.tail)


def _docker_compose_running() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "compose", "-f", str(REPO_ROOT / "deploy/compose.yaml"), "ps", "-q"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return probe.returncode == 0 and bool(probe.stdout.strip())


def _config_demo(_replacements: Mapping[str, str]) -> list[Step]:
    return [
        Step(
            display="uv run squad config validate examples/org examples/repo",
            argv=(
                "uv",
                "run",
                "squad",
                "config",
                "validate",
                "examples/org",
                "examples/repo",
            ),
            keep=12,
        ),
        Step(
            display=(
                "uv run squad config explain acme/web-shop "
                "--org examples/org/squad.yaml "
                "--projects examples/org/projects.yaml --format yaml"
            ),
            argv=(
                "uv",
                "run",
                "squad",
                "config",
                "explain",
                "acme/web-shop",
                "--org",
                "examples/org/squad.yaml",
                "--projects",
                "examples/org/projects.yaml",
                "--format",
                "yaml",
            ),
            keep=16,
        ),
    ]


def _review_demo(_replacements: Mapping[str, str]) -> list[Step]:
    return [
        Step(
            display="uv run python -m scripts.demo_review",
            argv=("uv", "run", "python", "-m", "scripts.demo_review"),
            keep=20,
            drop_prefixes=('{"ts"',),
        ),
    ]


def _gate_demo(replacements: Mapping[str, str]) -> list[Step]:
    site = replacements["<site>"]
    return [
        Step("uv run ruff check .", ("uv", "run", "ruff", "check", "."), 1, True),
        Step(
            "uv run ruff format --check .",
            ("uv", "run", "ruff", "format", "--check", "."),
            1,
            True,
        ),
        Step(
            "uv run mypy src tests scripts eval deploy",
            ("uv", "run", "mypy", "src", "tests", "scripts", "eval", "deploy"),
            1,
            True,
        ),
        Step(
            "uv run pytest -q",
            ("uv", "run", "pytest", "-o", "addopts=", "-q"),
            2,
            True,
        ),
        Step(
            "uv run python scripts/gen_docs.py --check",
            ("uv", "run", "python", "scripts/gen_docs.py", "--check"),
            1,
            True,
            if_empty="no drift: the generated reference pages match the code",
        ),
        Step(
            "uv run mkdocs build --strict",
            ("uv", "run", "mkdocs", "build", "--strict", "--site-dir", site),
            1,
            True,
        ),
    ]


def _smoke_demo(_replacements: Mapping[str, str]) -> list[Step]:
    return [
        Step(
            display="scripts/smoke_test.sh compose",
            argv=("scripts/smoke_test.sh", "compose"),
            keep=14,
        ),
    ]


@dataclass(frozen=True)
class Demo:
    name: str
    title: str
    steps: Callable[[Mapping[str, str]], list[Step]]
    requires: Callable[[], bool] = field(default=lambda: True)
    skip_reason: str = ""


DEMOS: Final[tuple[Demo, ...]] = (
    Demo(
        name="config",
        title="squad config: validate and explain (examples/)",
        steps=_config_demo,
    ),
    Demo(
        name="review",
        title="One dry-run review with jim (scripted model, fake VCS)",
        steps=_review_demo,
    ),
    Demo(
        name="gate",
        title="just check: each step, summary lines only",
        steps=_gate_demo,
    ),
    Demo(
        name="smoke",
        title="scripts/smoke_test.sh compose",
        steps=_smoke_demo,
        requires=_docker_compose_running,
        skip_reason=(
            "the compose stack is not running "
            "(docker compose -f deploy/compose.yaml up -d)"
        ),
    ),
)


def record(demo: Demo) -> Transcript:
    with tempfile.TemporaryDirectory(prefix="code-squad-demo-") as scratch:
        replacements = {
            str(REPO_ROOT): ".",
            "<site>": os.path.join(scratch, "site"),
            scratch: "<tmp>",
        }
        runs: list[tuple[str, list[str]]] = []
        for step in demo.steps(replacements):
            runs.append((step.display, run_step(step, replacements)))
    return build_transcript(demo.name, demo.title, runs)


def write(transcript: Transcript) -> tuple[Path, Path]:
    CAST_DIR.mkdir(parents=True, exist_ok=True)
    SVG_DIR.mkdir(parents=True, exist_ok=True)
    cast = CAST_DIR / f"{transcript.name}.cast"
    svg = SVG_DIR / f"{transcript.name}.svg"
    cast.write_text(render_cast(transcript), encoding="utf-8")
    svg.write_text(render_svg(transcript), encoding="utf-8")
    return cast, svg


def main(argv: Sequence[str]) -> int:
    wanted = set(argv[1:]) if argv[:1] == ["--only"] else None
    status = 0
    for demo in DEMOS:
        if wanted is not None and demo.name not in wanted:
            continue
        if not demo.requires():
            print(f"skipped {demo.name}: {demo.skip_reason}", file=sys.stderr)
            continue
        try:
            transcript = record(demo)
        except RecordError as exc:
            print(f"error: {exc}", file=sys.stderr)
            status = 1
            continue
        cast, svg = write(transcript)
        print(
            f"{demo.name}: {len(transcript.lines)} lines, "
            f"{cast.relative_to(REPO_ROOT)} ({cast.stat().st_size} bytes), "
            f"{svg.relative_to(REPO_ROOT)} ({svg.stat().st_size} bytes)"
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
