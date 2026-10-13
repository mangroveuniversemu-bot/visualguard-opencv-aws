"""Replayable local probe for revocation-list CAS, rollback, and append race."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import threading

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
KEY = b"visualguard-witness-fixture-revocation-key-01"
NOW = 2_000_000_200


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=4,
        rowset_sha256=hashlib.sha256(b"revocation-list-rowset-4").hexdigest(),
        policy_sha256="1" * 64,
        capture_schema_sha256="2" * 64,
        rowset_schema_sha256="3" * 64,
    )


def signed_witness(epoch: int) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": KEY_ID,
        "revocation_epoch": epoch,
        "issued_at": NOW,
        "state": state().as_dict(),
    }
    return {
        **payload,
        "signature": hmac.new(
            KEY,
            CaptureReplayWitnessVerifier.canonical_payload(payload),
            hashlib.sha256,
        ).hexdigest(),
    }


def verifier() -> CaptureReplayWitnessVerifier:
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={KEY_ID: CaptureReplayWitnessKey(KEY)},
        max_age_seconds=300,
    )


def append(store, epoch: int):
    return store.verify_and_append(
        verifier(),
        signed_witness(epoch),
        local_state=state(),
        minimum_sequence=4,
        now=NOW,
    )


def error_name(operation) -> str:
    try:
        operation()
    except CaptureReplayWitnessError as error:
        return str(error)
    return "UNEXPECTED_SUCCESS"


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "revocation-list.sqlite3"
        with CaptureReplayWitnessRevocationStore(database):
            pass
        barrier = threading.Barrier(2)

        def race_append():
            with CaptureReplayWitnessRevocationStore(database) as store:
                barrier.wait()
                try:
                    return append(store, 0)["status"]
                except CaptureReplayWitnessError as error:
                    return str(error)

        def race_revoke():
            with CaptureReplayWitnessRevocationStore(database) as store:
                barrier.wait()
                return store.cas_update_revocation_list(
                    expected_epoch=0,
                    replacement_epoch=1,
                    revoked_keys=((PROVIDER_ID, KEY_ID),),
                )[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            append_future = executor.submit(race_append)
            revoke_future = executor.submit(race_revoke)
            append_race = append_future.result(timeout=10)
            revocation_epoch = revoke_future.result(timeout=10)

        with CaptureReplayWitnessRevocationStore(database) as restarted:
            epoch, snapshot = restarted.revocation_list_state()
            rollback = error_name(
                lambda: restarted.cas_update_revocation_list(
                    expected_epoch=1,
                    replacement_epoch=2,
                    revoked_keys=((PROVIDER_ID, "replacement-only-key"),),
                )
            )
            revoked_current = error_name(lambda: append(restarted, 1))
            count = restarted.attestation_count()

        evidence = {
            "cut": (
                "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_EPOCH_ROLLBACK_"
                "CONCURRENCY_NEGATIVE001"
            ),
            "mode": "LOCAL_DETERMINISTIC_HMAC_SQLITE_FIXTURE",
            "live_external_witness": "NOT_RUN",
            "live_aws": "NOT_RUN",
            "seed": "NONE",
            "revocation_list_epoch_after_restart": epoch,
            "revocation_update_epoch": revocation_epoch,
            "revoked_keys_after_restart": [list(identity) for identity in snapshot],
            "attestation_count": count,
            "result": {
                "append_race": append_race,
                "rollback": rollback,
                "revoked_current_epoch": revoked_current,
            },
        }
        print(json.dumps(evidence, sort_keys=True))
        valid_append = {
            "APPENDED": 1,
            "REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE": 0,
        }
        return (
            0
            if (
                epoch == 1
                and revocation_epoch == 1
                and snapshot == ((PROVIDER_ID, KEY_ID),)
                and rollback == "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_ROLLBACK"
                and revoked_current == "REPLAY_LEDGER_WITNESS_KEY_REVOKED"
                and append_race in valid_append
                and count == valid_append[append_race]
            )
            else 1
        )


if __name__ == "__main__":
    raise SystemExit(main())
