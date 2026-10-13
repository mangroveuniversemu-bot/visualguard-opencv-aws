"""Replay bounded witness-key rotation negative controls.

All keys are deterministic HMAC fixtures shipped with this package. This does
not establish independent key custody, managed KMS, network observation or a
live external witness.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision.opencv5_inspection import (
    CaptureReplayAnchorState,
    CaptureReplayWitnessError,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
OLD_KEY_ID = "fixture-hmac-key-2026-10"
NEW_KEY_ID = "fixture-hmac-key-2026-11"
UNKNOWN_KEY_ID = "fixture-hmac-key-unknown"
OLD_KEY = b"visualguard-witness-fixture-old-key-0001"
NEW_KEY = b"visualguard-witness-fixture-new-key-0002"
NOW = 2_000_000_000
NEW_ACTIVE_FROM = NOW - 60
OLD_RETIRE_AT = NOW + 60


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=2,
        rowset_sha256=hashlib.sha256(b"rowset-2").hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def sign(key_id: str, key: bytes, issued_at: int) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "issued_at": issued_at,
        "state": state().as_dict(),
    }
    signature = hmac.new(
        key,
        CaptureReplayWitnessVerifier.canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()
    return {**payload, "signature": signature}


def verifier() -> CaptureReplayWitnessVerifier:
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={
            OLD_KEY_ID: CaptureReplayWitnessKey(
                OLD_KEY, active_from=0, retire_at=OLD_RETIRE_AT
            ),
            NEW_KEY_ID: CaptureReplayWitnessKey(
                NEW_KEY, active_from=NEW_ACTIVE_FROM
            ),
        },
        max_age_seconds=300,
        max_future_skew_seconds=5,
    )


def verify(witness: object, now: int) -> str:
    try:
        return verifier().verify(
            witness,
            local_state=state(),
            minimum_sequence=2,
            now=now,
        )["key_id"]
    except CaptureReplayWitnessError as error:
        return str(error)


def exercise() -> dict[str, str]:
    substituted = sign(OLD_KEY_ID, OLD_KEY, NOW)
    substituted["key_id"] = NEW_KEY_ID
    before_activation = NEW_ACTIVE_FROM - 1
    return {
        "overlap_old": verify(sign(OLD_KEY_ID, OLD_KEY, NOW), NOW),
        "overlap_new": verify(sign(NEW_KEY_ID, NEW_KEY, NOW), NOW),
        "before_activation": verify(
            sign(NEW_KEY_ID, NEW_KEY, before_activation),
            before_activation,
        ),
        "retired_old": verify(
            sign(OLD_KEY_ID, OLD_KEY, OLD_RETIRE_AT),
            OLD_RETIRE_AT,
        ),
        "post_rotation_new": verify(
            sign(NEW_KEY_ID, NEW_KEY, OLD_RETIRE_AT),
            OLD_RETIRE_AT,
        ),
        "unknown": verify(sign(UNKNOWN_KEY_ID, NEW_KEY, NOW), NOW),
        "substituted": verify(substituted, NOW),
    }


def main() -> None:
    print(
        json.dumps(
            {
                "authentication": "HMAC_SHA256_SHARED_SECRET_FIXTURE_ONLY",
                "keyring": "BOUNDED_LOCAL_FIXTURE",
                "live_external_witness": "NOT_RUN",
                "result": exercise(),
                "seed": "NONE",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
