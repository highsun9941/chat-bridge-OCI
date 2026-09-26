from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

DEFAULT_WORKDIR = Path(
    os.environ.get("AGENT_WORKDIR", "/home/ubuntu/projects/chatgptweb")
).expanduser().resolve()
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8000"))
MAX_COMMAND_OUTPUT = int(os.environ.get("MAX_COMMAND_OUTPUT", "200000"))
MAX_COMMAND_TIMEOUT = int(os.environ.get("MAX_COMMAND_TIMEOUT", "600"))

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


def _format_output(value: str | bytes | None) -> tuple[str, bool]:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    value = value or ""
    if len(value) <= MAX_COMMAND_OUTPUT:
        return value, False
    return value[:MAX_COMMAND_OUTPUT] + "\n...[truncated]", True


@mcp.tool(annotations=COMMAND)
def run_command(
    argv: list[str],
    cwd: str = ".",
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run an argv-style command on the OCI instance.

    The deployed service runs as root. Relative cwd resolves from AGENT_WORKDIR;
    absolute system paths are allowed.
    Example: ["systemctl", "status", "docker", "--no-pager"].
    """
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
        stdout, stderr = completed.stdout, completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout, exc.stderr
        exit_code = None

    stdout, out_truncated = _format_output(stdout)
    stderr, err_truncated = _format_output(stderr)
    return {
        "argv": argv,
        "cwd": str(workdir),
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": exit_code is None,
        "truncated": out_truncated or err_truncated,
    }


def main() -> None:
    DEFAULT_WORKDIR.mkdir(parents=True, exist_ok=True)
    mcp.run(
        transport="streamable-http",
        host=HOST,
        port=PORT,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
