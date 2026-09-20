#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.13}"
NODE_BIN="${NODE_BIN:-node}"

log() {
    printf '[install-host] %s\n' "$*"
}

fail() {
    printf '[install-host] ERROR: %s\n' "$*" >&2
    exit 1
}

[[ "$EUID" -eq 0 ]] || fail "run as root"
[[ -r /etc/os-release ]] || fail "cannot identify the operating system"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "amzn" && "${VERSION_ID:-}" == "2023" ]] || fail "Amazon Linux 2023 is required"

command -v "$PYTHON_BIN" >/dev/null || fail "install Python 3.13 separately; do not replace the system python3 link"
PYTHON_VERSION="$($PYTHON_BIN --version 2>&1)"
[[ "$PYTHON_VERSION" == Python\ 3.13.* ]] || fail "Python 3.13 is required"

command -v "$NODE_BIN" >/dev/null || fail "install Node.js 24"
NODE_VERSION="$($NODE_BIN --version)"
[[ "$NODE_VERSION" == v24.* ]] || fail "Node.js 24 is required"

command -v nginx >/dev/null || fail "install nginx before running this script"
command -v git >/dev/null || fail "install git before running this script"

if ! getent group zzik >/dev/null; then
    groupadd --system zzik
fi
if ! id zzik >/dev/null 2>&1; then
    useradd --system --gid zzik --home-dir /opt/zzik --shell /sbin/nologin zzik
fi

install -d -o zzik -g zzik /opt/zzik /opt/zzik/releases /opt/zzik/source
install -d -o root -g zzik -m 0750 /etc/zzik
install -d -o root -g root /var/www

if [[ ! -x /opt/zzik/venv/bin/python ]]; then
    "$PYTHON_BIN" -m venv /opt/zzik/venv
fi
chown -R zzik:zzik /opt/zzik/venv

install -o root -g root -m 0644 "$REPO_ROOT/nginx.conf" /etc/nginx/nginx.conf
install -o root -g root -m 0644 "$REPO_ROOT/systemd/zzik-api.service" /etc/systemd/system/zzik-api.service
install -o root -g root -m 0644 "$REPO_ROOT/systemd/zzik-worker.service" /etc/systemd/system/zzik-worker.service
install -o root -g root -m 0600 "$REPO_ROOT/infra/runtime.env.example" /etc/zzik/runtime.env.example

if [[ -f /etc/zzik/runtime.env ]]; then
    chown root:root /etc/zzik/runtime.env
    chmod 600 /etc/zzik/runtime.env
else
    log "create /etc/zzik/runtime.env from the installed example before starting ZZIK services"
fi

nginx -t
systemctl daemon-reload
systemctl enable nginx zzik-api zzik-worker

log "host configuration installed"
log "services were enabled but not started; configure runtime.env and deploy a release first"
