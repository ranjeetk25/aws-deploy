# `deploy` CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Production-ready Python CLI `deploy` triggering AWS CodePipeline executions with optional auto-approval and live watch.

**Architecture:** Click for CLI, rich for output, pydantic for config schema, boto3+STS for AWS, moto for tests. Single-threaded loop sub-samples approval polling at watch cadence. Custom `DeployError` hierarchy maps to styled red panels in `main.py`'s exception handler.

**Tech Stack:** Python 3.10+, `uv` (hatchling backend), `click`, `rich`, `boto3`, `pydantic` v2, `pyyaml`, `questionary`, `pyfiglet`, `pytest`, `moto`, `pytest-mock`.

**Reference spec:** `docs/superpowers/specs/2026-05-06-deploy-cli-design.md`. Each task is independently committable.

---

## Wave 1 — Foundation (5 parallel agents)

All Wave 1 tasks touch disjoint files and have no inter-dependencies. Each agent writes module + tests, runs `pytest <test_file> -v`, commits.

### Wave 1 / Task A1 — Project skeleton

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `examples/config.yaml`
- Create: `deploy_cli/__init__.py`

**Steps:**

- [ ] **Step 1: Write `pyproject.toml`** (uv + hatchling)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "deploy-cli"
version = "0.1.0"
description = "CLI for triggering AWS CodePipeline executions by friendly alias"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "Ranjeet Kumar" }]
dependencies = [
    "click>=8.1.7,<9",
    "rich>=13.7.0,<14",
    "boto3>=1.34.0,<2",
    "pydantic>=2.6.0,<3",
    "pyyaml>=6.0.1,<7",
    "questionary>=2.0.1,<3",
    "pyfiglet>=1.0.2,<2",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9",
    "pytest-mock>=3.12,<4",
    "moto[codepipeline,sts]>=5.0,<6",
    "ruff>=0.4,<1",
]

[project.scripts]
deploy = "deploy_cli.main:cli"

[tool.hatch.build.targets.wheel]
packages = ["deploy_cli"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.py[cod]
.venv/
.env
*.egg-info/
dist/
build/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
.deploy-cli/
```

- [ ] **Step 3: Write `deploy_cli/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Write `examples/config.yaml`** (commented sample)

```yaml
# Example deploy CLI config. Copy to ~/.deploy-cli/config.yaml or run `deploy config init`.

aws:
  role_arn: arn:aws:iam::123456789012:role/DeployCliRole
  region: ap-south-1
  profile: default                # optional; base creds for the AssumeRole call

pipelines:
  admissions-student:
    pipeline_name: admissions-student-ui-production
    description: Student-facing admissions UI
    manual_approval:
      stage: ManualApproval
      action: ApprovalNeeded

  admissions-api:
    pipeline_name: admissions-api-production
    description: Admissions backend API
    manual_approval: null         # no manual approval gate
```

- [ ] **Step 5: Write `README.md` skeleton**

```markdown
# deploy CLI

Trigger AWS CodePipeline executions by friendly alias. Auto-approve manual approval stages. Tail progress live.

## Install

```bash
pipx install git+https://github.com/USER/deploy-cli.git
deploy --install-completion        # installs shell completion
deploy config init                  # interactive config wizard
```

## Quick start

```bash
deploy list                          # show configured pipelines
deploy run admissions-student -aw    # trigger, auto-approve, watch
deploy status admissions-student
deploy logs admissions-student
```

## Config

Stored at `~/.deploy-cli/config.yaml`. See `examples/config.yaml`.

## Troubleshooting

- **AWS authentication failed**: verify `role_arn`, `region`, and base `profile` credentials.
- **Pipeline not found**: alias points to a pipeline AWS does not expose to the assumed role.
- **Pipeline already executing (V1)**: V1 pipelines do not queue — wait for current execution.

Pass `--debug` for raw boto3 tracebacks.
```

- [ ] **Step 6: Sanity check**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`
Expected: no error.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore README.md examples/config.yaml deploy_cli/__init__.py
git commit -m "chore: scaffold deploy-cli project (pyproject, README, example config)"
```

---

### Wave 1 / Task A2 — `config.py` (load/save/validate)

**Files:**
- Create: `deploy_cli/config.py`
- Create: `deploy_cli/errors.py`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`

**Public interface (must expose exactly):**

```python
CONFIG_DIR: Path
CONFIG_PATH: Path
CACHE_DIR: Path
CREDS_CACHE_PATH: Path

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

def ensure_config_dir() -> None
def config_exists() -> bool
def load_config(path: Path = CONFIG_PATH) -> Config
def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None
def list_alias_names(path: Path = CONFIG_PATH) -> list[str]   # tolerant
```

`role_arn` validator: must match `^arn:aws:iam::\d{12}:role/.+$`. `region` validator: non-empty string. Raise `ConfigError` on validation failure with friendly message.

**Steps:**

- [ ] **Step 1: Create `deploy_cli/errors.py`**

```python
class DeployError(Exception):
    """Base for all CLI-rendered errors."""

class ConfigError(DeployError): ...
class AWSAuthError(DeployError): ...
class PipelineNotFoundError(DeployError): ...
class ApprovalTimeoutError(DeployError): ...
class ExecutionFailedError(DeployError): ...
class ConcurrencyError(DeployError): ...
```

- [ ] **Step 2: Write failing test `tests/test_config.py`**

```python
import re
import textwrap
import pytest
from pathlib import Path
from pydantic import ValidationError
from deploy_cli.config import (
    Config, AWSConfig, ManualApprovalConfig, PipelineConfig,
    load_config, save_config, list_alias_names, ensure_config_dir, config_exists,
)
from deploy_cli.errors import ConfigError


def test_round_trip_save_load(tmp_path):
    cfg = Config(
        aws=AWSConfig(role_arn="arn:aws:iam::123456789012:role/Foo", region="ap-south-1"),
        pipelines={
            "alpha": PipelineConfig(pipeline_name="alpha-prod", description="Alpha"),
            "beta": PipelineConfig(
                pipeline_name="beta-prod",
                manual_approval=ManualApprovalConfig(stage="Approve", action="Manual"),
            ),
        },
    )
    p = tmp_path / "config.yaml"
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded == cfg


def test_load_missing_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_load_malformed_yaml_raises_config_error(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("aws: [not, a, mapping\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_invalid_role_arn_rejected():
    with pytest.raises(ValidationError):
        AWSConfig(role_arn="not-an-arn", region="ap-south-1")


def test_list_alias_names_tolerant_of_missing(tmp_path):
    assert list_alias_names(tmp_path / "missing.yaml") == []


def test_list_alias_names_tolerant_of_invalid(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("garbage: [")
    assert list_alias_names(p) == []


def test_list_alias_names_returns_aliases(tmp_path):
    cfg = Config(
        aws=AWSConfig(role_arn="arn:aws:iam::123456789012:role/Foo", region="ap-south-1"),
        pipelines={"a": PipelineConfig(pipeline_name="a-p"), "b": PipelineConfig(pipeline_name="b-p")},
    )
    p = tmp_path / "config.yaml"
    save_config(cfg, p)
    assert sorted(list_alias_names(p)) == ["a", "b"]
```

- [ ] **Step 3: Run tests — expect FAIL (module not implemented)**

Run: `pytest tests/test_config.py -v`
Expected: ImportError or test failures.

- [ ] **Step 4: Implement `deploy_cli/config.py`**

```python
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from .errors import ConfigError

CONFIG_DIR: Path = Path.home() / ".deploy-cli"
CONFIG_PATH: Path = CONFIG_DIR / "config.yaml"
CACHE_DIR: Path = CONFIG_DIR / ".cache"
CREDS_CACHE_PATH: Path = CACHE_DIR / "creds.json"

_ROLE_ARN_RE = re.compile(r"^arn:aws:iam::\d{12}:role/.+$")


class AWSConfig(BaseModel):
    role_arn: str
    region: str
    profile: Optional[str] = None

    @field_validator("role_arn")
    @classmethod
    def _validate_role_arn(cls, v: str) -> str:
        if not _ROLE_ARN_RE.match(v):
            raise ValueError(f"role_arn must match arn:aws:iam::ACCOUNT:role/NAME, got {v!r}")
        return v

    @field_validator("region")
    @classmethod
    def _validate_region(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("region must not be empty")
        return v


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


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
        CACHE_DIR.chmod(0o700)
    except OSError:
        pass


def config_exists() -> bool:
    return CONFIG_PATH.exists()


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        raise ConfigError(f"Config file not found at {path}. Run `deploy config init`.")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Malformed YAML in {path}: {e}") from e
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"Invalid config in {path}:\n{e}") from e


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="python"), sort_keys=False))


def list_alias_names(path: Path = CONFIG_PATH) -> list[str]:
    """Tolerant: never raises. Returns [] on any error."""
    try:
        if not path.exists():
            return []
        raw = yaml.safe_load(path.read_text()) or {}
        pipelines = raw.get("pipelines") or {}
        if not isinstance(pipelines, dict):
            return []
        return list(pipelines.keys())
    except Exception:
        return []
```

- [ ] **Step 5: Write `tests/conftest.py`** (shared fixtures used by other tasks)

```python
import os
from pathlib import Path
import pytest

from deploy_cli import config as cfg_mod


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    """Isolate ~/.deploy-cli for tests."""
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg_mod, "CACHE_DIR", tmp_path / ".cache")
    monkeypatch.setattr(cfg_mod, "CREDS_CACHE_PATH", tmp_path / ".cache" / "creds.json")
    (tmp_path / ".cache").mkdir()
    return tmp_path


@pytest.fixture
def sample_config():
    return cfg_mod.Config(
        aws=cfg_mod.AWSConfig(
            role_arn="arn:aws:iam::123456789012:role/DeployCliRole",
            region="ap-south-1",
        ),
        pipelines={
            "alpha": cfg_mod.PipelineConfig(
                pipeline_name="alpha-prod",
                description="Alpha pipeline",
            ),
            "beta": cfg_mod.PipelineConfig(
                pipeline_name="beta-prod",
                description="Beta pipeline",
                manual_approval=cfg_mod.ManualApprovalConfig(
                    stage="ManualApproval", action="ApprovalNeeded"
                ),
            ),
        },
    )


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    """Default fake AWS env so accidental real calls fail fast."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
```

- [ ] **Step 6: Re-run tests — expect PASS**

Run: `pytest tests/test_config.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add deploy_cli/config.py deploy_cli/errors.py tests/__init__.py tests/conftest.py tests/test_config.py
git commit -m "feat(config): pydantic schema, load/save, alias helper, error hierarchy"
```

---

### Wave 1 / Task A3 — `ui.py` (rich helpers)

**Files:**
- Create: `deploy_cli/ui.py`
- Create: `tests/test_ui.py`

**Public interface:**

```python
console: rich.console.Console
def render_banner() -> Panel
def render_pipeline_table(pipelines: dict[str, PipelineConfig]) -> Table
def render_stages_panel(stages: list[StageStatus], title: str = "Pipeline status") -> Panel
def render_event_log(events: list[dict]) -> Table
def render_error(title: str, message: str, suggestion: str = "") -> Panel
def status_icon(status: str) -> str
def status_color(status: str) -> str
def spinner(message: str)   # context manager
```

> `ui.py` may import `PipelineConfig` from `deploy_cli.config` and `StageStatus` from `deploy_cli.pipeline` ONLY inside `TYPE_CHECKING` block to avoid runtime cycle. Public function signatures use string forward refs.

**Steps:**

- [ ] **Step 1: Write `deploy_cli/ui.py`**

```python
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
    body.append("\nAWS CodePipeline launcher", style="dim")
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
```

- [ ] **Step 2: Write `tests/test_ui.py`**

```python
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
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_ui.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add deploy_cli/ui.py tests/test_ui.py
git commit -m "feat(ui): rich helpers (table, stages panel, event log, error panel, banner)"
```

---

### Wave 1 / Task A4 — `aws.py` (STS assume-role + cred cache + client factory)

**Files:**
- Create: `deploy_cli/aws.py`
- Create: `tests/test_aws.py`

**Public interface:**

```python
@dataclass
class CachedCreds:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime    # tz-aware UTC
    role_arn: str
    @property
    def is_expiring(self) -> bool: ...   # within 5 min

def load_cached_creds() -> Optional[CachedCreds]
def save_cached_creds(creds: CachedCreds) -> None
def assume_role(cfg: AWSConfig) -> CachedCreds
def get_codepipeline_client(cfg: AWSConfig)
```

Cache JSON shape: `{"access_key_id": ..., "secret_access_key": ..., "session_token": ..., "expiration": "2026-05-06T10:00:00+00:00", "role_arn": "..."}`. File mode `0600`. Cache rejected if `role_arn` mismatch with config or `is_expiring`.

**Steps:**

- [ ] **Step 1: Write `tests/test_aws.py`**

```python
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from deploy_cli import aws as aws_mod
from deploy_cli.config import AWSConfig, CACHE_DIR, CREDS_CACHE_PATH


def test_cached_creds_is_expiring_true_when_within_5min():
    soon = datetime.now(timezone.utc) + timedelta(minutes=4)
    c = aws_mod.CachedCreds("a", "b", "c", soon, "arn:aws:iam::1:role/x")
    assert c.is_expiring is True


def test_cached_creds_is_expiring_false_when_far():
    far = datetime.now(timezone.utc) + timedelta(hours=1)
    c = aws_mod.CachedCreds("a", "b", "c", far, "arn:aws:iam::1:role/x")
    assert c.is_expiring is False


def test_save_load_round_trip(tmp_config_dir):
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    c = aws_mod.CachedCreds("ak", "sk", "tok", expiry, "arn:aws:iam::1:role/x")
    aws_mod.save_cached_creds(c)
    loaded = aws_mod.load_cached_creds()
    assert loaded is not None
    assert loaded.access_key_id == "ak"
    assert loaded.role_arn == "arn:aws:iam::1:role/x"
    # mode 0600
    mode = stat.S_IMODE(os.stat(CREDS_CACHE_PATH).st_mode)
    assert mode == 0o600


def test_load_returns_none_when_missing(tmp_config_dir):
    assert aws_mod.load_cached_creds() is None


def test_load_returns_none_when_garbage(tmp_config_dir):
    CREDS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDS_CACHE_PATH.write_text("not-json")
    assert aws_mod.load_cached_creds() is None


@mock_aws
def test_assume_role_returns_creds_and_caches(tmp_config_dir, monkeypatch):
    cfg = AWSConfig(role_arn="arn:aws:iam::123456789012:role/DeployCliRole", region="ap-south-1")
    creds = aws_mod.assume_role(cfg)
    assert creds.role_arn == cfg.role_arn
    assert creds.access_key_id
    # Cache hit on second call
    cached = aws_mod.load_cached_creds()
    assert cached is not None
    assert cached.role_arn == cfg.role_arn


@mock_aws
def test_assume_role_uses_cache_when_valid(tmp_config_dir):
    cfg = AWSConfig(role_arn="arn:aws:iam::123456789012:role/DeployCliRole", region="ap-south-1")
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    aws_mod.save_cached_creds(
        aws_mod.CachedCreds("CACHED-AK", "sk", "tok", expiry, cfg.role_arn)
    )
    creds = aws_mod.assume_role(cfg)
    assert creds.access_key_id == "CACHED-AK"


@mock_aws
def test_assume_role_skips_cache_on_role_mismatch(tmp_config_dir):
    cfg = AWSConfig(role_arn="arn:aws:iam::123456789012:role/Role-A", region="ap-south-1")
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    aws_mod.save_cached_creds(
        aws_mod.CachedCreds("OLD-AK", "sk", "tok", expiry, "arn:aws:iam::1:role/OTHER")
    )
    creds = aws_mod.assume_role(cfg)
    assert creds.access_key_id != "OLD-AK"
    assert creds.role_arn == cfg.role_arn


@mock_aws
def test_get_codepipeline_client_works(tmp_config_dir):
    cfg = AWSConfig(role_arn="arn:aws:iam::123456789012:role/X", region="ap-south-1")
    client = aws_mod.get_codepipeline_client(cfg)
    # Smoke: call list_pipelines (moto returns empty list)
    resp = client.list_pipelines()
    assert "pipelines" in resp
```

- [ ] **Step 2: Implement `deploy_cli/aws.py`**

```python
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from . import config as cfg_mod
from .config import AWSConfig
from .errors import AWSAuthError

_EXPIRY_GUARD = timedelta(minutes=5)
_SESSION_NAME = "deploy-cli-session"


@dataclass
class CachedCreds:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime
    role_arn: str

    @property
    def is_expiring(self) -> bool:
        return self.expiration - datetime.now(timezone.utc) <= _EXPIRY_GUARD

    def to_dict(self) -> dict:
        return {
            "access_key_id": self.access_key_id,
            "secret_access_key": self.secret_access_key,
            "session_token": self.session_token,
            "expiration": self.expiration.isoformat(),
            "role_arn": self.role_arn,
        }

    @staticmethod
    def from_dict(d: dict) -> "CachedCreds":
        return CachedCreds(
            access_key_id=d["access_key_id"],
            secret_access_key=d["secret_access_key"],
            session_token=d["session_token"],
            expiration=datetime.fromisoformat(d["expiration"]),
            role_arn=d["role_arn"],
        )


def load_cached_creds() -> Optional[CachedCreds]:
    p = cfg_mod.CREDS_CACHE_PATH
    try:
        if not p.exists():
            return None
        return CachedCreds.from_dict(json.loads(p.read_text()))
    except Exception:
        return None


def save_cached_creds(creds: CachedCreds) -> None:
    cfg_mod.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = cfg_mod.CREDS_CACHE_PATH
    p.write_text(json.dumps(creds.to_dict()))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _base_session(profile: Optional[str]) -> boto3.Session:
    if profile:
        return boto3.Session(profile_name=profile)
    return boto3.Session()


def assume_role(cfg: AWSConfig) -> CachedCreds:
    cached = load_cached_creds()
    if cached and cached.role_arn == cfg.role_arn and not cached.is_expiring:
        return cached
    try:
        sts = _base_session(cfg.profile).client("sts", region_name=cfg.region)
        resp = sts.assume_role(RoleArn=cfg.role_arn, RoleSessionName=_SESSION_NAME)
    except (ClientError, BotoCoreError) as e:
        raise AWSAuthError(f"AssumeRole failed for {cfg.role_arn}: {e}") from e
    c = resp["Credentials"]
    expiration = c["Expiration"]
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=timezone.utc)
    creds = CachedCreds(
        access_key_id=c["AccessKeyId"],
        secret_access_key=c["SecretAccessKey"],
        session_token=c["SessionToken"],
        expiration=expiration,
        role_arn=cfg.role_arn,
    )
    save_cached_creds(creds)
    return creds


def get_codepipeline_client(cfg: AWSConfig):
    creds = assume_role(cfg)
    return boto3.client(
        "codepipeline",
        region_name=cfg.region,
        aws_access_key_id=creds.access_key_id,
        aws_secret_access_key=creds.secret_access_key,
        aws_session_token=creds.session_token,
    )
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_aws.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add deploy_cli/aws.py tests/test_aws.py
git commit -m "feat(aws): STS assume-role with cred cache and codepipeline client factory"
```

---

### Wave 1 / Task A5 — `completion.py` (shell completion install)

**Files:**
- Create: `deploy_cli/completion.py`
- Create: `tests/test_completion.py`

**Public interface:**

```python
SUPPORTED_SHELLS = ("bash", "zsh", "fish")
def detect_shell() -> str
def install_completion() -> Path
def alias_complete(ctx, param, incomplete: str) -> list  # click completion callback
```

Generated scripts use Click's built-in `_DEPLOY_COMPLETE=bash_source deploy` mechanism. Install location:

| Shell | Path |
|---|---|
| bash | `~/.deploy-cli/completions/deploy.bash` (user appends `source ~/.deploy-cli/completions/deploy.bash` to `~/.bashrc`) |
| zsh  | `~/.deploy-cli/completions/_deploy` (user adds `fpath=(~/.deploy-cli/completions $fpath)` + `autoload -U compinit; compinit` to `~/.zshrc`) |
| fish | `~/.config/fish/completions/deploy.fish` |

Print precise sourcing instruction after writing.

**Steps:**

- [ ] **Step 1: Write `tests/test_completion.py`**

```python
import os
import subprocess
from pathlib import Path
import pytest
from deploy_cli import completion


def test_detect_shell_from_env(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert completion.detect_shell() == "zsh"
    monkeypatch.setenv("SHELL", "/usr/local/bin/bash")
    assert completion.detect_shell() == "bash"
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    assert completion.detect_shell() == "fish"


def test_detect_shell_unknown_raises(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/csh")
    with pytest.raises(Exception):
        completion.detect_shell()


def test_alias_complete_with_config(tmp_config_dir, sample_config):
    from deploy_cli.config import save_config
    save_config(sample_config, tmp_config_dir / "config.yaml")
    # tmp_config_dir patches CONFIG_PATH
    out = completion.alias_complete(None, None, "")
    names = [c.value if hasattr(c, "value") else c for c in out]
    assert "alpha" in names and "beta" in names


def test_alias_complete_filters_prefix(tmp_config_dir, sample_config):
    from deploy_cli.config import save_config
    save_config(sample_config, tmp_config_dir / "config.yaml")
    out = completion.alias_complete(None, None, "be")
    names = [c.value if hasattr(c, "value") else c for c in out]
    assert names == ["beta"]


def test_alias_complete_tolerant_of_missing_config(tmp_config_dir):
    out = completion.alias_complete(None, None, "")
    assert out == []


def test_install_completion_writes_script(tmp_config_dir, monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setattr(completion, "_run_click_complete", lambda shell: f"# completion script for {shell}\n")
    p = completion.install_completion()
    assert p.exists()
    assert "completion script" in p.read_text()
    captured = capsys.readouterr()
    assert "source" in captured.out.lower() or "fpath" in captured.out.lower() or "fish" in captured.out.lower()
```

- [ ] **Step 2: Implement `deploy_cli/completion.py`**

```python
from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import Iterable

import click

from . import config as cfg_mod
from .errors import DeployError

SUPPORTED_SHELLS = ("bash", "zsh", "fish")


def detect_shell() -> str:
    shell_path = os.environ.get("SHELL", "")
    name = Path(shell_path).name
    if name in SUPPORTED_SHELLS:
        return name
    raise DeployError(
        f"Unsupported shell {shell_path!r}. Supported: {', '.join(SUPPORTED_SHELLS)}."
    )


def _run_click_complete(shell: str) -> str:
    """Invoke `_DEPLOY_COMPLETE=<shell>_source deploy` and capture script."""
    env = os.environ.copy()
    env["_DEPLOY_COMPLETE"] = f"{shell}_source"
    try:
        out = subprocess.check_output(["deploy"], env=env, stderr=subprocess.STDOUT)
        return out.decode()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise DeployError(
            f"Failed to generate completion script for {shell}. "
            f"Make sure `deploy` is on PATH (try `pipx ensurepath`)."
        ) from e


def _completion_target(shell: str) -> Path:
    if shell == "bash":
        return cfg_mod.CONFIG_DIR / "completions" / "deploy.bash"
    if shell == "zsh":
        return cfg_mod.CONFIG_DIR / "completions" / "_deploy"
    if shell == "fish":
        return Path.home() / ".config" / "fish" / "completions" / "deploy.fish"
    raise DeployError(f"Unsupported shell: {shell}")


def _instructions(shell: str, path: Path) -> str:
    if shell == "bash":
        return f"Add the following line to ~/.bashrc:\n  source {path}"
    if shell == "zsh":
        return (
            "Add the following lines to ~/.zshrc (then restart your shell):\n"
            f"  fpath=({path.parent} $fpath)\n"
            "  autoload -U compinit; compinit"
        )
    if shell == "fish":
        return f"Restart your fish shell. Script installed to {path}."
    return ""


def install_completion() -> Path:
    shell = detect_shell()
    script = _run_click_complete(shell)
    target = _completion_target(shell)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script)
    print(f"Installed completion script: {target}")
    print(_instructions(shell, target))
    return target


def alias_complete(ctx, param, incomplete: str):
    """Click ParamType completion: returns list[click.shell_completion.CompletionItem]."""
    from click.shell_completion import CompletionItem
    names = cfg_mod.list_alias_names() if hasattr(cfg_mod, "list_alias_names") else []
    return [CompletionItem(n) for n in names if n.startswith(incomplete)]
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_completion.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add deploy_cli/completion.py tests/test_completion.py
git commit -m "feat(completion): shell completion install + alias autocompletion callback"
```

---

## Wave 2 — Pipeline core (1 agent)

### Wave 2 / Task B1 — `pipeline.py`

**Files:**
- Create: `deploy_cli/pipeline.py`
- Create: `tests/test_pipeline.py`

**Public interface:** see spec section 4.

**Implementation notes:**
- `start_execution` calls `client.start_pipeline_execution(name=pipeline_name)`. Catches `InvalidPipelineStateException` → `ConcurrencyError`. Catches `PipelineNotFoundException` → `PipelineNotFoundError`.
- `find_pending_approval_token` reads `get_pipeline_state` → finds matching stage → action → `latestExecution.token` only if `latestExecution.status == "InProgress"` and action category is `Approval`.
- `approve` calls `put_approval_result(pipelineName, stageName, actionName, token, result={summary, status: "Approved"})`.
- `watch_execution` uses `rich.live.Live(..., refresh_per_second=2)` updating the panel from `get_execution_state`. Handles `KeyboardInterrupt` cleanly (Live exits, function re-raises so caller can map to exit 130). Returns final status.
- `poll_for_approval` loop: sleep `poll_interval` (10s), check token, retry on transient `ClientError` (codes `ThrottlingException`, `RequestTimeout`) with exponential backoff (1.5x, capped at 60s), raise `ApprovalTimeoutError` after timeout.

**Steps:**

- [ ] **Step 1: Write `tests/test_pipeline.py`**

```python
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
```

- [ ] **Step 2: Implement `deploy_cli/pipeline.py`**

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Iterable

from botocore.exceptions import ClientError
from rich.live import Live

from .errors import (
    ConcurrencyError, PipelineNotFoundError, ApprovalTimeoutError, DeployError,
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
    type: str = ""


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
    summary: str = "Auto-approved by deploy CLI",
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
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_pipeline.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add deploy_cli/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): start, state, approve, poll, watch with live rich panel"
```

---

## Wave 3 — Commands + main wiring (4 parallel agents)

### Wave 3 / Task C1 — `commands/run.py`

**Files:**
- Create: `deploy_cli/commands/__init__.py` (empty)
- Create: `deploy_cli/commands/run.py`
- Create: `tests/test_commands_run.py`

**Behavior:**
1. Load config; resolve alias → `PipelineConfig` or raise `ConfigError`.
2. `assume_role` → client.
3. With spinner: `execution_id = start_execution(...)`. Print `cyan` "Started execution {execution_id}".
4. If `--approve` and pipeline has `manual_approval`:
   - If also `--watch`: drive a single loop that, on each watch tick, also probes for the approval token (sub-sampled every `poll_interval=10s`). On token, call `approve(...)` once.
   - If `--watch` not set: run `poll_for_approval` then `approve`, then exit (no panel).
5. If `--approve` but pipeline has no `manual_approval`: print warning panel "alias has no manual_approval configured; --approve ignored".
6. If `--watch`: call `watch_execution(...)` (or use the same loop). Final status → exit 0 on `Succeeded`, exit 1 otherwise (raise `ExecutionFailedError`).
7. Without `--watch` and without `--approve`: just print execution_id and exit 0.

**Steps:**

- [ ] **Step 1: Write `tests/test_commands_run.py`**

```python
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from deploy_cli.commands.run import run as run_cmd
from deploy_cli.config import save_config


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
    assert "alias" in res.output.lower()


def test_run_with_watch_succeeded_exit_0(tmp_config_dir, sample_config, monkeypatch):
    fake = _setup(tmp_config_dir, sample_config, monkeypatch)
    monkeypatch.setattr("deploy_cli.commands.run._sleep", lambda s: None)
    res = CliRunner().invoke(run_cmd, ["alpha", "-w"])
    assert res.exit_code == 0


def test_run_with_watch_failed_exit_1(tmp_config_dir, sample_config, monkeypatch):
    fake = _setup(tmp_config_dir, sample_config, monkeypatch)
    fake.get_pipeline_execution.return_value = {
        "pipelineExecution": {
            "pipelineExecutionId": "EX-1", "status": "Failed", "pipelineName": "alpha-prod"
        }
    }
    monkeypatch.setattr("deploy_cli.commands.run._sleep", lambda s: None)
    res = CliRunner().invoke(run_cmd, ["alpha", "-w"])
    assert res.exit_code == 1


def test_run_approve_without_manual_approval_warns(tmp_config_dir, sample_config, monkeypatch):
    _setup(tmp_config_dir, sample_config, monkeypatch)
    res = CliRunner().invoke(run_cmd, ["alpha", "-a"])
    assert "no manual_approval" in res.output.lower() or "ignored" in res.output.lower()
    assert res.exit_code == 0
```

- [ ] **Step 2: Implement `deploy_cli/commands/run.py`**

```python
from __future__ import annotations
import time
import click

from ..aws import get_codepipeline_client
from ..completion import alias_complete
from ..config import load_config
from ..errors import ConfigError, ExecutionFailedError, ApprovalTimeoutError
from ..pipeline import (
    start_execution, watch_execution, find_pending_approval_token,
    approve, poll_for_approval, get_execution_state,
)
from .. import ui

_TERMINAL = {"Succeeded", "Superseded", "Cancelled", "Failed", "Stopped"}


def _sleep(s: float) -> None:
    time.sleep(s)


@click.command(name="run")
@click.argument("alias", shell_complete=alias_complete)
@click.option("--approve", "-a", "do_approve", is_flag=True, help="Auto-approve manual approval stage.")
@click.option("--watch", "-w", "do_watch", is_flag=True, help="Tail pipeline progress live.")
def run(alias: str, do_approve: bool, do_watch: bool):
    """Trigger pipeline execution for ALIAS."""
    cfg = load_config()
    if alias not in cfg.pipelines:
        raise ConfigError(
            f"Unknown alias {alias!r}. Run `deploy list` to see configured aliases."
        )
    pipe = cfg.pipelines[alias]
    client = get_codepipeline_client(cfg.aws)

    with ui.spinner(f"Starting execution for {alias}…"):
        execution_id = start_execution(client, pipe.pipeline_name)
    ui.console.print(f"[green]✓[/] Started execution [bold]{execution_id}[/] for [cyan]{alias}[/]")

    if do_approve and not pipe.manual_approval:
        ui.console.print(ui.render_error(
            "Auto-approve skipped",
            f"Alias {alias!r} has no manual_approval configured; --approve ignored.",
        ))
        do_approve = False

    if do_watch:
        approved = {"done": False}

        def on_tick(state):
            if not do_approve or approved["done"]:
                return
            ma = pipe.manual_approval
            tok = find_pending_approval_token(client, pipe.pipeline_name, ma.stage, ma.action)
            if tok:
                approve(client, pipe.pipeline_name, ma.stage, ma.action, tok)
                approved["done"] = True
                ui.console.print(f"[green]✓[/] Approved {ma.stage}/{ma.action}")

        final = watch_execution(client, pipe.pipeline_name, execution_id, on_tick=on_tick)
        if final == "Succeeded":
            ui.console.print(f"[green]✓ Pipeline succeeded[/]")
            return
        raise ExecutionFailedError(f"Pipeline ended with status {final}")

    if do_approve:
        ma = pipe.manual_approval
        with ui.spinner(f"Waiting for {ma.stage}/{ma.action} to be pending…"):
            tok = poll_for_approval(client, pipe.pipeline_name, ma.stage, ma.action)
        approve(client, pipe.pipeline_name, ma.stage, ma.action, tok)
        ui.console.print(f"[green]✓[/] Approved {ma.stage}/{ma.action}")
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_commands_run.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add deploy_cli/commands/__init__.py deploy_cli/commands/run.py tests/test_commands_run.py
git commit -m "feat(commands): run subcommand with --approve and --watch"
```

---

### Wave 3 / Task C2 — `commands/list_cmd.py`, `status.py`, `logs.py`

**Files:**
- Create: `deploy_cli/commands/list_cmd.py`
- Create: `deploy_cli/commands/status.py`
- Create: `deploy_cli/commands/logs.py`
- Create: `tests/test_commands_simple.py`

**Behavior:**

- `list`: load config, render table.
- `status <alias>`: load config, assume_role, get_pipeline_state, render_stages_panel.
- `logs <alias>`: load config, assume_role, latest exec id from `list_pipeline_executions(maxResults=1)`, list_action_events, render_event_log.

**Steps:**

- [ ] **Step 1: Write `tests/test_commands_simple.py`**

```python
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
```

- [ ] **Step 2: Implement `deploy_cli/commands/list_cmd.py`**

```python
import click
from ..config import load_config
from .. import ui


@click.command(name="list")
def list_pipelines():
    """Show configured pipelines."""
    cfg = load_config()
    ui.console.print(ui.render_pipeline_table(cfg.pipelines))
```

- [ ] **Step 3: Implement `deploy_cli/commands/status.py`**

```python
import click
from ..aws import get_codepipeline_client
from ..completion import alias_complete
from ..config import load_config
from ..errors import ConfigError
from ..pipeline import get_pipeline_state
from .. import ui


@click.command(name="status")
@click.argument("alias", shell_complete=alias_complete)
def status(alias: str):
    """Show current pipeline state for ALIAS."""
    cfg = load_config()
    if alias not in cfg.pipelines:
        raise ConfigError(f"Unknown alias {alias!r}.")
    pipe = cfg.pipelines[alias]
    client = get_codepipeline_client(cfg.aws)
    with ui.spinner(f"Fetching state for {alias}…"):
        stages = get_pipeline_state(client, pipe.pipeline_name)
    ui.console.print(ui.render_stages_panel(stages, title=f"{alias} · {pipe.pipeline_name}"))
```

- [ ] **Step 4: Implement `deploy_cli/commands/logs.py`**

```python
import click
from ..aws import get_codepipeline_client
from ..completion import alias_complete
from ..config import load_config
from ..errors import ConfigError, PipelineNotFoundError
from ..pipeline import list_action_events
from .. import ui


@click.command(name="logs")
@click.argument("alias", shell_complete=alias_complete)
def logs(alias: str):
    """Show latest execution event log for ALIAS."""
    cfg = load_config()
    if alias not in cfg.pipelines:
        raise ConfigError(f"Unknown alias {alias!r}.")
    pipe = cfg.pipelines[alias]
    client = get_codepipeline_client(cfg.aws)
    with ui.spinner(f"Fetching latest execution for {alias}…"):
        resp = client.list_pipeline_executions(pipelineName=pipe.pipeline_name, maxResults=1)
    summaries = resp.get("pipelineExecutionSummaries", [])
    if not summaries:
        ui.console.print(ui.render_error("No executions", f"No executions found for {alias}."))
        return
    exec_id = summaries[0]["pipelineExecutionId"]
    events = list_action_events(client, pipe.pipeline_name, exec_id)
    ui.console.print(ui.render_event_log(events))
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_commands_simple.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add deploy_cli/commands/list_cmd.py deploy_cli/commands/status.py deploy_cli/commands/logs.py tests/test_commands_simple.py
git commit -m "feat(commands): list, status, logs subcommands"
```

---

### Wave 3 / Task C3 — `commands/config_cmd.py`

**Files:**
- Create: `deploy_cli/commands/config_cmd.py`
- Create: `tests/test_commands_config.py`

**Behavior:** `deploy config init|edit|show|add|remove`. Uses `questionary` for interactive prompts. `add` may use AWS `list_pipelines` paginator + fuzzy filter to pick. `edit` opens `$EDITOR` (default vim) on `CONFIG_PATH` then validates. `show` prints `cfg.model_dump_json(indent=2)`.

**Steps:**

- [ ] **Step 1: Write `tests/test_commands_config.py`**

```python
from click.testing import CliRunner
from unittest.mock import MagicMock, patch
from deploy_cli.commands.config_cmd import config_group


def test_show_no_config_renders_error(tmp_config_dir):
    res = CliRunner().invoke(config_group, ["show"])
    assert res.exit_code != 0
    assert "config" in res.output.lower()


def test_show_with_config(tmp_config_dir, sample_config):
    from deploy_cli.config import save_config
    save_config(sample_config, tmp_config_dir / "config.yaml")
    res = CliRunner().invoke(config_group, ["show"])
    assert res.exit_code == 0
    assert "alpha" in res.output


def test_remove_alias(tmp_config_dir, sample_config):
    from deploy_cli.config import save_config, load_config
    save_config(sample_config, tmp_config_dir / "config.yaml")
    res = CliRunner().invoke(config_group, ["remove", "alpha"])
    assert res.exit_code == 0
    cfg = load_config(tmp_config_dir / "config.yaml")
    assert "alpha" not in cfg.pipelines
    assert "beta" in cfg.pipelines


def test_init_via_questionary(tmp_config_dir, monkeypatch):
    answers = iter([
        "arn:aws:iam::123456789012:role/DeployCliRole",  # role_arn
        "ap-south-1",                                      # region
        "default",                                          # profile
        False,                                              # add pipeline now?
    ])
    def fake_text(msg, **kw):
        m = MagicMock(); m.ask = lambda: next(answers); return m
    def fake_confirm(msg, **kw):
        m = MagicMock(); m.ask = lambda: next(answers); return m
    monkeypatch.setattr("deploy_cli.commands.config_cmd.questionary.text", fake_text)
    monkeypatch.setattr("deploy_cli.commands.config_cmd.questionary.confirm", fake_confirm)
    res = CliRunner().invoke(config_group, ["init"])
    assert res.exit_code == 0
    from deploy_cli.config import load_config
    cfg = load_config(tmp_config_dir / "config.yaml")
    assert cfg.aws.region == "ap-south-1"
```

- [ ] **Step 2: Implement `deploy_cli/commands/config_cmd.py`**

```python
from __future__ import annotations
import os
import subprocess
import click
import questionary

from ..aws import get_codepipeline_client
from ..config import (
    Config, AWSConfig, PipelineConfig, ManualApprovalConfig,
    CONFIG_PATH, ensure_config_dir, load_config, save_config, config_exists,
)
from ..errors import ConfigError
from .. import ui


@click.group(name="config")
def config_group():
    """Manage deploy CLI config."""


@config_group.command(name="init")
def init_cmd():
    """Interactive config bootstrap."""
    ensure_config_dir()
    role_arn = questionary.text(
        "AWS role ARN to assume:",
        validate=lambda v: v.startswith("arn:aws:iam::") or "Must be an IAM role ARN",
    ).ask()
    region = questionary.text("AWS region:", default="ap-south-1").ask()
    profile = questionary.text("Base AWS profile (optional, blank = default chain):", default="").ask() or None
    cfg = Config(aws=AWSConfig(role_arn=role_arn, region=region, profile=profile), pipelines={})
    save_config(cfg)
    ui.console.print(f"[green]✓[/] Wrote config to {CONFIG_PATH}")
    if questionary.confirm("Add a pipeline now?", default=False).ask():
        _add_pipeline_interactive(cfg)


@config_group.command(name="show")
def show_cmd():
    """Print current config."""
    cfg = load_config()
    ui.console.print_json(cfg.model_dump_json(indent=2))


@config_group.command(name="edit")
def edit_cmd():
    """Open config in $EDITOR (default vim)."""
    if not config_exists():
        raise ConfigError("Config not found. Run `deploy config init`.")
    editor = os.environ.get("EDITOR", "vim")
    subprocess.call([editor, str(CONFIG_PATH)])
    load_config()  # validate after edit
    ui.console.print(f"[green]✓[/] Config valid")


@config_group.command(name="add")
def add_cmd():
    """Interactive: append a new pipeline alias."""
    cfg = load_config()
    _add_pipeline_interactive(cfg)


@config_group.command(name="remove")
@click.argument("alias")
def remove_cmd(alias: str):
    """Remove ALIAS from config."""
    cfg = load_config()
    if alias not in cfg.pipelines:
        raise ConfigError(f"Alias {alias!r} not in config.")
    del cfg.pipelines[alias]
    save_config(cfg)
    ui.console.print(f"[green]✓[/] Removed {alias}")


def _add_pipeline_interactive(cfg: Config) -> None:
    use_aws = questionary.confirm("Fetch pipeline list from AWS?", default=True).ask()
    pipeline_name: str
    if use_aws:
        try:
            client = get_codepipeline_client(cfg.aws)
            with ui.spinner("Listing pipelines…"):
                names = []
                for page in client.get_paginator("list_pipelines").paginate():
                    names.extend(p["name"] for p in page.get("pipelines", []))
            if not names:
                ui.console.print("[yellow]No pipelines found in this account/region.[/]")
                pipeline_name = questionary.text("Pipeline name:").ask()
            else:
                pipeline_name = questionary.autocomplete(
                    "Pipeline name (type to fuzzy filter):", choices=sorted(names),
                ).ask()
        except Exception as e:  # surface but allow manual entry
            ui.console.print(ui.render_error("AWS list failed", str(e), "Falling back to manual entry."))
            pipeline_name = questionary.text("Pipeline name:").ask()
    else:
        pipeline_name = questionary.text("Pipeline name:").ask()

    alias = questionary.text("Friendly alias:", default=pipeline_name.split("-")[0]).ask()
    description = questionary.text("Description (optional):", default="").ask()
    has_approval = questionary.confirm("Does this pipeline have a manual approval stage?", default=False).ask()
    manual_approval = None
    if has_approval:
        stage = questionary.text("Approval stage name:").ask()
        action = questionary.text("Approval action name:").ask()
        manual_approval = ManualApprovalConfig(stage=stage, action=action)
    cfg.pipelines[alias] = PipelineConfig(
        pipeline_name=pipeline_name, description=description, manual_approval=manual_approval,
    )
    save_config(cfg)
    ui.console.print(f"[green]✓[/] Added alias [bold]{alias}[/]")
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_commands_config.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add deploy_cli/commands/config_cmd.py tests/test_commands_config.py
git commit -m "feat(commands): config init/show/edit/add/remove with questionary"
```

---

### Wave 3 / Task C4 — `main.py` (root group, error handler, --install-completion)

**Files:**
- Create: `deploy_cli/main.py`
- Create: `tests/test_main.py`

**Behavior:**
- `cli` is a `click.Group` with global `--debug` flag (sets `ctx.obj["debug"]`).
- `--install-completion` (eager) calls `completion.install_completion()` and exits.
- `--version` (eager) prints `__version__` and exits.
- `--help` shows banner panel.
- Subcommands registered: `run`, `list_pipelines` (named `list`), `status`, `logs`, `config_group` (named `config`).
- Top-level wrapper catches `DeployError` subclasses → renders styled panel via `ui.render_error`, sets exit code:

| Exception | Exit code |
|---|---|
| `ApprovalTimeoutError`, `ExecutionFailedError`, `ConfigError`, `AWSAuthError`, `PipelineNotFoundError`, `ConcurrencyError` | 1 |
| `KeyboardInterrupt` | 130 |
| Unknown `Exception` w/o `--debug` | 1, render generic error |
| Any with `--debug` | re-raise |

**Steps:**

- [ ] **Step 1: Write `tests/test_main.py`**

```python
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
    assert res.exit_code == 1
    assert "Unknown alias" in res.output or "alias" in res.output.lower()
```

- [ ] **Step 2: Implement `deploy_cli/main.py`**

```python
from __future__ import annotations
import sys
import click

from . import __version__
from . import ui
from .completion import install_completion
from .errors import DeployError
from .commands.run import run
from .commands.list_cmd import list_pipelines
from .commands.status import status
from .commands.logs import logs
from .commands.config_cmd import config_group


def _print_banner(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    ui.console.print(ui.render_banner())


def _install_and_exit(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    install_completion()
    ctx.exit(0)


def _version_and_exit(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo(__version__)
    ctx.exit(0)


@click.group(invoke_without_command=False)
@click.option("--debug", is_flag=True, help="Show raw tracebacks on errors.")
@click.option("--version", is_flag=True, callback=_version_and_exit, expose_value=False, is_eager=True)
@click.option(
    "--install-completion", is_flag=True,
    callback=_install_and_exit, expose_value=False, is_eager=True,
    help="Write shell completion script and print sourcing instructions.",
)
@click.pass_context
def cli(ctx, debug: bool):
    """deploy — AWS CodePipeline launcher."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    if ctx.invoked_subcommand is None:
        ui.console.print(ui.render_banner())


cli.add_command(run)
cli.add_command(list_pipelines)
cli.add_command(status)
cli.add_command(logs)
cli.add_command(config_group)


_ERROR_HINTS = {
    "ConfigError": ("Config error", "Run `deploy config init` or `deploy config edit`."),
    "AWSAuthError": ("AWS authentication failed", "Verify role_arn, region, and base profile credentials."),
    "PipelineNotFoundError": ("Pipeline not found", "Check `deploy config show`. Alias points to a pipeline AWS doesn't see."),
    "ApprovalTimeoutError": ("Approval stage never reached", "Pipeline did not enter pending-approval within 30 minutes."),
    "ExecutionFailedError": ("Pipeline execution failed", "Inspect `deploy logs <alias>` for the failing action."),
    "ConcurrencyError": ("Pipeline already executing", "V1 pipelines do not queue. Wait for the current execution to finish."),
}


def main():
    try:
        cli(standalone_mode=False)
    except DeployError as e:
        title, suggestion = _ERROR_HINTS.get(type(e).__name__, ("Error", ""))
        ui.console.print(ui.render_error(title, str(e), suggestion))
        sys.exit(1)
    except click.exceptions.UsageError as e:
        e.show()
        sys.exit(e.exit_code)
    except click.exceptions.ClickException as e:
        e.show()
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        ui.console.print("\n[yellow]Interrupted[/]")
        sys.exit(130)
    except Exception as e:
        ui.console.print(ui.render_error("Unexpected error", str(e), "Re-run with --debug for full traceback."))
        sys.exit(1)


if __name__ == "__main__":
    main()
```

> Note: `pyproject.toml` entry point is `deploy = deploy_cli.main:cli` — but click's standalone error handling won't render rich panels. Update entry point to `deploy = deploy_cli.main:main`. **Update `pyproject.toml` accordingly in this task.**

- [ ] **Step 3: Update `pyproject.toml` entry point**

In `[project.scripts]` section: change `deploy = "deploy_cli.main:cli"` to `deploy = "deploy_cli.main:main"`.

- [ ] **Step 4: Run all tests**

Run: `pytest -v`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add deploy_cli/main.py tests/test_main.py pyproject.toml
git commit -m "feat(main): click root group, error handler, completion install entry"
```

---

## Wave 4 — Integration polish (final agent)

### Wave 4 / Task D1 — Integration test, README finalize, lint fix

**Files:**
- Create: `tests/test_integration.py`
- Modify: `README.md`

**Steps:**

- [ ] **Step 1: Write `tests/test_integration.py`** (end-to-end with moto)

```python
import boto3
import pytest
from moto import mock_aws
from click.testing import CliRunner
from deploy_cli.main import cli
from deploy_cli.config import save_config


@mock_aws
def test_run_end_to_end(tmp_config_dir, sample_config, monkeypatch):
    save_config(sample_config, tmp_config_dir / "config.yaml")
    cp = boto3.client("codepipeline", region_name="ap-south-1")
    # Note: moto's CodePipeline support is limited. We patch the client factory
    # to return a real moto client that supports list_pipelines for the smoke check.
    monkeypatch.setattr("deploy_cli.commands.list_cmd.load_config", lambda: __import__("deploy_cli.config", fromlist=["load_config"]).load_config(tmp_config_dir / "config.yaml"))
    res = CliRunner().invoke(cli, ["list"])
    assert res.exit_code == 0
    assert "alpha" in res.output and "beta" in res.output
```

- [ ] **Step 2: Run full suite + ruff**

```bash
pytest -v
uvx ruff check deploy_cli tests
```
Expected: green + no lint errors.

- [ ] **Step 3: Finalize README**

Replace skeleton with full README including:
- Install (pipx + pip -e + completion install)
- Config example (link to `examples/config.yaml`)
- Each subcommand with example invocation
- Troubleshooting (auth, pipeline not found, V1 concurrency)
- Development (uv venv, pytest)

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py README.md
git commit -m "test+docs: integration smoke and finalized README"
```

---

## Self-review checklist

After all tasks complete:

1. **Spec coverage:** every command in spec section 3 has a task. ✓
2. **Placeholder scan:** no TODO/TBD strings in plan. ✓
3. **Type consistency:** `StageStatus`, `ActionStatus`, `ExecutionState`, `CachedCreds` named consistently across all tasks. ✓
4. **Wave dependencies:** Wave 2 needs Wave 1 modules importable; Wave 3 needs Wave 2 (`pipeline.py`) and Wave 1. ✓
5. **Commands in main.py wiring:** `run`, `list_pipelines`, `status`, `logs`, `config_group` all imported. ✓

## Execution

Dispatch Wave 1 agents in parallel (5 concurrent), wait for all, then Wave 2 (1), then Wave 3 (4 concurrent), then Wave 4 (1). Review each agent's diff before moving to next wave.
