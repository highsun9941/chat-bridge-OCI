from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

DEFAULT_WORKDIR = Path(
    os.environ.get(
        "AGENT_WORKDIR",
        os.environ.get("WORKSPACE_ROOT", "/home/ubuntu/projects/chatgptweb"),
    )
).expanduser().resolve()
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8000"))
MAX_COMMAND_OUTPUT = int(os.environ.get("MAX_COMMAND_OUTPUT", "200000"))
MAX_COMMAND_TIMEOUT = int(os.environ.get("MAX_COMMAND_TIMEOUT", "600"))

DEFAULT_WORKDIR.mkdir(parents=True, exist_ok=True)

mcp = MCPServer("OCI Instance Management Agent")

COMMAND = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)

SAFE_ENV_KEYS = {
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "USER",
    "LOGNAME",
    "SHELL",
    "COLORTERM",
    "NO_COLOR",
}


def _resolve_cwd(raw_path: str) -> Path:
    if not raw_path:
        return DEFAULT_WORKDIR

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = DEFAULT_WORKDIR / path

    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"cwd is not a directory: {resolved}")
    return resolved


def _safe_child_env() -> dict[str, str]:
    keys = set(SAFE_ENV_KEYS)
    extra = os.environ.get("CHAT_BRIDGE_EXTRA_ENV_KEYS", "")
    keys.update(key.strip() for key in extra.split(",") if key.strip())
    return {key: value for key, value in os.environ.items() if key in keys}


def _truncate(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_COMMAND_OUTPUT:
        return value, False
    return value[:MAX_COMMAND_OUTPUT] + "\n...[truncated]", True


def _run(argv: list[str], cwd: str, timeout_seconds: int) -> dict[str, Any]:
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise ValueError("argv must be a non-empty list of non-empty strings")

    workdir = _resolve_cwd(cwd)
    timeout = max(1, min(int(timeout_seconds), MAX_COMMAND_TIMEOUT))

    try:
        completed = subprocess.run(
            argv,
            cwd=workdir,
            env=_safe_child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        stdout, out_truncated = _truncate(completed.stdout)
        stderr, err_truncated = _truncate(completed.stderr)
        return {
            "argv": argv,
            "cwd": str(workdir),
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
            "truncated": out_truncated or err_truncated,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout or b"").decode("utf-8", "replace")
        )
        stderr = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else (exc.stderr or b"").decode("utf-8", "replace")
        )
        stdout, out_truncated = _truncate(stdout)
        stderr, err_truncated = _truncate(stderr)
        return {
            "argv": argv,
            "cwd": str(workdir),
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
            "truncated": out_truncated or err_truncated,
        }


@mcp.tool(annotations=COMMAND)
def run_command(
    argv: list[str],
    cwd: str = ".",
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run an arbitrary argv-style command on the OCI instance.

    The service is intentionally designed to run as root for full instance
    administration. The default working directory is AGENT_WORKDIR
    (/home/ubuntu/projects/chatgptweb by default), but cwd may also be an
    absolute system path such as /etc, /var, /opt, or /root.

    Use argv form, for example:
    ["systemctl", "status", "docker"]
    ["journalctl", "-u", "hermes-desktop.service", "-n", "200", "--no-pager"]
    ["bash", "-lc", "apt-get update && apt-get install -y tailscale"]
    """
    return _run(argv, cwd, timeout_seconds)


def main() -> None:
    mcp.run(
        transport="streamable-http",
        host=HOST,
        port=PORT,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
