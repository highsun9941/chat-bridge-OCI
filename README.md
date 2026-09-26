# chat-bridge-OCI

Minimal private MCP coding bridge for an Oracle Cloud Infrastructure (OCI) VPS.

The intended setup is:

```text
ChatGPT @OCI VPS MCP
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
/home/ubuntu/projects/chatgptweb
```

Port 8000 stays loopback-only. Do not open it in an OCI Security List or NSG.

## Fresh OCI: two commands

On a fresh **Ubuntu/Debian OCI instance**:

```bash
git clone https://github.com/highsun9941/chat-bridge-OCI.git
bash chat-bridge-OCI/bootstrap.sh
```

That's the canonical install path.

Before installing, create or open your Secure MCP Tunnel in OpenAI Platform:

https://platform.openai.com/settings/organization/tunnels

https://platform.openai.com/settings/organization/api-keys

Copy your own Tunnel ID from that page. It looks like:

```text
tunnel_6ab...
```

When `bootstrap.sh` starts, it asks for two values:

1. your **Secure MCP Tunnel ID**;
2. your **Secure MCP Tunnel runtime API key** (entered with a hidden prompt).

Example flow:

```text
OpenAI Secure MCP Tunnel ID (example: tunnel_6ab...): tunnel_6ab...
OpenAI tunnel runtime API key (hidden):
```

The runtime API key is never committed to Git. It is written to:

```text
/etc/chat-bridge-oci-tunnel/tunnel.env
```

with `root:tunnelclient` ownership and mode `0640`.

## What bootstrap.sh does

It automatically:

1. installs required OS packages;
2. installs this repository to `/opt/chat-bridge-OCI`;
3. creates the non-root `chatbridge` and `tunnelclient` service users;
4. creates `/home/ubuntu/projects/chatgptweb` and a shared `chatgptweb` group;
5. creates the Python virtual environment and installs the MCP server;
6. downloads the latest official Linux `openai/tunnel-client` release from GitHub;
7. verifies the published SHA-256 digest when available;
8. creates and enables `chat-bridge-oci.service`;
9. creates and enables `chat-bridge-oci-tunnel.service`;
10. keeps the MCP endpoint on `127.0.0.1:8000/mcp`;
11. runs the MCP smoke test;
12. waits for the tunnel `/readyz` endpoint before reporting success.

Both services are enabled for boot.

## MCP tool

The MCP surface intentionally exposes exactly **one tool**:

- `run_command` — run arbitrary argv-style commands inside the workspace.

There are no separate file, Git, or toolbox tools. ChatGPT uses ordinary CLI
programs through `run_command`, for example:

```text
["git", "status"]
["cat", "README.md"]
["find", ".", "-maxdepth", "2", "-type", "f"]
["bash", "-lc", "grep -R --line-number TODO . | head"]
```

The bridge uses a **full-access workspace sandbox**:

- `run_command` has no executable blocklist;
- any executable available to the `chatbridge` service account can be invoked;
- commands start in a workspace-relative working directory;
- the service stays non-root;
- persistent filesystem writes are confined by systemd to `WORKSPACE_ROOT`.

The default workspace after bootstrap is:

```text
/home/ubuntu/projects/chatgptweb
```

Clone or copy coding projects below that directory.

## Service layout

```text
/opt/chat-bridge-OCI
/home/ubuntu/projects/chatgptweb
/var/lib/chatbridge
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

Run the MCP smoke test manually:

```bash
sudo -u chatbridge env \
  HOME=/home/ubuntu/projects/chatgptweb/.home \
  MCP_URL=http://127.0.0.1:8000/mcp \
  /opt/chat-bridge-OCI/.venv/bin/python \
  /opt/chat-bridge-OCI/smoke_test.py
```

## ChatGPT after an OCI rebuild

If you reuse the same OpenAI Tunnel ID, the existing tunnel-backed
`OCI VPS MCP` app in ChatGPT does not need to be recreated.

Rebuild the OCI instance, run the two bootstrap commands, enter the same Tunnel
ID and a valid runtime API key, and the tunnel should reconnect to the same
OpenAI-hosted tunnel.

## Security model

- MCP listens only on `127.0.0.1:8000`.
- Secure MCP Tunnel makes outbound HTTPS connections to OpenAI.
- `chatbridge` and `tunnelclient` are separate non-root users.
- Neither account is added to sudoers by the bootstrap script.
- `chatbridge` has full read/write/execute access inside
  `/home/ubuntu/projects/chatgptweb`.
- the `ubuntu` user shares access through the `chatgptweb` group, so local dashboards can browse the same files.
- `run_command` intentionally has no executable blocklist.
- systemd `ProtectSystem=strict` plus `ReadWritePaths` confines persistent
  writes to the workspace; HOME, TMPDIR, and cache directories are also placed
  below the workspace.
- `NoNewPrivileges` and an empty capability set prevent privilege escalation.
- Tunnel credentials live outside the MCP service and repository.
- Child commands receive a reduced environment.

Do not expose TCP 8000 publicly and do not commit runtime keys.

## Manual/development install

`install.sh` remains available for local/manual MCP development without the
full systemd + Secure MCP Tunnel bootstrap.

## Updating an existing OCI

From the repository clone:

```bash
git pull --ff-only
bash bootstrap.sh
```

The bootstrap is designed to be safe to re-run. It refreshes the installed
source, Python environment, official tunnel-client binary, systemd units, and
health checks.
