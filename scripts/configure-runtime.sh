#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

RDS_HOST="${RDS_HOST:-zzik-db.cj24wem202yj.us-east-1.rds.amazonaws.com}"
RDS_PORT="${RDS_PORT:-5432}"
RDS_DATABASE="${RDS_DATABASE:-zzik}"
RDS_USER="${RDS_USER:-zzik}"
S3_BUCKET="${S3_BUCKET:-kmuct-ht-01-zzik-photos}"
AWS_REGION="${AWS_REGION:-us-east-1}"
RUNTIME_ENV="${RUNTIME_ENV:-/etc/zzik/runtime.env}"

fail() {
    printf '[configure-runtime] ERROR: %s\n' "$*" >&2
    exit 1
}

[[ "$EUID" -eq 0 ]] || fail "run with sudo"
[[ "$AWS_REGION" == "us-east-1" ]] || fail "AWS_REGION must be us-east-1"
[[ "$S3_BUCKET" == kmuct-ht-01-* ]] || fail "S3 bucket must use the kmuct-ht-01- prefix"
command -v python3 >/dev/null || fail "python3 is required to encode the database password"
command -v openssl >/dev/null || fail "openssl is required to generate SESSION_SECRET"

printf 'RDS password for %s (input hidden): ' "$RDS_USER"
IFS= read -r -s database_password
printf '\n'
[[ -n "$database_password" ]] || fail "database password cannot be empty"

encoded_password="$(printf '%s' "$database_password" | python3 -c 'import sys; from urllib.parse import quote; print(quote(sys.stdin.read(), safe=""))')"
unset database_password
session_secret="$(openssl rand -hex 32)"
temporary_file="$(mktemp)"
trap 'rm -f "$temporary_file"' EXIT

cat > "$temporary_file" <<EOF
DATABASE_URL=postgresql+psycopg://${RDS_USER}:${encoded_password}@${RDS_HOST}:${RDS_PORT}/${RDS_DATABASE}
STORAGE_BACKEND=s3
S3_BUCKET=${S3_BUCKET}
AWS_REGION=${AWS_REGION}
FACE_PROVIDER=rekognition
WORKER_CONCURRENCY=1
SESSION_SECRET=${session_secret}
EOF

install -d -o root -g root -m 0750 "$(dirname "$RUNTIME_ENV")"
install -o root -g root -m 0600 "$temporary_file" "$RUNTIME_ENV"
unset encoded_password session_secret

printf '[configure-runtime] wrote %s with mode 600\n' "$RUNTIME_ENV"
printf '[configure-runtime] no AWS access keys were written; the EC2 instance profile will be used\n'
