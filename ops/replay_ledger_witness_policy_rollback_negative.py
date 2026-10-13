#!/usr/bin/env python3
"""Replayable local evidence for witness-policy rollback fail-closed behavior."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision.opencv5_inspection import (  # noqa: E402
    CaptureReplayAnchorState,
    CaptureReplayWitnessDomain,
    CaptureReplayWitnessError,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessRevocationStore,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
OLD_POLICY = ("HMAC-SHA256", "fixture-hmac-sha256-epoch-0", 0, 0)
NEW_POLICY = ("HMAC-SHA512", "fixture-hmac-sha512-epoch-1", 1, 1)
OLD_KEY = b"visualguard-policy-rollback-old-key-0001"
NEW_KEY = b"visualguard-policy-rollback-new-key-0002"
NOW = 2_000_000_100


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=3,
        rowset_sha256=hashlib.sha256(b"rollback-rowset-3").hexdigest(),
        policy_sha256="d" * 64,
        capture_schema_sha256="e" * 64,
        rowset_schema_sha256="f" * 64,
    )


def domain(algorithm: str) -> CaptureReplayWitnessDomain:
    return CaptureReplayWitnessDomain(
        application_id="visualguard-opencv5",
        purpose="capture-replay-ledger-attestation",
        ledger_id="visualguard-fixture-ledger-a",
        deployment_environment="local-fixture",
        signature_algorithm=algorithm,
    )


def witness(policy, key: bytes):
    algorithm, key_id, key_epoch, migration_epoch = policy
    payload = {
        "witness_version": 4,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "key_epoch": key_epoch,
        "migration_epoch": migration_epoch,
        "revocation_epoch": 0,
        "issued_at": NOW,
        **domain(algorithm).as_dict(),
        "state": state().as_dict(),
    }
    digest = hashlib.sha256 if algorithm == "HMAC-SHA256" else hashlib.sha512
    return {
        **payload,
        "signature": hmac.new(
            key,
            CaptureReplayWitnessVerifier.canonical_payload(payload),
            digest,
        ).hexdigest(),
    }


def verifier(policy, key: bytes):
    algorithm, key_id, key_epoch, migration_epoch = policy
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={key_id: CaptureReplayWitnessKey(key, key_epoch=key_epoch)},
        expected_domain=domain(algorithm),
        required_key_epoch=key_epoch,
        required_migration_epoch=migration_epoch,
        max_age_seconds=300,
    )


def append(store, policy, key: bytes):
    return store.verify_and_append(
        verifier(policy, key),
        witness(policy, key),
        local_state=state(),
        minimum_sequence=3,
        now=NOW,
    )


def migrate(store, expected, replacement):
    return store.migrate_algorithm(
        expected_algorithm=expected[0],
        expected_key_id=expected[1],
        expected_key_epoch=expected[2],
        expected_migration_epoch=expected[3],
        replacement_algorithm=replacement[0],
        replacement_key_id=replacement[1],
        replacement_key_epoch=replacement[2],
        replacement_migration_epoch=replacement[3],
    )


def error_name(operation):
    try:
        operation()
    except CaptureReplayWitnessError as error:
        return str(error)
    return "UNEXPECTED_SUCCESS"


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "rollback.sqlite3"
        with CaptureReplayWitnessRevocationStore(database) as store:
            append(store, OLD_POLICY, OLD_KEY)
            migrate(store, OLD_POLICY, NEW_POLICY)
        with CaptureReplayWitnessRevocationStore(database) as reopened:
            rollback_result = error_name(
                lambda: migrate(reopened, NEW_POLICY, OLD_POLICY)
            )
        with CaptureReplayWitnessRevocationStore(database) as reopened:
            stale_epoch = error_name(
                lambda: append(reopened, (*NEW_POLICY[:3], 0), NEW_KEY)
            )
            active_after_restart = list(reopened.active_algorithm_policy_state())

        race_database = Path(temporary) / "rollback-race.sqlite3"
        with CaptureReplayWitnessRevocationStore(race_database) as store:
            append(store, OLD_POLICY, OLD_KEY)
            migrate(store, OLD_POLICY, NEW_POLICY)
        barrier = threading.Barrier(2)

        def racing_append():
            with CaptureReplayWitnessRevocationStore(race_database) as store:
                barrier.wait()
                return append(store, NEW_POLICY, NEW_KEY)["status"]

        def racing_rollback():
            with CaptureReplayWitnessRevocationStore(race_database) as store:
                barrier.wait()
                return error_name(lambda: migrate(store, NEW_POLICY, OLD_POLICY))

        with ThreadPoolExecutor(max_workers=2) as executor:
            append_future = executor.submit(racing_append)
            rollback_future = executor.submit(racing_rollback)
            race_append = append_future.result(timeout=10)
            race_rollback = rollback_future.result(timeout=10)
        with CaptureReplayWitnessRevocationStore(race_database) as reopened:
            terminal_policy = list(reopened.active_algorithm_policy_state())
            attestation_count = reopened.attestation_count()

    evidence = {
        "status": "PASS",
        "mode": "LOCAL_DETERMINISTIC_HMAC_FIXTURE",
        "live_external_witness": "NOT_RUN",
        "asymmetric_signing": "NOT_RUN",
        "kms_live": "NOT_RUN",
        "aws_live": "NOT_RUN",
        "camera_live": "NOT_RUN",
        "distributed_multi_writer": "NOT_RUN",
        "active_policy_after_restart": active_after_restart,
        "rollback_result": rollback_result,
        "stale_epoch_after_restart": stale_epoch,
        "race": {
            "append": race_append,
            "rollback": race_rollback,
            "terminal_policy": terminal_policy,
            "attestation_count": attestation_count,
        },
    }
    expected_error = "REPLAY_LEDGER_WITNESS_POLICY_ROLLBACK"
    if not (
        rollback_result == expected_error
        and stale_epoch == "REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_STALE"
        and race_append == "APPENDED"
        and race_rollback == expected_error
        and terminal_policy == list(NEW_POLICY)
        and attestation_count == 2
    ):
        evidence["status"] = "FAIL"
        print(json.dumps(evidence, sort_keys=True))
        return 1
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
