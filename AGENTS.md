# Agent instructions

This repository provides root-level OCI administration through OpenAI Secure
MCP Tunnel. See [README.md](README.md) for installation, configuration, updates,
and deployed-service verification. Keep user-facing instructions there.

## Invariants

- Expose exactly one MCP tool: `run_command`, with no executable blocklist.
- Run the MCP service as root. Do not add a non-root or read-only filesystem
  sandbox unless the user explicitly changes the authority model.
- Keep tunnel-client under the separate, hardened `tunnelclient` account.
- Enable both services at boot. Bind MCP to `127.0.0.1:8000` and tunnel health
  to `127.0.0.1:8080`; never expose MCP publicly or open inbound port 8000.
- Use `/home/ubuntu/projects/chatgptweb` for ordinary files, scripts, notes,
  downloads, and scratch work. This is a default, not a security boundary:
  absolute working directories and system administration under `/etc`, `/usr`,
  `/var`, `/opt`, and `/root` are allowed. Prefer `ubuntu:ubuntu` ownership for
  ordinary project files when practical.

## Maintenance

- Inspect current state and make the smallest change that solves the task.
- Do not delete or overwrite unrelated user data. Back up important
  configuration before replacing it when practical.
- Never print or commit tunnel keys, API keys, SSH keys, or other credentials;
  never include `tunnel.env` contents in reports.
- Confirm high-impact irreversible actions (disk formatting, volume deletion,
  destructive storage changes, or changes likely to lock out SSH) unless the
  user explicitly requested that exact action.
- Keep `bootstrap.sh` as the deployment entry point. Re-run it for updates
  instead of manually editing the generated units.
- Preserve explicit service restarts during bootstrap, the MCP `ExecStartPost`
  protocol check, and `MCP_STARTUP_WAIT_TIMEOUT=60s`. The tunnel must wait for
  actual MCP readiness during installation and boot.
- After code changes, run the local checks in README. For live deployments,
  also follow its service and HTTP checks; do not claim OCI reboot or tunnel
  verification from local tests alone.
