"""Replay durable witness algorithm/key-epoch migration controls."""

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
OLD = ("HMAC-SHA256", "fixture-hmac-sha256-epoch-0", 0)
NEW = ("HMAC-SHA512", "fixture-hmac-sha512-epoch-1", 1)
OLD_KEY = b"visualguard-algorithm-migration-old-key-01"
NEW_KEY = b"visualguard-algorithm-migration-new-key-02"
NOW = 2_000_000_000


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=2,
        rowset_sha256=hashlib.sha256(b"rowset-2").hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def domain(algorithm):
    return CaptureReplayWitnessDomain(
        application_id="visualguard-opencv5",
        purpose="capture-replay-ledger-attestation",
        ledger_id="visualguard-fixture-ledger-a",
        deployment_environment="local-fixture",
        signature_algorithm=algorithm,
    )


def witness(policy, key):
    algorithm, key_id, key_epoch = policy
    payload = {
        "witness_version": 3,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "key_epoch": key_epoch,
        "revocation_epoch": 0,
        "issued_at": NOW,
        **domain(algorithm).as_dict(),
        "state": state().as_dict(),
    }
    digest = hashlib.sha256 if algorithm == OLD[0] else hashlib.sha512
    return {
        **payload,
        "signature": hmac.new(
            key,
            CaptureReplayWitnessVerifier.canonical_payload(payload),
            digest,
        ).hexdigest(),
    }


def verifier(policy, key, *, versioned=True):
    algorithm, key_id, key_epoch = policy
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={key_id: CaptureReplayWitnessKey(key, key_epoch=key_epoch)},
        expected_domain=domain(algorithm),
        required_key_epoch=key_epoch if versioned else None,
        max_age_seconds=300,
    )


def append(store, policy, key):
    return store.verify_and_append(
        verifier(policy, key),
        witness(policy, key),
        local_state=state(),
        minimum_sequence=2,
        now=NOW,
    )


def migrate(store):
    return store.migrate_algorithm(
        expected_algorithm=OLD[0],
        expected_key_id=OLD[1],
        expected_key_epoch=OLD[2],
        replacement_algorithm=NEW[0],
        replacement_key_id=NEW[1],
        replacement_key_epoch=NEW[2],
    )


def error(callable_):
    try:
        callable_()
    except CaptureReplayWitnessError as exc:
        return str(exc)
    return "UNEXPECTED_ACCEPT"


def legacy_witness():
    payload = {
        "witness_version": 2,
        "provider_id": PROVIDER_ID,
        "key_id": OLD[1],
        "revocation_epoch": 0,
        "issued_at": NOW,
        **domain(OLD[0]).as_dict(),
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


def exercise():
    with tempfile.TemporaryDirectory(prefix="witness-algorithm-") as temporary:
        database = Path(temporary) / "algorithm.sqlite3"
        with CaptureReplayWitnessRevocationStore(database) as store:
            append(store, OLD, OLD_KEY)
            legacy_downgrade = error(
                lambda: store.verify_and_append(
                    verifier(OLD, OLD_KEY, versioned=False),
                    legacy_witness(),
                    local_state=state(),
                    minimum_sequence=2,
                    now=NOW,
                )
            )
            migrate(store)
        with CaptureReplayWitnessRevocationStore(database) as reopened:
            active_policy = reopened.active_algorithm_policy()
            old_after_restart = error(lambda: append(reopened, OLD, OLD_KEY))
            new_status = append(reopened, NEW, NEW_KEY)["status"]

        race_db = Path(temporary) / "race.sqlite3"
        with CaptureReplayWitnessRevocationStore(race_db) as store:
            append(store, OLD, OLD_KEY)
        barrier = threading.Barrier(2)

        def old_append():
            with CaptureReplayWitnessRevocationStore(race_db) as store:
                barrier.wait()
                try:
                    return append(store, OLD, OLD_KEY)["status"]
                except CaptureReplayWitnessError as exc:
                    return str(exc)

        def migration():
            with CaptureReplayWitnessRevocationStore(race_db) as store:
                barrier.wait()
                return list(migrate(store))

        with ThreadPoolExecutor(max_workers=2) as executor:
            old_future = executor.submit(old_append)
            migration_future = executor.submit(migration)
            race = {
                "old_append": old_future.result(timeout=10),
                "migration": migration_future.result(timeout=10),
            }
        with CaptureReplayWitnessRevocationStore(race_db) as reopened:
            race["active_policy"] = list(reopened.active_algorithm_policy())

    return {
        "active_policy_after_restart": list(active_policy),
        "old_algorithm_after_restart": old_after_restart,
        "new_algorithm_after_restart": new_status,
        "legacy_downgrade": legacy_downgrade,
        "append_vs_migration": race,
    }


def main():
    print(
        json.dumps(
            {
                **exercise(),
                "authentication": "HMAC_SHARED_SECRET_FIXTURE_ONLY",
                "live_external_witness": "NOT_RUN",
                "aws_live": "NOT_RUN",
                "kms_live": "NOT_RUN",
                "camera_live": "NOT_RUN",
                "physical_action": "NONE",
                "seed": "NONE",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
