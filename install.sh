#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
AGENT_WORKDIR="${AGENT_WORKDIR:-/home/ubuntu/projects/chatgptweb}"

"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .

mkdir -p "$AGENT_WORKDIR"

cat <<EOF
Installed chat-bridge-OCI for manual/development use.

Default agent work directory:
  $AGENT_WORKDIR

Start it with the privilege level you want the agent to have.

For full OCI administration:
  sudo env AGENT_WORKDIR="$AGENT_WORKDIR" MCP_HOST=127.0.0.1 MCP_PORT=8000 \
    $ROOT_DIR/.venv/bin/chat-bridge-oci

Then verify from another shell:
  MCP_URL=http://127.0.0.1:8000/mcp \
    $ROOT_DIR/.venv/bin/python $ROOT_DIR/smoke_test.py

For normal deployment, prefer bootstrap.sh so the root MCP service and
non-root OpenAI Secure MCP Tunnel service are installed consistently.

Do not open port 8000 publicly.
EOF
