from __future__ import annotations

import pytest

from code_squad._common.config.schema import ImplementerConfig
from code_squad.pam.workflow import (
    CheckOutcome,
    WorkflowError,
    branch_name,
    check_task_key,
    commit_message,
    declares_recipe,
    detect_checks,
    detect_package_manager,
    install_command,
    protected_path_violations,
    protected_paths_touched,
    render_mr_body,
    render_title,
    slugify,
)

PACKAGE_WITH_SCRIPTS = (
    '{"scripts": {"lint": "eslint .", "test": "vitest run", "build": "vite build"}}'
)
PROTECTED = ImplementerConfig().protected_paths


def test_slugify_lowercases_and_collapses_separators() -> None:
    assert slugify("Add Dark-Mode toggle!!") == "add-dark-mode-toggle"


def test_slugify_truncates_at_a_word_boundary() -> None:
    slug = slugify("Refactor the billing summary card layout", max_len=20)
    assert slug == "refactor-the"
    assert len(slug) <= 20


def test_slugify_falls_back_when_nothing_is_left() -> None:
    assert slugify("!!! ???") == "change"


def test_slugify_rejects_non_positive_length() -> None:
    with pytest.raises(WorkflowError):
        slugify("x", max_len=0)


def test_default_branch_template_yields_pam_prefix() -> None:
    name = branch_name("pam/{task_key}-{slug}", "PROJ-123", "Add a toggle")
    assert name == "pam/PROJ-123-add-a-toggle"


def test_custom_template_is_filled_and_validated() -> None:
    assert branch_name("feat/{slug}", "T1", "Fix Modal") == "feat/fix-modal"


def test_branch_template_producing_an_invalid_ref_is_refused() -> None:
    with pytest.raises(WorkflowError):
        branch_name("pam/../{task_key}", "PROJ-1", "x")


@pytest.mark.parametrize("key", ["", "-x", "a b", "a/b", "#42"])
def test_task_key_must_be_a_plain_token(key: str) -> None:
    with pytest.raises(WorkflowError):
        check_task_key(key)


def test_task_key_accepts_jira_style_keys() -> None:
    assert check_task_key("PROJ-123") == "PROJ-123"


def test_detect_override_wins_over_everything() -> None:
    commands = detect_checks(
        PACKAGE_WITH_SCRIPTS,
        has_justfile=True,
        has_makefile=True,
        override=["npm test -- --run", "git status --short"],
    )
    assert commands == [["npm", "test", "--", "--run"], ["git", "status", "--short"]]


def test_detect_override_rejects_unparseable_or_empty_commands() -> None:
    with pytest.raises(WorkflowError):
        detect_checks(None, False, False, override=["npm run 'lint"])
    with pytest.raises(WorkflowError):
        detect_checks(None, False, False, override=["   "])


def test_detect_prefers_just_check_then_make_check() -> None:
    assert detect_checks(PACKAGE_WITH_SCRIPTS, True, False, None) == [["just", "check"]]
    assert detect_checks(PACKAGE_WITH_SCRIPTS, False, True, None) == [["make", "check"]]


def test_detect_npm_scripts_in_order() -> None:
    assert detect_checks(PACKAGE_WITH_SCRIPTS, False, False, None) == [
        ["npm", "run", "lint"],
        ["npm", "run", "test"],
        ["npm", "run", "build"],
    ]


def test_detect_uses_detected_package_manager() -> None:
    pnpm = detect_checks(
        PACKAGE_WITH_SCRIPTS, False, False, None, package_manager="pnpm"
    )
    yarn = detect_checks(
        PACKAGE_WITH_SCRIPTS, False, False, None, package_manager="yarn"
    )
    assert pnpm[0] == ["pnpm", "run", "lint"]
    assert yarn[0] == ["yarn", "run", "lint"]


def test_detect_falls_back_to_tsc_when_typescript_has_no_typecheck_script() -> None:
    package = '{"scripts": {"test": "jest"}, "devDependencies": {"typescript": "5"}}'
    commands = detect_checks(package, False, False, None)
    assert commands == [
        ["npx", "--no", "tsc", "--noEmit"],
        ["npm", "run", "test"],
    ]


def test_detect_returns_nothing_without_package_or_targets() -> None:
    assert detect_checks(None, False, False, None) == []
    assert detect_checks('{"name": "x"}', False, False, None) == []
    assert detect_checks("not json", False, False, None) == []


def test_package_manager_follows_the_lockfile() -> None:
    assert detect_package_manager(["pnpm-lock.yaml", "package-lock.json"]) == "pnpm"
    assert detect_package_manager(["yarn.lock"]) == "yarn"
    assert detect_package_manager([]) == "npm"


def test_install_commands_are_locked_when_a_lockfile_exists() -> None:
    assert install_command("npm", locked=True) == ["npm", "ci"]
    assert install_command("npm", locked=False) == ["npm", "install"]
    assert install_command("pnpm", locked=True) == [
        "pnpm",
        "install",
        "--frozen-lockfile",
    ]


def test_recipe_detection_matches_check_targets_only() -> None:
    assert declares_recipe("check:\n\tnpm test\n", "check", make=True)
    assert not declares_recipe("check := 1\n", "check", make=True)
    assert declares_recipe("check arg:\n    echo\n", "check", make=False)
    assert not declares_recipe("lint:\n    x\n", "check", make=False)


def test_protected_globs_match_ci_files_and_lockfiles() -> None:
    changed = [
        ".github/workflows/ci.yml",
        ".gitlab-ci.yml",
        "packages/app/package-lock.json",
        "yarn.lock",
        "src/app.tsx",
    ]
    assert protected_paths_touched(changed, PROTECTED) == [
        ".github/workflows/ci.yml",
        ".gitlab-ci.yml",
        "packages/app/package-lock.json",
        "yarn.lock",
    ]


def test_protected_violations_are_empty_when_the_task_requires_the_paths() -> None:
    changed = [".github/workflows/ci.yml", "src/app.tsx"]
    assert protected_path_violations(changed, PROTECTED, "default") == [
        ".github/workflows/ci.yml"
    ]
    assert (
        protected_path_violations(changed, PROTECTED, "requires_protected_paths") == []
    )


def test_protected_glob_does_not_match_look_alike_paths() -> None:
    assert protected_paths_touched(["src/github/x.ts"], PROTECTED) == []
    assert protected_paths_touched(["docs/yarn.lock.md"], PROTECTED) == []


def test_commit_message_applies_template_and_keeps_one_line() -> None:
    message = commit_message(
        "feat({task_key}): {summary}", summary="add toggle", task_key="ENG-1"
    )
    assert message == "feat(ENG-1): add toggle"


def test_commit_message_refuses_multiline_summaries() -> None:
    with pytest.raises(WorkflowError):
        commit_message("feat: {summary}", summary="a\nb", task_key="T")


def test_render_title_uses_template() -> None:
    assert render_title(
        "{task_key}: {summary}", summary="Add toggle", task_key="E-1"
    ) == ("E-1: Add toggle")


def test_mr_body_contains_sections_checks_and_protected_notice() -> None:
    body = render_mr_body(
        ImplementerConfig().mr_body_template,
        what="Adds the toggle.",
        why="Users asked for it.",
        how_tested="Unit tests pass.",
        risks="none known",
        checks=[
            CheckOutcome("npm run lint", True, 0),
            CheckOutcome("npm run test", False, 1),
        ],
        protected_touched=[".github/workflows/ci.yml"],
    )
    assert "## What\nAdds the toggle." in body
    assert "## How tested\nUnit tests pass." in body
    assert "| npm run test | FAIL | 1 |" in body
    assert "| npm run lint | pass | 0 |" in body
    assert "## Protected paths touched" in body
    assert "`.github/workflows/ci.yml`" in body
    assert "A human reviews and merges" in body


def test_mr_body_states_when_checks_were_not_run() -> None:
    body = render_mr_body(
        "## What\n{summary}",
        what="x",
        why="y",
        how_tested="z",
        risks="none known",
        checks=[],
        protected_touched=[],
    )
    assert "Not run" in body
    assert "## Protected paths" not in body


def test_mr_body_escapes_pipes_in_check_names() -> None:
    body = render_mr_body(
        "{what}",
        what="x",
        why="",
        how_tested="",
        risks="",
        checks=[CheckOutcome("make a|b", True, 0)],
        protected_touched=[],
    )
    assert "make a\\|b" in body
