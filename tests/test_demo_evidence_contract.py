"""Fail-closed acceptance tests for the VisualGuard demo evidence contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from ops.verify_demo_evidence_contract import ContractError, verify_contract


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json"


class DemoEvidenceContractCases(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def verify_mutation(self, mutate):
        manifest = copy.deepcopy(self.manifest)
        mutate(manifest)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            return verify_contract(path, ROOT)

    def test_prepared_contract_passes_with_bounded_disclosures(self):
        result = verify_contract(MANIFEST, ROOT)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["duration_seconds"], 180)
        self.assertEqual(result["segment_count"], 6)
        self.assertEqual(result["artifact_count"], 2)
        self.assertEqual(result["aws"], "NOT_RUN")
        self.assertEqual(result["camera"], "NOT_RUN")
        self.assertFalse(result["action_executed"])

    def test_missing_required_segment_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "segment coverage mismatch"):
            self.verify_mutation(lambda value: value["segments"].pop())

    def test_duration_overrun_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "exceeds"):
            self.verify_mutation(
                lambda value: value["segments"][0].update(duration_seconds=21)
            )

    def test_recorded_video_claim_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "must not claim a recorded demo"):
            self.verify_mutation(lambda value: value.update(status="RECORDED"))

    def test_live_aws_claim_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "AWS as NOT_RUN"):
            self.verify_mutation(lambda value: value.update(aws_claim="DEPLOYED"))

    def test_artifact_digest_drift_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "artifact digest drift"):
            self.verify_mutation(
                lambda value: value["segments"][1]["artifacts"][0].update(
                    sha256="0" * 64
                )
            )

    def test_artifact_path_escape_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "escapes repository root"):
            self.verify_mutation(
                lambda value: value["segments"][1]["artifacts"][0].update(
                    path="../outside.json"
                )
            )


if __name__ == "__main__":
    unittest.main()
