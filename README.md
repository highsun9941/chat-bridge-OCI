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
/var/lib/chat-bridge/workspace
```

Port 8000 stays loopback-only. Do not open it in an OCI Security List or NSG.

## Fresh OCI: two commands

On a fresh **Ubuntu/Debian OCI instance**:

```bash
git clone https://github.com/highsun9941/chat-bridge-OCI.git
bash chat-bridge-OCI/bootstrap.sh
```

That's the canonical install path.

The script elevates itself with `sudo` when needed and asks once for the
**OpenAI Secure MCP Tunnel runtime API key** using a hidden prompt.

The default tunnel is already configured for this deployment:

```text
tunnel_6ab6752e2e9c8191b323f8ad2626d3ed
```

The runtime API key is never committed to Git. It is written to:

```text
/etc/chat-bridge-oci-tunnel/tunnel.env
```

with `root:tunnelclient` ownership and mode `0640`.

If the tunnel ID ever changes, override it for one install:

```bash
OPENAI_TUNNEL_ID=tunnel_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx bash chat-bridge-OCI/bootstrap.sh
```

## What bootstrap.sh does

It automatically:

1. installs required OS packages;
2. installs this repository to `/opt/chat-bridge-OCI`;
3. creates the non-root `chatbridge` and `tunnelclient` service users;
4. creates `/var/lib/chat-bridge/workspace`;
5. creates the Python virtual environment and installs the MCP server;
6. downloads the latest official Linux `openai/tunnel-client` release from GitHub;
7. verifies the published SHA-256 digest when available;
8. creates and enables `chat-bridge-oci.service`;
9. creates and enables `chat-bridge-oci-tunnel.service`;
10. keeps the MCP endpoint on `127.0.0.1:8000/mcp`;
11. runs the MCP smoke test;
12. waits for the tunnel `/readyz` endpoint before reporting success.

Both services are enabled for boot.

## MCP tools

The bridge exposes eight tools:

- `workspace_info`
- `list_files`
- `read_file`
- `write_file`
- `replace_text`
- `git_status`
- `git_diff`
- `run_command`

The bridge uses a **full-access workspace sandbox**:

- all eight MCP tools are available;
- `run_command` has no executable blocklist;
- any executable available to the `chatbridge` service account can be invoked;
- the service stays non-root;
- persistent filesystem writes are confined by systemd to `WORKSPACE_ROOT`.

The default workspace after bootstrap is:

```text
/var/lib/chat-bridge/workspace
```

Clone or copy coding projects below that directory.

## Service layout

```text
/opt/chat-bridge-OCI
/var/lib/chat-bridge/workspace
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
  HOME=/var/lib/chatbridge \
  MCP_URL=http://127.0.0.1:8000/mcp \
  /opt/chat-bridge-OCI/.venv/bin/python \
  /opt/chat-bridge-OCI/smoke_test.py
```

## ChatGPT after an OCI rebuild

If you reuse the same OpenAI Tunnel ID, the existing tunnel-backed
`OCI VPS MCP` app in ChatGPT does not need to be recreated.

Rebuild the OCI instance, run the two bootstrap commands, enter a valid runtime
API key, and the tunnel should reconnect to the same OpenAI-hosted tunnel.

## Security model

- MCP listens only on `127.0.0.1:8000`.
- Secure MCP Tunnel makes outbound HTTPS connections to OpenAI.
- `chatbridge` and `tunnelclient` are separate non-root users.
- Neither account is added to sudoers by the bootstrap script.
- `chatbridge` has full read/write/execute access inside
  `/var/lib/chat-bridge/workspace`.
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
