"""External-checkpoint controls and the same-domain co-rollback falsifier."""

from __future__ import annotations

import json
from pathlib import Path
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


class TrustRootHistoryExternalAnchorCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "trust-root.sqlite3"
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            store.cas_update_trust_root_set(
                expected_epoch=0,
                replacement_epoch=1,
                trusted_roots=((PROVIDER_ID, KEY_A), (PROVIDER_ID, KEY_B)),
            )
            self.epoch_one = store.trust_root_history_checkpoint()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_current_checkpoint_is_accepted(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(
                store.verify_trust_root_history_checkpoint(self.epoch_one),
                self.epoch_one,
            )

    def test_stale_anchor_is_rejected_after_history_advances(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            store.cas_update_trust_root_set(
                expected_epoch=1,
                replacement_epoch=2,
                trusted_roots=((PROVIDER_ID, KEY_B), (PROVIDER_ID, KEY_C)),
            )
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_ANCHOR_MISMATCH$",
            ):
                store.verify_trust_root_history_checkpoint(self.epoch_one)

    def test_future_anchor_is_rejected_by_older_history(self):
        future = dict(self.epoch_one)
        future["trust_root_epoch"] = 2
        future["root_set_sha256"] = "f" * 64
        future["chain_sha256"] = "e" * 64
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_ANCHOR_MISMATCH$",
            ):
                store.verify_trust_root_history_checkpoint(future)

    def test_malformed_anchor_is_rejected(self):
        malformed = dict(self.epoch_one)
        malformed["chain_sha256"] = "not-a-digest"
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "^REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_ANCHOR_INVALID$",
            ):
                store.verify_trust_root_history_checkpoint(malformed)

    def test_probe_exposes_co_rollback_limit(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_trust_root_history_external_anchor_co_rollback_falsifier.py"
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
        self.assertEqual(evidence["anchor_mode"], "LOCAL_FILE_ANCHOR_FIXTURE")
        self.assertEqual(evidence["live_external_witness"], "NOT_RUN")
        result = evidence["result"]
        self.assertEqual(result["epoch_one"]["trust_root_epoch"], 1)
        self.assertEqual(result["epoch_two"]["trust_root_epoch"], 2)
        self.assertEqual(
            result["database_only_rollback"],
            "REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_ANCHOR_MISMATCH",
        )
        self.assertEqual(
            result["anchor_only_rollback"],
            "REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_ANCHOR_MISMATCH",
        )
        self.assertEqual(
            result["co_rollback"]["verification"],
            "ACCEPTED_MATCHING_PAIR",
        )
        self.assertEqual(result["co_rollback"]["quick_check"], "ok")
        self.assertNotEqual(
            result["epoch_one"]["database_sha256"],
            result["epoch_two"]["database_sha256"],
        )
        self.assertNotEqual(
            result["epoch_one"]["anchor_sha256"],
            result["epoch_two"]["anchor_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
