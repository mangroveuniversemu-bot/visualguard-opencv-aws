"""Negative controls for CAS witness revocation-list epochs."""

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
    CaptureReplayWitnessError,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessRevocationStore,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-key-2026-11"
OTHER_KEY_ID = "fixture-hmac-key-2026-12"
THIRD_KEY_ID = "fixture-hmac-key-2027-01"
KEY = b"visualguard-witness-fixture-revocation-key-01"
OTHER_KEY = b"visualguard-witness-fixture-revocation-key-02"
NOW = 2_000_000_200


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=4,
        rowset_sha256=hashlib.sha256(b"revocation-list-rowset-4").hexdigest(),
        policy_sha256="1" * 64,
        capture_schema_sha256="2" * 64,
        rowset_schema_sha256="3" * 64,
    )


def signed_witness(
    *, key_id: str = KEY_ID, key: bytes = KEY, revocation_epoch: int = 0
) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "revocation_epoch": revocation_epoch,
        "issued_at": NOW,
        "state": state().as_dict(),
    }
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
        },
        max_age_seconds=300,
    )


def append(store, witness):
    return store.verify_and_append(
        verifier(),
        witness,
        local_state=state(),
        minimum_sequence=4,
        now=NOW,
    )


class ExternalWitnessRevocationListEpochCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "revocation-list.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_initial_state_is_empty_epoch_zero(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(store.revocation_list_state(), (0, ()))

    def test_additive_snapshot_persists_and_removal_rollback_fails_after_restart(self):
        snapshot = ((PROVIDER_ID, KEY_ID),)
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(
                store.cas_update_revocation_list(
                    expected_epoch=0,
                    replacement_epoch=1,
                    revoked_keys=snapshot,
                ),
                (1, snapshot),
            )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(reopened.revocation_list_state(), (1, snapshot))
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_REVOCATION_LIST_ROLLBACK$",
            ):
                reopened.cas_update_revocation_list(
                    expected_epoch=1,
                    replacement_epoch=2,
                    revoked_keys=((PROVIDER_ID, OTHER_KEY_ID),),
                )
            self.assertEqual(reopened.revocation_list_state(), (1, snapshot))

    def test_exact_retry_is_idempotent_but_stale_competing_snapshot_conflicts(self):
        first = ((PROVIDER_ID, KEY_ID),)
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            committed = store.cas_update_revocation_list(
                expected_epoch=0, replacement_epoch=1, revoked_keys=first
            )
            self.assertEqual(
                store.cas_update_revocation_list(
                    expected_epoch=0, replacement_epoch=1, revoked_keys=first
                ),
                committed,
            )
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_REVOCATION_LIST_CONFLICT$",
            ):
                store.cas_update_revocation_list(
                    expected_epoch=0,
                    replacement_epoch=1,
                    revoked_keys=((PROVIDER_ID, OTHER_KEY_ID),),
                )

    def test_epoch_rollback_gap_and_no_change_fail_closed(self):
        first = ((PROVIDER_ID, KEY_ID),)
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            store.cas_update_revocation_list(
                expected_epoch=0, replacement_epoch=1, revoked_keys=first
            )
            failures = (
                (1, 1, first, "REVOCATION_LIST_ROLLBACK"),
                (
                    1,
                    3,
                    first + ((PROVIDER_ID, OTHER_KEY_ID),),
                    "REVOCATION_LIST_EPOCH_GAP",
                ),
                (1, 2, first, "REVOCATION_LIST_NO_CHANGE"),
            )
            for expected, replacement, snapshot, suffix in failures:
                with (
                    self.subTest(suffix=suffix),
                    self.assertRaisesRegex(
                        CaptureReplayWitnessError,
                        f"^REPLAY_LEDGER_WITNESS_{suffix}$",
                    ),
                ):
                    store.cas_update_revocation_list(
                        expected_epoch=expected,
                        replacement_epoch=replacement,
                        revoked_keys=snapshot,
                    )
            self.assertEqual(store.revocation_list_state(), (1, first))

    def test_competing_cas_updates_have_one_epoch_winner(self):
        with CaptureReplayWitnessRevocationStore(self.database):
            pass
        barrier = threading.Barrier(2)

        def update(key_id):
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                try:
                    return store.cas_update_revocation_list(
                        expected_epoch=0,
                        replacement_epoch=1,
                        revoked_keys=((PROVIDER_ID, key_id),),
                    )
                except CaptureReplayWitnessError as error:
                    return str(error)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=10)
                for future in (
                    executor.submit(update, KEY_ID),
                    executor.submit(update, OTHER_KEY_ID),
                )
            ]
        self.assertEqual(
            sum(isinstance(result, tuple) for result in results),
            1,
        )
        self.assertIn("REPLAY_LEDGER_WITNESS_REVOCATION_LIST_CONFLICT", results)
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            epoch, snapshot = reopened.revocation_list_state()
            self.assertEqual(epoch, 1)
            self.assertEqual(len(snapshot), 1)

    def test_revoked_key_and_stale_epoch_fail_after_restart(self):
        snapshot = ((PROVIDER_ID, KEY_ID),)
        stale = signed_witness(revocation_epoch=0)
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            store.cas_update_revocation_list(
                expected_epoch=0, replacement_epoch=1, revoked_keys=snapshot
            )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE$",
            ):
                append(reopened, stale)
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_KEY_REVOKED$",
            ):
                append(reopened, signed_witness(revocation_epoch=1))
            accepted = append(
                reopened,
                signed_witness(
                    key_id=OTHER_KEY_ID,
                    key=OTHER_KEY,
                    revocation_epoch=1,
                ),
            )
            self.assertEqual(accepted["status"], "APPENDED")
            self.assertEqual(reopened.attestation_count(), 1)

    def test_append_and_revocation_list_cas_have_only_serial_outcomes(self):
        with CaptureReplayWitnessRevocationStore(self.database):
            pass
        barrier = threading.Barrier(2)

        def current_append():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                try:
                    return append(store, signed_witness())
                except CaptureReplayWitnessError as error:
                    return str(error)

        def revoke_snapshot():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                return store.cas_update_revocation_list(
                    expected_epoch=0,
                    replacement_epoch=1,
                    revoked_keys=((PROVIDER_ID, KEY_ID),),
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            append_future = executor.submit(current_append)
            revoke_future = executor.submit(revoke_snapshot)
            append_result = append_future.result(timeout=10)
            self.assertEqual(revoke_future.result(timeout=10)[0], 1)

        observed = (
            append_result if isinstance(append_result, str) else append_result["status"]
        )
        self.assertIn(
            observed,
            {"APPENDED", "REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE"},
        )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(
                reopened.revocation_list_state(),
                (1, ((PROVIDER_ID, KEY_ID),)),
            )
            self.assertEqual(
                reopened.attestation_count(), 1 if observed == "APPENDED" else 0
            )
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_KEY_REVOKED$",
            ):
                append(reopened, signed_witness(revocation_epoch=1))

    def test_replayable_probe_reports_cas_restart_rollback_and_race(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_revocation_list_epoch_negative.py"
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
        self.assertEqual(evidence["revocation_list_epoch_after_restart"], 1)
        self.assertEqual(
            evidence["result"]["rollback"],
            "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_ROLLBACK",
        )
        self.assertIn(
            evidence["result"]["append_race"],
            {"APPENDED", "REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE"},
        )


if __name__ == "__main__":
    unittest.main()
