# chat-bridge-OCI

Use the ChatGPT web chat experience as a private **Oracle Cloud Infrastructure (OCI) instance management agent**.

This project runs a minimal MCP server on an OCI VPS and connects it to ChatGPT through **OpenAI Secure MCP Tunnel**.

```text
ChatGPT web chat
      |
      | OpenAI Secure MCP Tunnel
      v
OpenAI tunnel endpoint
      ^
      | outbound HTTPS only
      |
OCI tunnel-client
      |
      v
127.0.0.1:8000/mcp
      |
      v
chat-bridge-OCI
      |
      v
root-level OCI instance administration
```

The MCP endpoint stays on loopback. Do **not** expose TCP 8000 in an OCI Security List, NSG, or public firewall.

## What this is for

The bridge is intended for day-to-day OCI VPS administration from ChatGPT, for example:

- checking systemd service status and logs;
- inspecting Hermes or other agent processes;
- restarting and repairing services;
- updating installed CLI tools;
- installing and managing Docker;
- installing and managing Tailscale;
- installing OCI CLI and other administration utilities;
- inspecting networking, storage, packages, processes, and system configuration;
- editing files under `/etc`, `/usr`, `/var`, `/opt`, or other system paths when maintenance requires it;
- using `/home/ubuntu/projects/chatgptweb` as the default location for ordinary project files and scratch work.

## Important security warning

This configuration intentionally runs the MCP management service as **root**.

That means ChatGPT, through the connected private MCP app, can execute commands with full administrative privileges on the instance. The default project directory is a workflow convention, **not a filesystem security boundary**.

Use this only on an instance you are comfortable administering through ChatGPT. Keep the tunnel runtime key private, keep port 8000 loopback-only, and maintain a recovery path such as OCI boot-volume backups or snapshots.

## Fresh OCI installation

On a fresh **Ubuntu/Debian OCI instance**:

```bash
git clone https://github.com/highsun9941/chat-bridge-OCI.git
bash chat-bridge-OCI/bootstrap.sh
```

The installer will ask for two values.

First, create or open your Secure MCP Tunnel:

https://platform.openai.com/settings/organization/tunnels

Copy your Tunnel ID. It looks like:

```text
tunnel_6ab...
```

Then obtain the runtime API key associated with your tunnel setup.

When `bootstrap.sh` starts:

```text
OpenAI Secure MCP Tunnel ID (example: tunnel_6ab...):
OpenAI tunnel runtime API key (hidden):
```

No personal Tunnel ID is stored in this repository.

The runtime key is written to:

```text
/etc/chat-bridge-oci-tunnel/tunnel.env
```

with restricted permissions and is never committed to Git.

## What bootstrap.sh does

The installer:

1. installs the required Ubuntu/Debian packages;
2. installs this repository to `/opt/chat-bridge-OCI`;
3. creates the default agent work directory at `/home/ubuntu/projects/chatgptweb`;
4. installs the Python MCP server;
5. downloads the latest official Linux `openai/tunnel-client` release;
6. verifies the published SHA-256 digest when available;
7. installs `chat-bridge-oci.service` as a **root** systemd service;
8. installs the tunnel as a separate non-root `tunnelclient` service;
9. binds MCP only to `127.0.0.1:8000/mcp`;
10. runs the MCP smoke test;
11. waits for the tunnel readiness endpoint before reporting success.

Both services are enabled at boot.

## MCP surface

The server intentionally exposes exactly **one MCP tool**:

- `run_command`

`run_command` accepts argv-style commands and can execute any executable available to root.

Examples:

```text
["systemctl", "status", "hermes-desktop.service", "--no-pager"]
["journalctl", "-u", "hermes-desktop.service", "-n", "200", "--no-pager"]
["docker", "ps", "-a"]
["tailscale", "status"]
["bash", "-lc", "apt-get update && apt-get upgrade -y"]
```

The default working directory is:

```text
/home/ubuntu/projects/chatgptweb
```

Relative `cwd` values resolve below that directory. Absolute `cwd` values such as `/etc`, `/var`, `/opt`, and `/root` are also allowed.

## Operating policy

The intended behavior is:

- create ordinary project files, notes, scripts, and scratch artifacts under `/home/ubuntu/projects/chatgptweb`;
- modify system paths when the requested maintenance task requires it;
- avoid touching unrelated user data;
- inspect state before destructive changes;
- back up important configuration files before replacing them when practical;
- do not commit secrets, tunnel keys, API keys, or private credentials to Git;
- confirm before high-impact irreversible actions such as disk formatting, destructive storage operations, or changes likely to lock out SSH access, unless the user explicitly requested that exact action.

These are operating rules, not OS-enforced write restrictions.

## Service layout

```text
/opt/chat-bridge-OCI
/home/ubuntu/projects/chatgptweb
/var/lib/tunnel-client
/etc/chat-bridge-oci-tunnel/tunnel.env
/etc/systemd/system/chat-bridge-oci.service
/etc/systemd/system/chat-bridge-oci-tunnel.service
/usr/local/bin/tunnel-client
```

Useful checks:

```bash
systemctl status chat-bridge-oci.service
systemctl status chat-bridge-oci-tunnel.service
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
```

Manual MCP smoke test:

```bash
sudo env \
  HOME=/root \
  AGENT_WORKDIR=/home/ubuntu/projects/chatgptweb \
  MCP_URL=http://127.0.0.1:8000/mcp \
  /opt/chat-bridge-OCI/.venv/bin/python \
  /opt/chat-bridge-OCI/smoke_test.py
```

The expected tool list is exactly:

```text
run_command
```

## Updating an existing instance

From the repository clone:

```bash
git pull --ff-only
sudo bash bootstrap.sh
```

Re-running bootstrap refreshes the installed source, Python environment, tunnel-client binary, systemd units, and health checks.

If the same OpenAI Tunnel ID is reused, the existing ChatGPT tunnel-backed app can reconnect to the rebuilt or updated instance without recreating the app.

## Security model

- MCP listens only on `127.0.0.1:8000`.
- The Secure MCP Tunnel makes outbound HTTPS connections to OpenAI.
- The tunnel-client runs as a separate non-root account.
- The MCP management service runs as root intentionally.
- The MCP service does **not** use `ProtectSystem=strict`, `ReadWritePaths`, an empty capability set, or a non-root sandbox, because those controls would block general instance administration.
- The default work directory is organizational, not restrictive.
- The runtime tunnel credential stays outside the repository.
- Child commands receive a reduced environment, while the root service PATH includes standard administrative directories.

This repository prioritizes full instance-management capability over filesystem sandboxing.
