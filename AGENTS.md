# AGENTS.md

## Purpose

This repository turns ChatGPT web chat into a private OCI instance management agent through OpenAI Secure MCP Tunnel.

The MCP server is intentionally minimal and exposes exactly one tool: `run_command`.

## Authority model

The MCP management service runs as **root**.

This is intentional. The agent is expected to perform full VPS administration, including package installation, systemd management, service repair, log inspection, Docker/Tailscale/OCI CLI installation, and system configuration changes.

Do not reintroduce a filesystem write sandbox such as `ProtectSystem=strict` plus a single `ReadWritePaths` directory unless the user explicitly changes the project back to a restricted coding bridge.

## Default work directory

Use this directory for ordinary project files, generated scripts, notes, downloads, and scratch work:

```text
/home/ubuntu/projects/chatgptweb
```

This is a **default location and operating convention**, not a security boundary.

When system administration requires it, modifying `/etc`, `/usr`, `/var`, `/opt`, `/root`, systemd units, package databases, or other system paths is allowed.

When practical, keep normal project files owned by `ubuntu:ubuntu` so they remain convenient to inspect from the Ubuntu account and local dashboards.

## Operating rules

- Prefer the smallest change that solves the requested maintenance task.
- Inspect current state before changing it.
- Ordinary new project/scratch files belong under `/home/ubuntu/projects/chatgptweb`.
- System files may be created or modified when required for the requested maintenance task.
- Do not delete or overwrite unrelated user data.
- Back up important configuration files before replacing them when practical.
- Do not expose the MCP listener publicly or bind it to `0.0.0.0`.
- Never print or commit tunnel runtime keys, API keys, SSH private keys, or other credentials.
- Do not include the contents of `/etc/chat-bridge-oci-tunnel/tunnel.env` in reports.
- Confirm before high-impact irreversible actions such as formatting disks, deleting volumes, destructive storage operations, or changes likely to lock out SSH access, unless the user explicitly requested that exact action.

## Fresh installation

From a fresh Ubuntu 24.04+ or Debian 12+ instance (Python 3.11+, systemd,
and git available):

```bash
git clone https://github.com/highsun9941/chat-bridge-OCI.git
bash chat-bridge-OCI/bootstrap.sh
```

The script asks for:

1. the user's own OpenAI Secure MCP Tunnel ID;
2. the OpenAI Secure MCP Tunnel runtime API key through a hidden prompt.

There is no repository-default Tunnel ID.

For non-interactive automation, `OPENAI_TUNNEL_ID` and `CONTROL_PLANE_API_KEY` may be supplied securely as environment variables.

## Expected end state

- `chat-bridge-oci.service` is enabled and active.
- `chat-bridge-oci.service` runs as `root`.
- `chat-bridge-oci-tunnel.service` is enabled and active.
- tunnel-client runs as non-root `tunnelclient`.
- MCP binds only to `127.0.0.1:8000`.
- tunnel health binds only to `127.0.0.1:8080`.
- the default agent work directory is `/home/ubuntu/projects/chatgptweb`.
- the public MCP surface exposes exactly `run_command`.
- `run_command` has no executable blocklist.
- absolute working directories are permitted for system administration.
- no inbound OCI firewall/NSG rule is needed for port 8000.
- runtime credentials remain outside Git.

## Verification

```bash
systemctl is-active chat-bridge-oci.service
systemctl is-enabled chat-bridge-oci.service
systemctl is-active chat-bridge-oci-tunnel.service
systemctl is-enabled chat-bridge-oci-tunnel.service
systemctl show chat-bridge-oci.service -p User -p Group
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
```

The service should report `User=root`.

The MCP smoke test should expose exactly:

```text
run_command
```

Manual smoke test:

```bash
sudo env \
  HOME=/root \
  AGENT_WORKDIR=/home/ubuntu/projects/chatgptweb \
  MCP_URL=http://127.0.0.1:8000/mcp \
  /opt/chat-bridge-OCI/.venv/bin/python \
  /opt/chat-bridge-OCI/smoke_test.py
```

## Troubleshooting

Agent logs:

```bash
journalctl -u chat-bridge-oci.service -n 150 --no-pager
```

Tunnel logs:

```bash
journalctl -u chat-bridge-oci-tunnel.service -n 150 --no-pager
curl -v http://127.0.0.1:8080/healthz
curl -v http://127.0.0.1:8080/readyz
```

## Updates

```bash
git pull --ff-only
sudo bash bootstrap.sh
```

Prefer re-running bootstrap over manually editing the generated bridge/tunnel systemd units.

Bootstrap must restart both services to apply updated code and environment,
not just `enable --now` them. Every MCP start uses an `ExecStartPost` protocol
check (up to 60 seconds) so the dependent tunnel waits for actual MCP readiness
at boot as well as during installation. The tunnel also sets
`MCP_STARTUP_WAIT_TIMEOUT=60s`. Keep these startup checks when changing units.

Local regression checks (no root, systemd daemon, or tunnel credentials needed):

```bash
.venv/bin/python -m unittest discover -s tests -v
bash -n bootstrap.sh install.sh
```
