"""Abort/restart atomicity controls for witness trust-root-set rotation."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from vision.opencv5_inspection import CaptureReplayWitnessRevocationStore


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-root-2026-11"
OTHER_KEY_ID = "fixture-hmac-root-2026-12"
THIRD_KEY_ID = "fixture-hmac-root-2027-01"


class ExternalWitnessTrustRootSetAtomicityCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "trust-root-atomicity.sqlite3"
        self.roots = ((PROVIDER_ID, KEY_ID), (PROVIDER_ID, OTHER_KEY_ID))
        self.replacement = (
            (PROVIDER_ID, OTHER_KEY_ID),
            (PROVIDER_ID, THIRD_KEY_ID),
        )
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            store.cas_update_trust_root_set(
                expected_epoch=0,
                replacement_epoch=1,
                trusted_roots=self.roots,
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def install_abort_trigger(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            """CREATE TRIGGER fail_trust_root_state_update
            BEFORE UPDATE ON replay_ledger_witness_trust_root_state
            WHEN OLD.trust_root_epoch = 1 AND NEW.trust_root_epoch = 2
            BEGIN
                SELECT RAISE(ABORT, 'INJECTED_TRUST_ROOT_UPDATE_ABORT');
            END"""
        )
        connection.commit()
        connection.close()

    def raw_rows(self) -> tuple[list[tuple], list[tuple], list[tuple]]:
        connection = sqlite3.connect(self.database)
        rows = (
            connection.execute(
                "SELECT trust_root_epoch, root_set_sha256 "
                "FROM replay_ledger_witness_trust_root_state ORDER BY singleton"
            ).fetchall(),
            connection.execute(
                "SELECT provider_id, key_id "
                "FROM replay_ledger_witness_trust_root ORDER BY provider_id, key_id"
            ).fetchall(),
            connection.execute(
                "SELECT trust_root_epoch, root_set_sha256 "
                "FROM replay_ledger_witness_trust_root_history "
                "ORDER BY trust_root_epoch"
            ).fetchall(),
        )
        connection.close()
        return rows

    def test_abort_rolls_back_state_roots_and_history_across_restart(self):
        before = self.raw_rows()
        self.install_abort_trigger()
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            with self.assertRaisesRegex(
                sqlite3.IntegrityError,
                "^INJECTED_TRUST_ROOT_UPDATE_ABORT$",
            ):
                store.cas_update_trust_root_set(
                    expected_epoch=1,
                    replacement_epoch=2,
                    trusted_roots=self.replacement,
                )
            self.assertEqual(store.trust_root_set_state(), (1, self.roots))
        self.assertEqual(self.raw_rows(), before)
        with CaptureReplayWitnessRevocationStore(self.database) as restarted:
            self.assertEqual(restarted.trust_root_set_state(), (1, self.roots))

    def test_committed_retry_after_abort_has_one_new_history_epoch(self):
        self.install_abort_trigger()
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            with self.assertRaises(sqlite3.IntegrityError):
                store.cas_update_trust_root_set(
                    expected_epoch=1,
                    replacement_epoch=2,
                    trusted_roots=self.replacement,
                )
        connection = sqlite3.connect(self.database)
        connection.execute("DROP TRIGGER fail_trust_root_state_update")
        connection.commit()
        connection.close()
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(
                store.cas_update_trust_root_set(
                    expected_epoch=1,
                    replacement_epoch=2,
                    trusted_roots=self.replacement,
                ),
                (2, self.replacement),
            )
        state_rows, root_rows, history_rows = self.raw_rows()
        self.assertEqual(state_rows[0][0], 2)
        self.assertEqual(root_rows, list(self.replacement))
        self.assertEqual([row[0] for row in history_rows], [0, 1, 2])

    def test_replayable_probe_reports_abort_restart_and_retry(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_trust_root_set_abort_restart_atomicity_negative.py"
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
        self.assertTrue(evidence["snapshot_unchanged_after_abort"])
        self.assertEqual(evidence["restart_state_after_abort"]["epoch"], 1)
        self.assertEqual(evidence["post_abort_append"], "APPENDED")
        self.assertEqual(evidence["retry_epoch"], 2)
        self.assertEqual(evidence["history_epoch_count"], 3)
        self.assertEqual(evidence["sqlite_quick_check"], ["ok"])
        self.assertEqual(evidence["live_external_witness"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
