from __future__ import annotations

import json
from typing import Annotated, Any

import typer

from code_squad._common.contract import Mode
from code_squad._common.registry import UnknownAgentError, get_spec
from code_squad._common.runtime import run_task
from code_squad._common.validation import ValidationFailure, validate_invocation

app = typer.Typer(help="Code Squad: run an agent locally.", no_args_is_help=True)
config_app = typer.Typer(
    help="Configuration commands (added in milestone M3).", no_args_is_help=True
)
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


@config_app.command("status")
def config_status() -> None:
    typer.echo("configuration commands are added in milestone M3", err=True)
    raise typer.Exit(code=1)


def main() -> None:
    app()
