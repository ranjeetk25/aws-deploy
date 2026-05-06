from __future__ import annotations
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock

from deploy_cli import pipeline as p
from deploy_cli.errors import (
    ConcurrencyError, PipelineNotFoundError, ApprovalTimeoutError,
)


def _client_with(states: list[dict]):
    """Mock CodePipeline client returning sequenced get_pipeline_state responses."""
    c = MagicMock()
    c.get_pipeline_state.side_effect = states
    return c


def _state_with_pending_approval():
    return {
        "stageStates": [{
            "stageName": "Approve",
            "actionStates": [{
                "actionName": "Manual",
                "latestExecution": {
                    "status": "InProgress",
                    "token": "TOK-123",
                },
            }],
        }],
    }


def _state_without_approval():
    return {"stageStates": [{"stageName": "Approve", "actionStates": [{"actionName": "Manual", "latestExecution": {"status": "InProgress"}}]}]}


def test_start_execution_returns_id():
    c = MagicMock()
    c.start_pipeline_execution.return_value = {"pipelineExecutionId": "EX-1"}
    assert p.start_execution(c, "pipe-x") == "EX-1"


def test_start_execution_concurrency_error():
    from botocore.exceptions import ClientError
    c = MagicMock()
    c.start_pipeline_execution.side_effect = ClientError(
        {"Error": {"Code": "InvalidPipelineStateException", "Message": "running"}}, "StartPipelineExecution"
    )
    with pytest.raises(ConcurrencyError):
        p.start_execution(c, "pipe-x")


def test_start_execution_not_found():
    from botocore.exceptions import ClientError
    c = MagicMock()
    c.start_pipeline_execution.side_effect = ClientError(
        {"Error": {"Code": "PipelineNotFoundException", "Message": "nope"}}, "StartPipelineExecution"
    )
    with pytest.raises(PipelineNotFoundError):
        p.start_execution(c, "pipe-x")


def test_find_pending_approval_token_found():
    c = _client_with([_state_with_pending_approval()])
    tok = p.find_pending_approval_token(c, "pipe-x", "Approve", "Manual")
    assert tok == "TOK-123"


def test_find_pending_approval_token_absent():
    c = _client_with([_state_without_approval()])
    assert p.find_pending_approval_token(c, "pipe-x", "Approve", "Manual") is None


def test_approve_calls_put_approval_result():
    c = MagicMock()
    p.approve(c, "pipe-x", "Approve", "Manual", "TOK-123", "OK")
    c.put_approval_result.assert_called_once()
    kwargs = c.put_approval_result.call_args.kwargs
    assert kwargs["pipelineName"] == "pipe-x"
    assert kwargs["stageName"] == "Approve"
    assert kwargs["actionName"] == "Manual"
    assert kwargs["token"] == "TOK-123"
    assert kwargs["result"]["status"] == "Approved"


def test_poll_for_approval_returns_token(monkeypatch):
    c = MagicMock()
    seq = [_state_without_approval(), _state_without_approval(), _state_with_pending_approval()]
    c.get_pipeline_state.side_effect = seq
    monkeypatch.setattr(p, "_sleep", lambda s: None)  # skip waits
    tok = p.poll_for_approval(c, "pipe-x", "Approve", "Manual", timeout_seconds=999, poll_interval=0)
    assert tok == "TOK-123"


def test_poll_for_approval_times_out(monkeypatch):
    c = MagicMock()
    c.get_pipeline_state.return_value = _state_without_approval()
    monkeypatch.setattr(p, "_sleep", lambda s: None)
    monkeypatch.setattr(p, "_now", iter([0, 1, 2, 3, 9999]).__next__)  # fast-forward time
    with pytest.raises(ApprovalTimeoutError):
        p.poll_for_approval(c, "pipe-x", "Approve", "Manual", timeout_seconds=2, poll_interval=0)


def test_get_execution_state_aggregates(monkeypatch):
    c = MagicMock()
    c.get_pipeline_execution.return_value = {
        "pipelineExecution": {
            "pipelineExecutionId": "EX-1",
            "status": "InProgress",
            "pipelineName": "pipe-x",
        }
    }
    c.get_pipeline_state.return_value = {
        "stageStates": [{
            "stageName": "Source",
            "latestExecution": {"status": "Succeeded", "lastStatusChange": datetime.now(timezone.utc)},
            "actionStates": [{
                "actionName": "S",
                "latestExecution": {"status": "Succeeded", "summary": "ok"},
                "latestStatusChange": datetime.now(timezone.utc),
            }],
        }],
    }
    es = p.get_execution_state(c, "pipe-x", "EX-1")
    assert es.execution_id == "EX-1"
    assert es.status == "InProgress"
    assert es.stages[0].name == "Source"
    assert es.stages[0].actions[0].status == "Succeeded"
