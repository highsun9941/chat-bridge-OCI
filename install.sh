#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-/home/ubuntu/projects/chatgptweb}"

"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .

mkdir -p "$WORKSPACE_ROOT"

cat <<EOF
Installed chat-bridge-OCI.

Workspace:
  $WORKSPACE_ROOT

Start it with:
  WORKSPACE_ROOT="$WORKSPACE_ROOT" MCP_HOST=127.0.0.1 MCP_PORT=8000 \
    $ROOT_DIR/.venv/bin/chat-bridge-oci

Then verify from another shell:
  MCP_URL=http://127.0.0.1:8000/mcp \
    $ROOT_DIR/.venv/bin/python $ROOT_DIR/smoke_test.py

Do not open port 8000 publicly. Prefer OpenAI Secure MCP Tunnel.
EOF
