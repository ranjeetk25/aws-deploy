import click
from ..aws import get_codepipeline_client
from ..completion import alias_complete
from ..config import load_config
from .. import config as _cfg_mod
from ..errors import ConfigError
from ..pipeline import get_pipeline_state
from .. import ui


@click.command(name="status")
@click.argument("alias", shell_complete=alias_complete)
def status(alias: str):
    """Show current pipeline state for ALIAS."""
    cfg = load_config(_cfg_mod.CONFIG_PATH)
    if alias not in cfg.pipelines:
        raise ConfigError(f"Unknown alias {alias!r}.")
    pipe = cfg.pipelines[alias]
    client = get_codepipeline_client(cfg.aws)
    with ui.spinner(f"Fetching state for {alias}…"):
        stages = get_pipeline_state(client, pipe.pipeline_name)
    ui.console.print(ui.render_stages_panel(stages, title=f"{alias} · {pipe.pipeline_name}"))
