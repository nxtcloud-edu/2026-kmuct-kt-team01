#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${S3_BUCKET:?S3_BUCKET is required}"
AWS_REGION="${AWS_REGION:-us-east-1}"
BACKUP_PREFIX="${1:-}"

[[ "$AWS_REGION" == "us-east-1" ]] || { printf 'AWS_REGION must be us-east-1\n' >&2; exit 1; }
[[ "$BACKUP_PREFIX" =~ ^system-backups/[0-9]{8}T[0-9]{6}Z$ ]] || {
    printf 'pass a system-backups/YYYYMMDDTHHMMSSZ prefix\n' >&2
    exit 1
}

PG_RESTORE_URL="${RESTORE_DATABASE_URL/postgresql+psycopg:/postgresql:}"
DATABASE_NAME="${PG_RESTORE_URL%%\?*}"
DATABASE_NAME="${DATABASE_NAME##*/}"
[[ "$DATABASE_NAME" == *_test || "$DATABASE_NAME" == *_e2e ]] || {
    printf 'restore is restricted to a database ending in _test or _e2e\n' >&2
    exit 1
}

for command_name in aws pg_restore sha256sum; do
    command -v "$command_name" >/dev/null || { printf '%s is required\n' "$command_name" >&2; exit 1; }
done

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
for file_name in database.dump database.dump.sha256; do
    aws s3 cp \
        --only-show-errors \
        --region "$AWS_REGION" \
        "s3://$S3_BUCKET/$BACKUP_PREFIX/$file_name" \
        "$WORK_DIR/$file_name"
done

(
    cd "$WORK_DIR"
    sha256sum --check database.dump.sha256
)

pg_restore \
    --dbname="$PG_RESTORE_URL" \
    --clean \
    --if-exists \
    --no-owner \
    --no-acl \
    --exit-on-error \
    "$WORK_DIR/database.dump"

printf 'restore_complete database_class=test prefix=%s\n' "$BACKUP_PREFIX"
