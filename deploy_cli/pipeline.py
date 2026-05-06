from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from botocore.exceptions import ClientError
from rich.live import Live

from .errors import (
    ConcurrencyError, PipelineNotFoundError, ApprovalTimeoutError,
)
from . import ui as ui_mod

# Indirection so tests can patch
def _now() -> float:
    return time.time()

def _sleep(s: float) -> None:
    time.sleep(s)


@dataclass
class ActionStatus:
    name: str
    status: str
    summary: str = ""
    last_status_change: Optional[datetime] = None


@dataclass
class StageStatus:
    name: str
    status: str
    actions: list[ActionStatus] = field(default_factory=list)
    last_status_change: Optional[datetime] = None


@dataclass
class ExecutionState:
    execution_id: str
    pipeline_name: str
    status: str
    start_time: Optional[datetime]
    last_update_time: Optional[datetime]
    stages: list[StageStatus]


_TERMINAL = {"Succeeded", "Superseded", "Cancelled", "Failed", "Stopped"}


def start_execution(client, pipeline_name: str) -> str:
    try:
        resp = client.start_pipeline_execution(name=pipeline_name)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "InvalidPipelineStateException":
            raise ConcurrencyError(
                f"Pipeline {pipeline_name!r} is currently executing. "
                "V1 pipelines do not queue."
            ) from e
        if code in ("PipelineNotFoundException", "ResourceNotFoundException"):
            raise PipelineNotFoundError(
                f"Pipeline {pipeline_name!r} not found in this AWS account/region."
            ) from e
        raise
    return resp["pipelineExecutionId"]


def get_pipeline_state(client, pipeline_name: str) -> list[StageStatus]:
    try:
        resp = client.get_pipeline_state(name=pipeline_name)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("PipelineNotFoundException", "ResourceNotFoundException"):
            raise PipelineNotFoundError(f"Pipeline {pipeline_name!r} not found.") from e
        raise
    stages: list[StageStatus] = []
    for st in resp.get("stageStates", []):
        latest = st.get("latestExecution") or {}
        actions: list[ActionStatus] = []
        for a in st.get("actionStates", []):
            ax = a.get("latestExecution") or {}
            actions.append(ActionStatus(
                name=a.get("actionName", ""),
                status=ax.get("status", ""),
                summary=ax.get("summary", "") or "",
                last_status_change=a.get("latestStatusChange"),
            ))
        stages.append(StageStatus(
            name=st.get("stageName", ""),
            status=latest.get("status", ""),
            actions=actions,
            last_status_change=latest.get("lastStatusChange"),
        ))
    return stages


def get_execution_state(client, pipeline_name: str, execution_id: str) -> ExecutionState:
    try:
        ex = client.get_pipeline_execution(
            pipelineName=pipeline_name, pipelineExecutionId=execution_id
        )["pipelineExecution"]
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("PipelineNotFoundException", "ResourceNotFoundException"):
            raise PipelineNotFoundError(f"Pipeline {pipeline_name!r} not found.") from e
        raise
    stages = get_pipeline_state(client, pipeline_name)
    return ExecutionState(
        execution_id=execution_id,
        pipeline_name=pipeline_name,
        status=ex.get("status", ""),
        start_time=ex.get("startTime"),
        last_update_time=ex.get("lastUpdateTime"),
        stages=stages,
    )


def list_action_events(client, pipeline_name: str, execution_id: str) -> list[dict]:
    paginator = client.get_paginator("list_action_executions")
    events: list[dict] = []
    for page in paginator.paginate(
        pipelineName=pipeline_name,
        filter={"pipelineExecutionId": execution_id},
    ):
        for d in page.get("actionExecutionDetails", []):
            events.append({
                "stageName": d.get("stageName", ""),
                "actionName": d.get("actionName", ""),
                "status": d.get("status", ""),
                "startTime": d.get("startTime"),
                "summary": (d.get("output", {}) or {}).get("executionResult", {}).get("externalExecutionSummary", ""),
            })
    return events


def find_pending_approval_token(
    client, pipeline_name: str, stage: str, action: str
) -> Optional[str]:
    resp = client.get_pipeline_state(name=pipeline_name)
    for st in resp.get("stageStates", []):
        if st.get("stageName") != stage:
            continue
        for a in st.get("actionStates", []):
            if a.get("actionName") != action:
                continue
            latest = a.get("latestExecution") or {}
            if latest.get("status") == "InProgress" and latest.get("token"):
                return latest["token"]
    return None


def approve(
    client, pipeline_name: str, stage: str, action: str, token: str,
    summary: str = "Auto-approved by aws-deploy CLI",
) -> None:
    client.put_approval_result(
        pipelineName=pipeline_name,
        stageName=stage,
        actionName=action,
        token=token,
        result={"summary": summary, "status": "Approved"},
    )


_TRANSIENT_CODES = {"ThrottlingException", "RequestTimeout", "ServiceUnavailable"}


def poll_for_approval(
    client, pipeline_name: str, stage: str, action: str,
    timeout_seconds: int = 1800, poll_interval: int = 10,
) -> str:
    start = _now()
    backoff = poll_interval
    while True:
        try:
            tok = find_pending_approval_token(client, pipeline_name, stage, action)
            if tok:
                return tok
            backoff = poll_interval
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in _TRANSIENT_CODES:
                backoff = min(backoff * 1.5, 60)
            else:
                raise
        if _now() - start >= timeout_seconds:
            raise ApprovalTimeoutError(
                f"Approval stage {stage}/{action} did not become pending within "
                f"{timeout_seconds}s for pipeline {pipeline_name}."
            )
        _sleep(backoff)


def watch_execution(
    client, pipeline_name: str, execution_id: str,
    refresh_seconds: float = 2.0,
    on_tick=None,
) -> str:
    """Live panel until execution reaches terminal state. Returns final status.

    on_tick: optional callback (state: ExecutionState) called every refresh.
    """
    with Live(console=ui_mod.console, refresh_per_second=max(1, int(1/refresh_seconds))) as live:
        while True:
            state = get_execution_state(client, pipeline_name, execution_id)
            live.update(ui_mod.render_stages_panel(
                state.stages,
                title=f"{pipeline_name} · {execution_id} · {state.status}",
            ))
            if on_tick is not None:
                on_tick(state)
            if state.status in _TERMINAL:
                return state.status
            _sleep(refresh_seconds)
