"""Negative controls for monotonic witness-policy migration epochs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from vision.opencv5_inspection import (
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


def signed_witness(policy, key: bytes):
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
        signed_witness(policy, key),
        local_state=state(),
        minimum_sequence=3,
        now=NOW,
    )


def migrate_forward(store):
    return store.migrate_algorithm(
        expected_algorithm=OLD_POLICY[0],
        expected_key_id=OLD_POLICY[1],
        expected_key_epoch=OLD_POLICY[2],
        expected_migration_epoch=OLD_POLICY[3],
        replacement_algorithm=NEW_POLICY[0],
        replacement_key_id=NEW_POLICY[1],
        replacement_key_epoch=NEW_POLICY[2],
        replacement_migration_epoch=NEW_POLICY[3],
    )


def rollback(store):
    return store.migrate_algorithm(
        expected_algorithm=NEW_POLICY[0],
        expected_key_id=NEW_POLICY[1],
        expected_key_epoch=NEW_POLICY[2],
        expected_migration_epoch=NEW_POLICY[3],
        replacement_algorithm=OLD_POLICY[0],
        replacement_key_id=OLD_POLICY[1],
        replacement_key_epoch=OLD_POLICY[2],
        replacement_migration_epoch=OLD_POLICY[3],
    )


class ExternalWitnessPolicyRollbackCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "rollback.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def migrate(self) -> None:
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(append(store, OLD_POLICY, OLD_KEY)["status"], "APPENDED")
            self.assertEqual(migrate_forward(store), NEW_POLICY[:3])

    def test_legacy_policy_schema_is_upgraded_with_epoch_zero(self):
        connection = sqlite3.connect(self.database)
        connection.execute(
            "CREATE TABLE replay_ledger_witness_algorithm_policy ("
            "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "signature_algorithm TEXT NOT NULL, key_id TEXT NOT NULL, "
            "key_epoch INTEGER NOT NULL CHECK (key_epoch >= 0))"
        )
        connection.execute(
            "INSERT INTO replay_ledger_witness_algorithm_policy VALUES (1, ?, ?, ?)",
            OLD_POLICY[:3],
        )
        connection.commit()
        connection.close()
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(reopened.active_algorithm_policy_state(), OLD_POLICY)

    def test_rollback_is_rejected_and_epoch_persists_after_restart(self):
        self.migrate()
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_POLICY_ROLLBACK$",
            ):
                rollback(store)
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(reopened.active_algorithm_policy_state(), NEW_POLICY)

    def test_stale_epoch_signature_is_rejected_after_restart(self):
        self.migrate()
        stale_policy = (*NEW_POLICY[:3], 0)
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_STALE$",
            ):
                append(reopened, stale_policy, NEW_KEY)
            self.assertEqual(reopened.attestation_count(), 1)

    def test_v3_signature_is_rejected_once_migration_epoch_advances(self):
        self.migrate()
        payload = {
            "witness_version": 3,
            "provider_id": PROVIDER_ID,
            "key_id": NEW_POLICY[1],
            "key_epoch": NEW_POLICY[2],
            "revocation_epoch": 0,
            "issued_at": NOW,
            **domain(NEW_POLICY[0]).as_dict(),
            "state": state().as_dict(),
        }
        witness = {
            **payload,
            "signature": hmac.new(
                NEW_KEY,
                CaptureReplayWitnessVerifier.canonical_payload(payload),
                hashlib.sha512,
            ).hexdigest(),
        }
        old_verifier = CaptureReplayWitnessVerifier(
            provider_id=PROVIDER_ID,
            trusted_keys={
                NEW_POLICY[1]: CaptureReplayWitnessKey(NEW_KEY, key_epoch=NEW_POLICY[2])
            },
            expected_domain=domain(NEW_POLICY[0]),
            required_key_epoch=NEW_POLICY[2],
            max_age_seconds=300,
        )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_REQUIRED$",
            ):
                reopened.verify_and_append(
                    old_verifier,
                    witness,
                    local_state=state(),
                    minimum_sequence=3,
                    now=NOW,
                )

    def test_append_and_rollback_race_has_one_terminal_policy(self):
        self.migrate()
        barrier = threading.Barrier(2)

        def current_append():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                return append(store, NEW_POLICY, NEW_KEY)["status"]

        def rollback_attempt():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                try:
                    rollback(store)
                except CaptureReplayWitnessError as error:
                    return str(error)
                return "UNEXPECTED_SUCCESS"

        with ThreadPoolExecutor(max_workers=2) as executor:
            append_future = executor.submit(current_append)
            rollback_future = executor.submit(rollback_attempt)
            self.assertEqual(append_future.result(timeout=10), "APPENDED")
            self.assertEqual(
                rollback_future.result(timeout=10),
                "REPLAY_LEDGER_WITNESS_POLICY_ROLLBACK",
            )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(reopened.active_algorithm_policy_state(), NEW_POLICY)
            self.assertEqual(reopened.attestation_count(), 2)

    def test_replayable_probe_reports_rollback_restart_and_race(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_policy_rollback_negative.py"
        )
        probe = subprocess.run(
            [sys.executable, script],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        evidence = json.loads(probe.stdout)
        self.assertEqual(evidence["live_external_witness"], "NOT_RUN")
        self.assertEqual(evidence["aws_live"], "NOT_RUN")
        self.assertEqual(evidence["active_policy_after_restart"], list(NEW_POLICY))
        self.assertEqual(
            evidence["rollback_result"],
            "REPLAY_LEDGER_WITNESS_POLICY_ROLLBACK",
        )
        self.assertEqual(
            evidence["stale_epoch_after_restart"],
            "REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_STALE",
        )


if __name__ == "__main__":
    unittest.main()
