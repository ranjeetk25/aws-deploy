import click
from ..aws import get_codepipeline_client
from ..completion import alias_complete
from ..config import load_config
from .. import config as _cfg_mod
from ..errors import ConfigError
from ..pipeline import list_action_events
from .. import ui


@click.command(name="logs")
@click.argument("alias", shell_complete=alias_complete)
def logs(alias: str):
    """Show latest execution event log for ALIAS."""
    cfg = load_config(_cfg_mod.CONFIG_PATH)
    if alias not in cfg.pipelines:
        raise ConfigError(f"Unknown alias {alias!r}.")
    pipe = cfg.pipelines[alias]
    client = get_codepipeline_client(cfg.aws)
    with ui.spinner(f"Fetching latest execution for {alias}…"):
        resp = client.list_pipeline_executions(pipelineName=pipe.pipeline_name, maxResults=1)
    summaries = resp.get("pipelineExecutionSummaries", [])
    if not summaries:
        ui.console.print(ui.render_error("No executions", f"No executions found for {alias}."))
        return
    exec_id = summaries[0]["pipelineExecutionId"]
    events = list_action_events(client, pipe.pipeline_name, exec_id)
    ui.console.print(ui.render_event_log(events))
