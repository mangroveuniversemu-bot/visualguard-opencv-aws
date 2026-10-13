"""Negative controls for CAS witness trust-root-set epochs."""

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
    CaptureReplayLedgerSchemaError,
    CaptureReplayWitnessError,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessRevocationStore,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-root-2026-11"
OTHER_KEY_ID = "fixture-hmac-root-2026-12"
THIRD_KEY_ID = "fixture-hmac-root-2027-01"
KEY = b"visualguard-witness-fixture-trust-root-key-01"
OTHER_KEY = b"visualguard-witness-fixture-trust-root-key-02"
THIRD_KEY = b"visualguard-witness-fixture-trust-root-key-03"
NOW = 2_000_000_300


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=5,
        rowset_sha256=hashlib.sha256(b"trust-root-rowset-5").hexdigest(),
        policy_sha256="4" * 64,
        capture_schema_sha256="5" * 64,
        rowset_schema_sha256="6" * 64,
    )


def signed_witness(
    *,
    key_id: str = KEY_ID,
    key: bytes = KEY,
    trust_root_epoch: int | None = 1,
) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "revocation_epoch": 0,
        "issued_at": NOW,
        "state": state().as_dict(),
    }
    if trust_root_epoch is not None:
        payload["trust_root_epoch"] = trust_root_epoch
    return {
        **payload,
        "signature": hmac.new(
            key,
            CaptureReplayWitnessVerifier.canonical_payload(payload),
            hashlib.sha256,
        ).hexdigest(),
    }


def verifier() -> CaptureReplayWitnessVerifier:
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={
            KEY_ID: CaptureReplayWitnessKey(KEY),
            OTHER_KEY_ID: CaptureReplayWitnessKey(OTHER_KEY),
            THIRD_KEY_ID: CaptureReplayWitnessKey(THIRD_KEY),
        },
        max_age_seconds=300,
    )


def append(store, witness):
    return store.verify_and_append(
        verifier(),
        witness,
        local_state=state(),
        minimum_sequence=5,
        now=NOW,
    )


class ExternalWitnessTrustRootSetEpochCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "trust-root-set.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def initialize(self):
        roots = ((PROVIDER_ID, KEY_ID), (PROVIDER_ID, OTHER_KEY_ID))
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(
                store.cas_update_trust_root_set(
                    expected_epoch=0,
                    replacement_epoch=1,
                    trusted_roots=roots,
                ),
                (1, roots),
            )
        return roots

    def test_initial_state_is_empty_epoch_zero(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(store.trust_root_set_state(), (0, ()))

    def test_missing_authoritative_history_row_fails_closed_after_restart(self):
        self.initialize()
        connection = sqlite3.connect(self.database)
        connection.execute(
            "DELETE FROM replay_ledger_witness_trust_root_history "
            "WHERE trust_root_epoch = 1"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(
            CaptureReplayLedgerSchemaError,
            "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_INVALID$",
        ):
            CaptureReplayWitnessRevocationStore(self.database)

    def test_rotation_persists_and_removed_root_fails_after_restart(self):
        self.initialize()
        replacement = (
            (PROVIDER_ID, OTHER_KEY_ID),
            (PROVIDER_ID, THIRD_KEY_ID),
        )
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(
                store.cas_update_trust_root_set(
                    expected_epoch=1,
                    replacement_epoch=2,
                    trusted_roots=replacement,
                ),
                (2, replacement),
            )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(reopened.trust_root_set_state(), (2, replacement))
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_EPOCH_STALE$",
            ):
                append(reopened, signed_witness(trust_root_epoch=1))
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_UNKNOWN$",
            ):
                append(reopened, signed_witness(trust_root_epoch=2))
            accepted = append(
                reopened,
                signed_witness(
                    key_id=OTHER_KEY_ID,
                    key=OTHER_KEY,
                    trust_root_epoch=2,
                ),
            )
            self.assertEqual(accepted["status"], "APPENDED")

    def test_previous_snapshot_cannot_be_restored_under_new_epoch(self):
        roots = self.initialize()
        replacement = ((PROVIDER_ID, OTHER_KEY_ID),)
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            store.cas_update_trust_root_set(
                expected_epoch=1,
                replacement_epoch=2,
                trusted_roots=replacement,
            )
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_ROLLBACK$",
            ):
                store.cas_update_trust_root_set(
                    expected_epoch=2,
                    replacement_epoch=3,
                    trusted_roots=roots,
                )
            self.assertEqual(store.trust_root_set_state(), (2, replacement))

    def test_exact_retry_is_idempotent_but_stale_competitor_conflicts(self):
        roots = self.initialize()
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(
                store.cas_update_trust_root_set(
                    expected_epoch=0,
                    replacement_epoch=1,
                    trusted_roots=roots,
                ),
                (1, roots),
            )
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_CONFLICT$",
            ):
                store.cas_update_trust_root_set(
                    expected_epoch=0,
                    replacement_epoch=1,
                    trusted_roots=((PROVIDER_ID, THIRD_KEY_ID),),
                )

    def test_epoch_rollback_gap_no_change_and_reused_empty_fail_closed(self):
        roots = self.initialize()
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            failures = (
                (1, 1, roots, "EPOCH_ROLLBACK"),
                (1, 3, ((PROVIDER_ID, THIRD_KEY_ID),), "EPOCH_GAP"),
                (1, 2, roots, "NO_CHANGE"),
            )
            for expected, replacement, snapshot, suffix in failures:
                with (
                    self.subTest(suffix=suffix),
                    self.assertRaisesRegex(
                        CaptureReplayWitnessError,
                        f"^REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_{suffix}$",
                    ),
                ):
                    store.cas_update_trust_root_set(
                        expected_epoch=expected,
                        replacement_epoch=replacement,
                        trusted_roots=snapshot,
                    )
            with self.assertRaises(ValueError):
                store.cas_update_trust_root_set(
                    expected_epoch=1,
                    replacement_epoch=2,
                    trusted_roots=(),
                )

    def test_competing_cas_updates_have_one_epoch_winner(self):
        self.initialize()
        barrier = threading.Barrier(2)

        def update(key_id):
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                try:
                    return store.cas_update_trust_root_set(
                        expected_epoch=1,
                        replacement_epoch=2,
                        trusted_roots=((PROVIDER_ID, key_id),),
                    )
                except CaptureReplayWitnessError as error:
                    return str(error)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=10)
                for future in (
                    executor.submit(update, OTHER_KEY_ID),
                    executor.submit(update, THIRD_KEY_ID),
                )
            ]
        self.assertEqual(sum(isinstance(result, tuple) for result in results), 1)
        self.assertIn("REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_CONFLICT", results)

    def test_missing_future_and_untrusted_root_fail_closed(self):
        self.initialize()
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_EPOCH_MISSING$",
            ):
                append(store, signed_witness(trust_root_epoch=None))
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_EPOCH_FROM_FUTURE$",
            ):
                append(store, signed_witness(trust_root_epoch=2))
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_UNKNOWN$",
            ):
                append(
                    store,
                    signed_witness(
                        key_id=THIRD_KEY_ID,
                        key=THIRD_KEY,
                        trust_root_epoch=1,
                    ),
                )

    def test_append_and_root_rotation_have_only_serial_outcomes(self):
        self.initialize()
        barrier = threading.Barrier(2)

        def current_append():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                try:
                    return append(store, signed_witness())["status"]
                except CaptureReplayWitnessError as error:
                    return str(error)

        def rotate():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                return store.cas_update_trust_root_set(
                    expected_epoch=1,
                    replacement_epoch=2,
                    trusted_roots=((PROVIDER_ID, OTHER_KEY_ID),),
                )[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            append_future = executor.submit(current_append)
            rotate_future = executor.submit(rotate)
            append_result = append_future.result(timeout=10)
            self.assertEqual(rotate_future.result(timeout=10), 2)
        self.assertIn(
            append_result,
            {"APPENDED", "REPLAY_LEDGER_WITNESS_TRUST_ROOT_EPOCH_STALE"},
        )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(
                reopened.attestation_count(), 1 if append_result == "APPENDED" else 0
            )

    def test_replayable_probe_reports_restart_rollback_and_race(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_trust_root_set_epoch_negative.py"
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
        self.assertEqual(evidence["trust_root_epoch_after_restart"], 2)
        self.assertEqual(
            evidence["result"]["snapshot_rollback"],
            "REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_ROLLBACK",
        )
        self.assertIn(
            evidence["result"]["append_race"],
            {"APPENDED", "REPLAY_LEDGER_WITNESS_TRUST_ROOT_EPOCH_STALE"},
        )


if __name__ == "__main__":
    unittest.main()
