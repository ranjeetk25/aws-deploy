"""End-to-end integration smoke test.

Verifies the full CLI plumbing: config load → click root group dispatch →
subcommand → ui render. We deliberately keep this test scoped to a
non-AWS-dependent subcommand (`deploy list`) because moto's CodePipeline
coverage is incomplete and would obscure the dispatch-layer signal we
actually want to assert. The AWS-touching subcommands have their own
unit tests with mocked clients in test_commands_*.py.
"""
from click.testing import CliRunner

from deploy_cli.config import save_config
from deploy_cli.main import cli


def test_cli_list_end_to_end(tmp_config_dir, sample_config):
    """deploy list end-to-end: config seeded, root cli invoked, table rendered."""
    save_config(sample_config, tmp_config_dir / "config.yaml")
    res = CliRunner().invoke(cli, ["list"])
    assert res.exit_code == 0, f"stderr: {res.output}"
    assert "alpha" in res.output
    assert "beta" in res.output


def test_cli_help_lists_subcommands():
    """--help renders banner and lists every spec-required subcommand."""
    res = CliRunner().invoke(cli, ["--help"])
    assert res.exit_code == 0
    for sub in ("run", "list", "status", "logs", "config"):
        assert sub in res.output, f"missing subcommand {sub!r} in help output"


def test_cli_version_smoke():
    """--version prints the package version cleanly."""
    res = CliRunner().invoke(cli, ["--version"])
    assert res.exit_code == 0
    assert "0.1.0" in res.output
