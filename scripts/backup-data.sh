#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${S3_BUCKET:?S3_BUCKET is required}"
AWS_REGION="${AWS_REGION:-us-east-1}"
[[ "$AWS_REGION" == "us-east-1" ]] || { printf 'AWS_REGION must be us-east-1\n' >&2; exit 1; }

for command_name in aws pg_dump sha256sum; do
    command -v "$command_name" >/dev/null || { printf '%s is required\n' "$command_name" >&2; exit 1; }
done

VERSIONING_STATUS="$(aws s3api get-bucket-versioning \
    --region "$AWS_REGION" \
    --bucket "$S3_BUCKET" \
    --query Status \
    --output text)"
[[ "$VERSIONING_STATUS" == "Enabled" ]] || {
    printf 'S3 bucket versioning must be enabled before backup\n' >&2
    exit 1
}

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PREFIX="system-backups/$TIMESTAMP"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
DATABASE_DUMP="$WORK_DIR/database.dump"
DATABASE_SHA="$WORK_DIR/database.dump.sha256"
OBJECT_MANIFEST="$WORK_DIR/object-versions.json"
PG_DATABASE_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

pg_dump \
    --dbname="$PG_DATABASE_URL" \
    --format=custom \
    --no-owner \
    --no-acl \
    --file="$DATABASE_DUMP"
(
    cd "$WORK_DIR"
    sha256sum database.dump > database.dump.sha256
)

aws s3api list-object-versions \
    --region "$AWS_REGION" \
    --bucket "$S3_BUCKET" \
    --output json > "$OBJECT_MANIFEST"

for file_name in database.dump database.dump.sha256 object-versions.json; do
    aws s3 cp \
        --only-show-errors \
        --region "$AWS_REGION" \
        --sse AES256 \
        "$WORK_DIR/$file_name" \
        "s3://$S3_BUCKET/$BACKUP_PREFIX/$file_name"
done

printf 'backup_complete prefix=%s\n' "$BACKUP_PREFIX"
