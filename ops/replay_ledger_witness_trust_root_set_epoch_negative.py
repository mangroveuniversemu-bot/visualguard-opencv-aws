"""Replayable trust-root-set epoch, rollback, restart, and append-race probe."""

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
OLD_KEY_ID = "fixture-hmac-root-2026-11"
NEW_KEY_ID = "fixture-hmac-root-2026-12"
OLD_KEY = b"visualguard-witness-fixture-trust-root-key-01"
NEW_KEY = b"visualguard-witness-fixture-trust-root-key-02"
NOW = 2_000_000_300


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=5,
        rowset_sha256=hashlib.sha256(b"trust-root-rowset-5").hexdigest(),
        policy_sha256="4" * 64,
        capture_schema_sha256="5" * 64,
        rowset_schema_sha256="6" * 64,
    )


def signed_witness(epoch: int) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": OLD_KEY_ID,
        "trust_root_epoch": epoch,
        "revocation_epoch": 0,
        "issued_at": NOW,
        "state": state().as_dict(),
    }
    return {
        **payload,
        "signature": hmac.new(
            OLD_KEY,
            CaptureReplayWitnessVerifier.canonical_payload(payload),
            hashlib.sha256,
        ).hexdigest(),
    }


def verifier() -> CaptureReplayWitnessVerifier:
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={
            OLD_KEY_ID: CaptureReplayWitnessKey(OLD_KEY),
            NEW_KEY_ID: CaptureReplayWitnessKey(NEW_KEY),
        },
        max_age_seconds=300,
    )


def append(store, epoch: int):
    return store.verify_and_append(
        verifier(),
        signed_witness(epoch),
        local_state=state(),
        minimum_sequence=5,
        now=NOW,
    )


def error_name(operation) -> str:
    try:
        operation()
    except CaptureReplayWitnessError as error:
        return str(error)
    return "UNEXPECTED_SUCCESS"


def main() -> int:
    old_roots = ((PROVIDER_ID, OLD_KEY_ID),)
    new_roots = ((PROVIDER_ID, NEW_KEY_ID),)
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "trust-root-set.sqlite3"
        with CaptureReplayWitnessRevocationStore(database) as store:
            store.cas_update_trust_root_set(
                expected_epoch=0,
                replacement_epoch=1,
                trusted_roots=old_roots,
            )
        barrier = threading.Barrier(2)

        def race_append():
            with CaptureReplayWitnessRevocationStore(database) as store:
                barrier.wait()
                try:
                    return append(store, 1)["status"]
                except CaptureReplayWitnessError as error:
                    return str(error)

        def race_rotate():
            with CaptureReplayWitnessRevocationStore(database) as store:
                barrier.wait()
                return store.cas_update_trust_root_set(
                    expected_epoch=1,
                    replacement_epoch=2,
                    trusted_roots=new_roots,
                )[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            append_future = executor.submit(race_append)
            rotate_future = executor.submit(race_rotate)
            append_race = append_future.result(timeout=10)
            rotation_epoch = rotate_future.result(timeout=10)

        with CaptureReplayWitnessRevocationStore(database) as restarted:
            epoch, roots = restarted.trust_root_set_state()
            snapshot_rollback = error_name(
                lambda: restarted.cas_update_trust_root_set(
                    expected_epoch=2,
                    replacement_epoch=3,
                    trusted_roots=old_roots,
                )
            )
            current_epoch_old_root = error_name(lambda: append(restarted, 2))
            count = restarted.attestation_count()

        evidence = {
            "cut": (
                "REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_EPOCH_ROLLBACK_"
                "CONCURRENCY_NEGATIVE001"
            ),
            "mode": "LOCAL_DETERMINISTIC_HMAC_SQLITE_FIXTURE",
            "live_external_witness": "NOT_RUN",
            "live_aws": "NOT_RUN",
            "seed": "NONE",
            "trust_root_epoch_after_restart": epoch,
            "rotation_epoch": rotation_epoch,
            "trusted_roots_after_restart": [list(identity) for identity in roots],
            "attestation_count": count,
            "result": {
                "append_race": append_race,
                "snapshot_rollback": snapshot_rollback,
                "removed_root_current_epoch": current_epoch_old_root,
            },
        }
        print(json.dumps(evidence, sort_keys=True))
        valid_append = {
            "APPENDED": 1,
            "REPLAY_LEDGER_WITNESS_TRUST_ROOT_EPOCH_STALE": 0,
        }
        return (
            0
            if (
                epoch == 2
                and rotation_epoch == 2
                and roots == new_roots
                and snapshot_rollback == "REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_ROLLBACK"
                and current_epoch_old_root == "REPLAY_LEDGER_WITNESS_TRUST_ROOT_UNKNOWN"
                and append_race in valid_append
                and count == valid_append[append_race]
            )
            else 1
        )


if __name__ == "__main__":
    raise SystemExit(main())
