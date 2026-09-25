# AGENTS.md

## Purpose

This repository is a minimal MCP coding bridge intended to run on an Oracle
Cloud Infrastructure VPS and be connected to ChatGPT as a private personal
plugin.

If the user asks you to install or operate this repository on the VPS, follow
this runbook.

## Desired end state

- The MCP server runs as a **non-root** Linux user.
- `WORKSPACE_ROOT` points to the directory containing repositories ChatGPT may edit.
- The MCP listener binds only to `127.0.0.1:8000`.
- OCI firewall / Security List / NSG does **not** expose TCP 8000.
- ChatGPT reaches the server through OpenAI Secure MCP Tunnel.
- No OpenAI API key, tunnel runtime key, SSH key, or other secret is committed
  to this repository.

## Install

From the repository checkout:

```bash
bash install.sh
```

By default this creates:

```text
./.venv
$HOME/chat-bridge-workspace
```

To use another workspace:

```bash
WORKSPACE_ROOT=/srv/chat-bridge-workspace bash install.sh
```

If the intended project already exists elsewhere, either set `WORKSPACE_ROOT`
to its parent directory or move/clone the project below the configured workspace.

## Start and verify

Start the service locally:

```bash
WORKSPACE_ROOT="$HOME/chat-bridge-workspace" \
MCP_HOST=127.0.0.1 \
MCP_PORT=8000 \
.venv/bin/chat-bridge-oci
```

In a second shell:

```bash
MCP_URL=http://127.0.0.1:8000/mcp .venv/bin/python smoke_test.py
```

The smoke test should list:

- workspace_info
- list_files
- read_file
- write_file
- replace_text
- git_status
- git_diff
- run_command

## Persistence

After the smoke test passes, run the same command under the host's normal
service manager (systemd is preferred on OCI Linux/Ubuntu).

The service account must:

1. not be root;
2. not have passwordless sudo;
3. have read/write permission only to the intended coding workspace and normal
   language/tool caches it needs;
4. receive no unnecessary secrets in its environment.

Do not weaken filesystem permissions merely to make the bridge work.

## ChatGPT connection

Preferred connection method: **OpenAI Secure MCP Tunnel**.

Do not make this server public just to connect ChatGPT.

When the user has created a tunnel in OpenAI Platform and supplied the required
tunnel configuration securely, run `tunnel-client` on this VPS and point its
MCP server URL to:

```text
http://127.0.0.1:8000/mcp
```

Keep the tunnel client and MCP server running as services after validation.

The user then creates a developer-mode ChatGPT plugin using **Connection:
Tunnel** and selects that tunnel. A useful display name is `VPS`.

## Safety notes

`run_command` intentionally uses `shell=False` and blocks obvious host
administration commands, but it is still a powerful coding primitive. Treat the
Linux service account's permissions as the real security boundary.

Do not:

- run the MCP service as root;
- add the service account to sudoers;
- bind to `0.0.0.0` unless the user intentionally replaces the tunnel design
  with a properly authenticated public MCP deployment;
- paste secrets into source files or commits;
- disable the workspace path checks.

## Upgrade

For a later repository update:

```bash
git pull --ff-only
.venv/bin/pip install -e .
```

Then restart the MCP service and rerun `smoke_test.py`.
