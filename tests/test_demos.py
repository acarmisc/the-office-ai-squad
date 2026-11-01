from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.record_demos import (
    CAST_DIR,
    DEMOS,
    SVG_DIR,
    Transcript,
    build_transcript,
    normalise,
    render_cast,
    render_svg,
    select_lines,
    strip_ansi,
)

SVG_NS = "{http://www.w3.org/2000/svg}"
REQUIRED = ("config", "review", "gate")


def _synthetic() -> Transcript:
    return build_transcript(
        "synthetic",
        'title with <markup> & "quotes"',
        [("echo hi", ["hi <there> & more", "second line"])],
    )


def test_svg_is_well_formed_and_animated() -> None:
    svg = render_svg(_synthetic())
    root = ET.fromstring(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert "@keyframes r0{" in svg
    assert "animation:r0" in svg
    assert "infinite" in svg
    assert "prefers-reduced-motion" in svg


def test_svg_has_no_script_or_external_reference() -> None:
    svg = render_svg(_synthetic())
    assert "<script" not in svg
    assert "<image" not in svg
    assert "@import" not in svg
    assert "url(" not in svg
    assert svg.count("http://www.w3.org/2000/svg") == 1


def test_svg_escapes_text_and_keeps_every_line() -> None:
    root = ET.fromstring(render_svg(_synthetic()))
    texts = [node.text for node in root.iter(f"{SVG_NS}text")]
    assert "hi <there> & more" in texts
    assert 'title with <markup> & "quotes"' in texts


def test_cast_header_is_valid_asciinema_v2() -> None:
    rows = render_cast(_synthetic()).splitlines()
    header = json.loads(rows[0])
    assert header["version"] == 2
    assert header["width"] >= 80
    assert header["height"] > 0
    assert header["title"] == 'title with <markup> & "quotes"'
    assert "timestamp" in header and "env" in header


def test_cast_events_are_monotonic_output_records() -> None:
    rows = render_cast(_synthetic()).splitlines()
    events: list[list[object]] = [json.loads(row) for row in rows[1:]]
    times = [float(str(event[0])) for event in events]
    assert times == sorted(times)
    assert all(len(event) == 3 and event[1] == "o" for event in events)
    assert all(isinstance(event[2], str) for event in events)
    text = "".join(str(event[2]) for event in events)
    assert "echo hi" in text
    assert "hi <there> & more\r\n" in text


def test_normalise_removes_volatile_values() -> None:
    raw = (
        "\x1b[32mok\x1b[0m\n"
        "1817 passed in 42.10s\n"
        "Documentation built in 1.26 seconds\n"
        '{"ts": "2026-11-01T10:00:00+00:00", "level": "INFO"}\n'
        "built at /tmp/scratch/site\n"
    )
    out = normalise(raw, {"/tmp/scratch": "<tmp>"})
    assert "\x1b" not in out
    assert "in N.NNs" in out
    assert "in N.NN seconds" in out
    assert "2026-11-01" not in out
    assert "<tmp>/site" in out
    assert strip_ansi("\x1b[1mbold\x1b[0m") == "bold"


def test_select_lines_marks_what_is_left_out() -> None:
    lines = [str(index) for index in range(10)]
    assert select_lines(lines, 3, tail=False) == [
        "0",
        "1",
        "2",
        "... (7 more lines not shown)",
    ]
    assert select_lines(lines, 2, tail=True) == [
        "... (8 more lines not shown)",
        "8",
        "9",
    ]
    assert select_lines(lines, 20, tail=False) == lines


def _read_cast(path: Path) -> list[list[object]]:
    rows = path.read_text(encoding="utf-8").splitlines()
    assert rows, path
    header = json.loads(rows[0])
    assert header["version"] == 2, path
    events: list[list[object]] = [json.loads(row) for row in rows[1:]]
    times = [float(str(event[0])) for event in events]
    assert times == sorted(times), path
    return events


@pytest.mark.parametrize("name", REQUIRED)
def test_committed_demos_exist_and_are_valid(name: str) -> None:
    svg = SVG_DIR / f"{name}.svg"
    cast = CAST_DIR / f"{name}.cast"
    assert svg.is_file(), f"missing {svg}; run scripts/record_demos.py"
    assert cast.is_file(), f"missing {cast}; run scripts/record_demos.py"
    root = ET.fromstring(svg.read_text(encoding="utf-8"))
    assert root.tag == f"{SVG_NS}svg"
    assert "@keyframes r0{" in svg.read_text(encoding="utf-8")
    assert "\x1b" not in svg.read_text(encoding="utf-8")
    events = _read_cast(cast)
    assert events, cast
    assert "\x1b" not in "".join(str(event[2]) for event in events)


def test_committed_demo_files_belong_to_a_known_demo() -> None:
    known = {demo.name for demo in DEMOS}
    for directory, suffix in ((SVG_DIR, ".svg"), (CAST_DIR, ".cast")):
        if not directory.is_dir():
            continue
        for path in directory.glob(f"*{suffix}"):
            assert path.stem in known, (
                f"{path} does not match a demo in record_demos.py"
            )


def test_readme_embeds_the_review_demo() -> None:
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8"
    )
    assert "docs/assets/demos/review.svg" in readme
