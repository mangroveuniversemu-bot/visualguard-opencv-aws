"""Negative controls for bounded external-witness key rotation."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import unittest

from vision.opencv5_inspection import (
    CaptureReplayAnchorState,
    CaptureReplayWitnessError,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
OLD_KEY_ID = "fixture-hmac-key-2026-10"
NEW_KEY_ID = "fixture-hmac-key-2026-11"
UNKNOWN_KEY_ID = "fixture-hmac-key-unknown"
OLD_KEY = b"visualguard-witness-fixture-old-key-0001"
NEW_KEY = b"visualguard-witness-fixture-new-key-0002"
NOW = 2_000_000_000
NEW_ACTIVE_FROM = NOW - 60
OLD_RETIRE_AT = NOW + 60


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=2,
        rowset_sha256=hashlib.sha256(b"rowset-2").hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def signed_witness(
    key_id: str,
    key: bytes,
    *,
    issued_at: int = NOW,
) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "issued_at": issued_at,
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
            OLD_KEY_ID: CaptureReplayWitnessKey(
                OLD_KEY,
                active_from=0,
                retire_at=OLD_RETIRE_AT,
            ),
            NEW_KEY_ID: CaptureReplayWitnessKey(
                NEW_KEY,
                active_from=NEW_ACTIVE_FROM,
            ),
        },
        max_age_seconds=300,
        max_future_skew_seconds=5,
    )


class ExternalWitnessKeyRotationCases(unittest.TestCase):
    def verify(self, witness: object, *, now: int = NOW):
        return verifier().verify(
            witness,
            local_state=state(),
            minimum_sequence=2,
            now=now,
        )

    def assert_rejected(self, witness: object, code: str, *, now: int = NOW):
        with self.assertRaisesRegex(CaptureReplayWitnessError, f"^{code}$"):
            self.verify(witness, now=now)

    def test_overlap_accepts_old_and_new_keys(self):
        self.assertEqual(
            self.verify(signed_witness(OLD_KEY_ID, OLD_KEY))["key_id"],
            OLD_KEY_ID,
        )
        self.assertEqual(
            self.verify(signed_witness(NEW_KEY_ID, NEW_KEY))["key_id"],
            NEW_KEY_ID,
        )

    def test_new_key_before_activation_fails_closed(self):
        before_activation = NEW_ACTIVE_FROM - 1
        self.assert_rejected(
            signed_witness(
                NEW_KEY_ID,
                NEW_KEY,
                issued_at=before_activation,
            ),
            "REPLAY_LEDGER_WITNESS_KEY_NOT_YET_ACTIVE",
            now=before_activation,
        )

    def test_old_key_at_retirement_fails_while_new_key_remains_valid(self):
        retirement = OLD_RETIRE_AT
        self.assert_rejected(
            signed_witness(
                OLD_KEY_ID,
                OLD_KEY,
                issued_at=retirement,
            ),
            "REPLAY_LEDGER_WITNESS_KEY_RETIRED",
            now=retirement,
        )
        result = self.verify(
            signed_witness(
                NEW_KEY_ID,
                NEW_KEY,
                issued_at=retirement,
            ),
            now=retirement,
        )
        self.assertEqual(result["key_id"], NEW_KEY_ID)

    def test_unknown_key_id_fails_closed(self):
        self.assert_rejected(
            signed_witness(UNKNOWN_KEY_ID, NEW_KEY),
            "REPLAY_LEDGER_WITNESS_KEY_UNKNOWN",
        )

    def test_signed_key_id_substitution_fails_authentication(self):
        witness = signed_witness(OLD_KEY_ID, OLD_KEY)
        substituted = copy.deepcopy(witness)
        substituted["key_id"] = NEW_KEY_ID
        self.assert_rejected(
            substituted,
            "REPLAY_LEDGER_WITNESS_AUTHENTICATION_FAILED",
        )

    def test_mixed_legacy_and_keyring_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "use either"):
            CaptureReplayWitnessVerifier(
                provider_id=PROVIDER_ID,
                key_id=OLD_KEY_ID,
                verifying_key=OLD_KEY,
                trusted_keys={
                    NEW_KEY_ID: CaptureReplayWitnessKey(NEW_KEY)
                },
                max_age_seconds=300,
            )

    def test_replayable_probe_reports_rotation_boundaries(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_external_witness_key_rotation_negative.py"
        )
        probe = subprocess.run(
            [sys.executable, script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        evidence = json.loads(probe.stdout)
        self.assertEqual(evidence["live_external_witness"], "NOT_RUN")
        self.assertEqual(evidence["result"]["overlap_old"], OLD_KEY_ID)
        self.assertEqual(evidence["result"]["overlap_new"], NEW_KEY_ID)
        self.assertEqual(
            evidence["result"]["before_activation"],
            "REPLAY_LEDGER_WITNESS_KEY_NOT_YET_ACTIVE",
        )
        self.assertEqual(
            evidence["result"]["retired_old"],
            "REPLAY_LEDGER_WITNESS_KEY_RETIRED",
        )
        self.assertEqual(
            evidence["result"]["unknown"],
            "REPLAY_LEDGER_WITNESS_KEY_UNKNOWN",
        )
        self.assertEqual(
            evidence["result"]["substituted"],
            "REPLAY_LEDGER_WITNESS_AUTHENTICATION_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
