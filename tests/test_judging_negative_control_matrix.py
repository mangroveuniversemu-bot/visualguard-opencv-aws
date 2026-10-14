"""Judge-facing OpenCV negative controls and downstream action routing."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from vision.follow_up import plan_follow_up
from vision.opencv5_inspection import verify_consequence, View, frame


class FollowUpPlanningCases(unittest.TestCase):
    def test_each_inspection_decision_changes_the_planned_follow_up(self):
        cases = (
            (
                {"decision": "REVIEW", "reason": "HUMAN_REVIEW"},
                "QUEUE_HUMAN_REVIEW",
            ),
            (
                {"decision": "REQUEST_VIEW", "reason": "OCCLUDED_VIEW"},
                "REQUEST_NEW_CAPTURE",
            ),
            (
                {"decision": "STOP", "reason": "ALARM"},
                "HOLD_AUTOMATION",
            ),
        )
        for inspection, expected_action in cases:
            with self.subTest(decision=inspection["decision"]):
                planned = plan_follow_up(inspection)
                self.assertEqual(planned["planned_action"], expected_action)
                self.assertFalse(planned["action_executed"])
                self.assertEqual(planned["physical_action"], "NONE")

    def test_consequence_mismatch_overrides_clear_review(self):
        consequence = verify_consequence(False, View(frame(True)))
        planned = plan_follow_up(
            {"decision": "REVIEW", "reason": "HUMAN_REVIEW"},
            consequence_result=consequence,
        )
        self.assertEqual(planned["planned_action"], "HOLD_AUTOMATION")
        self.assertEqual(planned["trigger"], "CONSEQUENCE_MISMATCH")
        self.assertFalse(planned["action_executed"])

    def test_invalid_or_unknown_evidence_fails_closed(self):
        for inspection in (
            None,
            [],
            {},
            {"decision": "ALLOW", "reason": "UNSUPPORTED"},
            {"decision": "REVIEW", "reason": None},
        ):
            with self.subTest(inspection=inspection):
                planned = plan_follow_up(inspection)
                self.assertEqual(planned["planned_action"], "HOLD_AUTOMATION")
                self.assertEqual(planned["trigger"], "INVALID_INSPECTION_RESULT")

    def test_invalid_consequence_evidence_fails_closed(self):
        planned = plan_follow_up(
            {"decision": "REVIEW", "reason": "HUMAN_REVIEW"},
            consequence_result="MATCH",
        )
        self.assertEqual(planned["planned_action"], "HOLD_AUTOMATION")
        self.assertEqual(planned["trigger"], "INVALID_CONSEQUENCE_RESULT")

    def test_replayable_matrix_covers_required_controls(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "opencv5_judging_negative_control_matrix.py"
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
        self.assertEqual(evidence["evidence_mode"], "SYNTHETIC_REPLAY")
        self.assertEqual(evidence["input"], "FIXED_SYNTHETIC_ARRAYS")
        self.assertEqual(evidence["aws"], "NOT_RUN")
        self.assertEqual(evidence["camera"], "NOT_RUN")
        self.assertEqual(evidence["physical_action"], "NONE")
        self.assertEqual(
            set(evidence["cases"]),
            {
                "alarm",
                "calibration_drift",
                "clear",
                "consequence_mismatch",
                "missing_view",
                "occluded",
                "stale",
                "version_drift",
            },
        )
        self.assertEqual(
            evidence["cases"]["clear"]["follow_up"]["planned_action"],
            "QUEUE_HUMAN_REVIEW",
        )
        self.assertEqual(
            evidence["cases"]["missing_view"]["follow_up"]["planned_action"],
            "REQUEST_NEW_CAPTURE",
        )
        self.assertEqual(
            evidence["cases"]["alarm"]["follow_up"]["planned_action"],
            "HOLD_AUTOMATION",
        )
        for case in evidence["cases"].values():
            self.assertFalse(case["follow_up"]["action_executed"])
            self.assertEqual(case["follow_up"]["physical_action"], "NONE")


if __name__ == "__main__":
    unittest.main()
