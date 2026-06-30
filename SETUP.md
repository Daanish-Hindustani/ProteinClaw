# Setup

ProteinClaw is launched by an MCP client or plugin host. There is no
`proteinclaw` command.

## Python Environment

```bash
uv sync --extra dev
uv run --extra dev pytest -m "not gpu and not live"
```

## MCP Server

Run the server directly for local client configuration or smoke testing:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

The repository plugin metadata in `.codex-plugin/plugin.json` points to
`.mcp.json`, which uses the same module launch command.

## Runtime Directories

Useful environment variables:

- `PROTEINCLAW_RUNS_DIR`: run artifact directory, default `./runs`.
- `PROTEINCLAW_WORKSPACE_ROOT`: host workspace root for GPU container mounts.
- `PROTEINCLAW_SKIP_DEBUG_TOOLS`: set to `0` to expose debug tools.
- `PROTEINCLAW_SKILLS_DIR`: override plugin skill root for tests/local installs.

## GPU Host

Install NVIDIA drivers, Docker Engine, and the NVIDIA Container Toolkit before
using GPU-backed tools. Follow `docs/gpu-docker-setup.md`, then verify:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

External agents own provider credentials and login state. ProteinClaw does not
read or manage model-provider credentials.
