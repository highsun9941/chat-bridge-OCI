from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

ROOT = Path(os.environ.get("WORKSPACE_ROOT", "/workspace")).expanduser().resolve()
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8000"))
MAX_READ_BYTES = int(os.environ.get("MAX_READ_BYTES", "1048576"))
MAX_WRITE_BYTES = int(os.environ.get("MAX_WRITE_BYTES", "2097152"))
MAX_COMMAND_OUTPUT = int(os.environ.get("MAX_COMMAND_OUTPUT", "200000"))
MAX_COMMAND_TIMEOUT = int(os.environ.get("MAX_COMMAND_TIMEOUT", "600"))

ROOT.mkdir(parents=True, exist_ok=True)

mcp = MCPServer("OCI VPS Coding Bridge")

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)
WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)
COMMAND = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)

BLOCKED_EXECUTABLES = {
    "sudo",
    "su",
    "doas",
    "systemctl",
    "service",
    "mount",
    "umount",
    "shutdown",
    "reboot",
    "poweroff",
    "halt",
    "useradd",
    "userdel",
    "usermod",
    "groupadd",
    "groupdel",
    "passwd",
    "chown",
    "chgrp",
    "iptables",
    "nft",
    "ufw",
    "kill",
    "killall",
    "pkill",
}

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


def _resolve_path(raw_path: str) -> Path:
    if not raw_path:
        raise ValueError("path must not be empty")

    path = Path(raw_path).expanduser()
    if path.is_absolute():
        raise ValueError("use a path relative to WORKSPACE_ROOT")

    resolved = (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError("path escapes WORKSPACE_ROOT")
    return resolved


def _relative(path: Path) -> str:
    if path == ROOT:
        return "."
    return path.relative_to(ROOT).as_posix()


def _load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(_relative(path))
    if not path.is_file():
        raise ValueError(f"not a file: {_relative(path)}")

    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise ValueError(
            f"file is {size} bytes; MAX_READ_BYTES is {MAX_READ_BYTES}. "
            "Raise MAX_READ_BYTES deliberately if you need to read it."
        )

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("only UTF-8 text files are supported") from exc


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

    executable = Path(argv[0]).name
    if executable in BLOCKED_EXECUTABLES:
        raise ValueError(f"blocked executable: {executable}")

    workdir = _resolve_path(cwd)
    if not workdir.exists() or not workdir.is_dir():
        raise ValueError(f"cwd is not a directory: {_relative(workdir)}")

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
            "cwd": _relative(workdir),
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
            "cwd": _relative(workdir),
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
            "truncated": out_truncated or err_truncated,
        }


@mcp.tool(annotations=READ_ONLY)
def workspace_info() -> dict[str, Any]:
    """Show the coding workspace root and bridge limits."""
    return {
        "workspace_root": str(ROOT),
        "max_read_bytes": MAX_READ_BYTES,
        "max_write_bytes": MAX_WRITE_BYTES,
        "max_command_output_chars": MAX_COMMAND_OUTPUT,
        "max_command_timeout_seconds": MAX_COMMAND_TIMEOUT,
    }


@mcp.tool(annotations=READ_ONLY)
def list_files(path: str = ".", max_entries: int = 300) -> dict[str, Any]:
    """List files and directories below a workspace-relative path."""
    target = _resolve_path(path)
    if not target.exists():
        raise FileNotFoundError(_relative(target))

    limit = max(1, min(int(max_entries), 2000))
    entries: list[dict[str, Any]] = []

    if target.is_file():
        return {
            "base": _relative(target),
            "entries": [
                {
                    "path": _relative(target),
                    "type": "file",
                    "size": target.stat().st_size,
                }
            ],
            "truncated": False,
        }

    for current, dirs, files in os.walk(target, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in sorted(dirs)
            if name not in {".git", ".venv", "node_modules", "__pycache__"}
        ]

        for name in dirs:
            item = current_path / name
            entries.append({"path": _relative(item), "type": "dir"})
            if len(entries) >= limit:
                return {
                    "base": _relative(target),
                    "entries": entries,
                    "truncated": True,
                }

        for name in sorted(files):
            item = current_path / name
            try:
                size = item.stat().st_size
            except OSError:
                size = None
            entries.append({"path": _relative(item), "type": "file", "size": size})
            if len(entries) >= limit:
                return {
                    "base": _relative(target),
                    "entries": entries,
                    "truncated": True,
                }

    return {"base": _relative(target), "entries": entries, "truncated": False}


@mcp.tool(annotations=READ_ONLY)
def read_file(path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    """Read a UTF-8 text file from the workspace using inclusive 1-based line bounds."""
    target = _resolve_path(path)
    text = _load_text(target)
    lines = text.splitlines(keepends=True)

    start = max(1, int(start_line))
    end = max(start, int(end_line))
    content = "".join(lines[start - 1 : end])

    return {
        "path": _relative(target),
        "start_line": start,
        "end_line": min(end, len(lines)),
        "total_lines": len(lines),
        "content": content,
    }


@mcp.tool(annotations=WRITE)
def write_file(path: str, content: str, create_parents: bool = True) -> dict[str, Any]:
    """Create or completely replace a UTF-8 text file inside the workspace."""
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ValueError(
            f"content is {len(encoded)} bytes; MAX_WRITE_BYTES is {MAX_WRITE_BYTES}"
        )

    target = _resolve_path(path)
    if target == ROOT:
        raise ValueError("cannot write to the workspace root directory")
    if target.exists() and target.is_dir():
        raise ValueError("target is a directory")

    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.parent.exists():
        raise FileNotFoundError(_relative(target.parent))

    target.write_text(content, encoding="utf-8")
    return {"path": _relative(target), "bytes_written": len(encoded)}


@mcp.tool(annotations=WRITE)
def replace_text(
    path: str,
    old: str,
    new: str,
    expected_replacements: int = 1,
) -> dict[str, Any]:
    """Replace exact text in a workspace file and fail if the match count is unexpected."""
    if not old:
        raise ValueError("old must not be empty")

    target = _resolve_path(path)
    text = _load_text(target)
    actual = text.count(old)
    expected = int(expected_replacements)

    if actual != expected:
        raise ValueError(
            f"expected {expected} occurrence(s), found {actual}; no changes were made"
        )

    updated = text.replace(old, new, expected)
    encoded = updated.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ValueError(
            f"result is {len(encoded)} bytes; MAX_WRITE_BYTES is {MAX_WRITE_BYTES}"
        )

    target.write_text(updated, encoding="utf-8")
    return {
        "path": _relative(target),
        "replacements": expected,
        "bytes_written": len(encoded),
    }


@mcp.tool(annotations=READ_ONLY)
def git_status(cwd: str = ".") -> dict[str, Any]:
    """Return concise git status for a repository in the workspace."""
    return _run(["git", "status", "--short", "--branch"], cwd, 30)


@mcp.tool(annotations=READ_ONLY)
def git_diff(cwd: str = ".", staged: bool = False) -> dict[str, Any]:
    """Return the current git diff for a repository in the workspace."""
    argv = ["git", "diff"]
    if staged:
        argv.append("--staged")
    return _run(argv, cwd, 30)


@mcp.tool(annotations=COMMAND)
def run_command(
    argv: list[str],
    cwd: str = ".",
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run a command without a shell in the workspace.

    Use argv form, for example ["pytest", "-q"] or ["npm", "test"].
    The service must run as a non-root Linux user; Linux permissions are the
    final security boundary.
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
