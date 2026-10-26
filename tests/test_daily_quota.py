"""The AWS inference quota is shared, atomic, Taiwan-day scoped and fail-closed."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from service.app import Service
from service.daily_quota import (
    DEFAULT_QUOTA_TABLE,
    QUOTA_LIMIT,
    DailyInferenceQuota,
    QuotaReached,
    QuotaUnavailable,
)


class FakeClientError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class AtomicMemoryDynamo:
    def __init__(self):
        self.lock = threading.Lock()
        self.items: dict[str, int] = {}
        self.requests: list[dict] = []

    def update_item(self, **kwargs):
        with self.lock:
            self.requests.append(kwargs)
            day = kwargs["Key"]["quota_date"]["S"]
            current = self.items.get(day, 0)
            limit = int(kwargs["ExpressionAttributeValues"][":limit"]["N"])
            if current >= limit:
                raise FakeClientError("ConditionalCheckFailedException")
            current += 1
            self.items[day] = current
            return {"Attributes": {"calls": {"N": str(current)}}}


class DailyInferenceQuotaTests(unittest.TestCase):
    def test_atomic_updates_allow_exactly_five_concurrent_claims(self):
        client = AtomicMemoryDynamo()
        quota = DailyInferenceQuota(
            client,
            clock=lambda: datetime(2026, 10, 26, 16, tzinfo=timezone.utc).timestamp(),
        )

        def claim():
            try:
                return quota.claim()
            except QuotaReached:
                return "LIMIT"

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: claim(), range(40)))

        self.assertEqual(sum(result != "LIMIT" for result in results), QUOTA_LIMIT)
        self.assertEqual(results.count("LIMIT"), 35)
        self.assertEqual(client.items, {"2026-10-27": QUOTA_LIMIT})
        self.assertEqual(len(client.requests), 40)
        for request in client.requests:
            self.assertEqual(request["TableName"], DEFAULT_QUOTA_TABLE)
            self.assertIn("#calls < :limit", request["ConditionExpression"])
            self.assertEqual(request["ReturnValues"], "UPDATED_NEW")

    def test_store_failure_is_fail_closed(self):
        class BrokenClient:
            def update_item(self, **_):
                raise FakeClientError("AccessDeniedException")

        quota = DailyInferenceQuota(BrokenClient())
        with self.assertRaises(QuotaUnavailable):
            quota.claim()

    def test_http_service_consumes_global_slots_and_blocks_the_sixth_request(self):
        client = AtomicMemoryDynamo()
        quota = DailyInferenceQuota(
            client,
            clock=lambda: datetime(2026, 10, 26, 16, tzinfo=timezone.utc).timestamp(),
        )
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            service = Service(Path(tmp) / "ledger.sqlite3", daily_quota=quota)
            try:
                health_status, _, _ = service.handle("GET", "/healthz")
                self.assertEqual(health_status, 200)
                self.assertEqual(client.requests, [])

                remaining = []
                for _ in range(QUOTA_LIMIT):
                    status, headers, payload = service.handle(
                        "POST", "/v1/inspect", b"not json"
                    )
                    self.assertEqual(status, 400)
                    remaining.append(int(headers["X-Daily-Quota-Remaining"]))
                    self.assertEqual(headers["X-Daily-Quota-Limit"], "5")
                    self.assertEqual(
                        headers["X-Daily-Quota-Reset-Timezone"], "Asia/Taipei"
                    )
                    self.assertEqual(json.loads(payload)["error"], "INVALID_JSON")
                self.assertEqual(remaining, [4, 3, 2, 1, 0])

                status, headers, payload = service.handle(
                    "POST", "/v1/inspect", b"{}"
                )
                result = json.loads(payload)
                self.assertEqual(status, 429)
                self.assertEqual(result["error"], "DAILY_INFERENCE_LIMIT_REACHED")
                self.assertEqual(result["decision"], "STOP")
                self.assertEqual(headers["X-Daily-Quota-Remaining"], "0")
                self.assertEqual(client.items["2026-10-27"], QUOTA_LIMIT)
            finally:
                service.close()

    def test_quota_database_error_returns_503_without_running_inference(self):
        class BrokenClient:
            def update_item(self, **_):
                raise FakeClientError("AccessDeniedException")

        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            service = Service(
                Path(tmp) / "ledger.sqlite3", daily_quota=DailyInferenceQuota(BrokenClient())
            )
            try:
                status, _, payload = service.handle("POST", "/v1/inspect", b"{}")
            finally:
                service.close()

        result = json.loads(payload)
        self.assertEqual(status, 503)
        self.assertEqual(result["error"], "DAILY_QUOTA_UNAVAILABLE")
        self.assertEqual(result["decision"], "STOP")
        self.assertEqual(result["follow_up"]["planned_action"], "HOLD_AUTOMATION")


if __name__ == "__main__":
    unittest.main()
