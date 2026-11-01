from __future__ import annotations

from code_squad._common.vcs.base import FileDiff
from code_squad._common.vcs.diff import line_in_changed_hunk, parse_patch

PATCH = (
    "@@ -1,3 +1,4 @@\n"
    " keep\n"
    "+added one\n"
    " middle\n"
    " tail\n"
    "@@ -20,2 +21,3 @@\n"
    " ctx\n"
    "-removed\n"
    "+new a\n"
    "+new b\n"
    "\\ No newline at end of file\n"
)


def _file(patch: str) -> FileDiff:
    return FileDiff("a.py", "a.py", "modified", parse_patch(patch), patch, False, False)


def test_parses_hunk_ranges_and_added_lines() -> None:
    hunks = parse_patch(PATCH)
    assert len(hunks) == 2
    assert (hunks[0].new_start, hunks[0].new_lines) == (1, 4)
    assert hunks[0].added_lines == frozenset({2})
    assert (hunks[1].old_start, hunks[1].old_lines) == (20, 2)
    assert (hunks[1].new_start, hunks[1].new_lines) == (21, 3)
    assert hunks[1].added_lines == frozenset({22, 23})


def test_default_counts_are_one_when_omitted() -> None:
    [hunk] = parse_patch("@@ -5 +7 @@\n-old\n+new\n")
    assert (hunk.old_lines, hunk.new_lines) == (1, 1)
    assert hunk.added_lines == frozenset({7})


def test_empty_patch_has_no_hunks() -> None:
    assert parse_patch("") == ()


def test_line_inside_changed_hunk_including_context() -> None:
    file_diff = _file(PATCH)
    assert line_in_changed_hunk(file_diff, 2, 2)
    assert line_in_changed_hunk(file_diff, 4, 4)
    assert line_in_changed_hunk(file_diff, 3, 40)
    assert not line_in_changed_hunk(file_diff, 10, 12)


def test_range_outside_all_hunks_is_rejected_and_reversed_range_is_normalised() -> None:
    file_diff = _file(PATCH)
    assert not line_in_changed_hunk(file_diff, 30, 31)
    assert line_in_changed_hunk(file_diff, 4, 2)


def test_pure_deletion_hunk_has_no_new_side_lines() -> None:
    file_diff = _file("@@ -3,2 +2,0 @@\n-gone\n-gone too\n")
    assert not line_in_changed_hunk(file_diff, 2, 2)
