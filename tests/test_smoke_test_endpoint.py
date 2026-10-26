"""The public endpoint smoke test must cover the judge UI and API together."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from ops import smoke_test_endpoint
from service.app import Service
from service.daily_quota import DailyInferenceQuota


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], payload: bytes):
        self.status = status
        self.headers = headers
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class PublicEndpointSmokeTest(unittest.TestCase):
    def test_judge_ui_and_unsigned_api_smoke_use_one_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = Service(Path(tmp) / "ledger.sqlite3")
            requests = []

            def urlopen(request, timeout=60):
                requests.append(request)
                self.assertIsNone(request.get_header("Authorization"))
                status, headers, payload = service.handle(
                    request.get_method(),
                    urlsplit(request.full_url).path,
                    request.data or b"",
                )
                return FakeResponse(status, headers, payload)

            try:
                with patch.object(smoke_test_endpoint.urllib.request, "urlopen", urlopen):
                    report = smoke_test_endpoint.run(
                        "https://judge.example", expected_environment="LOCAL"
                    )
            finally:
                service.close()

        self.assertEqual(report["status"], "PASS")
        checks = {item["check"]: item for item in report["checks"]}
        self.assertEqual(checks["public_ui"]["status"], "PASS")
        self.assertEqual(checks["public_ui_sample_catalog"]["sample_count"], 8)
        self.assertEqual(len(requests), 11)

    def test_public_aws_smoke_uses_one_inference_slot_and_checks_quota_headers(self):
        class QuotaClient:
            def __init__(self):
                self.calls = 0

            def update_item(self, **_):
                self.calls += 1
                return {"Attributes": {"calls": {"N": str(self.calls)}}}

        with tempfile.TemporaryDirectory() as tmp:
            client = QuotaClient()
            service = Service(
                Path(tmp) / "ledger.sqlite3",
                daily_quota=DailyInferenceQuota(client),
            )
            requests = []

            def urlopen(request, timeout=60):
                requests.append(request)
                self.assertIsNone(request.get_header("Authorization"))
                status, headers, payload = service.handle(
                    request.get_method(),
                    urlsplit(request.full_url).path,
                    request.data or b"",
                )
                return FakeResponse(status, headers, payload)

            try:
                with patch.dict(
                    os.environ,
                    {"AWS_LAMBDA_FUNCTION_NAME": "visualguard-inspector"},
                ), patch.object(
                    smoke_test_endpoint.urllib.request, "urlopen", urlopen
                ):
                    report = smoke_test_endpoint.run(
                        "https://judge.example", expected_environment="AWS_LAMBDA"
                    )
            finally:
                service.close()

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["inspection_requests_used"], 1)
        self.assertEqual(report["quota_evidence"]["limit"], 5)
        self.assertEqual(report["quota_evidence"]["remaining_after_smoke"], 4)
        self.assertEqual(sum(req.get_method() == "POST" for req in requests), 1)


if __name__ == "__main__":
    unittest.main()
