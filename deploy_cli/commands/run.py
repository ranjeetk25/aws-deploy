from __future__ import annotations
import sys
from datetime import datetime, timezone
from typing import Optional

import click
import questionary
from rich.panel import Panel
from rich.text import Text

from ..aws import get_codepipeline_client
from ..completion import alias_complete
from .. import config as cfg_mod
from ..config import load_config
from ..errors import UnknownAliasError, ExecutionFailedError
from ..pipeline import (
    InflightApproval, start_execution, watch_execution,
    find_pending_approval_token, find_inflight_approval,
    approve, poll_for_approval,
)
from .. import ui


def _is_interactive() -> bool:
    """True when stdin is a TTY. Wrapped for monkeypatching in tests."""
    return sys.stdin.isatty()


def _format_wait(t: Optional[datetime]) -> str:
    if t is None:
        return "unknown"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - t
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hrs, rem_mins = divmod(mins, 60)
    if hrs < 24:
        return f"{hrs}h {rem_mins}m"
    days, rem_hrs = divmod(hrs, 24)
    return f"{days}d {rem_hrs}h"


def _render_inflight_panel(inflight: InflightApproval) -> Panel:
    body = Text()
    body.append("Pipeline already has an execution awaiting approval.\n\n", style="white")
    body.append("Execution: ", style="dim")
    body.append(f"{inflight.pipeline_execution_id}\n", style="bold cyan")
    body.append("Stage:     ", style="dim")
    body.append(f"{inflight.stage} / {inflight.action}\n", style="bold")
    body.append("Waiting:   ", style="dim")
    body.append(f"{_format_wait(inflight.last_status_change)}\n", style="bold yellow")
    return Panel(body, title="[bold cyan]Pending approval[/]", border_style="cyan")


def _prompt_inflight_choice(inflight: InflightApproval) -> str:
    """Returns 'approve' | 'new' | 'cancel'."""
    ui.console.print(_render_inflight_panel(inflight))
    answer = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("Approve the existing execution", value="approve"),
            questionary.Choice("Trigger a new execution (existing one stays pending)", value="new"),
            questionary.Choice("Cancel", value="cancel"),
        ],
        style=ui.prompt_style,
    ).ask()
    return answer or "cancel"


@click.command(name="run")
@click.argument("alias", shell_complete=alias_complete)
@click.option("--approve", "-a", "do_approve", is_flag=True, help="Auto-approve manual approval stage on the new execution.")
@click.option("--watch", "-w", "do_watch", is_flag=True, help="Tail pipeline progress live.")
@click.option("--new", "force_new", is_flag=True, help="Skip the inflight-approval check and always trigger a new execution.")
def run(alias: str, do_approve: bool, do_watch: bool, force_new: bool):
    """Trigger pipeline execution for ALIAS.

    If the pipeline already has an execution sitting at the configured manual
    approval stage (e.g. one auto-triggered by a main-branch merge), you'll be
    asked whether to approve the existing one or trigger a new execution.
    Pass --new to skip this check unconditionally.
    """
    cfg = load_config(cfg_mod.CONFIG_PATH)
    if alias not in cfg.pipelines:
        raise UnknownAliasError(
            f"Unknown alias {alias!r}. Run `aws-deploy list` to see configured aliases."
        )
    pipe = cfg.pipelines[alias]
    client = get_codepipeline_client(cfg.aws)

    # Inflight check: only meaningful if pipeline has manual_approval configured.
    # Skip in non-TTY contexts (CI/scripts) unless user is in a TTY — there we
    # default to triggering new, matching prior behaviour.
    if pipe.manual_approval and not force_new and _is_interactive():
        inflight = find_inflight_approval(
            client, pipe.pipeline_name, pipe.manual_approval.stage, pipe.manual_approval.action,
        )
        if inflight is not None:
            choice = _prompt_inflight_choice(inflight)
            if choice == "cancel":
                ui.console.print("[yellow]Cancelled.[/]")
                return
            if choice == "approve":
                with ui.spinner("Approving existing execution…"):
                    approve(client, pipe.pipeline_name, inflight.stage, inflight.action, inflight.token)
                ui.console.print(
                    f"[green]✓[/] Approved {inflight.stage}/{inflight.action} on execution "
                    f"[bold]{inflight.pipeline_execution_id}[/]"
                )
                if do_watch:
                    final = watch_execution(client, pipe.pipeline_name, inflight.pipeline_execution_id)
                    if final == "Succeeded":
                        ui.console.print("[green]✓ Pipeline succeeded[/]")
                        return
                    raise ExecutionFailedError(f"Pipeline ended with status {final}")
                return
            # choice == "new": fall through to trigger

    # Standard path: trigger a new execution.
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
