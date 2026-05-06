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
