# `deploy` CLI Design Spec

**Date:** 2026-05-06
**Status:** Approved
**Goal:** Production-ready Python CLI for triggering AWS CodePipeline executions with optional auto-approval of manual approval stages.

---

## 1. Overview

`deploy` is a `pipx`-installable Python CLI that lets engineers trigger AWS CodePipeline executions by friendly alias, auto-approve manual approval stages, and watch live progress. Pipelines are declared in a user-managed YAML config (`~/.deploy-cli/config.yaml`); the CLI never operates on pipelines outside that allow-list.

Core capabilities:
- Trigger pipeline by alias (relies on AWS CodePipeline V2 native queuing)
- Auto-approve a configured manual-approval stage via polling + `PutApprovalResult`
- Tail live progress with stage-by-stage status panel
- Show config-defined pipeline catalog
- Show current state of any pipeline
- Show event log for the latest execution
- Bootstrap and edit config interactively
- Tab completion for subcommands, aliases, flags

## 2. Resolved Design Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | `deploy logs` scope | Pipeline execution event log only (`list_action_executions` + execution metadata). No CloudWatch fetch. |
| 2 | Concurrent execution | Always call `start_pipeline_execution`. V2 queues natively. V1 surfaces `InvalidPipelineStateException` as a friendly message. |
| 3 | Build tool | `uv` + `hatchling` backend, `pyproject.toml` only |
| 4 | `--approve --watch` 30-min timeout | Hard fail (exit 1) with red panel "approval stage never reached" |
| 5 | `--watch` exit code | `0` on `Succeeded`, `1` on `Failed`/`Stopped`/`Cancelled`/`Superseded` |
| - | Python min | `3.10` |
| - | Multi-approval pipelines | Auto-approve only the single `stage`+`action` declared in config; other manual approvals stay manual |
| - | Cred cache | `~/.deploy-cli/.cache/creds.json`, mode `0600`, refresh when within 5 min of expiry |
| - | Watch refresh interval | 2s |
| - | Approval poll interval | 10s, exponential backoff (1.5x) on transient `ClientError`, max 30 min |

## 3. User Experience

### Commands

```
deploy run <alias> [--approve|-a] [--watch|-w] [--debug]
deploy list
deploy status <alias>
deploy logs <alias>
deploy config init
deploy config edit
deploy config show
deploy config add
deploy config remove <alias>
deploy --install-completion
deploy --version
deploy --help          # banner with ASCII logo
```

### Visual conventions (rich)

- Cyan = info, green = success, yellow = warn, red = error
- Spinner during AWS calls (assume-role, start-execution, poll)
- Progress / live panel for `--watch` and `deploy status`
- Status icons: `✓` Succeeded, `⏳` InProgress, `✗` Failed, `⊘` Stopped/Cancelled/Skipped, `…` Pending/Queued
- Error rendering: red panel + actionable suggestion line; raw boto3 traceback only with `--debug`

## 4. Architecture

### File layout

```
deployment-helper/
├── pyproject.toml              # uv-managed, hatchling backend
├── README.md                   # install, config, usage, troubleshooting
├── .gitignore
├── examples/
│   └── config.yaml             # commented sample config
├── docs/superpowers/
│   ├── specs/2026-05-06-deploy-cli-design.md
│   └── plans/2026-05-06-deploy-cli.md
├── deploy_cli/
│   ├── __init__.py             # __version__
│   ├── main.py                 # click root group, banner, --install-completion, --version
│   ├── config.py               # pydantic models, paths, load/save/validate
│   ├── aws.py                  # STS assume-role, cred cache, client factory
│   ├── pipeline.py             # trigger, poll, approve, state, event log
│   ├── ui.py                   # rich helpers: tables, panels, spinners, error renderer, icons
│   ├── completion.py           # detect shell, write completion script, alias autocomplete
│   ├── errors.py               # custom exception hierarchy
│   └── commands/
│       ├── __init__.py
│       ├── run.py              # deploy run
│       ├── list_cmd.py         # deploy list
│       ├── status.py           # deploy status
│       ├── logs.py             # deploy logs
│       └── config_cmd.py       # deploy config (sub-group)
└── tests/
    ├── __init__.py
    ├── conftest.py             # shared moto fixtures, tmp config dir
    ├── test_config.py
    ├── test_aws.py
    ├── test_pipeline.py
    ├── test_ui.py
    ├── test_completion.py
    ├── test_main.py
    └── test_commands.py
```

> Note: `commands/list.py` would shadow stdlib `list`; renamed to `list_cmd.py`. Same for `config_cmd.py` to disambiguate from `deploy_cli/config.py`.

### Module boundaries (interfaces)

#### `deploy_cli/config.py`

```python
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, field_validator

CONFIG_DIR: Path = Path.home() / ".deploy-cli"
CONFIG_PATH: Path = CONFIG_DIR / "config.yaml"
CACHE_DIR: Path = CONFIG_DIR / ".cache"
CREDS_CACHE_PATH: Path = CACHE_DIR / "creds.json"

class AWSConfig(BaseModel):
    role_arn: str
    region: str
    profile: Optional[str] = None

class ManualApprovalConfig(BaseModel):
    stage: str
    action: str

class PipelineConfig(BaseModel):
    pipeline_name: str
    manual_approval: Optional[ManualApprovalConfig] = None
    description: str = ""

class Config(BaseModel):
    aws: AWSConfig
    pipelines: dict[str, PipelineConfig] = Field(default_factory=dict)

def ensure_config_dir() -> None: ...
def config_exists() -> bool: ...
def load_config(path: Path = CONFIG_PATH) -> Config: ...
def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None: ...
def list_alias_names(path: Path = CONFIG_PATH) -> list[str]:
    """Used by completion. Tolerant of missing/invalid file → returns []."""
```

#### `deploy_cli/errors.py`

```python
class DeployError(Exception): ...
class ConfigError(DeployError): ...
class AWSAuthError(DeployError): ...
class PipelineNotFoundError(DeployError): ...
class ApprovalTimeoutError(DeployError): ...
class ExecutionFailedError(DeployError): ...
class ConcurrencyError(DeployError): ...   # V1 InvalidPipelineStateException
```

#### `deploy_cli/aws.py`

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from .config import AWSConfig

@dataclass
class CachedCreds:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime
    role_arn: str

    @property
    def is_expiring(self) -> bool:
        """True if within 5 minutes of expiry."""

def load_cached_creds() -> Optional[CachedCreds]: ...
def save_cached_creds(creds: CachedCreds) -> None: ...
def assume_role(cfg: AWSConfig) -> CachedCreds:
    """Uses cached creds if non-expiring + matching role_arn, else AssumeRole."""
def get_codepipeline_client(cfg: AWSConfig): ...   # boto3 client
```

#### `deploy_cli/pipeline.py`

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class ActionStatus:
    name: str
    status: str            # InProgress, Succeeded, Failed, Stopped, Stopping, Pending, ""
    summary: str
    last_status_change: Optional[datetime]
    type: str              # action category, e.g. Source, Build, Approval, Deploy

@dataclass
class StageStatus:
    name: str
    status: str            # aggregate
    actions: list[ActionStatus]
    last_status_change: Optional[datetime]

@dataclass
class ExecutionState:
    execution_id: str
    pipeline_name: str
    status: str            # Succeeded, Superseded, Cancelled, Failed, Stopped, Stopping, InProgress, Queued
    start_time: Optional[datetime]
    last_update_time: Optional[datetime]
    stages: list[StageStatus]

# Public API:
def start_execution(client, pipeline_name: str) -> str: ...
def get_pipeline_state(client, pipeline_name: str) -> list[StageStatus]: ...
def get_execution_state(client, pipeline_name: str, execution_id: str) -> ExecutionState: ...
def list_action_events(client, pipeline_name: str, execution_id: str) -> list[dict]: ...
def find_pending_approval_token(client, pipeline_name: str, stage: str, action: str) -> Optional[str]: ...
def approve(client, pipeline_name: str, stage: str, action: str, token: str, summary: str = "Auto-approved by deploy CLI") -> None: ...
def watch_execution(client, pipeline_name: str, execution_id: str, refresh_seconds: float = 2.0) -> str:
    """Live rich panel until terminal state. Returns final status. Ctrl+C clean."""
def poll_for_approval(client, pipeline_name: str, stage: str, action: str, timeout_seconds: int = 1800, poll_interval: int = 10) -> str:
    """Polls until approval token returned. Raises ApprovalTimeoutError on timeout."""
```

#### `deploy_cli/ui.py`

```python
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console: Console  # module-level, used everywhere

def render_banner() -> Panel: ...
def render_pipeline_table(pipelines: dict[str, "PipelineConfig"]) -> Table: ...
def render_stages_panel(stages: list["StageStatus"], title: str = "Pipeline status") -> Panel: ...
def render_event_log(events: list[dict]) -> Table: ...
def render_error(title: str, message: str, suggestion: str = "") -> Panel: ...
def status_icon(status: str) -> str: ...
def status_color(status: str) -> str: ...
def spinner(message: str): ...   # context manager → rich.status.Status
```

#### `deploy_cli/completion.py`

```python
def detect_shell() -> str:
    """Return 'bash' | 'zsh' | 'fish'. Raises if unknown."""
def install_completion() -> Path:
    """Write completion script to known shell location, print source line. Returns path."""
def alias_complete(ctx, param, incomplete: str) -> list:
    """Click completion callback. Reads config tolerantly."""
```

#### `deploy_cli/main.py`

- Click root group with `--debug`, `--version`, `--install-completion`
- Registers subcommands: `run`, `list` (from `list_cmd`), `status`, `logs`, `config`
- Banner shown on `--help`
- Top-level exception handler maps `DeployError` subclasses → `ui.render_error` and proper exit codes; `--debug` re-raises

### Data flow

1. **`deploy run <alias>`**
   - load_config → assume_role → get_codepipeline_client
   - start_execution(client, pipeline_name) → execution_id (or `ConcurrencyError` for V1 conflict)
   - if `--approve`: start polling task in same loop as watch
   - if `--watch`: live panel until terminal state; otherwise print execution_id and exit
2. **`deploy list`** → load_config → render_pipeline_table
3. **`deploy status <alias>`** → load_config → assume_role → get_pipeline_state → render_stages_panel
4. **`deploy logs <alias>`** → load_config → assume_role → get latest exec id from `list_pipeline_executions` → list_action_events → render_event_log
5. **`deploy config init|add`** → questionary wizard → save_config; `add` may call `list_pipelines` (assume_role) to fuzzy-pick

### Auto-approve + watch concurrency

Single-threaded async-ish loop:

```
start watch_loop (refresh 2s):
  state = get_execution_state(client, pipeline_name, execution_id)
  render panel
  if approve_enabled and not approved_yet:
    if elapsed > 30min: raise ApprovalTimeoutError
    every 10s: token = find_pending_approval_token(...)
    if token: approve(...); approved_yet = True
  if state.status terminal: break
return final_status
```

No threads; one loop ticks at the watch cadence and sub-samples the approval poll. Ctrl+C → `KeyboardInterrupt` cleanly bubbles to main exit handler.

### Error rendering

`main.py` wraps the click invocation in a try/except for `DeployError`. Each subclass maps to:

| Exception | Title | Suggestion |
|---|---|---|
| `ConfigError` | "Config error" | "Run `deploy config init` to create config or `deploy config edit` to fix." |
| `AWSAuthError` | "AWS authentication failed" | "Verify role_arn, region, and base profile credentials." |
| `PipelineNotFoundError` | "Pipeline not found" | "Alias points to a pipeline AWS doesn't see. Check `deploy config show`." |
| `ApprovalTimeoutError` | "Approval stage never reached" | "Pipeline did not enter pending-approval within 30 min." |
| `ExecutionFailedError` | "Pipeline execution failed" | (shows stage / action that failed) |
| `ConcurrencyError` | "Pipeline already executing" | "V1 pipelines do not queue. Wait for the current execution to finish." |
| boto3 `ClientError` (uncaught) | code mapped (`AccessDenied` → check role permissions) | – |

`--debug` short-circuits: re-raise so traceback prints.

## 5. Testing strategy

- `pytest` + `moto` (mock AWS) + `click.testing.CliRunner` + `pytest-mock`
- `conftest.py` provides:
  - `tmp_config_dir` fixture monkey-patching `CONFIG_DIR`/`CACHE_DIR` to `tmp_path`
  - `mock_codepipeline` fixture using `moto.mock_aws` (or `mock_codepipeline` legacy decorator)
  - `sample_config` fixture with two pipelines (one with manual_approval, one without)
- Coverage targets:
  - `config.py`: load/save round-trip, schema validation, missing file, malformed YAML
  - `aws.py`: assume_role happy path, cache hit (non-expiring), cache miss (expiring), expiry boundary
  - `pipeline.py`: start_execution, find_pending_approval_token (true/false), approve, watch_execution (terminal states), poll_for_approval (timeout, transient retry)
  - `ui.py`: snapshot tests on rendered tables/panels (rich `Console.export_text`)
  - `completion.py`: detect_shell from $SHELL env, alias_complete with valid/missing config
  - `commands/*`: CliRunner invocations covering happy + error paths
  - `main.py`: error handler mapping each `DeployError` to expected exit code + panel
- `moto` does not mock STS `AssumeRole` for cross-account in all versions — for STS use `pytest-mock` to patch `get_sts_client` directly when needed.
- Integration smoke test: end-to-end `run --approve --watch` against moto-backed pipeline with stubbed approval stage.

## 6. Distribution

- `pipx install git+https://github.com/USER/deploy-cli.git` → installs `deploy` command
- `pip install -e .` for local dev
- Post-install user runs `deploy config init`
- Completion: `deploy --install-completion` writes shell-specific script and prints sourcing line.

## 7. Out of scope (YAGNI)

- CloudWatch log fetching
- Multi-account profile switching mid-command
- Pipeline definition editing (CLI only triggers/observes)
- Slack/email notifications
- Caching pipeline state to disk
- Multi-approval auto-handling (only the single configured stage/action is auto-approved)

## 8. Acceptance criteria

- `pipx install` → `deploy config init` → `deploy run <alias> --approve --watch` works end-to-end against a moto-backed test pipeline
- `deploy --install-completion` writes script for current shell and tab completion works for subcommands and aliases after shell reload
- All `DeployError` subclasses render as styled rich panels (no tracebacks unless `--debug`)
- `deploy list` table fits 80-column terminal
- Exit codes: `0` on success, `1` on `DeployError`/pipeline failure, `130` on Ctrl+C
- `pytest` test suite green, coverage ≥ 80% on non-IO modules
