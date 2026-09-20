#!/usr/bin/env bash
set -Eeuo pipefail

RELEASE_ROOT="${RELEASE_ROOT:-/opt/zzik/releases}"
CURRENT_LINK="${CURRENT_LINK:-/opt/zzik/current}"
STATIC_LINK="${STATIC_LINK:-/var/www/zzik}"
TARGET_REVISION="${1:-}"

fail() {
    printf '[rollback] ERROR: %s\n' "$*" >&2
    exit 1
}

[[ "$EUID" -eq 0 ]] || fail "run as root"
[[ "$TARGET_REVISION" =~ ^[0-9a-f]{40}$ ]] || fail "pass the full 40-character commit SHA"
TARGET_RELEASE="$RELEASE_ROOT/$TARGET_REVISION"
[[ -d "$TARGET_RELEASE/backend" ]] || fail "target release does not exist"
[[ -f "$TARGET_RELEASE/frontend/dist/index.html" ]] || fail "target frontend build is missing"

ln -sfnT "$TARGET_RELEASE" "$CURRENT_LINK"
ln -sfnT "$TARGET_RELEASE/frontend/dist" "$STATIC_LINK"
systemctl restart zzik-api zzik-worker
systemctl reload nginx

printf '[rollback] application release restored to %s\n' "$TARGET_REVISION"
printf '[rollback] database schema was not downgraded; verify compatibility before serving traffic\n'
