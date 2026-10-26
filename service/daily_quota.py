"""Globally shared daily inference quota backed by DynamoDB."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

QUOTA_LIMIT = 5
QUOTA_TIME_ZONE = "Asia/Taipei"
DEFAULT_QUOTA_TABLE = "visualguard-daily-quota"


class DynamoClient(Protocol):
    def update_item(self, **kwargs) -> dict: ...


class QuotaReached(Exception):
    """The shared daily inference limit has already been consumed."""


class QuotaUnavailable(Exception):
    """The quota store failed; callers must stop without running inference."""


class DailyInferenceQuota:
    def __init__(
        self,
        client: DynamoClient,
        *,
        table_name: str = DEFAULT_QUOTA_TABLE,
        clock=time.time,
        limit: int = QUOTA_LIMIT,
    ):
        self.client = client
        self.table_name = table_name
        self.clock = clock
        self.limit = limit

    def claim(self) -> int:
        """Atomically consume one slot and return the number left today."""
        local_day = datetime.fromtimestamp(
            float(self.clock()), timezone(timedelta(hours=8), name=QUOTA_TIME_ZONE)
        ).date().isoformat()
        try:
            response = self.client.update_item(
                TableName=self.table_name,
                Key={"quota_date": {"S": local_day}},
                UpdateExpression="SET #calls = if_not_exists(#calls, :zero) + :one",
                ConditionExpression="attribute_not_exists(#calls) OR #calls < :limit",
                ExpressionAttributeNames={"#calls": "calls"},
                ExpressionAttributeValues={
                    ":zero": {"N": "0"},
                    ":one": {"N": "1"},
                    ":limit": {"N": str(self.limit)},
                },
                ReturnValues="UPDATED_NEW",
            )
            used = int(response["Attributes"]["calls"]["N"])
            if not 1 <= used <= self.limit:
                raise ValueError("quota counter returned an out-of-range value")
            return self.limit - used
        except Exception as error:
            code = (
                getattr(error, "response", {})
                .get("Error", {})
                .get("Code")
            )
            if code == "ConditionalCheckFailedException":
                raise QuotaReached from error
            if isinstance(error, (QuotaReached, QuotaUnavailable)):
                raise
            raise QuotaUnavailable from error
