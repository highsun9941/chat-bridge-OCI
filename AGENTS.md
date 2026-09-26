# AGENTS.md

## Purpose

This repository provides a private MCP coding bridge from ChatGPT to an OCI VPS.

For a fresh Ubuntu/Debian OCI installation, **use `bootstrap.sh` as the
canonical path**. Do not manually reproduce all setup steps unless bootstrap
fails and you are diagnosing the failure.

## Fresh installation

From the user's clone:

```bash
bash chat-bridge-OCI/bootstrap.sh
```

If already inside the repository:

```bash
bash bootstrap.sh
```

The script will request the OpenAI Secure MCP Tunnel runtime API key through a
hidden TTY prompt. Never echo that key, put it into a command line, source file,
issue, log message, or Git commit.

The default tunnel ID is:

```text
tunnel_6ab6752e2e9c8191b323f8ad2626d3ed
```

Only use `OPENAI_TUNNEL_ID=...` when the user explicitly wants another tunnel.

## Expected end state

After bootstrap:

- `chat-bridge-oci.service` is enabled and active.
- `chat-bridge-oci-tunnel.service` is enabled and active.
- MCP runs as non-root user `chatbridge`.
- tunnel-client runs as non-root user `tunnelclient`.
- workspace is `/var/lib/chat-bridge/workspace`.
- `chatbridge` has full read/write/execute access inside that workspace.
- all MCP tools are available and `run_command` has no executable blocklist.
- persistent filesystem writes from the MCP service are confined to the workspace.
- MCP binds only to `127.0.0.1:8000`.
- tunnel health is available only on loopback at `127.0.0.1:8080`.
- no inbound OCI firewall/NSG rule is needed for port 8000.
- runtime credentials are stored at
  `/etc/chat-bridge-oci-tunnel/tunnel.env`, outside Git.
- the existing ChatGPT tunnel-backed app can reconnect through the same tunnel.

## Verification

Run:

```bash
systemctl is-active chat-bridge-oci.service
systemctl is-enabled chat-bridge-oci.service
systemctl is-active chat-bridge-oci-tunnel.service
systemctl is-enabled chat-bridge-oci-tunnel.service
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
```

The MCP smoke test should expose exactly these tools:

- workspace_info
- list_files
- read_file
- write_file
- replace_text
- git_status
- git_diff
- run_command

Manual smoke test:

```bash
sudo -u chatbridge env \
  HOME=/var/lib/chatbridge \
  MCP_URL=http://127.0.0.1:8000/mcp \
  /opt/chat-bridge-OCI/.venv/bin/python \
  /opt/chat-bridge-OCI/smoke_test.py
```

## Coding workspace

Only repositories below this directory are intended for ChatGPT coding work:

```text
/var/lib/chat-bridge/workspace
```

Put projects under that root rather than weakening the path checks.

## Safety requirements

Do not:

- run either service as root;
- add `chatbridge` or `tunnelclient` to sudoers;
- expose TCP 8000 or the tunnel health listener publicly;
- bind MCP to `0.0.0.0`;
- commit tunnel/API credentials;
- print credentials while troubleshooting;
- disable workspace path validation or systemd hardening merely to make a test pass.

`run_command` intentionally permits any executable available to `chatbridge`.
The systemd sandbox, not a command blocklist, is the security boundary.
Keep `ProtectSystem=strict`, `ReadWritePaths=/var/lib/chat-bridge/workspace`,
`NoNewPrivileges=true`, and the empty capability set intact.

## Troubleshooting

If MCP fails:

```bash
journalctl -u chat-bridge-oci.service -n 100 --no-pager
```

If the tunnel fails:

```bash
journalctl -u chat-bridge-oci-tunnel.service -n 150 --no-pager
curl -v http://127.0.0.1:8080/healthz
curl -v http://127.0.0.1:8080/readyz
```

Do not include the contents of `/etc/chat-bridge-oci-tunnel/tunnel.env` in a
report.

## Updates

For a normal update:

```bash
git pull --ff-only
bash bootstrap.sh
```

Re-running bootstrap should be preferred over hand-editing the generated
systemd units.
