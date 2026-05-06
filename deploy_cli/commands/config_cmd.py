from __future__ import annotations
import os
import re
import subprocess
import click
import questionary
from questionary import Style

from ..aws import get_codepipeline_client
from ..config import (
    Config, AWSConfig, PipelineConfig, ManualApprovalConfig,
    ensure_config_dir, load_config, save_config,
)
from .. import config as _cfg_mod
from ..errors import ConfigError
from .. import ui

_ROLE_ARN_RE = re.compile(r"^arn:aws:iam::\d{12}:role/.+$")

# High-contrast style so the autocomplete dropdown stays readable on
# dark terminals (questionary defaults render orange-on-yellow which
# is unreadable). Tuples follow prompt_toolkit Style classes.
_STYLE = Style([
    ("qmark", "fg:#5fafff bold"),
    ("question", "bold"),
    ("answer", "fg:#5fd700 bold"),
    ("pointer", "fg:#5fafff bold"),
    ("highlighted", "fg:#5fafff bold"),
    ("selected", "fg:#5fd700"),
    ("separator", "fg:#666666"),
    ("instruction", "fg:#888888"),
    ("text", ""),
    ("disabled", "fg:#858585 italic"),
    ("completion-menu", "bg:#1c1c1c fg:#dcdcdc"),
    ("completion-menu.completion", "bg:#1c1c1c fg:#dcdcdc"),
    ("completion-menu.completion.current", "bg:#5fafff fg:#1c1c1c bold"),
    ("completion-menu.meta.completion", "bg:#1c1c1c fg:#888888"),
    ("completion-menu.meta.completion.current", "bg:#5fafff fg:#1c1c1c"),
    ("scrollbar.background", "bg:#3a3a3a"),
    ("scrollbar.button", "bg:#5fafff"),
])


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
        style=_STYLE,
    ).ask()
    region = questionary.text("AWS region:", default="ap-south-1", style=_STYLE).ask()
    profile = questionary.text(
        "Base AWS profile (optional, blank = default chain):", default="", style=_STYLE,
    ).ask() or None
    cfg = Config(aws=AWSConfig(role_arn=role_arn, region=region, profile=profile), pipelines={})
    save_config(cfg, _cfg_mod.CONFIG_PATH)
    ui.console.print(f"[green]✓[/] Wrote config to {_cfg_mod.CONFIG_PATH}")
    if questionary.confirm("Add a pipeline now?", default=False, style=_STYLE).ask():
        _add_pipeline_interactive(cfg)


@config_group.command(name="show")
def show_cmd():
    """Print current config."""
    if not _cfg_mod.CONFIG_PATH.exists():
        raise ConfigError(
            f"Config file not found at {_cfg_mod.CONFIG_PATH}. Run `aws-deploy config init`."
        )
    cfg = load_config(_cfg_mod.CONFIG_PATH)
    ui.console.print_json(cfg.model_dump_json(indent=2))


@config_group.command(name="edit")
def edit_cmd():
    """Open config in $EDITOR (default vim)."""
    if not _cfg_mod.CONFIG_PATH.exists():
        raise ConfigError("Config not found. Run `aws-deploy config init`.")
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
    use_aws = questionary.confirm("Fetch pipeline list from AWS?", default=True, style=_STYLE).ask()
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
                pipeline_name = questionary.text("Pipeline name:", style=_STYLE).ask()
            else:
                # `select` shows a navigable list with high-contrast highlight,
                # avoiding the unreadable autocomplete dropdown defaults.
                pipeline_name = questionary.select(
                    "Pipeline name:", choices=sorted(names), style=_STYLE,
                    use_search_filter=True, use_jk_keys=False,
                ).ask()
        except Exception as e:  # surface but allow manual entry
            ui.console.print(ui.render_error("AWS list failed", str(e), "Falling back to manual entry."))
            pipeline_name = questionary.text("Pipeline name:", style=_STYLE).ask()
    else:
        pipeline_name = questionary.text("Pipeline name:", style=_STYLE).ask()

    alias = questionary.text(
        "Friendly alias:", default=pipeline_name.split("-")[0], style=_STYLE,
    ).ask()
    description = questionary.text("Description (optional):", default="", style=_STYLE).ask()
    has_approval = questionary.confirm(
        "Does this pipeline have a manual approval stage?", default=False, style=_STYLE,
    ).ask()
    manual_approval = None
    if has_approval:
        stage = questionary.text("Approval stage name:", style=_STYLE).ask()
        action = questionary.text("Approval action name:", style=_STYLE).ask()
        manual_approval = ManualApprovalConfig(stage=stage, action=action)
    cfg.pipelines[alias] = PipelineConfig(
        pipeline_name=pipeline_name, description=description, manual_approval=manual_approval,
    )
    save_config(cfg, _cfg_mod.CONFIG_PATH)
    ui.console.print(f"[green]✓[/] Added alias [bold]{alias}[/]")
