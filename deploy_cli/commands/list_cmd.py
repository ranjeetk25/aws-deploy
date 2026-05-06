import click
from ..config import load_config
from .. import config as _cfg_mod
from .. import ui


@click.command(name="list")
def list_pipelines():
    """Show configured pipelines."""
    cfg = load_config(_cfg_mod.CONFIG_PATH)
    ui.console.print(ui.render_pipeline_table(cfg.pipelines))
