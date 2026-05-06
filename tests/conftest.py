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
