from __future__ import annotations

from pathlib import Path

import pytest

from code_squad._common.sandbox.errors import (
    CommandNotAllowedError,
    PathEscapeError,
    SandboxError,
)
from code_squad._common.sandbox.policy import (
    ALLOWED_EXECUTABLES,
    allowed_executables,
    safe_join,
    validate_argv,
    validate_branch,
    validate_patch,
    validate_ref,
    validate_repo_url,
)

ALLOWED = allowed_executables()


def _ok(argv: list[str], **kwargs: str) -> tuple[str, ...]:
    return validate_argv(argv, ALLOWED, **kwargs)


def test_allow_list_is_exactly_the_brief_set() -> None:
    assert (
        frozenset(
            {
                "git",
                "node",
                "npm",
                "pnpm",
                "yarn",
                "npx",
                "tsc",
                "vitest",
                "jest",
                "eslint",
                "prettier",
                "just",
                "make",
            }
        )
        == ALLOWED_EXECUTABLES
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["sh", "-c", "id"],
        ["bash", "-c", "id"],
        ["env", "FOO=1", "node"],
        ["curl", "https://example.test"],
        ["/bin/sh", "-c", "id"],
        ["./evil", "x"],
        ["../evil"],
        ["unknown-tool"],
        [],
        "git status",
        ["git", "status\x00"],
    ],
)
def test_unknown_shells_paths_and_malformed_argv_are_refused(argv: object) -> None:
    with pytest.raises(CommandNotAllowedError):
        validate_argv(argv, ALLOWED)  # type: ignore[arg-type]


def test_extra_executables_cannot_add_shells_or_interpreters() -> None:
    assert "gradle" in allowed_executables(["gradle"])
    with pytest.raises(ValueError):
        allowed_executables(["sh"])
    with pytest.raises(ValueError):
        allowed_executables(["/bin/sh"])


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "clone", "file:///tmp/x"],
        ["git", "push", "origin", "main"],
        ["git", "config", "credential.helper", "x"],
        ["git", "-c", "core.sshCommand=evil", "status"],
        ["git", "--git-dir=/x", "status"],
        ["git", "remote", "add", "x", "y"],
        ["git", "fetch", "--upload-pack=sh -c id", "origin"],
        ["git", "log", "--output=/tmp/x"],
        ["git", "diff", "--no-index", "/etc/passwd", "/etc/hosts"],
        ["git"],
    ],
)
def test_git_refuses_clone_push_config_and_dangerous_options(argv: list[str]) -> None:
    with pytest.raises(CommandNotAllowedError):
        _ok(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "add", "--pathspec-from-file=/etc/hostname"],
        ["git", "add", "--pathspec-file-nul", "--pathspec-from-file=x"],
        ["git", "add", "--pathspec-from-file", "/proc/self/environ"],
        ["git", "diff", "-O/etc/hostname"],
        ["git", "diff", "-O", "orderfile"],
        ["git", "status", "-C", "/tmp"],
        ["git", "status", "-ccore.pager=cat"],
        ["git", "diff", "-c", "core.pager=cat"],
        ["git", "log", "--config-env=core.pager=X"],
        ["git", "config", "--get", "core.pager"],
        ["git", "-c", "core.pager=cat", "status"],
    ],
)
def test_git_refuses_read_capable_and_config_altering_options(argv: list[str]) -> None:
    with pytest.raises(CommandNotAllowedError):
        _ok(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "commit", "-F", "/etc/hostname"],
        ["git", "commit", "--file=/etc/hostname"],
        ["git", "commit", "--template=/etc/hostname", "-m", "x"],
        ["git", "commit", "--allow-empty-message", "-m", "x"],
        ["git", "commit", "-a", "-m", "x"],
        ["git", "commit", "--amend", "-m", "x"],
        ["git", "commit", "-m", "x", "--no-verify"],
    ],
)
def test_git_commit_accepts_only_the_message_options(argv: list[str]) -> None:
    with pytest.raises(CommandNotAllowedError):
        _ok(argv)


def test_git_commit_accepts_message_and_quiet() -> None:
    assert _ok(["git", "commit", "-q", "-m", "fix: x"]) == (
        "git",
        "commit",
        "-q",
        "-m",
        "fix: x",
    )
    assert _ok(["git", "commit", "--message=fix: x"]) == (
        "git",
        "commit",
        "--message=fix: x",
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "status"],
        ["git", "switch", "-c", "feature/x"],
        ["git", "checkout", "-b", "feature/x"],
        ["git", "add", "--", "."],
        ["git", "commit", "-m", "fix: thing"],
        ["git", "diff", "--no-ext-diff", "HEAD"],
        ["git", "apply", "--whitespace=nowarn", "patch.diff"],
    ],
)
def test_git_allows_the_working_subcommands(argv: list[str]) -> None:
    assert _ok(argv) == tuple(argv)


def test_npm_install_always_gets_ignore_scripts() -> None:
    assert _ok(["npm", "install"]) == ("npm", "install", "--ignore-scripts")
    assert _ok(["npm", "ci"]) == ("npm", "ci", "--ignore-scripts")
    assert _ok(["pnpm", "install", "--frozen-lockfile"]) == (
        "pnpm",
        "install",
        "--frozen-lockfile",
        "--ignore-scripts",
    )
    assert _ok(["yarn", "install", "--ignore-scripts"]) == (
        "yarn",
        "install",
        "--ignore-scripts",
    )


def test_ignore_scripts_is_forced_before_double_dash() -> None:
    assert _ok(["npm", "install", "--", "--ignore-scripts"]) == (
        "npm",
        "install",
        "--ignore-scripts",
        "--",
        "--ignore-scripts",
    )


def test_npm_run_test_and_script_names() -> None:
    assert _ok(["npm", "run", "lint"]) == ("npm", "run", "lint")
    assert _ok(["npm", "test", "--", "--watch=false"]) == (
        "npm",
        "test",
        "--",
        "--watch=false",
    )
    with pytest.raises(CommandNotAllowedError):
        _ok(["npm", "run", "--prefix=/elsewhere"])
    with pytest.raises(CommandNotAllowedError):
        _ok(["npm", "run", "a;b"])


@pytest.mark.parametrize(
    "argv",
    [
        ["npm", "exec", "evil-package"],
        ["npm", "publish"],
        ["npm", "config", "set", "registry", "x"],
        ["npm", "--userconfig=/x", "test"],
        ["npm", "test", "--script-shell=/bin/sh"],
        ["pnpm", "dlx", "evil"],
        ["yarn", "exec", "evil"],
    ],
)
def test_package_managers_refuse_exec_and_config_redirects(argv: list[str]) -> None:
    with pytest.raises(CommandNotAllowedError):
        _ok(argv)


def test_npx_is_forced_to_no_install_and_needs_a_local_binary(tmp_path: Path) -> None:
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "tsc").write_text("#!/bin/sh\n")
    assert _ok(["npx", "tsc", "--noEmit"], local_bin_dir=str(bin_dir)) == (
        "npx",
        "--no",
        "tsc",
        "--noEmit",
    )
    with pytest.raises(CommandNotAllowedError):
        _ok(["npx", "cowsay", "hi"], local_bin_dir=str(bin_dir))
    with pytest.raises(CommandNotAllowedError):
        _ok(["npx", "-c", "id"])
    with pytest.raises(CommandNotAllowedError):
        _ok(["npx", "--package=evil", "tsc"])
    with pytest.raises(CommandNotAllowedError):
        _ok(["npx", "-p", "evil", "tsc"])


def test_node_runs_only_script_files_or_version() -> None:
    assert _ok(["node", "probe.js"]) == ("node", "probe.js")
    assert _ok(["node", "--version"]) == ("node", "--version")
    for argv in (
        ["node", "-e", "process.exit(0)"],
        ["node", "--eval=1"],
        ["node", "-p", "1"],
        ["node", "-r", "./hook.js", "x.js"],
        ["node"],
    ):
        with pytest.raises(CommandNotAllowedError):
            _ok(argv)
    for argv in (["node", "/etc/x.js"], ["node", "../x.js"]):
        with pytest.raises((CommandNotAllowedError, PathEscapeError)):
            _ok(argv)


def test_make_and_just_accept_plain_target_names_only() -> None:
    assert _ok(["make", "test"]) == ("make", "test")
    assert _ok(["just", "check:all"]) == ("just", "check:all")
    for argv in (
        ["make", "-f", "/tmp/evil.mk"],
        ["make", "CC=evil"],
        ["just", "--justfile", "/x"],
        ["make", "$(shell id)"],
        ["make", "-jx"],
    ):
        with pytest.raises(CommandNotAllowedError):
            _ok(argv)


def test_plain_tools_pass_through() -> None:
    assert _ok(["vitest", "run"]) == ("vitest", "run")
    assert _ok(["eslint", ".", "--max-warnings=0"]) == (
        "eslint",
        ".",
        "--max-warnings=0",
    )


def test_repo_urls_are_limited_to_allowed_schemes_and_carry_no_credentials() -> None:
    assert validate_repo_url("https://git.example.test/org/app.git", ("https",))
    for url in (
        "ext::sh -c id",
        "git@git.example.test:org/app.git",
        "https://user:secret@git.example.test/org/app.git",
        "https://git.example.test/a b",
        "-uplink",
        "file:///tmp/x",
    ):
        with pytest.raises(SandboxError):
            validate_repo_url(url, ("https",))


def test_refs_and_branches_are_validated() -> None:
    assert validate_ref("main") == "main"
    for ref in ("-x", "a..b", "a/", "x.lock", "a//b", "HEAD@{1}"):
        with pytest.raises(SandboxError):
            validate_ref(ref)


@pytest.mark.parametrize(
    "branch", ["main", "master", "develop", "release/1.2", "Main", "HEAD"]
)
def test_protected_branches_are_refused(branch: str) -> None:
    with pytest.raises(SandboxError):
        validate_branch(branch, ("main", "master", "develop", "release/*"))


def test_feature_branch_names_pass() -> None:
    assert (
        validate_branch("pam/ENG-12-add-filter", ("main", "release/*"))
        == "pam/ENG-12-add-filter"
    )


def test_safe_join_refuses_traversal_absolute_and_symlink_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside)
    assert safe_join(root, "src/a.ts") == (root / "src" / "a.ts").resolve()
    for rel in ("../x", "/etc/passwd", "src/../../x", "escape/secret", ".git/config"):
        with pytest.raises(PathEscapeError):
            safe_join(root, rel)
    assert safe_join(root, ".git/HEAD", allow_git=True).name == "HEAD"


def test_patch_with_escaping_or_git_paths_is_refused() -> None:
    good = (
        "diff --git a/src/a.txt b/src/a.txt\n"
        "--- a/src/a.txt\n"
        "+++ b/src/a.txt\n"
        "@@ -1 +1 @@\n-one\n+two\n"
    )
    validate_patch(good)
    bad_paths = [
        "--- a/../../etc/passwd\n+++ b/../../etc/passwd\n",
        "--- a/.git/hooks/pre-commit\n+++ b/.git/hooks/pre-commit\n",
        "--- /dev/null\n+++ b//etc/passwd\n",
        "rename from ../x\nrename to y\n",
    ]
    for patch in bad_paths:
        with pytest.raises(SandboxError):
            validate_patch(patch)


def test_patch_creating_symlinks_is_refused() -> None:
    patch = (
        "diff --git a/link b/link\nnew file mode 120000\n"
        "index 0000000..1111111 120000\n"
        "--- /dev/null\n+++ b/link\n@@ -0,0 +1 @@\n+/etc/passwd\n"
    )
    with pytest.raises(SandboxError):
        validate_patch(patch)
