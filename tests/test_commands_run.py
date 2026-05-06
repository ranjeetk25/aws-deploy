import pytest
from unittest.mock import MagicMock
from click.testing import CliRunner
from deploy_cli.commands.run import run as run_cmd
from deploy_cli.config import save_config
from deploy_cli.errors import UnknownAliasError


def _setup(tmp_config_dir, sample_config, monkeypatch):
    save_config(sample_config, tmp_config_dir / "config.yaml")
    fake_client = MagicMock()
    fake_client.start_pipeline_execution.return_value = {"pipelineExecutionId": "EX-1"}
    fake_client.get_pipeline_state.return_value = {"stageStates": []}
    fake_client.get_pipeline_execution.return_value = {
        "pipelineExecution": {
            "pipelineExecutionId": "EX-1", "status": "Succeeded", "pipelineName": "alpha-prod"
        }
    }
    monkeypatch.setattr("deploy_cli.commands.run.get_codepipeline_client", lambda cfg: fake_client)
    return fake_client


def test_run_alpha_no_flags_starts_and_exits(tmp_config_dir, sample_config, monkeypatch):
    fake = _setup(tmp_config_dir, sample_config, monkeypatch)
    res = CliRunner().invoke(run_cmd, ["alpha"])
    assert res.exit_code == 0, res.output
    fake.start_pipeline_execution.assert_called_once_with(name="alpha-prod")
    assert "EX-1" in res.output


def test_run_unknown_alias_errors(tmp_config_dir, sample_config, monkeypatch):
    _setup(tmp_config_dir, sample_config, monkeypatch)
    res = CliRunner().invoke(run_cmd, ["does-not-exist"])
    assert res.exit_code != 0
    assert isinstance(res.exception, UnknownAliasError)


def test_run_with_watch_succeeded_exit_0(tmp_config_dir, sample_config, monkeypatch):
    _setup(tmp_config_dir, sample_config, monkeypatch)
    monkeypatch.setattr("deploy_cli.pipeline._sleep", lambda s: None)
    res = CliRunner().invoke(run_cmd, ["alpha", "-w"])
    assert res.exit_code == 0


def test_run_with_watch_failed_exit_1(tmp_config_dir, sample_config, monkeypatch):
    fake = _setup(tmp_config_dir, sample_config, monkeypatch)
    fake.get_pipeline_execution.return_value = {
        "pipelineExecution": {
            "pipelineExecutionId": "EX-1", "status": "Failed", "pipelineName": "alpha-prod"
        }
    }
    monkeypatch.setattr("deploy_cli.pipeline._sleep", lambda s: None)
    res = CliRunner().invoke(run_cmd, ["alpha", "-w"])
    assert res.exit_code == 1


def test_run_approve_without_manual_approval_warns(tmp_config_dir, sample_config, monkeypatch):
    _setup(tmp_config_dir, sample_config, monkeypatch)
    res = CliRunner().invoke(run_cmd, ["alpha", "-a"])
    assert "no manual_approval" in res.output.lower() or "ignored" in res.output.lower()
    assert res.exit_code == 0


def _setup_beta_with_inflight(tmp_config_dir, sample_config, monkeypatch, *, isatty=True):
    """Simulate the beta pipeline (manual_approval configured) currently sitting
    at the approval stage with an existing execution waiting on a token."""
    save_config(sample_config, tmp_config_dir / "config.yaml")
    fake = MagicMock()
    fake.start_pipeline_execution.return_value = {"pipelineExecutionId": "EX-NEW"}
    fake.get_pipeline_state.return_value = {
        "stageStates": [{
            "stageName": "ManualApproval",
            "latestExecution": {"pipelineExecutionId": "EX-EXISTING", "status": "InProgress"},
            "actionStates": [{
                "actionName": "ApprovalNeeded",
                "latestExecution": {"status": "InProgress", "token": "TOK-EXISTING"},
            }],
        }],
    }
    fake.get_pipeline_execution.return_value = {
        "pipelineExecution": {"pipelineExecutionId": "EX-EXISTING", "status": "Succeeded", "pipelineName": "beta-prod"}
    }
    monkeypatch.setattr("deploy_cli.commands.run.get_codepipeline_client", lambda cfg: fake)
    monkeypatch.setattr("deploy_cli.pipeline._sleep", lambda s: None)
    monkeypatch.setattr("deploy_cli.commands.run._is_interactive", lambda: isatty)
    return fake


def test_run_inflight_approve_existing(tmp_config_dir, sample_config, monkeypatch):
    """User picks 'approve': existing execution gets approved, no new trigger."""
    fake = _setup_beta_with_inflight(tmp_config_dir, sample_config, monkeypatch)
    monkeypatch.setattr(
        "deploy_cli.commands.run._prompt_inflight_choice", lambda inflight: "approve"
    )
    res = CliRunner().invoke(run_cmd, ["beta"])
    assert res.exit_code == 0, res.output
    fake.put_approval_result.assert_called_once()
    kw = fake.put_approval_result.call_args.kwargs
    assert kw["token"] == "TOK-EXISTING"
    fake.start_pipeline_execution.assert_not_called()


def test_run_inflight_trigger_new(tmp_config_dir, sample_config, monkeypatch):
    """User picks 'new': existing left alone, new execution triggered."""
    fake = _setup_beta_with_inflight(tmp_config_dir, sample_config, monkeypatch)
    monkeypatch.setattr(
        "deploy_cli.commands.run._prompt_inflight_choice", lambda inflight: "new"
    )
    res = CliRunner().invoke(run_cmd, ["beta"])
    assert res.exit_code == 0, res.output
    fake.start_pipeline_execution.assert_called_once_with(name="beta-prod")
    fake.put_approval_result.assert_not_called()


def test_run_inflight_cancel(tmp_config_dir, sample_config, monkeypatch):
    """User picks 'cancel': nothing happens."""
    fake = _setup_beta_with_inflight(tmp_config_dir, sample_config, monkeypatch)
    monkeypatch.setattr(
        "deploy_cli.commands.run._prompt_inflight_choice", lambda inflight: "cancel"
    )
    res = CliRunner().invoke(run_cmd, ["beta"])
    assert res.exit_code == 0
    fake.start_pipeline_execution.assert_not_called()
    fake.put_approval_result.assert_not_called()


def test_run_force_new_flag_skips_inflight_check(tmp_config_dir, sample_config, monkeypatch):
    """--new bypasses the prompt even when an inflight pending approval exists."""
    fake = _setup_beta_with_inflight(tmp_config_dir, sample_config, monkeypatch)
    # If the prompt were called, this would fail — inflight check should be skipped.
    monkeypatch.setattr(
        "deploy_cli.commands.run._prompt_inflight_choice",
        lambda inflight: pytest.fail("inflight prompt should not be called with --new"),
    )
    res = CliRunner().invoke(run_cmd, ["beta", "--new"])
    assert res.exit_code == 0
    fake.start_pipeline_execution.assert_called_once_with(name="beta-prod")


def test_run_non_tty_skips_inflight_check(tmp_config_dir, sample_config, monkeypatch):
    """In non-TTY contexts (CI/scripts), inflight prompt is bypassed."""
    fake = _setup_beta_with_inflight(tmp_config_dir, sample_config, monkeypatch, isatty=False)
    monkeypatch.setattr(
        "deploy_cli.commands.run._prompt_inflight_choice",
        lambda inflight: pytest.fail("inflight prompt should not be called in non-TTY mode"),
    )
    res = CliRunner().invoke(run_cmd, ["beta"])
    assert res.exit_code == 0
    fake.start_pipeline_execution.assert_called_once_with(name="beta-prod")


def test_run_approve_watch_interleaves_approval(tmp_config_dir, sample_config, monkeypatch):
    """`-aw` on a manual_approval pipeline: on_tick finds the token and approves, then watches to terminal."""
    save_config(sample_config, tmp_config_dir / "config.yaml")
    fake = MagicMock()
    fake.start_pipeline_execution.return_value = {"pipelineExecutionId": "EX-2"}
    state_with_tok = {
        "stageStates": [{
            "stageName": "ManualApproval",
            "actionStates": [{
                "actionName": "ApprovalNeeded",
                "latestExecution": {"status": "InProgress", "token": "TOK-OK"},
            }],
        }],
    }
    fake.get_pipeline_state.return_value = state_with_tok
    fake.get_pipeline_execution.side_effect = [
        {"pipelineExecution": {"pipelineExecutionId": "EX-2", "status": "InProgress", "pipelineName": "beta-prod"}},
        {"pipelineExecution": {"pipelineExecutionId": "EX-2", "status": "Succeeded", "pipelineName": "beta-prod"}},
    ]
    monkeypatch.setattr("deploy_cli.commands.run.get_codepipeline_client", lambda cfg: fake)
    monkeypatch.setattr("deploy_cli.pipeline._sleep", lambda s: None)
    res = CliRunner().invoke(run_cmd, ["beta", "-aw"])
    assert res.exit_code == 0, res.output
    fake.put_approval_result.assert_called_once()
    kw = fake.put_approval_result.call_args.kwargs
    assert kw["token"] == "TOK-OK"
    assert kw["stageName"] == "ManualApproval"
    assert kw["actionName"] == "ApprovalNeeded"
