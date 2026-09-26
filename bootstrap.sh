#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/chat-bridge-OCI"
AGENT_WORKDIR="/home/ubuntu/projects/chatgptweb"
TUNNEL_HOME="/var/lib/tunnel-client"
TUNNEL_ENV_DIR="/etc/chat-bridge-oci-tunnel"
TUNNEL_ENV_FILE="$TUNNEL_ENV_DIR/tunnel.env"
MCP_URL="http://127.0.0.1:8000/mcp"
HEALTH_URL="http://127.0.0.1:8080"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || die "sudo is required when not running as root"
  exec sudo -E bash "$0" "$@"
fi

command -v apt-get >/dev/null 2>&1 || die "This bootstrap currently supports Ubuntu/Debian images (apt-get required)."

TUNNEL_ID="${OPENAI_TUNNEL_ID:-}"
if [[ -z "$TUNNEL_ID" ]]; then
  [[ -r /dev/tty ]] || die "No TTY available. Set OPENAI_TUNNEL_ID and re-run."
  printf 'OpenAI Secure MCP Tunnel ID (example: tunnel_6ab...): ' >/dev/tty
  IFS= read -r TUNNEL_ID </dev/tty
fi
[[ "$TUNNEL_ID" =~ ^tunnel_[0-9a-f]{32}$ ]] || die "Invalid tunnel id. Expected tunnel_ followed by 32 lowercase hexadecimal characters."

RUNTIME_KEY="${CONTROL_PLANE_API_KEY:-}"
if [[ -z "$RUNTIME_KEY" ]]; then
  [[ -r /dev/tty ]] || die "No TTY available. Set CONTROL_PLANE_API_KEY securely and re-run."
  printf 'OpenAI tunnel runtime API key (hidden): ' >/dev/tty
  IFS= read -r -s RUNTIME_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[[ -n "$RUNTIME_KEY" ]] || die "Runtime API key must not be empty"
[[ "$RUNTIME_KEY" != *$'\n'* && "$RUNTIME_KEY" != *$'\r'* ]] || die "Runtime API key contains an invalid newline"

log "Installing OS dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl unzip python3 python3-venv python3-pip git util-linux
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || \
  die "Python 3.11+ is required. Use Ubuntu 24.04+ or Debian 12+."

log "Installing repository into $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [[ "$SCRIPT_DIR" != "$INSTALL_DIR" ]]; then
  find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  cp -a "$SCRIPT_DIR"/. "$INSTALL_DIR"/
fi
chown -R root:root "$INSTALL_DIR"

log "Creating default agent work directory"
if id -u ubuntu >/dev/null 2>&1; then
  install -d -o ubuntu -g ubuntu -m 0755 /home/ubuntu/projects
  install -d -o ubuntu -g ubuntu -m 0775 "$AGENT_WORKDIR"
else
  install -d -o root -g root -m 0755 "$AGENT_WORKDIR"
fi

log "Creating tunnel service user"
if ! id -u tunnelclient >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$TUNNEL_HOME" --shell /usr/sbin/nologin tunnelclient
fi
install -d -o tunnelclient -g tunnelclient -m 0750 "$TUNNEL_HOME"

log "Installing MCP Python service"
rm -rf "$INSTALL_DIR/.venv"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -e "$INSTALL_DIR"
chown -R root:root "$INSTALL_DIR/.venv"

log "Installing latest official OpenAI tunnel-client"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"; unset RUNTIME_KEY CONTROL_PLANE_API_KEY' EXIT
RELEASE_JSON="$TMP_DIR/release.json"
curl -fsSL \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  https://api.github.com/repos/openai/tunnel-client/releases/latest \
  -o "$RELEASE_JSON"

TAG="$(python3 - "$RELEASE_JSON" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    print(json.load(f)['tag_name'])
PY
)"

case "$(uname -m)" in
  x86_64|amd64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) die "Unsupported CPU architecture: $(uname -m)" ;;
esac

ASSET="tunnel-client-${TAG}-linux-${ARCH}.zip"
read -r ASSET_URL ASSET_DIGEST < <(python3 - "$RELEASE_JSON" "$ASSET" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    release = json.load(f)
name = sys.argv[2]
for asset in release.get('assets', []):
    if asset.get('name') == name:
        print(asset['browser_download_url'], asset.get('digest', ''))
        break
else:
    raise SystemExit(f'asset not found: {name}')
PY
)

ARCHIVE="$TMP_DIR/$ASSET"
curl -fL "$ASSET_URL" -o "$ARCHIVE"
if [[ "$ASSET_DIGEST" == sha256:* ]]; then
  printf '%s  %s\n' "${ASSET_DIGEST#sha256:}" "$ARCHIVE" | sha256sum -c -
fi
unzip -q "$ARCHIVE" -d "$TMP_DIR/tunnel-client"
TUNNEL_BIN="$(find "$TMP_DIR/tunnel-client" -type f -name tunnel-client -print -quit)"
[[ -n "$TUNNEL_BIN" ]] || die "tunnel-client binary not found in $ASSET"
install -o root -g root -m 0755 "$TUNNEL_BIN" /usr/local/bin/tunnel-client
/usr/local/bin/tunnel-client --version

log "Writing root OCI management MCP service"
cat >/etc/systemd/system/chat-bridge-oci.service <<EOF_UNIT
[Unit]
Description=ChatGPT OCI instance management agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$AGENT_WORKDIR
Environment=AGENT_WORKDIR=$AGENT_WORKDIR
Environment=HOME=/root
Environment=TMPDIR=/tmp
Environment=XDG_CACHE_HOME=/root/.cache
Environment=MCP_HOST=127.0.0.1
Environment=MCP_PORT=8000
Environment=MCP_URL=$MCP_URL
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$INSTALL_DIR/.venv/bin/chat-bridge-oci
# After= dependencies wait for this MCP protocol check, including at boot.
ExecStartPost=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/smoke_test.py --wait-seconds 60
TimeoutStartSec=75
Restart=on-failure
RestartSec=3
UMask=0022

[Install]
WantedBy=multi-user.target
EOF_UNIT

log "Writing tunnel credentials and systemd service"
install -d -o root -g tunnelclient -m 0750 "$TUNNEL_ENV_DIR"
quote_env() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}
umask 077
{
  printf 'CONTROL_PLANE_API_KEY=%s\n' "$(quote_env "$RUNTIME_KEY")"
  printf 'CONTROL_PLANE_TUNNEL_ID=%s\n' "$(quote_env "$TUNNEL_ID")"
  printf 'MCP_SERVER_URL=%s\n' "$(quote_env "$MCP_URL")"
  printf 'MCP_STARTUP_WAIT_TIMEOUT=%s\n' "$(quote_env '60s')"
  printf 'HEALTH_LISTEN_ADDR=%s\n' "$(quote_env '127.0.0.1:8080')"
} >"$TUNNEL_ENV_FILE"
chown root:tunnelclient "$TUNNEL_ENV_FILE"
chmod 0640 "$TUNNEL_ENV_FILE"

cat >/etc/systemd/system/chat-bridge-oci-tunnel.service <<EOF_UNIT
[Unit]
Description=OpenAI Secure MCP Tunnel for ChatGPT OCI management agent
Requires=chat-bridge-oci.service
After=network-online.target chat-bridge-oci.service
Wants=network-online.target

[Service]
Type=simple
User=tunnelclient
Group=tunnelclient
EnvironmentFile=$TUNNEL_ENV_FILE
ExecStart=/usr/local/bin/tunnel-client run --log.level=info --log.format=struct-text
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$TUNNEL_HOME
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictRealtime=true
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0077

[Install]
WantedBy=multi-user.target
EOF_UNIT

unset RUNTIME_KEY CONTROL_PLANE_API_KEY

log "Starting root management agent"
systemctl daemon-reload
systemctl enable chat-bridge-oci.service chat-bridge-oci-tunnel.service
# enable --now does not refresh an already active process. Stop the tunnel
# before restarting MCP so it cannot discover the backend while it is down.
systemctl stop chat-bridge-oci-tunnel.service
if ! systemctl restart chat-bridge-oci.service; then
  journalctl -u chat-bridge-oci.service -n 80 --no-pager >&2 || true
  die "MCP service startup or smoke test failed"
fi

systemctl restart chat-bridge-oci-tunnel.service

log "Waiting for Secure MCP Tunnel readiness"
READY=0
for _ in {1..45}; do
  if curl -fsS "$HEALTH_URL/readyz" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

if [[ "$READY" -ne 1 ]]; then
  journalctl -u chat-bridge-oci-tunnel.service -n 120 --no-pager >&2 || true
  die "Tunnel did not become ready within 45 seconds"
fi

curl -fsS "$HEALTH_URL/healthz" >/dev/null
curl -fsS "$HEALTH_URL/readyz" >/dev/null

log "Setup complete"
printf '%s\n' \
  "Agent service:    $(systemctl is-active chat-bridge-oci.service) / $(systemctl is-enabled chat-bridge-oci.service)" \
  "Tunnel service:   $(systemctl is-active chat-bridge-oci-tunnel.service) / $(systemctl is-enabled chat-bridge-oci-tunnel.service)" \
  "Agent privilege:  root" \
  "Tunnel ID:        $TUNNEL_ID" \
  "Default workdir:  $AGENT_WORKDIR" \
  "Local MCP:        $MCP_URL" \
  "Tunnel health:    $HEALTH_URL/readyz" \
  "" \
  "The MCP endpoint remains loopback-only. Do not open inbound TCP 8000."
