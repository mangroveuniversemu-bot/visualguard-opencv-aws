"""OpenCV 5 scene pipeline: quality gates, indicator detection, fusion, controls."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from ops.evaluate_scene_pipeline import evaluate
from vision import scene_analysis as sa
from vision.follow_up import plan_follow_up
from vision.opencv5_inspection import CaptureReplayLedger
from vision.synthetic_scenes import SCENARIOS, SCENARIOS_BY_NAME, render_scene

NOW = 1_000.0


def scene(name: str, index: int = 0):
    return render_scene(SCENARIOS_BY_NAME[name], split="dev", index=index)


def pair(rendered, prefix: str, *, captured_at: float = NOW - 1.0):
    return {
        name: sa.SceneView(
            pixels,
            source_id=f"camera-{name}-v1",
            capture_id=f"{prefix}-{name}",
            captured_at=captured_at,
        )
        for name, pixels in rendered.views.items()
    }


class SceneLedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = CaptureReplayLedger(Path(self._tmp.name) / "scene.sqlite3")

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def analyze(self, views, **kwargs):
        kwargs.setdefault("captured_at", NOW - 1.0)
        kwargs.setdefault("now", NOW)
        kwargs.setdefault("replay_ledger", self.ledger)
        return sa.analyze_scene(views, **kwargs)


class GeneratorDeterminism(unittest.TestCase):
    def test_same_seed_renders_identical_bytes_and_splits_differ(self):
        first = scene("alarm_red_both_views")
        again = scene("alarm_red_both_views")
        held_out = render_scene(first.scenario, split="test", index=0)
        self.assertEqual(first.digest(), again.digest())
        self.assertNotEqual(first.seed, held_out.seed)
        self.assertNotEqual(first.digest(), held_out.digest())
        for pixels in first.views.values():
            self.assertTrue(sa.validate_frame(pixels))


class QualityGates(unittest.TestCase):
    def setUp(self):
        self.clear = scene("normal_green_clear").views["front"]

    def test_clear_frame_is_usable(self):
        quality = sa.measure_quality(self.clear)
        self.assertTrue(quality["usable"], quality)

    def test_pixel_measured_degradations_fail_their_gate(self):
        occluded = self.clear.copy()
        cv2.ellipse(occluded, (320, 240), (240, 170), 0, 0, 360, (12, 12, 14), -1)
        cases = {
            "BLURRED_VIEW": cv2.GaussianBlur(self.clear, (0, 0), 7.0),
            "UNDEREXPOSED_VIEW": cv2.convertScaleAbs(self.clear, alpha=0.12),
            "OVEREXPOSED_VIEW": cv2.convertScaleAbs(self.clear, alpha=3.2, beta=50),
            "OCCLUDED_VIEW": occluded,
        }
        for reason, pixels in cases.items():
            with self.subTest(reason=reason):
                quality = sa.measure_quality(pixels)
                self.assertIn(reason, quality["failures"], quality)
                self.assertFalse(quality["usable"])


class IndicatorDetection(unittest.TestCase):
    def test_lit_red_indicator_is_detected_with_geometry(self):
        detections = sa.detect_red_indicators(
            scene("alarm_red_both_views").views["side"]
        )
        self.assertEqual(len(detections), 1)
        detection = detections[0]
        self.assertGreaterEqual(detection["fill"], sa.CONFIG["lamp_min_fill"])
        self.assertGreaterEqual(detection["area"], sa.CONFIG["lamp_min_area"])

    def test_distractors_are_rejected_where_baselines_fire(self):
        sticker = scene("normal_green_with_red_sticker").views["front"]
        glare = scene("normal_green_with_glare").views["front"]
        unlit = scene("normal_unlit_red_lamp").views["front"]
        self.assertEqual(sa.detect_red_indicators(sticker), [])
        self.assertEqual(sa.detect_red_indicators(glare), [])
        self.assertEqual(sa.detect_red_indicators(unlit), [])
        self.assertTrue(sa.baseline_naive_red(sticker))
        self.assertTrue(sa.baseline_legacy_brightness(glare))

    def test_known_hard_round_red_sticker_still_false_stops(self):
        # Documented failure: a bright round red non-emissive object is
        # indistinguishable from a lit lamp by colour and shape alone.
        rendered = scene("normal_round_red_sticker")
        fused = sa.fuse({n: sa.analyze_view(px) for n, px in rendered.views.items()})
        self.assertEqual(fused["decision"], "STOP")


class ScenarioRouting(unittest.TestCase):
    def test_every_scenario_routes_to_an_acceptable_decision(self):
        for scenario in SCENARIOS:
            if scenario.name == "normal_round_red_sticker":
                continue
            with self.subTest(scenario=scenario.name):
                rendered = render_scene(scenario, split="dev", index=0)
                fused = sa.fuse(
                    {n: sa.analyze_view(px) for n, px in rendered.views.items()}
                )
                self.assertIn(fused["decision"], scenario.acceptable, fused)
                if scenario.alarm_present:
                    self.assertNotEqual(fused["decision"], "REVIEW")


class AnalyzeSceneDecisions(SceneLedgerCase):
    def test_decision_changes_the_planned_follow_up(self):
        cases = (
            ("normal_green_clear", "REVIEW", "QUEUE_HUMAN_REVIEW"),
            ("normal_defocus", "REQUEST_VIEW", "REQUEST_NEW_CAPTURE"),
            ("alarm_red_side_only", "STOP", "HOLD_AUTOMATION"),
        )
        for name, decision, action in cases:
            with self.subTest(scenario=name):
                result = self.analyze(pair(scene(name), name))
                self.assertEqual(result["decision"], decision, result.get("reason"))
                self.assertEqual(result["physical_action"], "NONE")
                planned = plan_follow_up(result)
                self.assertEqual(planned["planned_action"], action)
                self.assertFalse(planned["action_executed"])
        evidence = result["evidence"]
        self.assertEqual(evidence["pipeline_version"], sa.PIPELINE_VERSION)
        self.assertEqual(evidence["config_sha256"], sa.CONFIG_SHA256)
        self.assertEqual(evidence["capture_replay_status"], "RECORDED")

    def test_identical_replay_is_idempotent(self):
        views = pair(scene("normal_green_clear"), "same")
        first = self.analyze(views)
        second = self.analyze(views)
        self.assertEqual(first["decision"], second["decision"])
        self.assertEqual(second["evidence"]["capture_replay_status"], "REPLAYED")


class AnalyzeSceneNegativeControls(SceneLedgerCase):
    def setUp(self):
        super().setUp()
        self.rendered = scene("normal_green_clear")

    def test_provenance_and_input_controls_fail_closed(self):
        good = pair(self.rendered, "ctl")
        wrong_shape = dict(good)
        wrong_shape["side"] = sa.SceneView(
            np.zeros((16, 24, 3), np.uint8), "camera-side-v1", "ctl-x", NOW - 1.0
        )
        shared = dict(good)
        shared["side"] = sa.SceneView(
            good["front"].pixels, "camera-side-v1", "ctl-shared", NOW - 1.0
        )
        cases = {
            "INCOMPLETE_COVERAGE": ({"front": good["front"]}, {}),
            "REPLAY_LEDGER_REQUIRED": (good, {"replay_ledger": None}),
            "STALE_OR_FUTURE_FRAME": (good, {"now": NOW + 60}),
            "INVALID_CAPTURE_TIME": (good, {"captured_at": float("nan")}),
            "INVALID_VIEW_CONTAINER": ([good["front"]], {}),
            "INVALID_FRAME": (wrong_shape, {}),
            "DUPLICATED_VIEW_BUFFER": (shared, {}),
            "PIPELINE_CONFIG_CHANGED": (
                good,
                {"config": {**sa.CONFIG, "min_sharpness": 0.0}},
            ),
        }
        for reason, (views, kwargs) in cases.items():
            with self.subTest(reason=reason):
                result = self.analyze(views, **kwargs)
                self.assertEqual(result["reason"], reason)
                self.assertNotEqual(result["decision"], "REVIEW")
                self.assertEqual(result["physical_action"], "NONE")

    def test_capture_identity_controls(self):
        good = pair(self.rendered, "id")
        duplicate = {
            name: sa.SceneView(v.pixels, v.source_id, "same-id", v.captured_at)
            for name, v in good.items()
        }
        wrong_source = dict(good)
        wrong_source["side"] = sa.SceneView(
            good["side"].pixels, "camera-unknown", "id-side", NOW - 1.0
        )
        skewed = dict(good)
        skewed["side"] = sa.SceneView(
            good["side"].pixels, "camera-side-v1", "id-side", NOW - 2.0
        )
        for reason, views in (
            ("DUPLICATED_CAPTURE_ID", duplicate),
            ("VIEW_SOURCE_MISMATCH", wrong_source),
            ("VIEW_CAPTURE_TIME_SKEW", skewed),
        ):
            with self.subTest(reason=reason):
                result = self.analyze(views)
                self.assertEqual(result["decision"], "REQUEST_VIEW")
                self.assertEqual(result["reason"], reason)

    def test_capture_id_reuse_with_different_pixels_stops(self):
        first = self.analyze(pair(self.rendered, "reuse"))
        self.assertEqual(first["decision"], "REVIEW")
        substituted = pair(scene("alarm_red_both_views"), "reuse")
        result = self.analyze(substituted)
        self.assertEqual(result["decision"], "STOP")
        self.assertEqual(result["reason"], "CAPTURE_ID_REPLAY_MISMATCH")


class EvaluationSmoke(unittest.TestCase):
    def test_pipeline_beats_baselines_without_unsafe_misses(self):
        report = evaluate("dev", 1)
        methods = report["methods"]
        pipeline = methods["pipeline"]
        self.assertEqual(pipeline["unsafe_miss_count"], 0)
        for baseline in (
            "baseline_naive_red",
            "baseline_legacy_brightness",
            "ablation_no_quality_gate",
        ):
            with self.subTest(baseline=baseline):
                self.assertGreater(
                    pipeline["acceptable_rate"], methods[baseline]["acceptable_rate"]
                )
        self.assertEqual(pipeline["request_view_recall_on_degraded"], 1.0)


class AnnotationOverlay(unittest.TestCase):
    def test_overlay_preserves_shape_and_marks_detection(self):
        pixels = scene("alarm_red_both_views").views["side"]
        result = sa.analyze_view(pixels)
        canvas = sa.annotate(pixels, result)
        self.assertEqual(canvas.shape, pixels.shape)
        self.assertFalse(np.array_equal(canvas, pixels))


if __name__ == "__main__":
    unittest.main()
