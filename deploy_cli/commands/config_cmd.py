from __future__ import annotations
import os
import re
import subprocess
import click
import questionary

from ..aws import get_codepipeline_client
from ..config import (
    Config, AWSConfig, PipelineConfig, ManualApprovalConfig,
    ensure_config_dir, load_config, save_config,
)
from .. import config as _cfg_mod
from ..errors import ConfigError
from .. import ui

_ROLE_ARN_RE = re.compile(r"^arn:aws:iam::\d{12}:role/.+$")


def _validate_role_arn(v: str):
    return bool(_ROLE_ARN_RE.match(v)) or "Must match arn:aws:iam::ACCOUNT:role/NAME"


@click.group(name="config")
def config_group():
    """Manage deploy CLI config."""


@config_group.command(name="init")
def init_cmd():
    """Interactive config bootstrap."""
    ensure_config_dir()
    role_arn = questionary.text(
        "AWS role ARN to assume:",
        validate=_validate_role_arn,
    ).ask()
    region = questionary.text("AWS region:", default="ap-south-1").ask()
    profile = questionary.text("Base AWS profile (optional, blank = default chain):", default="").ask() or None
    cfg = Config(aws=AWSConfig(role_arn=role_arn, region=region, profile=profile), pipelines={})
    save_config(cfg, _cfg_mod.CONFIG_PATH)
    ui.console.print(f"[green]✓[/] Wrote config to {_cfg_mod.CONFIG_PATH}")
    if questionary.confirm("Add a pipeline now?", default=False).ask():
        _add_pipeline_interactive(cfg)


@config_group.command(name="show")
def show_cmd():
    """Print current config."""
    if not _cfg_mod.CONFIG_PATH.exists():
        raise ConfigError(
            f"Config file not found at {_cfg_mod.CONFIG_PATH}. Run `deploy config init`."
        )
    cfg = load_config(_cfg_mod.CONFIG_PATH)
    ui.console.print_json(cfg.model_dump_json(indent=2))


@config_group.command(name="edit")
def edit_cmd():
    """Open config in $EDITOR (default vim)."""
    if not _cfg_mod.CONFIG_PATH.exists():
        raise ConfigError("Config not found. Run `deploy config init`.")
    editor = os.environ.get("EDITOR", "vim")
    subprocess.call([editor, str(_cfg_mod.CONFIG_PATH)])
    load_config(_cfg_mod.CONFIG_PATH)  # validate after edit
    ui.console.print("[green]✓[/] Config valid")


@config_group.command(name="add")
def add_cmd():
    """Interactive: append a new pipeline alias."""
    cfg = load_config(_cfg_mod.CONFIG_PATH)
    _add_pipeline_interactive(cfg)


@config_group.command(name="remove")
@click.argument("alias")
def remove_cmd(alias: str):
    """Remove ALIAS from config."""
    cfg = load_config(_cfg_mod.CONFIG_PATH)
    if alias not in cfg.pipelines:
        raise ConfigError(f"Alias {alias!r} not in config.")
    del cfg.pipelines[alias]
    save_config(cfg, _cfg_mod.CONFIG_PATH)
    ui.console.print(f"[green]✓[/] Removed {alias}")


def _add_pipeline_interactive(cfg: Config) -> None:
    use_aws = questionary.confirm("Fetch pipeline list from AWS?", default=True).ask()
    pipeline_name: str
    if use_aws:
        try:
            client = get_codepipeline_client(cfg.aws)
            with ui.spinner("Listing pipelines…"):
                names = []
                for page in client.get_paginator("list_pipelines").paginate():
                    names.extend(p["name"] for p in page.get("pipelines", []))
            if not names:
                ui.console.print("[yellow]No pipelines found in this account/region.[/]")
                pipeline_name = questionary.text("Pipeline name:").ask()
            else:
                pipeline_name = questionary.autocomplete(
                    "Pipeline name (type to fuzzy filter):", choices=sorted(names),
                ).ask()
        except Exception as e:  # surface but allow manual entry
            ui.console.print(ui.render_error("AWS list failed", str(e), "Falling back to manual entry."))
            pipeline_name = questionary.text("Pipeline name:").ask()
    else:
        pipeline_name = questionary.text("Pipeline name:").ask()

    alias = questionary.text("Friendly alias:", default=pipeline_name.split("-")[0]).ask()
    description = questionary.text("Description (optional):", default="").ask()
    has_approval = questionary.confirm("Does this pipeline have a manual approval stage?", default=False).ask()
    manual_approval = None
    if has_approval:
        stage = questionary.text("Approval stage name:").ask()
        action = questionary.text("Approval action name:").ask()
        manual_approval = ManualApprovalConfig(stage=stage, action=action)
    cfg.pipelines[alias] = PipelineConfig(
        pipeline_name=pipeline_name, description=description, manual_approval=manual_approval,
    )
    save_config(cfg, _cfg_mod.CONFIG_PATH)
    ui.console.print(f"[green]✓[/] Added alias [bold]{alias}[/]")
