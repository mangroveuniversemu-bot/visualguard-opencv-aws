"""Negative controls for durable witness algorithm/key-epoch migration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
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
OLD_KEY_ID = "fixture-hmac-sha256-epoch-0"
NEW_KEY_ID = "fixture-hmac-sha512-epoch-1"
OLD_KEY = b"visualguard-algorithm-migration-old-key-01"
NEW_KEY = b"visualguard-algorithm-migration-new-key-02"
NOW = 2_000_000_000
OLD_ALGORITHM = "HMAC-SHA256"
NEW_ALGORITHM = "HMAC-SHA512"


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=2,
        rowset_sha256=hashlib.sha256(b"rowset-2").hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def domain(algorithm: str) -> CaptureReplayWitnessDomain:
    return CaptureReplayWitnessDomain(
        application_id="visualguard-opencv5",
        purpose="capture-replay-ledger-attestation",
        ledger_id="visualguard-fixture-ledger-a",
        deployment_environment="local-fixture",
        signature_algorithm=algorithm,
    )


def signed_witness(
    algorithm: str,
    key_id: str,
    key: bytes,
    key_epoch: int,
    migration_epoch: int | None = None,
):
    payload = {
        "witness_version": 4 if migration_epoch is not None else 3,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "key_epoch": key_epoch,
        "revocation_epoch": 0,
        "issued_at": NOW,
        **domain(algorithm).as_dict(),
        "state": state().as_dict(),
    }
    if migration_epoch is not None:
        payload["migration_epoch"] = migration_epoch
    digest = hashlib.sha256 if algorithm == OLD_ALGORITHM else hashlib.sha512
    return {
        **payload,
        "signature": hmac.new(
            key,
            CaptureReplayWitnessVerifier.canonical_payload(payload),
            digest,
        ).hexdigest(),
    }


def verifier(
    algorithm: str,
    key_id: str,
    key: bytes,
    key_epoch: int,
    migration_epoch: int | None = None,
):
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={key_id: CaptureReplayWitnessKey(key, key_epoch=key_epoch)},
        expected_domain=domain(algorithm),
        required_key_epoch=key_epoch,
        required_migration_epoch=migration_epoch,
        max_age_seconds=300,
    )


def append(store, algorithm, key_id, key, key_epoch, migration_epoch=None):
    return store.verify_and_append(
        verifier(algorithm, key_id, key, key_epoch, migration_epoch),
        signed_witness(algorithm, key_id, key, key_epoch, migration_epoch),
        local_state=state(),
        minimum_sequence=2,
        now=NOW,
    )


def migrate(store):
    return store.migrate_algorithm(
        expected_algorithm=OLD_ALGORITHM,
        expected_key_id=OLD_KEY_ID,
        expected_key_epoch=0,
        replacement_algorithm=NEW_ALGORITHM,
        replacement_key_id=NEW_KEY_ID,
        replacement_key_epoch=1,
    )


class ExternalWitnessAlgorithmMigrationCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "algorithm.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def bootstrap(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            result = append(store, OLD_ALGORITHM, OLD_KEY_ID, OLD_KEY, 0)
            self.assertEqual(result["status"], "APPENDED")
            self.assertEqual(
                store.active_algorithm_policy(),
                (OLD_ALGORITHM, OLD_KEY_ID, 0),
            )

    def test_migration_persists_and_only_new_policy_is_accepted_after_restart(self):
        self.bootstrap()
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(migrate(store), (NEW_ALGORITHM, NEW_KEY_ID, 1))
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(
                reopened.active_algorithm_policy(),
                (NEW_ALGORITHM, NEW_KEY_ID, 1),
            )
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_ALGORITHM_POLICY_MISMATCH$",
            ):
                append(reopened, OLD_ALGORITHM, OLD_KEY_ID, OLD_KEY, 0)
            accepted = append(reopened, NEW_ALGORITHM, NEW_KEY_ID, NEW_KEY, 1, 1)
            self.assertEqual(accepted["status"], "APPENDED")
            self.assertEqual(accepted["key_epoch"], 1)

    def test_legacy_v2_downgrade_is_rejected_after_policy_initialization(self):
        self.bootstrap()
        payload = {
            "witness_version": 2,
            "provider_id": PROVIDER_ID,
            "key_id": OLD_KEY_ID,
            "revocation_epoch": 0,
            "issued_at": NOW,
            **domain(OLD_ALGORITHM).as_dict(),
            "state": state().as_dict(),
        }
        legacy = {
            **payload,
            "signature": hmac.new(
                OLD_KEY,
                CaptureReplayWitnessVerifier.canonical_payload(payload),
                hashlib.sha256,
            ).hexdigest(),
        }
        legacy_verifier = CaptureReplayWitnessVerifier(
            provider_id=PROVIDER_ID,
            trusted_keys={OLD_KEY_ID: CaptureReplayWitnessKey(OLD_KEY)},
            expected_domain=domain(OLD_ALGORITHM),
            max_age_seconds=300,
        )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_ALGORITHM_MIGRATION_REQUIRED$",
            ):
                reopened.verify_and_append(
                    legacy_verifier,
                    legacy,
                    local_state=state(),
                    minimum_sequence=2,
                    now=NOW,
                )

    def test_key_epoch_tamper_and_policy_mismatch_fail_closed(self):
        witness = signed_witness(OLD_ALGORITHM, OLD_KEY_ID, OLD_KEY, 0)
        witness["key_epoch"] = 1
        with self.assertRaisesRegex(
            CaptureReplayWitnessError,
            "^REPLAY_LEDGER_WITNESS_KEY_EPOCH_MISMATCH$",
        ):
            verifier(OLD_ALGORITHM, OLD_KEY_ID, OLD_KEY, 0).verify(
                witness,
                local_state=state(),
                minimum_sequence=2,
                now=NOW,
            )
        with self.assertRaisesRegex(
            CaptureReplayWitnessError,
            "^REPLAY_LEDGER_WITNESS_KEY_POLICY_EPOCH_MISMATCH$",
        ):
            CaptureReplayWitnessVerifier(
                provider_id=PROVIDER_ID,
                trusted_keys={OLD_KEY_ID: CaptureReplayWitnessKey(OLD_KEY)},
                expected_domain=domain(OLD_ALGORITHM),
                required_key_epoch=1,
                max_age_seconds=300,
            ).verify(
                signed_witness(OLD_ALGORITHM, OLD_KEY_ID, OLD_KEY, 1),
                local_state=state(),
                minimum_sequence=2,
                now=NOW,
            )

    def test_append_and_migration_serialize_to_one_active_policy(self):
        self.bootstrap()
        barrier = threading.Barrier(2)

        def old_append():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                try:
                    return append(store, OLD_ALGORITHM, OLD_KEY_ID, OLD_KEY, 0)[
                        "status"
                    ]
                except CaptureReplayWitnessError as error:
                    return str(error)

        def migration():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                return migrate(store)

        with ThreadPoolExecutor(max_workers=2) as executor:
            append_future = executor.submit(old_append)
            migration_future = executor.submit(migration)
            old_status = append_future.result(timeout=10)
            self.assertEqual(
                migration_future.result(timeout=10),
                (NEW_ALGORITHM, NEW_KEY_ID, 1),
            )
        self.assertIn(
            old_status,
            {"REPLAYED", "REPLAY_LEDGER_WITNESS_ALGORITHM_POLICY_MISMATCH"},
        )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(
                reopened.active_algorithm_policy(),
                (NEW_ALGORITHM, NEW_KEY_ID, 1),
            )
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_ALGORITHM_POLICY_MISMATCH$",
            ):
                append(reopened, OLD_ALGORITHM, OLD_KEY_ID, OLD_KEY, 0)

    def test_replayable_probe_reports_restart_downgrade_and_race(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_algorithm_migration_negative.py"
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
        self.assertEqual(
            evidence["active_policy_after_restart"],
            [NEW_ALGORITHM, NEW_KEY_ID, 1],
        )
        self.assertEqual(
            evidence["old_algorithm_after_restart"],
            "REPLAY_LEDGER_WITNESS_ALGORITHM_POLICY_MISMATCH",
        )
        self.assertEqual(
            evidence["legacy_downgrade"],
            "REPLAY_LEDGER_WITNESS_ALGORITHM_MIGRATION_REQUIRED",
        )


if __name__ == "__main__":
    unittest.main()
