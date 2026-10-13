"""Negative controls for the replay-ledger witness authenticity contract."""
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
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-key-2026-10"
VERIFYING_KEY = b"visualguard-witness-fixture-key-0001"
WRONG_KEY = b"visualguard-witness-fixture-key-9999"
NOW = 2_000_000_000


def state(sequence: int) -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=sequence,
        rowset_sha256=hashlib.sha256(f"rowset-{sequence}".encode()).hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def signed_witness(
    anchor_state: CaptureReplayAnchorState,
    *,
    issued_at: int = NOW,
    key: bytes = VERIFYING_KEY,
) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": KEY_ID,
        "issued_at": issued_at,
        "state": anchor_state.as_dict(),
    }
    signature = hmac.new(
        key,
        CaptureReplayWitnessVerifier.canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()
    return {**payload, "signature": signature}


class ExternalWitnessAuthenticityCases(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = CaptureReplayWitnessVerifier(
            provider_id=PROVIDER_ID,
            key_id=KEY_ID,
            verifying_key=VERIFYING_KEY,
            max_age_seconds=300,
            max_future_skew_seconds=5,
        )

    def verify(
        self,
        witness: object,
        *,
        local_state: CaptureReplayAnchorState | None = None,
        minimum_sequence: int = 2,
    ) -> dict[str, object]:
        return self.verifier.verify(
            witness,
            local_state=state(2) if local_state is None else local_state,
            minimum_sequence=minimum_sequence,
            now=NOW,
        )

    def assert_rejected(self, witness: object, code: str, **kwargs) -> None:
        with self.assertRaisesRegex(CaptureReplayWitnessError, f"^{code}$"):
            self.verify(witness, **kwargs)

    def test_valid_authenticated_witness_is_accepted(self):
        result = self.verify(signed_witness(state(2)))
        self.assertEqual(result["status"], "VERIFIED_AUTHENTICATED_FIXTURE")
        self.assertEqual(result["sequence"], 2)
        self.assertEqual(result["provider_id"], PROVIDER_ID)
        self.assertEqual(result["key_id"], KEY_ID)

    def test_unsigned_witness_is_rejected(self):
        witness = signed_witness(state(2))
        del witness["signature"]
        self.assert_rejected(witness, "REPLAY_LEDGER_WITNESS_UNSIGNED")

    def test_wrong_key_signature_is_rejected(self):
        self.assert_rejected(
            signed_witness(state(2), key=WRONG_KEY),
            "REPLAY_LEDGER_WITNESS_AUTHENTICATION_FAILED",
        )

    def test_stale_witness_is_rejected(self):
        self.assert_rejected(
            signed_witness(state(2), issued_at=NOW - 301),
            "REPLAY_LEDGER_WITNESS_STALE",
        )

    def test_signed_regressed_witness_is_rejected(self):
        self.assert_rejected(
            signed_witness(state(1)),
            "REPLAY_LEDGER_WITNESS_REGRESSED",
        )

    def test_authenticated_witness_detects_local_co_rollback(self):
        witness = signed_witness(state(2))
        self.assert_rejected(
            witness,
            "REPLAY_LEDGER_ROLLBACK_DETECTED",
            local_state=state(1),
        )

    def test_authenticated_state_tamper_is_rejected(self):
        witness = signed_witness(state(2))
        tampered = copy.deepcopy(witness)
        tampered["state"]["rowset_sha256"] = "f" * 64
        self.assert_rejected(
            tampered,
            "REPLAY_LEDGER_WITNESS_AUTHENTICATION_FAILED",
        )

    def test_replayable_probe_reports_all_negative_controls(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_external_witness_authenticity_negative.py"
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
        self.assertEqual(
            evidence["authentication"],
            "HMAC_SHA256_SHARED_SECRET_FIXTURE_ONLY",
        )
        self.assertEqual(evidence["live_external_witness"], "NOT_RUN")
        self.assertEqual(evidence["result"]["valid"]["sequence"], 2)
        self.assertEqual(
            evidence["result"]["unsigned"],
            "REPLAY_LEDGER_WITNESS_UNSIGNED",
        )
        self.assertEqual(
            evidence["result"]["wrong_key"],
            "REPLAY_LEDGER_WITNESS_AUTHENTICATION_FAILED",
        )
        self.assertEqual(
            evidence["result"]["stale"],
            "REPLAY_LEDGER_WITNESS_STALE",
        )
        self.assertEqual(
            evidence["result"]["regressed"],
            "REPLAY_LEDGER_WITNESS_REGRESSED",
        )
        self.assertEqual(
            evidence["result"]["co_rollback"],
            "REPLAY_LEDGER_ROLLBACK_DETECTED",
        )
        self.assertEqual(
            evidence["result"]["tampered"],
            "REPLAY_LEDGER_WITNESS_AUTHENTICATION_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
