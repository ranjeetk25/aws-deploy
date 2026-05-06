from __future__ import annotations
import sys
import click

from . import __version__
from . import ui
from .completion import install_completion
from .errors import DeployError
from .commands.run import run
from .commands.list_cmd import list_pipelines
from .commands.status import status
from .commands.logs import logs
from .commands.config_cmd import config_group


_ERROR_HINTS = {
    "ConfigError": ("Config error", "Run `deploy config init` or `deploy config edit`."),
    "UnknownAliasError": ("Unknown alias", "Run `deploy list` to see configured aliases."),
    "AWSAuthError": ("AWS authentication failed", "Verify role_arn, region, and base profile credentials."),
    "PipelineNotFoundError": ("Pipeline not found", "Check `deploy config show`. Alias points to a pipeline AWS doesn't see."),
    "ApprovalTimeoutError": ("Approval stage never reached", "Pipeline did not enter pending-approval within 30 minutes."),
    "ExecutionFailedError": ("Pipeline execution failed", "Inspect `deploy logs <alias>` for the failing action."),
    "ConcurrencyError": ("Pipeline already executing", "V1 pipelines do not queue. Wait for the current execution to finish."),
}


class DeployGroup(click.Group):
    """Click group that renders DeployError subclasses as styled panels.

    With --debug on the root, re-raises so the traceback prints. Otherwise renders
    a red panel via ui.render_error and marks the exception so main()'s outer
    handler does not re-render it.
    """

    def get_help(self, ctx: click.Context) -> str:
        from rich.console import Console
        banner_console = Console(record=True, width=ctx.max_content_width or 80, no_color=False)
        banner_console.print(ui.render_banner())
        return banner_console.export_text() + "\n" + super().get_help(ctx)

    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except DeployError as e:
            if ctx.params.get("debug"):
                raise
            title, suggestion = _ERROR_HINTS.get(type(e).__name__, ("Error", ""))
            ui.console.print(ui.render_error(title, str(e), suggestion))
            e._rendered = True
            raise


def _install_and_exit(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    install_completion()
    ctx.exit(0)


def _version_and_exit(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo(__version__)
    ctx.exit(0)


@click.group(cls=DeployGroup, invoke_without_command=True)
@click.option("--debug", is_flag=True, help="Show raw tracebacks on errors instead of styled panels.")
@click.option("--version", is_flag=True, callback=_version_and_exit, expose_value=False, is_eager=True)
@click.option(
    "--install-completion", is_flag=True,
    callback=_install_and_exit, expose_value=False, is_eager=True,
    help="Write shell completion script and print sourcing instructions.",
)
@click.pass_context
def cli(ctx: click.Context, debug: bool):
    """deploy — AWS CodePipeline launcher."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


cli.add_command(run)
cli.add_command(list_pipelines)
cli.add_command(status)
cli.add_command(logs)
cli.add_command(config_group)


def main():
    debug = "--debug" in sys.argv
    try:
        cli(standalone_mode=False)
    except DeployError as e:
        if debug:
            raise
        if not getattr(e, "_rendered", False):
            title, suggestion = _ERROR_HINTS.get(type(e).__name__, ("Error", ""))
            ui.console.print(ui.render_error(title, str(e), suggestion))
        sys.exit(1)
    except click.exceptions.UsageError as e:
        e.show()
        sys.exit(e.exit_code)
    except click.exceptions.Exit as e:
        sys.exit(e.exit_code)
    except click.exceptions.ClickException as e:
        e.show()
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        ui.console.print("\n[yellow]Interrupted[/]")
        sys.exit(130)
    except Exception as e:
        if debug:
            raise
        ui.console.print(ui.render_error("Unexpected error", str(e), "Re-run with --debug for full traceback."))
        sys.exit(1)


if __name__ == "__main__":
    main()
