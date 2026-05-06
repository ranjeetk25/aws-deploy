from click.testing import CliRunner
from deploy_cli.main import cli


def test_help_shows_banner():
    res = CliRunner().invoke(cli, ["--help"])
    assert res.exit_code == 0
    assert "deploy" in res.output.lower()


def test_version():
    res = CliRunner().invoke(cli, ["--version"])
    assert res.exit_code == 0
    assert "0.1.0" in res.output


def test_unknown_alias_renders_panel(tmp_config_dir, sample_config, monkeypatch):
    from deploy_cli.config import save_config
    save_config(sample_config, tmp_config_dir / "config.yaml")
    fake = type("F", (), {"start_pipeline_execution": lambda self, **kw: {"pipelineExecutionId":"X"}, "get_pipeline_state": lambda self, **kw: {"stageStates":[]}})()
    monkeypatch.setattr("deploy_cli.commands.run.get_codepipeline_client", lambda cfg: fake)
    res = CliRunner().invoke(cli, ["run", "missing-alias"])
    assert res.exit_code != 0
    assert "Unknown alias" in res.output
    assert "deploy list" in res.output


def test_debug_flag_reraises(tmp_config_dir, sample_config):
    """With --debug, DeployError propagates instead of being rendered as a panel."""
    from deploy_cli.config import save_config
    from deploy_cli.errors import UnknownAliasError
    save_config(sample_config, tmp_config_dir / "config.yaml")
    res = CliRunner().invoke(cli, ["--debug", "run", "missing-alias"])
    assert isinstance(res.exception, UnknownAliasError)


def test_help_includes_banner_art():
    """`deploy --help` prepends the ASCII banner before standard click help."""
    res = CliRunner().invoke(cli, ["--help"])
    assert res.exit_code == 0
    assert "AWS CodePipeline launcher" in res.output
    assert "Usage:" in res.output
    assert "Commands:" in res.output


def test_bare_invocation_shows_banner_and_help():
    """`deploy` with no subcommand shows banner + help (exit 0)."""
    res = CliRunner().invoke(cli, [])
    assert res.exit_code == 0
    assert "AWS CodePipeline launcher" in res.output
    assert "Commands:" in res.output
