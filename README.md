# deploy

A `pipx`-installable Python CLI for triggering AWS CodePipeline executions by friendly alias, auto-approving manual approval stages, and tailing live progress. Pipelines are declared up front in a user-managed YAML config; the CLI never operates on pipelines outside that allow-list.

## Install

```bash
# End-user install (isolated)
pipx install git+https://github.com/USER/deploy-cli.git

# Local development
git clone https://github.com/USER/deploy-cli.git
cd deploy-cli
uv venv
uv pip install -e ".[dev]"
```

## Quick start

```bash
deploy --install-completion          # write shell completion (bash/zsh/fish)
deploy config init                   # interactive bootstrap → ~/.deploy-cli/config.yaml
deploy list                          # show configured pipelines
deploy run admissions-student -aw    # trigger, auto-approve, watch live
```

After `--install-completion`, source the printed line in your shell rc to enable tab completion for subcommands and pipeline aliases.

## Commands

| Command | Description |
| --- | --- |
| `deploy run <alias> [-a] [-w]` | Trigger pipeline execution. `-a/--approve` auto-approves the configured manual stage; `-w/--watch` tails progress until terminal state. |
| `deploy list` | Show all configured pipelines as a table. |
| `deploy status <alias>` | Show current stage-by-stage state of a pipeline. |
| `deploy logs <alias>` | Show event log for the most recent execution. |
| `deploy config init` | Bootstrap `~/.deploy-cli/config.yaml` interactively. |
| `deploy config show` | Pretty-print current config as JSON. |
| `deploy config edit` | Open config in `$EDITOR`; validates on save. |
| `deploy config add` | Append a new alias (optionally fuzzy-pick from `list_pipelines`). |
| `deploy config remove <alias>` | Delete an alias. |
| `deploy --install-completion` | Install shell completion script. |
| `deploy --version` | Print version. |
| `deploy --debug ...` | Show raw boto3 tracebacks instead of styled error panels. |

### Examples

```bash
# Trigger and exit (just print execution id)
deploy run admissions-api

# Trigger + auto-approve manual stage + watch live (combined short flags)
deploy run admissions-student -aw

# Inspect what's deployed right now
deploy status admissions-student

# What happened in the last run?
deploy logs admissions-api

# Add a new pipeline alias by fuzzy-picking from AWS
deploy config add
```

Exit codes: `0` on success, `1` on `DeployError` or pipeline failure, `130` on Ctrl+C.

## Config schema

Stored at `~/.deploy-cli/config.yaml` (mode `0700`). Full example at [`examples/config.yaml`](examples/config.yaml):

```yaml
aws:
  role_arn: arn:aws:iam::123456789012:role/DeployCliRole
  region: ap-south-1
  profile: default                # optional; base creds for AssumeRole

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

Credentials are cached at `~/.deploy-cli/.cache/creds.json` (mode `0600`) and refreshed when within 5 minutes of expiry.

## Troubleshooting

**AWS authentication failed.** Verify `role_arn`, `region`, and that your base profile credentials (or default chain) can call `sts:AssumeRole` on the target role. Re-run with `--debug` for the raw boto3 traceback.

**Pipeline not found.** Your alias points to a pipeline name that the assumed role cannot see in the configured region. Check `deploy config show` and confirm the pipeline exists with `aws codepipeline list-pipelines`.

**Pipeline already executing (V1 concurrency).** V1 pipelines surface `InvalidPipelineStateException` rather than queueing. The CLI maps this to a friendly "Pipeline already executing" panel — wait for the current execution to finish, or upgrade the pipeline to V2 (which queues natively).

**Approval stage never reached.** When using `--approve --watch`, the CLI polls for up to 30 minutes for the configured stage/action to enter `pending-approval`. If the pipeline takes longer or never reaches that stage, the command fails with `ApprovalTimeoutError`. Inspect with `deploy status <alias>` to see where the pipeline stalled.

## Development

```bash
uv venv
uv pip install -e ".[dev]"
. .venv/bin/activate

pytest                          # run full suite
pytest -v tests/test_config.py  # narrow scope
ruff check deploy_cli tests     # lint
```

The test suite uses `pytest`, `pytest-mock`, `moto`, and `click.testing.CliRunner`. Shared fixtures (`tmp_config_dir`, `sample_config`) live in `tests/conftest.py`.

## License

MIT
