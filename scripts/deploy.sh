#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
SOURCE_REPO="${SOURCE_REPO:-/opt/zzik/source}"
RELEASE_ROOT="${RELEASE_ROOT:-/opt/zzik/releases}"
CURRENT_LINK="${CURRENT_LINK:-/opt/zzik/current}"
STATIC_LINK="${STATIC_LINK:-/var/www/zzik}"
VENV_DIR="${VENV_DIR:-/opt/zzik/venv}"
PYTHON_BIN="${PYTHON_BIN:-python3.13}"
RUNTIME_ENV="${RUNTIME_ENV:-/etc/zzik/runtime.env}"
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
    if [[ "$ACTIVATED" -eq 1 ]]; then
        if [[ -n "$PREVIOUS_RELEASE" && -d "$PREVIOUS_RELEASE" ]]; then
            log "deployment failed after activation; restoring previous application release"
            ln -sfnT "$PREVIOUS_RELEASE" "$CURRENT_LINK"
            if [[ -d "$PREVIOUS_RELEASE/frontend/dist" ]]; then
                ln -sfnT "$PREVIOUS_RELEASE/frontend/dist" "$STATIC_LINK"
            fi
            systemctl restart zzik-api zzik-worker || true
            log "application release restored; database migrations were not downgraded"
        else
            rm -f "$CURRENT_LINK" "$STATIC_LINK"
            systemctl stop zzik-api zzik-worker || true
            log "first release activation failed; incomplete links were removed"
        fi
    fi
    exit "$exit_code"
}
trap rollback_on_error ERR

[[ "$EUID" -eq 0 ]] || fail "run as root so services and release links can be updated"
[[ -d "$SOURCE_REPO/.git" ]] || fail "SOURCE_REPO must be an existing Git clone"
[[ -r "$RUNTIME_ENV" ]] || fail "RUNTIME_ENV must exist and be readable"
[[ "$(stat -c '%a' "$RUNTIME_ENV")" == "600" ]] || fail "RUNTIME_ENV permissions must be 600"
command -v git >/dev/null || fail "git is required"
command -v npm >/dev/null || fail "Node.js 24 and npm are required"
command -v "$PYTHON_BIN" >/dev/null || fail "Python 3.13 is required"

DATABASE_LINE="$(grep -m 1 '^DATABASE_URL=' "$RUNTIME_ENV" || true)"
[[ -n "$DATABASE_LINE" ]] || fail "DATABASE_URL is missing from RUNTIME_ENV"
DATABASE_URL="${DATABASE_LINE#DATABASE_URL=}"
DATABASE_URL="${DATABASE_URL%$'\r'}"
if [[ "$DATABASE_URL" == \"*\" || "$DATABASE_URL" == \'*\' ]]; then
    DATABASE_URL="${DATABASE_URL:1:${#DATABASE_URL}-2}"
fi
[[ -n "$DATABASE_URL" && "$DATABASE_URL" != *CHANGE_ME* ]] || fail "DATABASE_URL is not configured"
export DATABASE_URL

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

[[ -f "$RELEASE_DIR/requirements.txt" ]] || fail "requirements.txt is missing"
[[ -f "$RELEASE_DIR/alembic.ini" ]] || fail "alembic.ini is missing"
[[ -f "$RELEASE_DIR/frontend/package-lock.json" ]] || fail "frontend/package-lock.json is missing"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

log "installing pinned Python dependencies"
"$VENV_DIR/bin/python" -m pip install --requirement "$RELEASE_DIR/requirements.txt"

log "applying database migrations"
(
    cd "$RELEASE_DIR"
    "$VENV_DIR/bin/python" -m alembic -c alembic.ini upgrade head
)

log "building frontend"
(
    cd "$RELEASE_DIR/frontend"
    npm ci
    npm run build
)
[[ -f "$RELEASE_DIR/frontend/dist/index.html" ]] || fail "frontend build did not produce dist/index.html"

log "activating release $REVISION"
ACTIVATED=1
ln -sfnT "$RELEASE_DIR" "$CURRENT_LINK"
ln -sfnT "$RELEASE_DIR/frontend/dist" "$STATIC_LINK"
systemctl restart zzik-api zzik-worker
systemctl reload nginx

log "deployment complete"
