from rich.console import Console
from deploy_cli import ui
from deploy_cli.config import PipelineConfig, ManualApprovalConfig


def _capture(renderable) -> str:
    c = Console(record=True, width=80)
    c.print(renderable)
    return c.export_text()


def test_status_icon_known():
    assert "✓" in ui.status_icon("Succeeded")
    assert "⏳" in ui.status_icon("InProgress")
    assert "✗" in ui.status_icon("Failed")


def test_status_icon_unknown_returns_default():
    assert ui.status_icon("WhoKnows") == ui.status_icon("")


def test_render_pipeline_table_has_alias_and_name():
    pipelines = {
        "alpha": PipelineConfig(pipeline_name="alpha-prod", description="A"),
        "beta": PipelineConfig(
            pipeline_name="beta-prod",
            manual_approval=ManualApprovalConfig(stage="S", action="A"),
        ),
    }
    out = _capture(ui.render_pipeline_table(pipelines))
    assert "alpha" in out and "alpha-prod" in out
    assert "beta" in out and "beta-prod" in out
    assert "yes" in out and "no" in out


def test_render_error_includes_suggestion():
    out = _capture(ui.render_error("Oops", "something broke", "try again"))
    assert "Oops" in out
    assert "something broke" in out
    assert "try again" in out


def test_render_banner_renders():
    out = _capture(ui.render_banner())
    assert "deploy" in out.lower()
