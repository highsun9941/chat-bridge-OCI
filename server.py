from __future__ import annotations

import inspect
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

ROOT = Path(
    os.environ.get("WORKSPACE_ROOT", "/home/ubuntu/projects/chatgptweb")
).expanduser().resolve()
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8000"))
MAX_READ_BYTES = int(os.environ.get("MAX_READ_BYTES", "1048576"))
MAX_WRITE_BYTES = int(os.environ.get("MAX_WRITE_BYTES", "2097152"))
MAX_COMMAND_OUTPUT = int(os.environ.get("MAX_COMMAND_OUTPUT", "200000"))
MAX_COMMAND_TIMEOUT = int(os.environ.get("MAX_COMMAND_TIMEOUT", "600"))

ROOT.mkdir(parents=True, exist_ok=True)

mcp = MCPServer("OCI VPS Coding Bridge")

TOOLBOX = ToolAnnotations(
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


# Internal toolbox functions. These are intentionally NOT exposed as MCP tools.

def _workspace_info() -> dict[str, Any]:
    return {
        "workspace_root": str(ROOT),
        "max_read_bytes": MAX_READ_BYTES,
        "max_write_bytes": MAX_WRITE_BYTES,
        "max_command_output_chars": MAX_COMMAND_OUTPUT,
        "max_command_timeout_seconds": MAX_COMMAND_TIMEOUT,
        "command_policy": "all executables available to the service account are allowed",
        "persistent_write_scope": str(ROOT),
    }


def _list_files(path: str = ".", max_entries: int = 300) -> dict[str, Any]:
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


def _read_file(
    path: str,
    start_line: int = 1,
    end_line: int = 400,
) -> dict[str, Any]:
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


def _write_file(
    path: str,
    content: str,
    create_parents: bool = True,
) -> dict[str, Any]:
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


def _replace_text(
    path: str,
    old: str,
    new: str,
    expected_replacements: int = 1,
) -> dict[str, Any]:
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


def _git_status(cwd: str = ".") -> dict[str, Any]:
    return _run(["git", "status", "--short", "--branch"], cwd, 30)


def _git_diff(cwd: str = ".", staged: bool = False) -> dict[str, Any]:
    argv = ["git", "diff"]
    if staged:
        argv.append("--staged")
    return _run(argv, cwd, 30)


ToolHandler = Callable[..., dict[str, Any]]

TOOLBOX_CATALOG: dict[str, dict[str, Any]] = {
    "workspace_info": {
        "category": "workspace",
        "description": "Show the workspace root, limits, command policy, and write scope.",
        "tags": ["workspace", "root", "limits", "environment", "작업공간", "경로", "제한"],
        "arguments": {},
        "read_only": True,
    },
    "list_files": {
        "category": "filesystem",
        "description": "Recursively list files and directories below a workspace-relative path.",
        "tags": ["files", "directories", "tree", "list", "ls", "파일", "폴더", "목록"],
        "arguments": {
            "path": "string, workspace-relative, default '.'",
            "max_entries": "integer, default 300, maximum 2000",
        },
        "read_only": True,
    },
    "read_file": {
        "category": "filesystem",
        "description": "Read a UTF-8 text file using inclusive 1-based line bounds.",
        "tags": ["read", "file", "text", "cat", "view", "lines", "파일", "읽기", "텍스트"],
        "arguments": {
            "path": "string, required, workspace-relative",
            "start_line": "integer, default 1",
            "end_line": "integer, default 400",
        },
        "read_only": True,
    },
    "write_file": {
        "category": "filesystem",
        "description": "Create or completely replace a UTF-8 text file inside the workspace.",
        "tags": ["write", "create", "save", "file", "text", "파일", "쓰기", "생성", "저장"],
        "arguments": {
            "path": "string, required, workspace-relative",
            "content": "string, required",
            "create_parents": "boolean, default true",
        },
        "read_only": False,
    },
    "replace_text": {
        "category": "filesystem",
        "description": "Replace exact text in a workspace file and verify the expected match count.",
        "tags": ["edit", "replace", "patch", "modify", "text", "파일", "수정", "교체", "패치"],
        "arguments": {
            "path": "string, required, workspace-relative",
            "old": "string, required",
            "new": "string, required",
            "expected_replacements": "integer, default 1",
        },
        "read_only": False,
    },
    "git_status": {
        "category": "git",
        "description": "Return concise Git branch and working-tree status for a repository.",
        "tags": ["git", "status", "branch", "changes", "repository", "깃", "상태", "변경"],
        "arguments": {
            "cwd": "string, workspace-relative directory, default '.'",
        },
        "read_only": True,
    },
    "git_diff": {
        "category": "git",
        "description": "Return the current Git diff, optionally for staged changes.",
        "tags": ["git", "diff", "patch", "changes", "staged", "깃", "차이", "변경"],
        "arguments": {
            "cwd": "string, workspace-relative directory, default '.'",
            "staged": "boolean, default false",
        },
        "read_only": True,
    },
}

TOOLBOX_HANDLERS: dict[str, ToolHandler] = {
    "workspace_info": _workspace_info,
    "list_files": _list_files,
    "read_file": _read_file,
    "write_file": _write_file,
    "replace_text": _replace_text,
    "git_status": _git_status,
    "git_diff": _git_diff,
}


def _public_tool_spec(name: str) -> dict[str, Any]:
    spec = TOOLBOX_CATALOG[name]
    return {
        "name": name,
        "category": spec["category"],
        "description": spec["description"],
        "tags": spec["tags"],
        "arguments": spec["arguments"],
        "read_only": spec["read_only"],
        "call": {
            "action": "call",
            "tool": name,
            "arguments": spec["arguments"],
        },
    }


def _search_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+|[가-힣]+", value.lower())


def _search_toolbox(query: str, limit: int) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("query is required for action='search'")

    query_lower = query.lower()
    tokens = _search_tokens(query)
    scored: list[tuple[int, str]] = []

    for name, spec in TOOLBOX_CATALOG.items():
        name_lower = name.lower()
        description = str(spec["description"]).lower()
        category = str(spec["category"]).lower()
        tags = [str(tag).lower() for tag in spec["tags"]]
        haystack = " ".join([name_lower, description, category, *tags])

        score = 0
        if query_lower == name_lower:
            score += 100
        if query_lower in name_lower:
            score += 40
        if query_lower in haystack:
            score += 25

        for token in tokens:
            if token == name_lower:
                score += 30
            elif token in name_lower:
                score += 15
            if token == category:
                score += 12
            if token in tags:
                score += 12
            elif token in haystack:
                score += 4

        if score > 0:
            scored.append((score, name))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = scored[: max(1, min(int(limit), 25))]

    return {
        "query": query,
        "matches": [
            {"score": score, **_public_tool_spec(name)}
            for score, name in selected
        ],
        "match_count": len(selected),
        "hint": "Use toolbox(action='call', tool='<name>', arguments={...}) to execute a match.",
    }


def _list_toolbox(category: str) -> dict[str, Any]:
    category = category.strip().lower()

    if not category:
        counts: dict[str, int] = {}
        for spec in TOOLBOX_CATALOG.values():
            key = str(spec["category"])
            counts[key] = counts.get(key, 0) + 1
        return {
            "categories": [
                {"category": key, "tool_count": counts[key]}
                for key in sorted(counts)
            ],
            "total_tools": len(TOOLBOX_CATALOG),
            "hint": "Call list again with a category, or use search with keywords.",
        }

    names = [
        name
        for name, spec in TOOLBOX_CATALOG.items()
        if str(spec["category"]).lower() == category
    ]
    if not names:
        raise ValueError(f"unknown toolbox category: {category}")

    return {
        "category": category,
        "tools": [_public_tool_spec(name) for name in sorted(names)],
        "tool_count": len(names),
    }


def _call_toolbox(tool: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    tool = tool.strip()
    if not tool:
        raise ValueError("tool is required for action='call'")
    if tool not in TOOLBOX_HANDLERS:
        raise ValueError(f"unknown toolbox tool: {tool}")

    args = arguments or {}
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")

    handler = TOOLBOX_HANDLERS[tool]
    try:
        inspect.signature(handler).bind(**args)
    except TypeError as exc:
        raise ValueError(f"invalid arguments for {tool}: {exc}") from exc

    return {
        "tool": tool,
        "result": handler(**args),
    }


@mcp.tool(annotations=TOOLBOX)
def toolbox(
    action: str,
    query: str = "",
    category: str = "",
    tool: str = "",
    arguments: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Discover and call specialized bridge tools without exposing them all.

    Actions:
    - search: find relevant internal tools by keyword using query.
    - list: list toolbox categories, or tools in one category.
    - call: execute one internal tool using tool and arguments.

    Prefer search before call when you are unsure which specialized tool fits.
    run_command remains separately available for arbitrary CLI work.
    """
    normalized = action.strip().lower()

    if normalized == "search":
        return _search_toolbox(query, limit)
    if normalized == "list":
        return _list_toolbox(category)
    if normalized == "call":
        return _call_toolbox(tool, arguments)

    raise ValueError("action must be one of: search, list, call")


@mcp.tool(annotations=COMMAND)
def run_command(
    argv: list[str],
    cwd: str = ".",
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run an arbitrary argv-style command inside the workspace.

    Use argv form, for example ["pytest", "-q"] or ["npm", "test"].
    Any executable available to the service account may be invoked. The
    systemd sandbox is the security boundary: persistent writes are confined
    to WORKSPACE_ROOT while the service remains non-root.
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
