# chat-bridge-OCI

Minimal MCP server for letting ChatGPT work on code inside an Oracle Cloud VPS.

## What it exposes

The server intentionally keeps the tool set small:

- `workspace_info` — show the configured workspace root.
- `list_files` — list files under the workspace.
- `read_file` — read a UTF-8 text file with line bounds.
- `write_file` — create or replace a UTF-8 text file.
- `replace_text` — make a targeted text replacement.
- `git_status` — inspect repository state.
- `git_diff` — inspect working-tree or staged changes.
- `run_command` — run an argv-style command in the workspace.

All file paths are constrained to `WORKSPACE_ROOT`. The HTTP listener defaults to
`127.0.0.1:8000`, so it is **not public by default**.

## Recommended architecture

```text
ChatGPT
   |
   | Secure MCP Tunnel
   v
OpenAI tunnel endpoint
   ^
   | outbound HTTPS only
   |
tunnel-client on OCI
   |
   v
127.0.0.1:8000/mcp
   |
   v
this MCP server
   |
   v
WORKSPACE_ROOT
```

For a private VPS coding bridge, keep the MCP endpoint on localhost and use
OpenAI Secure MCP Tunnel. Do not open port 8000 in the OCI security list/NSG.

## Quick start

Requirements: Python 3.11+.

```bash
git clone https://github.com/highsun9941/chat-bridge-OCI.git
cd chat-bridge-OCI

python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e .

mkdir -p "$HOME/chat-bridge-workspace"

WORKSPACE_ROOT="$HOME/chat-bridge-workspace" \
MCP_HOST=127.0.0.1 \
MCP_PORT=8000 \
.venv/bin/chat-bridge-oci
```

The MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

Test it with MCP Inspector:

```bash
npx @modelcontextprotocol/inspector@latest
```

Choose **Streamable HTTP** and connect to `http://127.0.0.1:8000/mcp`.

## Connect it to ChatGPT

Recommended: OpenAI Secure MCP Tunnel.

1. Create a tunnel in OpenAI Platform tunnel settings.
2. Install/run `tunnel-client` on this VPS.
3. Point it at `http://127.0.0.1:8000/mcp`.
4. In ChatGPT, enable Developer mode.
5. Open Plugins → + → Connection: **Tunnel** → choose the tunnel.
6. Name the resulting personal plugin something like `VPS`.

Do **not** commit the tunnel runtime API key or any other secret to this repo.

See `AGENTS.md` for an installation checklist intended for a coding agent.

## Security model

This is deliberately a small bridge, not a full host-management daemon.

- File APIs reject paths outside `WORKSPACE_ROOT`.
- `run_command` uses `shell=False`; commands are passed as an argv list.
- Obvious privilege/system-management commands such as `sudo`, `su`,
  `systemctl`, `mount`, `shutdown`, and `reboot` are blocked.
- Child processes receive a reduced environment so service secrets are not
  automatically forwarded to commands.
- The recommended network path is localhost + Secure MCP Tunnel.

**Important:** `run_command` is still powerful. Run this service as a dedicated,
non-root Linux user whose filesystem permissions are limited to the code you
want ChatGPT to modify. Linux user permissions are the final security boundary.

## Configuration

Copy `.env.example` as a reference; the server reads environment variables
directly.

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORKSPACE_ROOT` | `/workspace` | Root directory visible to file tools |
| `MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `MCP_PORT` | `8000` | HTTP port |
| `MAX_READ_BYTES` | `1048576` | Maximum file size accepted by `read_file` |
| `MAX_WRITE_BYTES` | `2097152` | Maximum content size accepted by write tools |
| `MAX_COMMAND_OUTPUT` | `200000` | Max stdout/stderr chars returned per command |
| `MAX_COMMAND_TIMEOUT` | `600` | Hard upper bound for command timeout |
| `CHAT_BRIDGE_EXTRA_ENV_KEYS` | empty | Comma-separated env keys to pass to child commands |

## Why no built-in OAuth?

The minimal/private setup uses Secure MCP Tunnel, so the MCP service does not
need to be exposed publicly. If you later publish this as a public remote MCP
server, add standards-compliant OAuth 2.1 authorization before exposing write
tools or private data.
