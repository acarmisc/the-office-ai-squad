from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Mapping
from pathlib import PurePosixPath
from typing import Any, Final

import yaml

from code_squad.dwight.deps.model import Package, ParseResult

Parser = Callable[[str, str], ParseResult]

_NPM_DEP_SECTIONS: Final = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)
_YARN_VERSION: Final = re.compile(r'^  version:?\s+"?([^"\s]+)"?\s*$')
_NS_PREFIX: Final = re.compile(r"^\{[^}]*\}")
_PROPERTY: Final = re.compile(r"\$\{([^}]+)\}")
_GRADLE_DEP: Final = re.compile(
    r"^\s*(?P<conf>implementation|api|compileOnly|runtimeOnly|testImplementation"
    r"|testCompileOnly|testRuntimeOnly|annotationProcessor|kapt|compile|runtime"
    r"|testCompile|testRuntime)\s*\(?\s*"
    r"(?:(?:platform|enforcedPlatform)\s*\(\s*)?[\"'](?P<coord>[^\"']+)[\"']"
)
_COMMENT: Final = re.compile(r"(^|\s+)#.*$")
_REQ_NAME: Final = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?P<spec>.*)$"
)
_REQ_EXACT: Final = re.compile(r"^===?\s*([A-Za-z0-9][A-Za-z0-9._+!-]*)$")
_ARG: Final = re.compile(r"^ARG\s+(?P<body>.+)$", re.IGNORECASE)
_FROM: Final = re.compile(r"^FROM\s+(?P<rest>.+)$", re.IGNORECASE)
_DOCKER_VAR: Final = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)"
)
_REQUIREMENTS_FILE: Final = re.compile(r"^requirements.*\.txt$")
_DOCKERFILE: Final = re.compile(r"^(?:Dockerfile(?:\.[\w-]+)?|[\w.-]+\.Dockerfile)$")


def is_manifest(path: str) -> bool:
    return _parser_for(path) is not None


def parse_file(path: str, text: str) -> ParseResult:
    parser = _parser_for(path)
    if parser is None:
        return _failure(path, "not a supported dependency manifest")
    return parser(path, text)


def _parser_for(path: str) -> Parser | None:
    name = PurePosixPath(path).name
    exact = _EXACT_PARSERS.get(name)
    if exact is not None:
        return exact
    if _REQUIREMENTS_FILE.match(name):
        return parse_requirements
    if _DOCKERFILE.match(name):
        return parse_dockerfile
    return None


def _failure(path: str, reason: str) -> ParseResult:
    return ParseResult((), (f"{path}: {reason}",))


def _unpinned_warning(path: str, name: str, reason: str) -> str:
    return f"{path}: {name} is not pinned ({reason})"


# npm ----------------------------------------------------------------------


def parse_package_lock(path: str, text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return _failure(path, f"invalid JSON ({exc.msg})")
    if not isinstance(data, dict):
        return _failure(path, "unexpected JSON structure")
    packages: list[Package] = []
    warnings: list[str] = []
    entries = data.get("packages")
    if isinstance(entries, dict):
        _npm_v2_entries(path, entries, packages, warnings)
    elif isinstance(data.get("dependencies"), dict):
        _npm_v1_tree(path, data["dependencies"], packages, warnings)
    else:
        return _failure(path, "no packages or dependencies section")
    return ParseResult(tuple(packages), tuple(warnings))


def _npm_v2_entries(
    path: str,
    entries: Mapping[str, Any],
    packages: list[Package],
    warnings: list[str],
) -> None:
    direct_names = _npm_root_names(entries.get(""))
    for key, meta in entries.items():
        if "node_modules/" not in key or not isinstance(meta, dict):
            continue
        if meta.get("link") is True:
            continue
        name = key.rsplit("node_modules/", 1)[1]
        is_direct = (
            None
            if direct_names is None
            else (key == f"node_modules/{name}" and name in direct_names)
        )
        version = meta.get("version")
        if isinstance(version, str) and version:
            packages.append(Package("npm", name, version, True, path, None, is_direct))
        else:
            packages.append(Package("npm", name, None, False, path, None, is_direct))
            warnings.append(_unpinned_warning(path, name, "no version in lockfile"))


def _npm_root_names(root: object) -> set[str] | None:
    if not isinstance(root, dict):
        return None
    names: set[str] = set()
    for section in _NPM_DEP_SECTIONS:
        values = root.get(section)
        if isinstance(values, dict):
            names.update(str(key) for key in values)
    return names


def _npm_v1_tree(
    path: str,
    tree: Mapping[str, Any],
    packages: list[Package],
    warnings: list[str],
) -> None:
    for name, meta in tree.items():
        if not isinstance(meta, dict):
            continue
        version = meta.get("version")
        if isinstance(version, str) and version:
            packages.append(Package("npm", name, version, True, path, None, None))
        else:
            packages.append(Package("npm", name, None, False, path, None, None))
            warnings.append(_unpinned_warning(path, name, "no version in lockfile"))
        nested = meta.get("dependencies")
        if isinstance(nested, dict):
            _npm_v1_tree(path, nested, packages, warnings)


def _split_npm_spec(spec: str) -> tuple[str, str] | None:
    index = spec.find("@", 1)
    if index <= 0:
        return None
    name, version = spec[:index], spec[index + 1 :]
    return (name, version) if name and version else None


def parse_yarn_lock(path: str, text: str) -> ParseResult:
    headers: list[tuple[int, str, str | None]] = []
    header_line = 0
    header: str | None = None
    version: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            if header is not None:
                headers.append((header_line, header, version))
            header_line, header, version = number, raw.rstrip().rstrip(":"), None
            continue
        match = _YARN_VERSION.match(raw)
        if match is not None and header is not None:
            version = match.group(1)
    if header is not None:
        headers.append((header_line, header, version))

    packages: list[Package] = []
    warnings: list[str] = []
    for line, key, found in headers:
        first_spec = key.split(",")[0].strip().strip('"')
        if first_spec.startswith("__metadata") or "@workspace:" in first_spec:
            continue
        parsed = _split_npm_spec(first_spec)
        if parsed is None:
            warnings.append(f"{path}:{line}: unrecognised yarn entry")
            continue
        name = parsed[0]
        if found:
            packages.append(Package("npm", name, found, True, path, line, None))
        else:
            packages.append(Package("npm", name, None, False, path, line, None))
            warnings.append(_unpinned_warning(path, name, "no version in lockfile"))
    return ParseResult(tuple(packages), tuple(warnings))


def parse_pnpm_lock(path: str, text: str) -> ParseResult:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return _failure(path, "invalid YAML")
    if not isinstance(data, dict):
        return _failure(path, "unexpected YAML structure")
    entries = data.get("packages")
    if not isinstance(entries, dict):
        return _failure(path, "no packages section")
    direct = _pnpm_direct_names(data)
    packages: list[Package] = []
    warnings: list[str] = []
    for key in entries:
        parsed = _pnpm_key(str(key))
        if parsed is None:
            warnings.append(f"{path}: unrecognised package key {key}")
            continue
        name, version = parsed
        is_direct = None if direct is None else name in direct
        packages.append(Package("npm", name, version, True, path, None, is_direct))
    return ParseResult(tuple(packages), tuple(warnings))


def _pnpm_key(key: str) -> tuple[str, str] | None:
    spec = key.strip().lstrip("/").split("(", 1)[0]
    parsed = _split_npm_spec(spec)
    if parsed is None:
        return None
    name, version = parsed
    return name, version.split("_", 1)[0]


def _pnpm_direct_names(data: Mapping[str, Any]) -> set[str] | None:
    importers = data.get("importers")
    section: object = data
    if isinstance(importers, dict) and isinstance(importers.get("."), dict):
        section = importers["."]
    if not isinstance(section, dict):
        return None
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        values = section.get(key)
        if isinstance(values, dict):
            names.update(str(name) for name in values)
    return names or None


# Maven and Gradle ------------------------------------------------------------


def parse_pom(path: str, text: str) -> ParseResult:
    if "<!DOCTYPE" in text.upper():
        return _failure(path, "DOCTYPE declarations are not supported")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return _failure(path, f"invalid XML ({exc.msg})")
    props = _pom_properties(root)
    managed = _pom_managed(root, props)
    packages: list[Package] = []
    warnings: list[str] = []
    for dep in _children(_child(root, "dependencies"), "dependency"):
        group = _resolve(_text(dep, "groupId"), props)
        artifact = _resolve(_text(dep, "artifactId"), props)
        if not group or not artifact:
            warnings.append(f"{path}: dependency with unresolved coordinates skipped")
            continue
        name = f"{group}:{artifact}"
        raw = _text(dep, "version")
        if raw is None:
            resolved = managed.get((group, artifact))
        else:
            resolved = _resolve(raw, props)
        version, reason = _maven_version(resolved, raw is None, name)
        if version is None:
            warnings.append(_unpinned_warning(path, name, reason))
        packages.append(
            Package("Maven", name, version, version is not None, path, None, True)
        )
    return ParseResult(tuple(packages), tuple(warnings))


def _local(tag: str) -> str:
    return _NS_PREFIX.sub("", tag)


def _child(parent: ET.Element | None, name: str) -> ET.Element | None:
    if parent is None:
        return None
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _children(parent: ET.Element | None, name: str) -> list[ET.Element]:
    if parent is None:
        return []
    return [child for child in parent if _local(child.tag) == name]


def _text(parent: ET.Element | None, name: str) -> str | None:
    child = _child(parent, name)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _pom_properties(root: ET.Element) -> dict[str, str]:
    props: dict[str, str] = {}
    properties = _child(root, "properties")
    if properties is not None:
        for prop in properties:
            if prop.text and prop.text.strip():
                props[_local(prop.tag)] = prop.text.strip()
    parent = _child(root, "parent")
    version = _text(root, "version") or _text(parent, "version")
    group = _text(root, "groupId") or _text(parent, "groupId")
    if version:
        props["project.version"] = version
    if group:
        props["project.groupId"] = group
    return props


def _pom_managed(
    root: ET.Element, props: Mapping[str, str]
) -> dict[tuple[str, str], str | None]:
    managed: dict[tuple[str, str], str | None] = {}
    management = _child(root, "dependencyManagement")
    for dep in _children(_child(management, "dependencies"), "dependency"):
        group = _resolve(_text(dep, "groupId"), props)
        artifact = _resolve(_text(dep, "artifactId"), props)
        if group and artifact:
            managed[(group, artifact)] = _resolve(_text(dep, "version"), props)
    return managed


def _resolve(value: str | None, props: Mapping[str, str]) -> str | None:
    if value is None:
        return None
    current = value
    for _ in range(5):
        if "${" not in current:
            return current
        current = _PROPERTY.sub(lambda m: props.get(m.group(1), m.group(0)), current)
    return None if "${" in current else current


def _maven_version(
    resolved: str | None, declared_without_version: bool, name: str
) -> tuple[str | None, str]:
    if resolved is None:
        reason = (
            f"no version for {name}; managed version not found"
            if declared_without_version
            else "version property is unresolved"
        )
        return None, reason
    if resolved.upper() in {"LATEST", "RELEASE"}:
        return None, "dynamic version"
    if resolved.startswith(("[", "(")) or "," in resolved:
        if resolved.startswith("[") and resolved.endswith("]") and "," not in resolved:
            return resolved[1:-1].strip(), ""
        return None, "version range"
    return resolved, ""


def parse_gradle_lockfile(path: str, text: str) -> ParseResult:
    packages: list[Package] = []
    warnings: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "empty=")):
            continue
        parts = line.split("=", 1)[0].split(":")
        if len(parts) < 3:
            warnings.append(f"{path}:{number}: unrecognised lock entry")
            continue
        name = f"{parts[0]}:{parts[1]}"
        packages.append(Package("Maven", name, parts[2], True, path, number, None))
    return ParseResult(tuple(packages), tuple(warnings))


def parse_gradle_build(path: str, text: str) -> ParseResult:
    packages: list[Package] = []
    warnings: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        match = _GRADLE_DEP.match(raw)
        if match is None:
            continue
        parts = match.group("coord").split(":")
        if len(parts) < 2:
            warnings.append(f"{path}:{number}: unrecognised dependency notation")
            continue
        name = f"{parts[0]}:{parts[1]}"
        version, reason = _gradle_version(parts[2] if len(parts) > 2 else None)
        if version is None:
            warnings.append(_unpinned_warning(path, name, reason))
        packages.append(
            Package("Maven", name, version, version is not None, path, number, True)
        )
    return ParseResult(tuple(packages), tuple(warnings))


def _gradle_version(raw: str | None) -> tuple[str | None, str]:
    if not raw:
        return None, "no version; managed by a platform or BOM"
    if "$" in raw:
        return None, "version is a property reference"
    if "+" in raw or raw.startswith("latest.") or any(c in raw for c in "[](),"):
        return None, "dynamic or range version"
    return raw, ""


# Python ----------------------------------------------------------------------


def _normalise_pypi(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _logical_lines(text: str) -> Iterator[tuple[int, str]]:
    buffer = ""
    start = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        if not buffer:
            start = number
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        buffer += raw
        yield start, buffer.strip()
        buffer = ""
    if buffer.strip():
        yield start, buffer.strip()


def _strip_requirement(line: str) -> str:
    line = _COMMENT.sub("", line)
    line = line.split(" --hash", 1)[0]
    line = line.split(";", 1)[0]
    return line.strip()


def parse_requirements(path: str, text: str) -> ParseResult:
    packages: list[Package] = []
    warnings: list[str] = []
    for number, logical in _logical_lines(text):
        req = _strip_requirement(logical)
        if not req:
            continue
        if req.startswith("-"):
            warnings.append(f"{path}:{number}: option '{req.split()[0]}' not analysed")
            continue
        match = _REQ_NAME.match(req)
        if match is None or match.group("spec").startswith("@"):
            warnings.append(f"{path}:{number}: requirement not analysed")
            continue
        name = _normalise_pypi(match.group("name"))
        spec = match.group("spec").strip()
        exact = _REQ_EXACT.match(spec)
        if exact is not None and "*" not in spec:
            packages.append(
                Package("PyPI", name, exact.group(1), True, path, number, True)
            )
            continue
        reason = "no exact pin" if not spec else "version range"
        packages.append(Package("PyPI", name, None, False, path, number, True))
        warnings.append(_unpinned_warning(path, name, reason))
    return ParseResult(tuple(packages), tuple(warnings))


def parse_uv_lock(path: str, text: str) -> ParseResult:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return _failure(path, "invalid TOML")
    entries = data.get("package")
    if not isinstance(entries, list):
        return _failure(path, "no package entries")
    root = next((e for e in entries if isinstance(e, dict) and _uv_is_project(e)), None)
    direct = _uv_direct_names(root)
    packages: list[Package] = []
    warnings: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or _uv_is_project(entry):
            continue
        raw_name = entry.get("name")
        if not isinstance(raw_name, str):
            continue
        name = _normalise_pypi(raw_name)
        version = entry.get("version")
        is_direct = None if direct is None else name in direct
        if isinstance(version, str) and version:
            packages.append(Package("PyPI", name, version, True, path, None, is_direct))
        else:
            packages.append(Package("PyPI", name, None, False, path, None, is_direct))
            warnings.append(_unpinned_warning(path, name, "no version in lockfile"))
    return ParseResult(tuple(packages), tuple(warnings))


def _uv_is_project(entry: Mapping[str, Any]) -> bool:
    source = entry.get("source")
    return isinstance(source, dict) and ("editable" in source or "virtual" in source)


def _uv_direct_names(root: Mapping[str, Any] | None) -> set[str] | None:
    if root is None:
        return None
    names: set[str] = set()
    for dep in root.get("dependencies", []):
        if isinstance(dep, dict) and isinstance(dep.get("name"), str):
            names.add(_normalise_pypi(dep["name"]))
    dev = root.get("dev-dependencies", {})
    if isinstance(dev, dict):
        for group in dev.values():
            for dep in group if isinstance(group, list) else []:
                if isinstance(dep, dict) and isinstance(dep.get("name"), str):
                    names.add(_normalise_pypi(dep["name"]))
    return names


# Containers ------------------------------------------------------------------


def parse_dockerfile(path: str, text: str) -> ParseResult:
    global_args: dict[str, str] = {}
    stages: set[str] = set()
    seen_from = False
    packages: list[Package] = []
    warnings: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        arg = _ARG.match(line)
        if arg is not None and not seen_from:
            _collect_global_args(arg.group("body"), global_args)
            continue
        frm = _FROM.match(line)
        if frm is None:
            continue
        seen_from = True
        tokens = [t for t in frm.group("rest").split() if not t.startswith("--")]
        if not tokens:
            warnings.append(f"{path}:{number}: FROM without image")
            continue
        image_ref = tokens[0]
        if image_ref.lower() in stages:
            alias = (
                tokens[2] if len(tokens) >= 3 and tokens[1].lower() == "as" else None
            )
            if alias:
                stages.add(alias.lower())
            continue
        alias = tokens[2] if len(tokens) >= 3 and tokens[1].lower() == "as" else None
        if alias:
            stages.add(alias.lower())
        image = _substitute(image_ref, global_args)
        if image is None:
            warnings.append(f"{path}:{number}: image '{image_ref}' has unresolved ARG")
            packages.append(
                Package("Docker", image_ref, None, False, path, number, True)
            )
            continue
        if image == "scratch":
            continue
        repo, tag, digest = _split_image(image)
        if digest:
            packages.append(Package("Docker", repo, digest, True, path, number, True))
        elif tag and tag != "latest":
            packages.append(Package("Docker", repo, tag, True, path, number, True))
        else:
            packages.append(Package("Docker", repo, None, False, path, number, True))
            warnings.append(_unpinned_warning(path, repo, "no digest or specific tag"))
    return ParseResult(tuple(packages), tuple(warnings))


def _collect_global_args(body: str, args: dict[str, str]) -> None:
    for token in body.split():
        key, sep, value = token.partition("=")
        if sep and key:
            args[key] = value


def _substitute(image: str, args: Mapping[str, str]) -> str | None:
    names = [m.group(1) or m.group(2) for m in _DOCKER_VAR.finditer(image)]
    if any(name not in args for name in names):
        return None
    return _DOCKER_VAR.sub(lambda m: args[m.group(1) or m.group(2)], image)


def _split_image(image: str) -> tuple[str, str | None, str | None]:
    digest: str | None = None
    if "@" in image:
        image, digest = image.split("@", 1)
    tag: str | None = None
    if ":" in image.rsplit("/", 1)[-1]:
        image, tag = image.rsplit(":", 1)
    return image, tag, digest


_EXACT_PARSERS: Final[dict[str, Parser]] = {
    "package-lock.json": parse_package_lock,
    "yarn.lock": parse_yarn_lock,
    "pnpm-lock.yaml": parse_pnpm_lock,
    "pom.xml": parse_pom,
    "gradle.lockfile": parse_gradle_lockfile,
    "build.gradle": parse_gradle_build,
    "build.gradle.kts": parse_gradle_build,
    "uv.lock": parse_uv_lock,
}
