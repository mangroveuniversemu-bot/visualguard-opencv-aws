"""Negative controls for persistent witness-key revocation epochs."""

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


class ExternalWitnessRevocationEpochCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "revocations.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def append(self, store, witness):
        return store.verify_and_append(
            verifier(),
            witness,
            local_state=state(),
            minimum_sequence=2,
            now=NOW,
        )

    def test_signed_current_epoch_is_appended_once(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            result = self.append(store, signed_witness())
            self.assertEqual(result["status"], "APPENDED")
            self.assertEqual(result["revocation_epoch"], 0)
            self.assertEqual(store.attestation_count(), 1)
            replay = self.append(store, signed_witness())
            self.assertEqual(replay["status"], "REPLAYED")
            self.assertEqual(store.attestation_count(), 1)

    def test_revoked_or_stale_epoch_fails_closed_after_restart(self):
        stale = signed_witness(revocation_epoch=0)
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(store.revoke(PROVIDER_ID, KEY_ID), 1)
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE$",
            ):
                self.append(reopened, stale)
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_KEY_REVOKED$",
            ):
                self.append(reopened, signed_witness(revocation_epoch=1))
            accepted = self.append(
                reopened,
                signed_witness(
                    key_id=OTHER_KEY_ID,
                    key=OTHER_KEY,
                    revocation_epoch=1,
                ),
            )
            self.assertEqual(accepted["key_id"], OTHER_KEY_ID)

    def test_future_and_tampered_epoch_fail_closed(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_FROM_FUTURE$",
            ):
                self.append(store, signed_witness(revocation_epoch=1))
            tampered = signed_witness()
            tampered["revocation_epoch"] = 1
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_AUTHENTICATION_FAILED$",
            ):
                self.append(store, tampered)

    def test_append_and_revoke_serialize_without_stale_acceptance(self):
        # Bootstrap schema before both connections rendezvous. The race under
        # test is append-versus-revocation, not concurrent DDL creation.
        with CaptureReplayWitnessRevocationStore(self.database):
            pass
        barrier = threading.Barrier(2)

        def append():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                try:
                    return self.append(store, signed_witness())
                except CaptureReplayWitnessError as error:
                    return str(error)

        def revoke():
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                return store.revoke(PROVIDER_ID, KEY_ID)

        with ThreadPoolExecutor(max_workers=2) as executor:
            appended = executor.submit(append)
            revoked = executor.submit(revoke)
            append_result = appended.result(timeout=10)
            self.assertEqual(revoked.result(timeout=10), 1)

        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertIn(
                append_result
                if isinstance(append_result, str)
                else append_result["status"],
                {"APPENDED", "REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE"},
            )
            self.assertEqual(
                reopened.attestation_count(),
                1 if isinstance(append_result, dict) else 0,
            )
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE$",
            ):
                self.append(reopened, signed_witness())

    def test_replayable_probe_reports_restart_and_serialization(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_revocation_epoch_negative.py"
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
        self.assertEqual(evidence["revocation_epoch_after_restart"], 1)
        self.assertEqual(
            evidence["result"]["stale_after_restart"],
            "REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE",
        )
        self.assertEqual(
            evidence["result"]["revoked_current_epoch"],
            "REPLAY_LEDGER_WITNESS_KEY_REVOKED",
        )
        self.assertEqual(evidence["result"]["other_key"], OTHER_KEY_ID)


if __name__ == "__main__":
    unittest.main()
