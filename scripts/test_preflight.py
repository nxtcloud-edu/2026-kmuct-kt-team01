from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

MODULE_PATH = pathlib.Path(__file__).with_name("preflight.py")
SPEC = importlib.util.spec_from_file_location("zzik_preflight", MODULE_PATH)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class FakeCursor:
    def __init__(self, row=(1,)):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query):
        if query != "SELECT 1":
            raise AssertionError("unexpected query")

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row=(1,)):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return FakeCursor(self.row)


class FakeAwsClient:
    def head_bucket(self, **_kwargs):
        return {}

    def list_collections(self, **_kwargs):
        return {"CollectionIds": []}

    def get_caller_identity(self):
        return {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:role/SafeRole"}


class FailingAwsClient:
    def __getattr__(self, _name):
        def fail(**_kwargs):
            raise RuntimeError(
                "AccessDenied arn:aws:iam::123456789012:role/private bucket kmu-proj-06-zzik secret-key"
            )

        return fail


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "DATABASE_URL": "postgresql://private-user:private-password@db.internal/zzik",
            "S3_BUCKET": "kmu-proj-06-zzik",
            "AWS_REGION": "us-east-1",
        }

    def test_all_checks_succeed_without_returning_identity(self):
        report = preflight.run_checks(
            self.env,
            db_connect=lambda *_args, **_kwargs: FakeConnection(),
            client_factory=lambda _service: FakeAwsClient(),
        )

        self.assertTrue(report["ok"])
        self.assertEqual([item["name"] for item in report["checks"]], ["database", "s3", "rekognition", "sts"])
        serialized = json.dumps(report)
        self.assertNotIn("123456789012", serialized)
        self.assertNotIn("arn:aws", serialized)
        self.assertNotIn("kmu-proj-06-zzik", serialized)
        self.assertNotIn("private-password", serialized)

    def test_sqlalchemy_psycopg_url_is_normalized_for_driver(self):
        captured = {}

        def connect(database_url, **kwargs):
            captured["database_url"] = database_url
            captured["connect_timeout"] = kwargs["connect_timeout"]
            return FakeConnection()

        result = preflight._check_database(
            "postgresql+psycopg://private-user:private-password@db.internal/zzik",
            connect,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            captured,
            {
                "database_url": "postgresql://private-user:private-password@db.internal/zzik",
                "connect_timeout": 5,
            },
        )

    def test_failures_are_sanitized(self):
        def fail_database(*_args, **_kwargs):
            raise RuntimeError("postgresql://private-user:private-password@db.internal/zzik")

        report = preflight.run_checks(
            self.env,
            db_connect=fail_database,
            client_factory=lambda _service: FailingAwsClient(),
        )

        self.assertFalse(report["ok"])
        serialized = json.dumps(report)
        for secret in ("private-password", "123456789012", "arn:aws", "kmu-proj-06-zzik", "secret-key"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(
            [item["code"] for item in report["checks"]],
            ["DB_UNAVAILABLE", "S3_ACCESS_FAILED", "REKOGNITION_ACCESS_FAILED", "STS_ACCESS_FAILED"],
        )

    def test_invalid_region_skips_all_aws_calls(self):
        called = False

        def client_factory(_service):
            nonlocal called
            called = True
            raise AssertionError("AWS client must not be created")

        report = preflight.run_checks(
            {**self.env, "AWS_REGION": "ap-northeast-2"},
            db_connect=lambda *_args, **_kwargs: FakeConnection(),
            client_factory=client_factory,
        )

        self.assertFalse(report["ok"])
        self.assertFalse(called)
        self.assertEqual(
            [item["code"] for item in report["checks"][1:]],
            ["AWS_REGION_INVALID", "AWS_REGION_INVALID", "AWS_REGION_INVALID"],
        )

    def test_main_prints_one_json_document_and_returns_failure(self):
        stream = io.StringIO()
        with patch.object(preflight, "run_checks", return_value={"ok": False, "checks": []}):
            with redirect_stdout(stream):
                exit_code = preflight.main()

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(stream.getvalue()), {"ok": False, "checks": []})
        self.assertEqual(stream.getvalue().count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
