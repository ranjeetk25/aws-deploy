from __future__ import annotations
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
