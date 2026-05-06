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
