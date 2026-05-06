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
