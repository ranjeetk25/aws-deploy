import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from deploy_cli import aws as aws_mod
from deploy_cli import config as cfg_mod
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
    mode = stat.S_IMODE(os.stat(cfg_mod.CREDS_CACHE_PATH).st_mode)
    assert mode == 0o600


def test_load_returns_none_when_missing(tmp_config_dir):
    assert aws_mod.load_cached_creds() is None


def test_load_returns_none_when_garbage(tmp_config_dir):
    cfg_mod.CREDS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg_mod.CREDS_CACHE_PATH.write_text("not-json")
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
