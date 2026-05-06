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
        raise ConfigError(f"Config file not found at {path}. Run `aws-deploy config init`.")
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
