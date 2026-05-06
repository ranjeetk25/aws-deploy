from unittest.mock import MagicMock
from click.testing import CliRunner
from deploy_cli.commands.list_cmd import list_pipelines as list_cmd
from deploy_cli.commands.status import status as status_cmd
from deploy_cli.commands.logs import logs as logs_cmd
from deploy_cli.config import save_config


def test_list_renders(tmp_config_dir, sample_config):
    save_config(sample_config, tmp_config_dir / "config.yaml")
    res = CliRunner().invoke(list_cmd)
    assert res.exit_code == 0
    assert "alpha" in res.output and "beta" in res.output


def test_status_renders_stages(tmp_config_dir, sample_config, monkeypatch):
    save_config(sample_config, tmp_config_dir / "config.yaml")
    fake = MagicMock()
    fake.get_pipeline_state.return_value = {
        "stageStates": [{"stageName": "Source", "latestExecution": {"status": "Succeeded"}, "actionStates": []}]
    }
    monkeypatch.setattr("deploy_cli.commands.status.get_codepipeline_client", lambda cfg: fake)
    res = CliRunner().invoke(status_cmd, ["alpha"])
    assert res.exit_code == 0
    assert "Source" in res.output


def test_logs_renders_events(tmp_config_dir, sample_config, monkeypatch):
    save_config(sample_config, tmp_config_dir / "config.yaml")
    fake = MagicMock()
    fake.list_pipeline_executions.return_value = {
        "pipelineExecutionSummaries": [{"pipelineExecutionId": "EX-1"}]
    }
    paginator = MagicMock()
    paginator.paginate.return_value = [{
        "actionExecutionDetails": [
            {"stageName": "Build", "actionName": "Build", "status": "Succeeded",
             "output": {"executionResult": {"externalExecutionSummary": "ok"}}}
        ]
    }]
    fake.get_paginator.return_value = paginator
    monkeypatch.setattr("deploy_cli.commands.logs.get_codepipeline_client", lambda cfg: fake)
    res = CliRunner().invoke(logs_cmd, ["alpha"])
    assert res.exit_code == 0
    assert "Build" in res.output
