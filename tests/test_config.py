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
