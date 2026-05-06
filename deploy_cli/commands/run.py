from __future__ import annotations
import click

from ..aws import get_codepipeline_client
from ..completion import alias_complete
from .. import config as cfg_mod
from ..config import load_config
from ..errors import UnknownAliasError, ExecutionFailedError
from ..pipeline import (
    start_execution, watch_execution, find_pending_approval_token,
    approve, poll_for_approval,
)
from .. import ui


@click.command(name="run")
@click.argument("alias", shell_complete=alias_complete)
@click.option("--approve", "-a", "do_approve", is_flag=True, help="Auto-approve manual approval stage.")
@click.option("--watch", "-w", "do_watch", is_flag=True, help="Tail pipeline progress live.")
def run(alias: str, do_approve: bool, do_watch: bool):
    """Trigger pipeline execution for ALIAS."""
    cfg = load_config(cfg_mod.CONFIG_PATH)
    if alias not in cfg.pipelines:
        raise UnknownAliasError(
            f"Unknown alias {alias!r}. Run `aws-deploy list` to see configured aliases."
        )
    pipe = cfg.pipelines[alias]
    client = get_codepipeline_client(cfg.aws)

    with ui.spinner(f"Starting execution for {alias}…"):
        execution_id = start_execution(client, pipe.pipeline_name)
    ui.console.print(f"[green]✓[/] Started execution [bold]{execution_id}[/] for [cyan]{alias}[/]")

    if do_approve and not pipe.manual_approval:
        ui.console.print(ui.render_error(
            "Auto-approve skipped",
            f"Alias {alias!r} has no manual_approval configured; --approve ignored.",
        ))
        do_approve = False

    if do_watch:
        approved = {"done": False}

        def on_tick(state):
            if not do_approve or approved["done"]:
                return
            ma = pipe.manual_approval
            tok = find_pending_approval_token(client, pipe.pipeline_name, ma.stage, ma.action)
            if tok:
                approve(client, pipe.pipeline_name, ma.stage, ma.action, tok)
                approved["done"] = True
                ui.console.print(f"[green]✓[/] Approved {ma.stage}/{ma.action}")

        final = watch_execution(client, pipe.pipeline_name, execution_id, on_tick=on_tick)
        if final == "Succeeded":
            ui.console.print("[green]✓ Pipeline succeeded[/]")
            return
        raise ExecutionFailedError(f"Pipeline ended with status {final}")

    if do_approve:
        ma = pipe.manual_approval
        with ui.spinner(f"Waiting for {ma.stage}/{ma.action} to be pending…"):
            tok = poll_for_approval(client, pipe.pipeline_name, ma.stage, ma.action)
        approve(client, pipe.pipeline_name, ma.stage, ma.action, tok)
        ui.console.print(f"[green]✓[/] Approved {ma.stage}/{ma.action}")
