#!/usr/bin/env python3
"""Verify ZZIK runtime dependencies without leaking cloud or database details."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

REQUIRED_REGION = "us-east-1"


def _result(name: str, ok: bool, code: str, message: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "code": code, "message": message}


def _check_database(
    database_url: str | None,
    connect: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if not database_url:
        return _result("database", False, "DB_CONFIG_MISSING", "DATABASE_URL 설정이 필요합니다.")

    try:
        if connect is None:
            import psycopg

            connect = psycopg.connect
        with connect(database_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
        if not row or row[0] != 1:
            return _result("database", False, "DB_CHECK_FAILED", "데이터베이스 확인 결과가 올바르지 않습니다.")
        return _result("database", True, "OK", "데이터베이스 연결을 확인했습니다.")
    except ImportError:
        return _result("database", False, "DB_DRIVER_MISSING", "PostgreSQL 드라이버 설치가 필요합니다.")
    except Exception:
        return _result("database", False, "DB_UNAVAILABLE", "데이터베이스 연결을 확인하지 못했습니다.")


def _check_s3(client_factory: Callable[[str], Any], bucket: str | None) -> dict[str, Any]:
    if not bucket:
        return _result("s3", False, "S3_CONFIG_MISSING", "S3_BUCKET 설정이 필요합니다.")
    try:
        client_factory("s3").head_bucket(Bucket=bucket)
        return _result("s3", True, "OK", "S3 버킷 접근을 확인했습니다.")
    except Exception:
        return _result("s3", False, "S3_ACCESS_FAILED", "S3 버킷 접근 권한을 확인하지 못했습니다.")


def _check_rekognition(client_factory: Callable[[str], Any]) -> dict[str, Any]:
    try:
        client_factory("rekognition").list_collections(MaxResults=1)
        return _result("rekognition", True, "OK", "Rekognition 호출 권한을 확인했습니다.")
    except Exception:
        return _result(
            "rekognition",
            False,
            "REKOGNITION_ACCESS_FAILED",
            "Rekognition 호출 권한을 확인하지 못했습니다.",
        )


def _check_sts(client_factory: Callable[[str], Any]) -> dict[str, Any]:
    try:
        response = client_factory("sts").get_caller_identity()
        if not response.get("Account") or not response.get("Arn"):
            return _result("sts", False, "STS_IDENTITY_INVALID", "실행 주체 정보를 확인하지 못했습니다.")
        return _result("sts", True, "OK", "인스턴스 역할 자격증명을 확인했습니다.")
    except Exception:
        return _result("sts", False, "STS_ACCESS_FAILED", "인스턴스 역할 자격증명을 확인하지 못했습니다.")


def run_checks(
    environ: Mapping[str, str] | None = None,
    *,
    db_connect: Callable[..., Any] | None = None,
    client_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Run all checks and return a sanitized, machine-readable report."""
    env = os.environ if environ is None else environ
    region = env.get("AWS_REGION", REQUIRED_REGION)
    checks = [_check_database(env.get("DATABASE_URL"), db_connect)]

    if region != REQUIRED_REGION:
        checks.extend(
            _result(name, False, "AWS_REGION_INVALID", f"AWS_REGION은 {REQUIRED_REGION}이어야 합니다.")
            for name in ("s3", "rekognition", "sts")
        )
    else:
        if client_factory is None:
            try:
                import boto3

                client_factory = lambda service: boto3.client(service, region_name=REQUIRED_REGION)
            except ImportError:
                checks.extend(
                    _result(name, False, "AWS_SDK_MISSING", "AWS SDK 설치가 필요합니다.")
                    for name in ("s3", "rekognition", "sts")
                )
                return {"ok": False, "checks": checks}

        checks.extend(
            (
                _check_s3(client_factory, env.get("S3_BUCKET")),
                _check_rekognition(client_factory),
                _check_sts(client_factory),
            )
        )

    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def main() -> int:
    logging.disable(logging.CRITICAL)
    report = run_checks()
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
