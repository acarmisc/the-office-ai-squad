from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from code_squad._common.config.commands import (
    SCHEMA_KINDS,
    expand_paths,
    schema_text,
    validate_file,
)
from code_squad._common.config.errors import ConfigError
from code_squad._common.config.explain import render
from code_squad._common.config.loader import (
    ConfigSources,
    load_org,
    load_registry,
    resolve,
)
from code_squad._common.config.scaffolds import scaffold, scaffold_kinds
from code_squad._common.contract import Mode
from code_squad._common.registry import UnknownAgentError, get_spec
from code_squad._common.runtime import run_task
from code_squad._common.validation import ValidationFailure, validate_invocation

app = typer.Typer(help="Code Squad: run an agent locally.", no_args_is_help=True)
config_app = typer.Typer(help="Configuration commands.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@app.command()
def invoke(
    agent: Annotated[str, typer.Argument(help="Agent id, for example michael or jim.")],
    prompt: Annotated[str, typer.Argument(help="Prompt text for the agent.")],
    post: Annotated[
        bool | None,
        typer.Option(
            "--post/--no-post", help="Allow external writes. Absent keeps the default."
        ),
    ] = None,
    project: Annotated[
        str | None, typer.Option(help="Project key or repository path.")
    ] = None,
    target: Annotated[
        str | None, typer.Option(help="Change request or issue reference.")
    ] = None,
    mode: Annotated[
        Mode | None, typer.Option(help="Run mode supported by the agent.")
    ] = None,
) -> None:
    _run_agent(agent, prompt, post=post, project=project, target=target, mode=mode)


@app.command()
def review(
    target: Annotated[str, typer.Argument(help="Change request number or reference.")],
    project: Annotated[
        str, typer.Option("--project", help="Project key or repository path.")
    ],
    post: Annotated[
        bool | None,
        typer.Option(
            "--post/--no-post", help="Allow external writes. Absent keeps the default."
        ),
    ] = None,
) -> None:
    """Review a change request: an alias for invoke with michael."""
    _run_agent(
        "michael",
        f"review change request {target}",
        post=post,
        project=project,
        target=target,
        mode=None,
    )


def _run_agent(
    agent: str,
    prompt: str,
    *,
    post: bool | None,
    project: str | None,
    target: str | None,
    mode: Mode | None,
) -> None:
    try:
        spec = get_spec(agent)
    except UnknownAgentError:
        typer.echo(f"unknown agent: {agent}", err=True)
        raise typer.Exit(code=2) from None
    raw: dict[str, Any] = {"prompt": prompt}
    if post is not None:
        raw["post"] = post
    if project:
        raw["project"] = project
    if target:
        raw["target"] = target
    if mode is not None:
        raw["mode"] = mode.value
    try:
        request = validate_invocation(raw, spec)
    except ValidationFailure as exc:
        typer.echo(json.dumps({"errors": exc.errors}), err=True)
        raise typer.Exit(code=2) from None
    result = run_task(spec, request)
    typer.echo(result.model_dump_json(indent=2))


@config_app.command("schema")
def config_schema(
    kind: Annotated[
        str,
        typer.Option(
            help="config (repo file), projects, baseline, invocation or finding."
        ),
    ] = "config",
) -> None:
    """Print the JSON Schema for a configuration document."""
    if kind not in SCHEMA_KINDS:
        typer.echo(
            f"unknown kind: {kind}; choose from {', '.join(SCHEMA_KINDS)}", err=True
        )
        raise typer.Exit(code=2)
    typer.echo(schema_text(kind), nl=False)


@config_app.command("validate")
def config_validate(
    paths: Annotated[
        list[Path],
        typer.Argument(exists=True, help="Files or directories to validate."),
    ],
) -> None:
    """Validate configuration files; the kind is detected from each file."""
    failures = 0
    for report in [validate_file(path) for path in expand_paths(paths)]:
        if report.ok:
            typer.echo(f"ok: {report.path} ({report.kind})")
            continue
        failures += 1
        for problem in report.problems:
            typer.echo(f"error: {report.path} ({report.kind}): {problem}", err=True)
    if failures:
        typer.echo(f"{failures} file(s) failed validation", err=True)
        raise typer.Exit(code=1)


@config_app.command("explain")
def config_explain(
    project: Annotated[str, typer.Argument(help="Project key or repository path.")],
    org: Annotated[
        Path | None,
        typer.Option(envvar="SQUAD_CONFIG_FILE", help="Org configuration file."),
    ] = None,
    projects: Annotated[
        Path | None,
        typer.Option(envvar="SQUAD_PROJECTS_DIR", help="Project registry file or dir."),
    ] = None,
    profiles: Annotated[
        Path | None,
        typer.Option(envvar="SQUAD_PROFILES_DIR", help="Extra profile directory."),
    ] = None,
    repo_config: Annotated[
        Path | None, typer.Option(help="Repository .squad/config.yml to apply.")
    ] = None,
    output_format: Annotated[
        str, typer.Option("--format", help="yaml or json.")
    ] = "yaml",
) -> None:
    """Show the effective configuration with the layer that set each key."""
    if output_format not in ("yaml", "json"):
        typer.echo("--format must be yaml or json", err=True)
        raise typer.Exit(code=2)
    fmt: Literal["yaml", "json"] = "json" if output_format == "json" else "yaml"
    sources = ConfigSources(
        org_file=org,
        env=dict(os.environ),
        projects_dir=projects,
        profiles_dir=profiles,
    )
    try:
        loaded = load_org(sources)
        registry = load_registry(sources)
        effective = resolve(
            project,
            org=loaded,
            registry=registry,
            repo_config_text=repo_config.read_text(encoding="utf-8")
            if repo_config
            else None,
            call_overrides=None,
            bootstrap_env=dict(os.environ),
        )
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(render(effective, fmt), nl=False)


@config_app.command("init")
def config_init(
    kind: Annotated[str, typer.Argument(help="react, java or generic.")],
    output: Annotated[
        Path | None, typer.Option(help="Write to this file instead of stdout.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing file.")
    ] = False,
) -> None:
    """Print a starter .squad/config.yml that starts with the schema hint."""
    if kind not in scaffold_kinds():
        typer.echo(
            f"unknown kind: {kind}; choose from {', '.join(scaffold_kinds())}", err=True
        )
        raise typer.Exit(code=2)
    text = scaffold(kind)
    if output is None:
        typer.echo(text, nl=False)
        return
    if output.exists() and not force:
        typer.echo(f"refusing to overwrite {output}; pass --force", err=True)
        raise typer.Exit(code=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {output}")


def main() -> None:
    app()
