"""Replayable local fixture for witness revocation epoch controls."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.opencv5_inspection import (  # noqa: E402
    CaptureReplayAnchorState,
    CaptureReplayWitnessError,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessRevocationStore,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-key-2026-11"
OTHER_KEY_ID = "fixture-hmac-key-2026-12"
KEY = b"visualguard-witness-fixture-revocation-key-01"
OTHER_KEY = b"visualguard-witness-fixture-revocation-key-02"
NOW = 2_000_000_000


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=2,
        rowset_sha256=hashlib.sha256(b"rowset-2").hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def sign(key_id: str, key: bytes, epoch: int) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "revocation_epoch": epoch,
        "issued_at": NOW,
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
            KEY_ID: CaptureReplayWitnessKey(KEY),
            OTHER_KEY_ID: CaptureReplayWitnessKey(OTHER_KEY),
        },
        max_age_seconds=300,
    )


def append(store, witness):
    try:
        return store.verify_and_append(
            verifier(),
            witness,
            local_state=state(),
            minimum_sequence=2,
            now=NOW,
        )
    except CaptureReplayWitnessError as error:
        return str(error)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "revocations.sqlite3"
        with CaptureReplayWitnessRevocationStore(database) as store:
            before = append(store, sign(KEY_ID, KEY, 0))
            revoked_epoch = store.revoke(PROVIDER_ID, KEY_ID)
        with CaptureReplayWitnessRevocationStore(database) as restarted:
            stale = append(restarted, sign(KEY_ID, KEY, 0))
            revoked = append(restarted, sign(KEY_ID, KEY, revoked_epoch))
            other = append(
                restarted,
                sign(OTHER_KEY_ID, OTHER_KEY, revoked_epoch),
            )
            evidence = {
                "authentication": "HMAC_SHA256_SHARED_SECRET_FIXTURE_ONLY",
                "live_external_witness": "NOT_RUN",
                "aws_live": "NOT_RUN",
                "camera_live": "NOT_RUN",
                "physical_action": "NONE",
                "revocation_epoch_after_restart": restarted.current_epoch(),
                "attestation_count": restarted.attestation_count(),
                "result": {
                    "before_revocation": before["status"],
                    "stale_after_restart": stale,
                    "revoked_current_epoch": revoked,
                    "other_key": other["key_id"],
                },
            }
        print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
