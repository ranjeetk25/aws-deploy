from __future__ import annotations
import os
import subprocess
from pathlib import Path

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
    """Invoke `_DEPLOY_COMPLETE=<shell>_source deploy` and capture script.

    stderr is captured separately so that import-time warnings from boto3
    or other libs don't pollute the completion script written to disk.
    """
    env = os.environ.copy()
    env["_DEPLOY_COMPLETE"] = f"{shell}_source"
    try:
        proc = subprocess.run(
            ["deploy"], env=env, capture_output=True, check=True, text=True,
        )
        return proc.stdout
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
    if hasattr(cfg_mod, "list_alias_names"):
        # Pass CONFIG_PATH explicitly so monkeypatched paths in tests are honored
        # (default args are bound at def-time, not call-time).
        names = cfg_mod.list_alias_names(cfg_mod.CONFIG_PATH)
    else:
        names = []
    return [CompletionItem(n) for n in names if n.startswith(incomplete)]
