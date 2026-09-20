#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
SOURCE_REPO="${SOURCE_REPO:-/opt/zzik/source}"
RELEASE_ROOT="${RELEASE_ROOT:-/opt/zzik/releases}"
CURRENT_LINK="${CURRENT_LINK:-/opt/zzik/current}"
STATIC_LINK="${STATIC_LINK:-/var/www/zzik}"
VENV_DIR="${VENV_DIR:-/opt/zzik/venv}"
PYTHON_BIN="${PYTHON_BIN:-python3.13}"
PREVIOUS_RELEASE=""
ACTIVATED=0

log() {
    printf '[deploy] %s\n' "$*"
}

fail() {
    printf '[deploy] ERROR: %s\n' "$*" >&2
    exit 1
}

rollback_on_error() {
    local exit_code=$?
    trap - ERR
    if [[ "$ACTIVATED" -eq 1 && -n "$PREVIOUS_RELEASE" && -d "$PREVIOUS_RELEASE" ]]; then
        log "deployment failed after activation; restoring previous application release"
        ln -sfnT "$PREVIOUS_RELEASE" "$CURRENT_LINK"
        if [[ -d "$PREVIOUS_RELEASE/frontend/dist" ]]; then
            ln -sfnT "$PREVIOUS_RELEASE/frontend/dist" "$STATIC_LINK"
        fi
        systemctl restart zzik-api zzik-worker || true
        log "application release restored; database migrations were not downgraded"
    fi
    exit "$exit_code"
}
trap rollback_on_error ERR

[[ "$EUID" -eq 0 ]] || fail "run as root so services and release links can be updated"
[[ -d "$SOURCE_REPO/.git" ]] || fail "SOURCE_REPO must be an existing Git clone"
command -v git >/dev/null || fail "git is required"
command -v npm >/dev/null || fail "Node.js 24 and npm are required"
command -v "$PYTHON_BIN" >/dev/null || fail "Python 3.13 is required"

if [[ -L "$CURRENT_LINK" ]]; then
    PREVIOUS_RELEASE="$(readlink -f "$CURRENT_LINK")"
fi

log "updating ${DEPLOY_BRANCH} with a fast-forward-only pull"
git -C "$SOURCE_REPO" switch "$DEPLOY_BRANCH"
git -C "$SOURCE_REPO" pull --ff-only origin "$DEPLOY_BRANCH"
REVISION="$(git -C "$SOURCE_REPO" rev-parse HEAD)"
RELEASE_DIR="$RELEASE_ROOT/$REVISION"

install -d -o zzik -g zzik "$RELEASE_ROOT"
if [[ ! -d "$RELEASE_DIR" ]]; then
    install -d -o zzik -g zzik "$RELEASE_DIR"
    git -C "$SOURCE_REPO" archive "$REVISION" | tar -x -C "$RELEASE_DIR"
    chown -R zzik:zzik "$RELEASE_DIR"
fi

[[ -f "$RELEASE_DIR/backend/requirements.txt" ]] || fail "backend/requirements.txt is missing"
[[ -f "$RELEASE_DIR/backend/alembic.ini" ]] || fail "backend/alembic.ini is missing"
[[ -f "$RELEASE_DIR/frontend/package-lock.json" ]] || fail "frontend/package-lock.json is missing"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

log "installing pinned Python dependencies"
"$VENV_DIR/bin/python" -m pip install --requirement "$RELEASE_DIR/backend/requirements.txt"

log "applying database migrations"
(
    cd "$RELEASE_DIR/backend"
    "$VENV_DIR/bin/python" -m alembic upgrade head
)

log "building frontend"
(
    cd "$RELEASE_DIR/frontend"
    npm ci
    npm run build
)
[[ -f "$RELEASE_DIR/frontend/dist/index.html" ]] || fail "frontend build did not produce dist/index.html"

log "activating release $REVISION"
ln -sfnT "$RELEASE_DIR" "$CURRENT_LINK"
ln -sfnT "$RELEASE_DIR/frontend/dist" "$STATIC_LINK"
ACTIVATED=1
systemctl restart zzik-api zzik-worker
systemctl reload nginx

log "deployment complete"
