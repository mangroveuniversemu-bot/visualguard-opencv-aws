"""Restart fail-closed controls for the trust-root history chain."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from vision.opencv5_inspection import (
    CaptureReplayLedgerSchemaError,
    CaptureReplayWitnessRevocationStore,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_A = "fixture-hmac-root-2026-11"
KEY_B = "fixture-hmac-root-2026-12"
KEY_C = "fixture-hmac-root-2027-01"


class ExternalWitnessTrustRootHistoryIntegrityCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "trust-root-history.sqlite3"
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            store.cas_update_trust_root_set(
                expected_epoch=0,
                replacement_epoch=1,
                trusted_roots=((PROVIDER_ID, KEY_A), (PROVIDER_ID, KEY_B)),
            )
            store.cas_update_trust_root_set(
                expected_epoch=1,
                replacement_epoch=2,
                trusted_roots=((PROVIDER_ID, KEY_B), (PROVIDER_ID, KEY_C)),
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def mutate(self, statement: str, parameters: tuple[object, ...] = ()) -> list[str]:
        connection = sqlite3.connect(self.database)
        connection.execute(statement, parameters)
        connection.commit()
        quick_check = [
            str(row[0]) for row in connection.execute("PRAGMA quick_check").fetchall()
        ]
        connection.close()
        return quick_check

    def assert_restart_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            CaptureReplayLedgerSchemaError,
            "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_INVALID$",
        ):
            CaptureReplayWitnessRevocationStore(self.database)

    def test_restart_rejects_earlier_root_digest_tamper(self):
        self.assertEqual(
            self.mutate(
                "UPDATE replay_ledger_witness_trust_root_history "
                "SET root_set_sha256 = ? WHERE trust_root_epoch = 1",
                ("f" * 64,),
            ),
            ["ok"],
        )
        self.assert_restart_fails_closed()

    def test_restart_rejects_history_gap(self):
        self.assertEqual(
            self.mutate(
                "DELETE FROM replay_ledger_witness_trust_root_history "
                "WHERE trust_root_epoch = 1"
            ),
            ["ok"],
        )
        self.assert_restart_fails_closed()

    def test_restart_rejects_chain_digest_tamper(self):
        self.assertEqual(
            self.mutate(
                "UPDATE replay_ledger_witness_trust_root_history "
                "SET chain_sha256 = ? WHERE trust_root_epoch = 1",
                ("e" * 64,),
            ),
            ["ok"],
        )
        self.assert_restart_fails_closed()

    def test_pristine_chain_restarts_and_advances(self):
        with CaptureReplayWitnessRevocationStore(self.database) as restarted:
            epoch, roots = restarted.trust_root_set_state()
            self.assertEqual(epoch, 2)
            self.assertEqual(
                roots,
                ((PROVIDER_ID, KEY_B), (PROVIDER_ID, KEY_C)),
            )
            self.assertEqual(
                restarted.cas_update_trust_root_set(
                    expected_epoch=2,
                    replacement_epoch=3,
                    trusted_roots=((PROVIDER_ID, KEY_C),),
                ),
                (3, ((PROVIDER_ID, KEY_C),)),
            )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(reopened.trust_root_set_state()[0], 3)

    def test_replayable_probe_reports_logical_tamper_fail_closed(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_trust_root_history_tamper_restart_negative.py"
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
        self.assertEqual(evidence["sqlite_quick_check_after_tamper"], ["ok"])
        self.assertEqual(
            evidence["restart_error"],
            "REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_INVALID",
        )
        self.assertEqual(evidence["attestation_count_after_tamper"], 0)
        self.assertEqual(evidence["live_external_witness"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
