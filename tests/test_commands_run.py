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
