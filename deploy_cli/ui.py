from __future__ import annotations
from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import pyfiglet

if TYPE_CHECKING:
    from .config import PipelineConfig
    from .pipeline import StageStatus

console = Console()

_ICONS = {
    "Succeeded": "[bold green]✓[/]",
    "InProgress": "[bold cyan]⏳[/]",
    "Failed": "[bold red]✗[/]",
    "Stopped": "[bold yellow]⊘[/]",
    "Stopping": "[bold yellow]⊘[/]",
    "Cancelled": "[bold yellow]⊘[/]",
    "Superseded": "[dim]⊘[/]",
    "Skipped": "[dim]⊘[/]",
    "Pending": "[bold yellow]…[/]",
    "Queued": "[bold yellow]…[/]",
    "": "[dim]·[/]",
}

_COLORS = {
    "Succeeded": "green",
    "InProgress": "cyan",
    "Failed": "red",
    "Stopped": "yellow",
    "Stopping": "yellow",
    "Cancelled": "yellow",
    "Superseded": "dim",
    "Skipped": "dim",
    "Pending": "yellow",
    "Queued": "yellow",
}


def status_icon(status: str) -> str:
    return _ICONS.get(status, _ICONS[""])


def status_color(status: str) -> str:
    return _COLORS.get(status, "white")


def render_banner() -> Panel:
    art = pyfiglet.figlet_format("deploy", font="small")
    body = Text(art, style="bold cyan")
    body.append("\ndeploy — AWS CodePipeline launcher", style="dim")
    return Panel(body, border_style="cyan", padding=(0, 2))


def render_pipeline_table(pipelines: "dict[str, PipelineConfig]") -> Table:
    t = Table(title="Configured pipelines", show_lines=False, header_style="bold cyan")
    t.add_column("Alias", style="bold")
    t.add_column("Pipeline name")
    t.add_column("Manual approval")
    t.add_column("Description")
    for alias, p in pipelines.items():
        ma = "yes" if p.manual_approval else "no"
        t.add_row(alias, p.pipeline_name, ma, p.description or "")
    return t


def render_stages_panel(stages: "list[StageStatus]", title: str = "Pipeline status") -> Panel:
    t = Table(show_header=True, header_style="bold cyan", expand=True)
    t.add_column("", width=2)
    t.add_column("Stage", style="bold")
    t.add_column("Status")
    t.add_column("Actions")
    for s in stages:
        actions = ", ".join(f"{status_icon(a.status)} {a.name}" for a in s.actions)
        t.add_row(status_icon(s.status), s.name, f"[{status_color(s.status)}]{s.status}[/]", actions)
    return Panel(t, title=title, border_style="cyan")


def render_event_log(events: list[dict]) -> Table:
    t = Table(title="Latest execution events", header_style="bold cyan")
    t.add_column("Time")
    t.add_column("Stage")
    t.add_column("Action")
    t.add_column("Status")
    t.add_column("Summary")
    for e in events:
        t.add_row(
            str(e.get("startTime", "")),
            e.get("stageName", ""),
            e.get("actionName", ""),
            f"[{status_color(e.get('status',''))}]{e.get('status','')}[/]",
            e.get("summary", "") or "",
        )
    return t


def render_error(title: str, message: str, suggestion: str = "") -> Panel:
    body = Text()
    body.append(message, style="white")
    if suggestion:
        body.append("\n\n→ ", style="bold yellow")
        body.append(suggestion, style="yellow")
    return Panel(body, title=f"[bold red]{title}[/]", border_style="red")


@contextmanager
def spinner(message: str):
    with console.status(f"[cyan]{message}[/]", spinner="dots"):
        yield
