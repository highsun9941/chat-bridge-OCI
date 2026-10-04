# chat-bridge-OCI

Manage an OCI instance from ChatGPT through OpenAI Secure MCP Tunnel.
The MCP server exposes one tool, `run_command`, with **root privileges**.
Commands default to `/`; no dedicated agent workspace is required. This is not
a filesystem sandbox. Keep a recovery path such as a boot-volume backup.

## Install

Requirements: Ubuntu 24.04+ or Debian 12+, Python 3.11+, systemd, `git`,
and root or sudo access. Linux amd64 and arm64 are supported.

Prepare your [Secure MCP Tunnel](https://platform.openai.com/settings/organization/tunnels)
and runtime API key. Using the server from ChatGPT also requires a tunnel-backed
app configured in ChatGPT.

```bash
git clone https://github.com/highsun9941/chat-bridge-OCI.git
bash chat-bridge-OCI/bootstrap.sh
```

Enter your **Tunnel ID** (`tunnel_...`), then your **runtime API key** at the hidden
prompt. Bootstrap elevates itself with sudo. These two commands and two inputs
are the complete instance-side installation.

For automation, securely supply `OPENAI_TUNNEL_ID` and `CONTROL_PLANE_API_KEY`
in the environment. There are no default credentials, and `.env` files are not
automatically loaded.

## Installed result

Bootstrap installs the application and the latest official
[OpenAI tunnel-client](https://github.com/openai/tunnel-client) release, checking
its SHA-256 digest when published. It enables both services at boot:

| Service | User | Loopback endpoint |
| --- | --- | --- |
| `chat-bridge-oci.service` | `root` | `127.0.0.1:8000/mcp` |
| `chat-bridge-oci-tunnel.service` | `tunnelclient` | `127.0.0.1:8080/readyz` |

The tunnel uses outbound HTTPS. Do not open inbound port 8000 or bind MCP publicly.
Application files live in `/opt/chat-bridge-OCI`; tunnel credentials live in
`/etc/chat-bridge-oci-tunnel/tunnel.env`, mode `0640`, owned by `root:tunnelclient`.
Never print or commit credentials.

This configuration was verified on a running OCI Ubuntu 24.04 arm64 instance
on **2026-10-04**, with Python 3.12.3, MCP 2.2.0, and tunnel-client 0.0.15:

| Check | Observed result |
| --- | --- |
| Services | Both active and enabled |
| MCP tools | `run_command` only |
| `run_command(["id", "-u"])` | Exit code `0`, stdout `0` (root) |
| `run_command(["pwd"])` | Exit code `0`, stdout `/` |
| `/healthz` / `/readyz` | HTTP `200`, `live` / `ready` |
| Boot order | MCP protocol check completed before the tunnel started |

These versions describe the verified deployment; future installs use the
declared dependency range and the latest tunnel-client release.

## Update and check

From the repository clone, run:

```bash
git pull --ff-only
bash bootstrap.sh
```

Supply the same two inputs again. Bootstrap refreshes the installation, stops
the tunnel, restarts MCP, then restarts the tunnel with the new settings.
On every MCP start, a protocol check waits up to 60 seconds for exactly
`run_command` before the dependent tunnel starts. The tunnel also sets
`MCP_STARTUP_WAIT_TIMEOUT=60s`.

```bash
systemctl is-active chat-bridge-oci.service chat-bridge-oci-tunnel.service
systemctl is-enabled chat-bridge-oci.service chat-bridge-oci-tunnel.service
systemctl show chat-bridge-oci.service -p User -p Group
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
sudo /opt/chat-bridge-OCI/.venv/bin/python /opt/chat-bridge-OCI/smoke_test.py
```

Expect both services active/enabled, the MCP service running as root, both HTTP
checks succeeding, and only `run_command` in the tool list. To inspect failures:

```bash
sudo journalctl -u chat-bridge-oci.service -u chat-bridge-oci-tunnel.service -n 150 --no-pager
```

Bootstrap preserves local systemd drop-ins. Use `systemctl cat` with the service
name to inspect any overrides when an existing installation behaves differently.

The verified deployment logged an `OAuth discovery failed` warning because
the local MCP server does not advertise OAuth metadata. Its `/health/oauth`
diagnostic reported `status: ok`, `state: not_advertised`, and `/readyz` remained
HTTP `200`. Check readiness alongside that warning.

## Command interface and configuration

`run_command(argv, cwd=".", timeout_seconds=120)` runs an argv-style command,
for example `["systemctl", "status", "docker", "--no-pager"]`.
The API default `cwd="."` resolves to `/` in the deployed service. Relative
`cwd` values resolve from `/`; absolute paths are allowed.
The result contains `argv`, `cwd`, `exit_code`, `stdout`, `stderr`, `timed_out`,
and `truncated`. A timeout returns `exit_code: null` and any captured output.

The Python server reads these environment variables. For an installed service,
use a systemd override; for local development, set them when launching it.

| Variable | Default |
| --- | --- |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8000` (keep the host on loopback) |
| `MAX_COMMAND_TIMEOUT` | `600` seconds; requests are clamped to 1–600 by default |
| `MAX_COMMAND_OUTPUT` | `200000` characters per output stream |
| `CHAT_BRIDGE_EXTRA_ENV_KEYS` | Empty; comma-separated extra variables inherited by child commands |

Child commands inherit a reduced environment. The smoke test separately reads
`MCP_URL`, defaulting to `http://127.0.0.1:8000/mcp`.
If you override the MCP address, also align that probe URL and the tunnel's
`MCP_SERVER_URL` with it.

## Local development

Use a virtual environment from the repository directory; no tunnel key or root
access is needed for these checks:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
bash -n bootstrap.sh
```

To run the server locally with your own user privileges:

```bash
.venv/bin/chat-bridge-oci
```

From another terminal, run `.venv/bin/python smoke_test.py`.
See [AGENTS.md](AGENTS.md) for maintenance rules.
