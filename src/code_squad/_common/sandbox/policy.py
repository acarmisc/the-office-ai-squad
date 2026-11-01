from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import urlsplit

from code_squad._common.sandbox.errors import (
    CommandNotAllowedError,
    PathEscapeError,
    SandboxError,
)

ALLOWED_EXECUTABLES: Final = frozenset(
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
DENIED_EXECUTABLES: Final = frozenset(
    {
        "sh",
        "bash",
        "dash",
        "zsh",
        "ksh",
        "env",
        "xargs",
        "busybox",
        "sudo",
        "su",
        "ssh",
        "scp",
        "curl",
        "wget",
        "nc",
        "python",
        "python3",
        "perl",
        "ruby",
        "php",
        "awk",
        "gawk",
        "sed",
        "find",
        "tar",
        "docker",
        "kubectl",
        "helm",
    }
)
DEFAULT_PROTECTED_BRANCHES: Final = ("main", "master", "develop", "release/*")

MAX_ARGS: Final = 128
MAX_ARG_LEN: Final = 8192
MAX_PATH_LEN: Final = 1024

GIT_SUBCOMMANDS: Final = frozenset(
    {
        "checkout",
        "switch",
        "status",
        "diff",
        "add",
        "commit",
        "log",
        "show",
        "rev-parse",
        "branch",
        "apply",
        "fetch",
    }
)
_GIT_REFUSED: Final = {
    "clone": "use Sandbox.clone",
    "push": "use Sandbox.push",
}
_GIT_DENIED_LONG: Final = (
    "--config-env",
    "--exec",
    "--exec-path",
    "--ext-diff",
    "--file",
    "--git-dir",
    "--namespace",
    "--no-index",
    "--open-files-in-pager",
    "--output",
    "--receive-pack",
    "--super-prefix",
    "--template",
    "--textconv",
    "--unsafe-paths",
    "--upload-pack",
    "--work-tree",
)
_PACKAGE_MANAGER_SUBCOMMANDS: Final = {
    "npm": frozenset({"run", "run-script", "test", "install", "i", "ci"}),
    "pnpm": frozenset({"run", "test", "install", "i"}),
    "yarn": frozenset({"run", "test", "install"}),
}
_INSTALL_SUBCOMMANDS: Final = frozenset({"install", "i", "ci"})
_PACKAGE_MANAGER_DENIED_LONG: Final = (
    "--cache",
    "--cwd",
    "--globalconfig",
    "--prefix",
    "--registry",
    "--script-shell",
    "--shell",
    "--userconfig",
)
_NPX_ALLOWED_FLAGS: Final = frozenset({"--no", "--no-install"})
_NODE_VERSION_FLAGS: Final = frozenset({"--version", "-v"})

_SCRIPT_NAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9:_.-]{0,127}$")
_BIN_NAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_TARGET: Final = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.:-]{0,127}$")
_EXECUTABLE_NAME: Final = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_REF: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_MODE_LINES: Final = (
    "new file mode",
    "deleted file mode",
    "old mode",
    "new mode",
    "index ",
)
_PATH_KEYWORDS: Final = ("rename from ", "rename to ", "copy from ", "copy to ")


def allowed_executables(extra: Iterable[str] = ()) -> frozenset[str]:
    names = frozenset(extra)
    for name in names:
        if not _EXECUTABLE_NAME.match(name):
            raise ValueError(f"invalid executable name: {name!r}")
        if name in DENIED_EXECUTABLES:
            raise ValueError(f"executable can never be allowed: {name!r}")
    return ALLOWED_EXECUTABLES | names


def validate_argv(
    argv: Sequence[str],
    allowed: frozenset[str],
    *,
    local_bin_dir: str | None = None,
) -> tuple[str, ...]:
    items = _check_items(argv)
    exe = items[0]
    if "/" in exe or "\\" in exe or exe.startswith("."):
        raise CommandNotAllowedError(f"executable must be a bare name: {exe!r}")
    if exe not in allowed:
        raise CommandNotAllowedError(f"executable not allowed: {exe!r}")
    if exe == "git":
        return _check_git(items)
    if exe in _PACKAGE_MANAGER_SUBCOMMANDS:
        return _check_package_manager(exe, items)
    if exe == "npx":
        return _check_npx(items, local_bin_dir)
    if exe == "node":
        return _check_node(items)
    if exe in ("make", "just"):
        return _check_targets(items)
    return tuple(items)


def _check_items(argv: Sequence[str]) -> list[str]:
    if isinstance(argv, (str, bytes)) or not argv:
        raise CommandNotAllowedError("argv must be a non-empty list of strings")
    items = list(argv)
    if len(items) > MAX_ARGS:
        raise CommandNotAllowedError("too many arguments")
    for item in items:
        if not isinstance(item, str):
            raise CommandNotAllowedError("argv must contain only strings")
        if "\x00" in item:
            raise CommandNotAllowedError("argv contains a NUL byte")
        if len(item) > MAX_ARG_LEN:
            raise CommandNotAllowedError("argument too long")
    return items


def _check_git(items: list[str]) -> tuple[str, ...]:
    if len(items) < 2:
        raise CommandNotAllowedError("git needs a subcommand")
    sub = items[1]
    if sub in _GIT_REFUSED:
        raise CommandNotAllowedError(f"git {sub} is not available: {_GIT_REFUSED[sub]}")
    if sub not in GIT_SUBCOMMANDS:
        raise CommandNotAllowedError(f"git subcommand not allowed: {sub!r}")
    _reject_options(items[2:], _GIT_DENIED_LONG, short_letters="F")
    return tuple(items)


def _check_package_manager(exe: str, items: list[str]) -> tuple[str, ...]:
    if len(items) < 2 or items[1] not in _PACKAGE_MANAGER_SUBCOMMANDS[exe]:
        raise CommandNotAllowedError(f"{exe} subcommand not allowed")
    sub = items[1]
    rest = items[2:]
    _reject_options(rest, _PACKAGE_MANAGER_DENIED_LONG)
    if sub in ("run", "run-script") and (not rest or not _SCRIPT_NAME.match(rest[0])):
        raise CommandNotAllowedError(f"{exe} run needs a script name")
    if sub in _INSTALL_SUBCOMMANDS:
        return tuple(_with_flag(items, "--ignore-scripts"))
    return tuple(items)


def _with_flag(items: list[str], flag: str) -> list[str]:
    """Install scripts run arbitrary code, so the flag is forced before any `--`."""
    marker = items.index("--") if "--" in items else len(items)
    if flag in items[:marker]:
        return items
    return [*items[:marker], flag, *items[marker:]]


def _check_npx(items: list[str], local_bin_dir: str | None) -> tuple[str, ...]:
    args = items[1:]
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] not in _NPX_ALLOWED_FLAGS:
            raise CommandNotAllowedError(f"npx option not allowed: {args[index]!r}")
        index += 1
    if index >= len(args):
        raise CommandNotAllowedError("npx needs a local binary name")
    name = args[index]
    if not _BIN_NAME.match(name):
        raise CommandNotAllowedError(f"npx binary name not allowed: {name!r}")
    if local_bin_dir is not None and not os.path.isfile(
        os.path.join(local_bin_dir, name)
    ):
        raise CommandNotAllowedError(
            f"npx only runs installed local binaries: {name!r}"
        )
    return ("npx", "--no", name, *args[index + 1 :])


def _check_node(items: list[str]) -> tuple[str, ...]:
    if len(items) < 2:
        raise CommandNotAllowedError("node needs a script path or --version")
    first = items[1]
    if first in _NODE_VERSION_FLAGS:
        if len(items) != 2:
            raise CommandNotAllowedError("node version flag takes no arguments")
        return tuple(items)
    if first.startswith("-"):
        raise CommandNotAllowedError("node only runs a script file (no -e, -p, -r)")
    check_relpath(first, allow_git=True)
    return tuple(items)


def _check_targets(items: list[str]) -> tuple[str, ...]:
    for token in items[1:]:
        if not _TARGET.match(token):
            raise CommandNotAllowedError(
                f"{items[0]} accepts plain target names only: {token!r}"
            )
    return tuple(items)


def _reject_options(
    args: Sequence[str],
    denied_long: Sequence[str],
    *,
    short_letters: str = "",
) -> None:
    for arg in args:
        if arg == "--":
            return
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            if any(option.startswith(name) for option in denied_long):
                raise CommandNotAllowedError(f"option not allowed: {name}")
        elif arg.startswith("-") and any(letter in arg[1:] for letter in short_letters):
            raise CommandNotAllowedError(f"option not allowed: {arg}")


def check_relpath(rel: str, *, allow_git: bool) -> None:
    if not rel or "\x00" in rel or len(rel) > MAX_PATH_LEN:
        raise PathEscapeError("empty, NUL-containing or overlong path")
    if rel.startswith("/"):
        raise PathEscapeError(f"absolute path not allowed: {rel!r}")
    parts = PurePosixPath(rel).parts
    if ".." in parts:
        raise PathEscapeError(f"parent directory reference not allowed: {rel!r}")
    if not allow_git and any(part.lower() == ".git" for part in parts):
        raise PathEscapeError(f"writes into .git are not allowed: {rel!r}")


def validate_repo_url(url: str, schemes: Sequence[str]) -> str:
    if not url or len(url) > 2048 or any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise SandboxError("invalid repository URL")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in schemes:
        raise SandboxError(f"repository URL scheme not allowed: {scheme!r}")
    if "@" in parts.netloc:
        raise SandboxError("repository URL must not embed credentials")
    if scheme == "file":
        if parts.netloc or not parts.path.startswith("/"):
            raise SandboxError("file repository URLs must be absolute")
        return url
    if not parts.hostname:
        raise SandboxError("repository URL has no host")
    return url


def validate_ref(ref: str) -> str:
    if not _REF.match(ref) or _has_bad_ref_shape(ref):
        raise SandboxError(f"invalid git ref: {ref!r}")
    return ref


def validate_branch(branch: str, protected: Sequence[str]) -> str:
    validate_ref(branch)
    if branch == "HEAD":
        raise SandboxError("refusing to push HEAD as a branch name")
    lowered = branch.lower()
    if any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in protected):
        raise SandboxError(f"refusing to push to protected branch: {branch!r}")
    return branch


def _has_bad_ref_shape(ref: str) -> bool:
    return (
        ".." in ref or "//" in ref or "@{" in ref or ref.endswith(("/", ".lock", "."))
    )


def validate_patch(patch: str) -> None:
    if not patch.strip() or "\x00" in patch:
        raise SandboxError("patch is empty or contains NUL bytes")
    for line in patch.splitlines():
        _check_patch_line(line)


def _check_patch_line(line: str) -> None:
    if line.startswith(("--- ", "+++ ")):
        raw = line[4:].split("\t", 1)[0].strip()
        if raw != "/dev/null":
            _check_patch_path(raw)
    elif line.startswith("diff --git "):
        _check_diff_header(line[len("diff --git ") :])
    elif line.startswith(_PATH_KEYWORDS):
        check_relpath(line.split(" ", 2)[2], allow_git=False)
    elif line.startswith(_MODE_LINES) and "120000" in line:
        raise SandboxError("symlinks are not allowed in patches")


def _check_diff_header(rest: str) -> None:
    if not rest.startswith("a/") or " b/" not in rest:
        raise SandboxError("unsupported diff header in patch")
    old, new = rest[2:].split(" b/", 1)
    _check_patch_path(old)
    _check_patch_path(new)


def _check_patch_path(raw: str) -> None:
    path = raw[2:] if raw.startswith(("a/", "b/")) else raw
    check_relpath(path, allow_git=False)


def safe_join(root: Path, rel: str, *, allow_git: bool = False) -> Path:
    """Resolves rel under root; refuses absolute, parent-ref and symlink escapes."""
    check_relpath(rel, allow_git=allow_git)
    base = root.resolve()
    candidate = (base / rel).resolve()
    if not candidate.is_relative_to(base):
        raise PathEscapeError(f"path escapes the root: {rel!r}")
    inside = candidate.relative_to(base).parts
    if not allow_git and any(part.lower() == ".git" for part in inside):
        raise PathEscapeError(f"writes into .git are not allowed: {rel!r}")
    return candidate
