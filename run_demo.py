"""Run the bounded VisualGuard OpenCV and witness-revocation demo."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import tempfile

from vision.opencv5_inspection import (
    CaptureReplayAnchorState,
    CaptureReplayLedger,
    CaptureReplayWitnessDomain,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessRevocationStore,
    CaptureReplayWitnessVerifier,
    View,
    frame,
    inspect,
    runtime_evidence,
    verify_consequence,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-key-2026-11"
KEY = b"visualguard-witness-fixture-revocation-key-01"
NOW = 2_000_000_000
WITNESS_DOMAIN = CaptureReplayWitnessDomain(
    application_id="visualguard-opencv5",
    purpose="capture-replay-ledger-attestation",
    ledger_id="visualguard-fixture-ledger-a",
    deployment_environment="local-fixture",
)


def witness_state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=2,
        rowset_sha256=hashlib.sha256(b"rowset-2").hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def signed_witness(epoch: int) -> dict[str, object]:
    payload = {
        "witness_version": 2,
        "provider_id": PROVIDER_ID,
        "key_id": KEY_ID,
        "revocation_epoch": epoch,
        "issued_at": NOW,
        **WITNESS_DOMAIN.as_dict(),
        "state": witness_state().as_dict(),
    }
    signature = hmac.new(
        KEY,
        CaptureReplayWitnessVerifier.canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()
    return {**payload, "signature": signature}


def view(alarm: bool, source: str, capture: str, *, visible: float = 1.0):
    return View(
        frame(alarm),
        visible_fraction=visible,
        source_id=source,
        capture_id=capture,
        captured_at=100.0,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="visualguard-demo-") as temporary:
        replay = CaptureReplayLedger(Path(temporary) / "capture.sqlite3")
        clear = inspect(
            {
                "front": view(False, "camera-front-v1", "clear-front"),
                "side": view(False, "camera-side-v1", "clear-side"),
            },
            captured_at=100,
            now=101,
            replay_ledger=replay,
        )
        occluded = inspect(
            {
                "front": view(
                    False,
                    "camera-front-v1",
                    "occluded-front",
                    visible=0.5,
                ),
                "side": view(False, "camera-side-v1", "occluded-side"),
            },
            captured_at=100,
            now=101,
            replay_ledger=replay,
        )
        alarm = inspect(
            {
                "front": view(False, "camera-front-v1", "alarm-front"),
                "side": view(True, "camera-side-v1", "alarm-side"),
            },
            captured_at=100,
            now=101,
            replay_ledger=replay,
        )
        replay.close()

        revocation_db = Path(temporary) / "revocations.sqlite3"
        verifier = CaptureReplayWitnessVerifier(
            provider_id=PROVIDER_ID,
            trusted_keys={KEY_ID: CaptureReplayWitnessKey(KEY)},
            expected_domain=WITNESS_DOMAIN,
            max_age_seconds=300,
        )
        with CaptureReplayWitnessRevocationStore(revocation_db) as store:
            appended = store.verify_and_append(
                verifier,
                signed_witness(0),
                local_state=witness_state(),
                minimum_sequence=2,
                now=NOW,
            )
            epoch = store.revoke(PROVIDER_ID, KEY_ID)

        output = {
            "runtime": runtime_evidence(),
            "input": "FIXED_SYNTHETIC_ARRAYS",
            "vision": {
                "clear": clear["decision"],
                "occluded": occluded["decision"],
                "alarm": alarm["decision"],
                "consequence_mismatch": verify_consequence(False, View(frame(True)))[
                    "closure"
                ],
            },
            "witness": {
                "append": appended["status"],
                "revocation_epoch": epoch,
                "authentication": "HMAC_SHA256_SHARED_SECRET_FIXTURE_ONLY",
                "domain": WITNESS_DOMAIN.as_dict(),
            },
            "live_external_witness": "NOT_RUN",
            "aws_live": "NOT_RUN",
            "camera_live": "NOT_RUN",
            "physical_action": "NONE",
        }
        print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
