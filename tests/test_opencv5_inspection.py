from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import numpy as np

from vision.opencv5_inspection import (
    CALIBRATION_DIGEST,
    CAPTURE_ENVELOPE_SCHEMA_VERSION,
    CaptureReplayLedger,
    CaptureReplayAnchor,
    CaptureReplayAnchorState,
    CaptureReplayLedgerAnchorError,
    CaptureReplayLedgerDurabilityError,
    CaptureReplayLedgerIntegrityError,
    CaptureReplayLedgerSchemaError,
    MAX_BATCH_VIEW_TIME_DIVERGENCE_SECONDS,
    MAX_VIEW_CAPTURE_SKEW_SECONDS,
    OPENCV_VERSION,
    PACKAGE_VERSION,
    PIPELINE_VERSION,
    REPLAY_LEDGER_CAPTURE_TABLE_INFO,
    REPLAY_LEDGER_CAPTURE_TABLE_SQL,
    REPLAY_LEDGER_POLICY_TABLE_INFO,
    REPLAY_LEDGER_POLICY_TABLE_SQL,
    REPLAY_LEDGER_ROWSET_TABLE_INFO,
    REPLAY_LEDGER_ROWSET_TABLE_SQL,
    View,
    capture_envelope_sha256,
    frame,
    inspect,
    runtime_evidence,
    verify_consequence,
)


class FakeReplayAnchor(CaptureReplayAnchor):
    def __init__(self, state=None):
        self.state = state
        self.available = True
        self.fail_next_compare_and_swap = False
        self.compare_and_swap_calls = 0

    def read(self):
        if not self.available:
            raise OSError("fake anchor unavailable")
        return self.state

    def compare_and_swap(self, expected, replacement):
        self.compare_and_swap_calls += 1
        if not self.available:
            raise OSError("fake anchor unavailable")
        if self.fail_next_compare_and_swap:
            self.fail_next_compare_and_swap = False
            return False
        if self.state != expected:
            return False
        self.state = replacement
        return True


class ConcurrentRecoveryAnchor(FakeReplayAnchor):
    """Thread-safe fixture with deterministic recovery interleavings."""

    def __init__(self, state=None):
        super().__init__(state)
        self._state_lock = threading.Lock()
        self.recovery_barrier = None
        self.pause_after_advance = False
        self.anchor_advanced = threading.Event()
        self.release_advance = threading.Event()
        self.successful_advances = 0

    def read(self):
        if not self.available:
            raise OSError("fake anchor unavailable")
        with self._state_lock:
            return self.state

    def compare_and_swap(self, expected, replacement):
        self.compare_and_swap_calls += 1
        if not self.available:
            raise OSError("fake anchor unavailable")
        if self.fail_next_compare_and_swap:
            self.fail_next_compare_and_swap = False
            return False
        barrier = self.recovery_barrier
        if barrier is not None:
            barrier.wait(timeout=5)
        with self._state_lock:
            if self.state != expected:
                return False
            self.state = replacement
            self.successful_advances += 1
        if self.pause_after_advance:
            self.anchor_advanced.set()
            if not self.release_advance.wait(timeout=5):
                raise TimeoutError("recovery advance was not released")
        return True


class OpenCV5InspectionCases(unittest.TestCase):
    def view(self, name, *, pixels=None, visibility=1.0,
             source_id=None, capture_id=None, captured_at=100.0):
        return View(
            frame(False) if pixels is None else pixels,
            visibility,
            source_id=f"camera-{name}-v1" if source_id is None else source_id,
            capture_id=f"capture-{name}-001" if capture_id is None else capture_id,
            captured_at=captured_at,
        )

    def views(self, *, alarm=False, visibility=1.0):
        return {
            "front": self.view("front", visibility=visibility),
            "side": self.view("side", pixels=frame(alarm), visibility=visibility),
        }

    def call(self, views=None, **kwargs):
        replay_ledger = kwargs.pop("replay_ledger", None)
        owns_ledger = replay_ledger is None
        if owns_ledger:
            replay_ledger = CaptureReplayLedger(":memory:")
        try:
            return inspect(
                self.views() if views is None else views,
                captured_at=kwargs.pop("captured_at", 100),
                now=kwargs.pop("now", 101),
                replay_ledger=replay_ledger,
                **kwargs,
            )
        finally:
            if owns_ledger:
                replay_ledger.close()

    def replace_policy_table_without_constraints(self, path):
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                ALTER TABLE replay_ledger_policy
                RENAME TO replay_ledger_policy_old;
                CREATE TABLE replay_ledger_policy (
                    singleton INTEGER,
                    policy_schema_version INTEGER NOT NULL,
                    max_entries INTEGER NOT NULL,
                    max_wal_backlog_frames INTEGER NOT NULL,
                    max_new_entries_per_batch INTEGER NOT NULL
                );
                INSERT INTO replay_ledger_policy
                SELECT * FROM replay_ledger_policy_old;
                DROP TABLE replay_ledger_policy_old;
                """
            )

    def replace_capture_table_without_constraints(self, path):
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                ALTER TABLE capture_replay RENAME TO capture_replay_old;
                CREATE TABLE capture_replay (
                    capture_id TEXT,
                    envelope_schema_version INTEGER,
                    envelope_sha256 TEXT,
                    policy_sha256 TEXT
                );
                INSERT INTO capture_replay
                SELECT * FROM capture_replay_old;
                DROP TABLE capture_replay_old;
                """
            )

    def replace_rowset_table_without_constraints(self, path, *, duplicate=False):
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                ALTER TABLE replay_ledger_rowset
                RENAME TO replay_ledger_rowset_old;
                CREATE TABLE replay_ledger_rowset (
                    singleton INTEGER,
                    rowset_schema_version INTEGER,
                    row_count INTEGER,
                    rowset_sha256 TEXT
                );
                INSERT INTO replay_ledger_rowset
                SELECT * FROM replay_ledger_rowset_old;
                DROP TABLE replay_ledger_rowset_old;
                """
            )
            if duplicate:
                connection.execute(
                    "INSERT INTO replay_ledger_rowset "
                    "SELECT * FROM replay_ledger_rowset"
                )

    def test_exact_opencv5_runtime_is_recorded(self):
        evidence = runtime_evidence()
        self.assertEqual(evidence["opencv_version"], "5.0.0")
        self.assertEqual(evidence["package_version"], PACKAGE_VERSION)
        self.assertEqual(evidence["algorithm"], "cv2.threshold+cv2.countNonZero")

    def test_clear_views_still_require_human_review(self):
        result = self.call()
        self.assertEqual(result["decision"], "REVIEW")
        self.assertEqual(result["physical_action"], "NONE")

    def test_side_alarm_stops(self):
        self.assertEqual(self.call(self.views(alarm=True))["reason"], "ALARM")

    def test_missing_view_requests_another_view(self):
        result = self.call({"front": self.view("front")})
        self.assertEqual(result, {"decision": "REQUEST_VIEW", "reason": "INCOMPLETE_COVERAGE"})

    def test_invalid_view_container_stops_instead_of_raising_or_requesting(self):
        for views in (None, [], ("front", "side"), "front"):
            with self.subTest(views=views):
                self.assertEqual(
                    inspect(views, captured_at=100, now=101),
                    {"decision": "STOP", "reason": "INVALID_VIEW_CONTAINER"},
                )

    def test_invalid_view_item_stops_instead_of_raising(self):
        for invalid in (None, object(), frame(False)):
            with self.subTest(item_type=type(invalid).__name__):
                self.assertEqual(
                    self.call({"front": invalid, "side": self.view("side")}),
                    {"decision": "STOP", "reason": "INVALID_VIEW"},
                )

    def test_shared_pixel_buffer_cannot_satisfy_two_view_coverage(self):
        pixels = frame(False)
        for side_pixels in (pixels, pixels.view()):
            with self.subTest(exact_alias=side_pixels is pixels):
                self.assertEqual(
                    self.call({
                        "front": self.view("front", pixels=pixels),
                        "side": self.view("side", pixels=side_pixels),
                    }),
                    {"decision": "REQUEST_VIEW", "reason": "DUPLICATED_VIEW_BUFFER"},
                )

    def test_source_identity_is_bound_to_logical_view(self):
        result = self.call({
            "front": self.view("front", source_id="camera-side-v1"),
            "side": self.view("side"),
        })
        self.assertEqual(
            result,
            {"decision": "REQUEST_VIEW", "reason": "VIEW_SOURCE_MISMATCH"},
        )

    def test_capture_ids_must_be_present_and_distinct(self):
        missing = self.call({
            "front": self.view("front", capture_id=" "),
            "side": self.view("side"),
        })
        self.assertEqual(
            missing,
            {"decision": "REQUEST_VIEW", "reason": "INVALID_CAPTURE_ID"},
        )
        duplicate = self.call({
            "front": self.view("front", capture_id="capture-shared"),
            "side": self.view("side", capture_id="capture-shared"),
        })
        self.assertEqual(
            duplicate,
            {"decision": "REQUEST_VIEW", "reason": "DUPLICATED_CAPTURE_ID"},
        )

    def test_view_provenance_is_recorded_in_evidence(self):
        evidence = self.call()["evidence"]
        self.assertEqual(
            evidence["view_source_ids"],
            {"front": "camera-front-v1", "side": "camera-side-v1"},
        )
        self.assertEqual(
            evidence["capture_ids"],
            {"front": "capture-front-001", "side": "capture-side-001"},
        )
        self.assertEqual(
            evidence["capture_envelope_versions"],
            {
                "calibration_digest": CALIBRATION_DIGEST,
                "opencv_version": OPENCV_VERSION,
                "package_version": PACKAGE_VERSION,
                "pipeline_version": PIPELINE_VERSION,
                "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
            },
        )

    def test_capture_envelope_digest_binds_view_source_capture_and_pixels(self):
        result = self.call()
        observations = result["observations"]
        views = self.views()
        for name, view in views.items():
            envelope = {
                "calibration_digest": CALIBRATION_DIGEST,
                "capture_id": view.capture_id,
                "captured_at": 100.0,
                "logical_view": name,
                "opencv_version": OPENCV_VERSION,
                "package_version": PACKAGE_VERSION,
                "pixel_dtype": str(view.pixels.dtype),
                "pixel_shape": list(view.pixels.shape),
                "pipeline_version": PIPELINE_VERSION,
                "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
                "source_id": view.source_id,
                "view_captured_at": 100.0,
            }
            expected = hashlib.sha256(
                json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
                + b"\0"
                + view.pixels.tobytes()
            ).hexdigest()
            self.assertEqual(observations[name]["capture_envelope_sha256"], expected)

        self.assertEqual(
            observations["front"]["frame_sha256"],
            observations["side"]["frame_sha256"],
        )
        self.assertNotEqual(
            observations["front"]["capture_envelope_sha256"],
            observations["side"]["capture_envelope_sha256"],
        )

    def test_capture_envelope_digest_binds_all_interpretation_versions(self):
        view = self.view("front")
        contract = {
            "calibration_digest": CALIBRATION_DIGEST,
            "pipeline_version": PIPELINE_VERSION,
            "opencv_version": OPENCV_VERSION,
            "package_version": PACKAGE_VERSION,
        }
        baseline = capture_envelope_sha256("front", view, 100.0, **contract)
        variants = (
            {**contract, "calibration_digest": "changed-calibration"},
            {**contract, "pipeline_version": "opencv5-threshold-v2"},
            {**contract, "opencv_version": "5.0.1"},
            {**contract, "package_version": "5.0.0.94"},
        )
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    baseline,
                    capture_envelope_sha256("front", view, 100.0, **changed),
                )

    def test_capture_envelope_digest_binds_schema_version(self):
        view = self.view("front")
        contract = {
            "calibration_digest": CALIBRATION_DIGEST,
            "pipeline_version": PIPELINE_VERSION,
            "opencv_version": OPENCV_VERSION,
            "package_version": PACKAGE_VERSION,
        }
        current = capture_envelope_sha256("front", view, 100.0, **contract)
        changed = capture_envelope_sha256(
            "front", view, 100.0,
            schema_version=CAPTURE_ENVELOPE_SCHEMA_VERSION + 1,
            **contract,
        )
        self.assertNotEqual(current, changed)

    def test_replay_ledger_rejects_same_capture_under_changed_version_envelope(self):
        view = self.view("front")
        contract = {
            "calibration_digest": CALIBRATION_DIGEST,
            "pipeline_version": PIPELINE_VERSION,
            "opencv_version": OPENCV_VERSION,
            "package_version": PACKAGE_VERSION,
        }
        baseline = capture_envelope_sha256("front", view, 100.0, **contract)
        changed = capture_envelope_sha256(
            "front", view, 100.0,
            **{**contract, "package_version": "5.0.0.94"},
        )
        with CaptureReplayLedger(":memory:") as ledger:
            self.assertEqual(
                ledger.check_and_record({view.capture_id: baseline}),
                ("RECORDED", 1),
            )
            self.assertEqual(
                ledger.check_and_record({view.capture_id: changed}),
                ("MISMATCH", 1),
            )

    def test_capture_id_replay_rotates_envelope_but_not_pixel_hash(self):
        original = self.call()["observations"]["front"]
        replayed = self.views()
        replayed["front"] = self.view("front", capture_id="capture-front-002")
        changed = self.call(replayed)["observations"]["front"]
        self.assertEqual(original["frame_sha256"], changed["frame_sha256"])
        self.assertNotEqual(
            original["capture_envelope_sha256"],
            changed["capture_envelope_sha256"],
        )

    def test_capture_time_replay_rotates_envelope_not_pixel_hash(self):
        original_result = self.call()
        changed_result = self.call(captured_at=100.25, now=101.5)
        original = original_result["observations"]["front"]
        changed = changed_result["observations"]["front"]
        self.assertEqual(original["frame_sha256"], changed["frame_sha256"])
        self.assertNotEqual(
            original["capture_envelope_sha256"],
            changed["capture_envelope_sha256"],
        )
        self.assertEqual(original_result["evidence"]["captured_at"], 100.0)
        self.assertEqual(changed_result["evidence"]["captured_at"], 100.25)

    def test_valid_inspection_requires_replay_ledger(self):
        self.assertEqual(
            inspect(self.views(), captured_at=100, now=101),
            {"decision": "STOP", "reason": "REPLAY_LEDGER_REQUIRED"},
        )

    def test_exact_capture_replay_survives_ledger_restart(self):
        with tempfile.TemporaryDirectory(prefix="capture-replay-") as directory:
            path = Path(directory) / "captures.sqlite3"
            first_ledger = CaptureReplayLedger(path, max_entries=4)
            first = self.call(replay_ledger=first_ledger)
            self.assertEqual(first["decision"], "REVIEW")
            self.assertEqual(first["evidence"]["capture_replay_status"], "RECORDED")
            self.assertEqual(first["evidence"]["capture_replay_ledger_entries"], 2)
            first_ledger.close()

            restarted = CaptureReplayLedger(path, max_entries=4)
            replay = self.call(replay_ledger=restarted, now=101.5)
            self.assertEqual(replay["decision"], "REVIEW")
            self.assertEqual(replay["evidence"]["capture_replay_status"], "REPLAYED")
            self.assertEqual(restarted.entry_count(), 2)
            restarted.close()

    def test_replay_ledger_persists_envelope_schema_version(self):
        with tempfile.TemporaryDirectory(prefix="capture-schema-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
            connection = sqlite3.connect(path)
            try:
                versions = connection.execute(
                    "SELECT DISTINCT envelope_schema_version FROM capture_replay"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(versions, [(CAPTURE_ENVELOPE_SCHEMA_VERSION,)])

    def test_capture_rows_persist_policy_digest_and_replay_after_restart(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-binding-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                expected_policy = ledger.policy_digest()
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
            with sqlite3.connect(path) as connection:
                policy_digests = connection.execute(
                    "SELECT DISTINCT policy_sha256 FROM capture_replay"
                ).fetchall()
            self.assertEqual(policy_digests, [(expected_policy,)])

            with CaptureReplayLedger(path) as restarted:
                replay = self.call(replay_ledger=restarted, now=101.5)
                self.assertEqual(replay["decision"], "REVIEW")
                self.assertEqual(
                    replay["evidence"]["capture_replay_status"], "REPLAYED"
                )
                self.assertEqual(
                    replay["evidence"]["capture_replay_policy_sha256"],
                    expected_policy,
                )

    def test_unbound_capture_policy_schema_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-unbound-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    ALTER TABLE capture_replay RENAME TO capture_replay_bound;
                    CREATE TABLE capture_replay (
                        capture_id TEXT PRIMARY KEY,
                        envelope_schema_version INTEGER NOT NULL,
                        envelope_sha256 TEXT NOT NULL
                    );
                    INSERT INTO capture_replay
                    SELECT capture_id, envelope_schema_version, envelope_sha256
                    FROM capture_replay_bound;
                    DROP TABLE capture_replay_bound;
                    """
                )
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_CAPTURE_POLICY_MISSING",
            ):
                CaptureReplayLedger(path)

    def test_restart_rejects_capture_policy_digest_mismatch(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-mismatch-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE capture_replay SET policy_sha256 = ?",
                    ("b" * 64,),
                )
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_CAPTURE_POLICY_MISMATCH",
            ):
                CaptureReplayLedger(path)

    def test_runtime_capture_policy_digest_drift_stops_without_writing(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-runtime-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
                self.assertEqual(ledger.entry_count(), 2)
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "UPDATE capture_replay SET policy_sha256 = ? "
                        "WHERE capture_id = ?",
                        ("b" * 64, "capture-front-001"),
                    )
                self.assertEqual(
                    self.call(replay_ledger=ledger, now=101.5),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_POLICY_BINDING_MISMATCH",
                    },
                )
                self.assertEqual(ledger.entry_count(), 2)

    def test_capture_schema_digest_binds_canonical_ddl_and_metadata(self):
        with CaptureReplayLedger(":memory:") as ledger:
            identity = ledger.capture_schema_identity()
            expected_identity = {
                "ddl": " ".join(REPLAY_LEDGER_CAPTURE_TABLE_SQL.split()),
                "table_info": [
                    list(row) for row in REPLAY_LEDGER_CAPTURE_TABLE_INFO
                ],
            }
            self.assertEqual(identity["ddl"], expected_identity["ddl"])
            self.assertEqual(
                identity["table_info"], expected_identity["table_info"]
            )
            expected_digest = hashlib.sha256(
                json.dumps(
                    expected_identity,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            self.assertEqual(identity["sha256"], expected_digest)
            result = self.call(replay_ledger=ledger)
            self.assertEqual(
                result["evidence"]["capture_replay_schema_sha256"],
                expected_digest,
            )

    def test_restart_rejects_capture_extra_column(self):
        with tempfile.TemporaryDirectory(prefix="capture-schema-extra-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "ALTER TABLE capture_replay ADD COLUMN unbound TEXT"
                )
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_CAPTURE_SCHEMA_INVALID",
            ):
                CaptureReplayLedger(path)

    def test_restart_rejects_weakened_capture_constraints(self):
        with tempfile.TemporaryDirectory(prefix="capture-schema-weak-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
            self.replace_capture_table_without_constraints(path)
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_CAPTURE_SCHEMA_INVALID",
            ):
                CaptureReplayLedger(path)

    def test_runtime_capture_schema_drift_stops_without_writing(self):
        with tempfile.TemporaryDirectory(prefix="capture-schema-runtime-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "ALTER TABLE capture_replay ADD COLUMN unbound TEXT"
                    )
                self.assertEqual(
                    self.call(replay_ledger=ledger, now=101.5),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_SCHEMA_MISMATCH",
                    },
                )
                self.assertEqual(ledger.entry_count(), 2)

    def test_runtime_capture_schema_drift_after_preflight_rolls_back(self):
        with tempfile.TemporaryDirectory(prefix="capture-schema-race-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                original = ledger._capture_schema_matches_unlocked
                schema_checks = 0

                def drift_after_first_schema_check():
                    nonlocal schema_checks
                    matches = original()
                    schema_checks += 1
                    if schema_checks == 1:
                        with sqlite3.connect(path) as connection:
                            connection.execute(
                                "ALTER TABLE capture_replay "
                                "ADD COLUMN unbound TEXT"
                            )
                    return matches

                ledger._capture_schema_matches_unlocked = (
                    drift_after_first_schema_check
                )
                statements = []
                ledger._connection.set_trace_callback(statements.append)
                result = ledger.check_and_record({"capture-race": "a" * 64})
                ledger._connection.set_trace_callback(None)
                self.assertEqual(result, ("CAPTURE_SCHEMA_ERROR", 0))
                self.assertEqual(schema_checks, 2)
                self.assertEqual(
                    sum(
                        statement.lstrip().upper().startswith("BEGIN")
                        for statement in statements
                    ),
                    1,
                )
                self.assertEqual(ledger.entry_count(), 0)

    def test_rowset_commitment_persists_and_replays_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            entries = {
                "capture-front-rowset": "a" * 64,
                "capture-side-rowset": "b" * 64,
            }
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(
                    ledger.check_and_record(entries), ("RECORDED", 2)
                )
                first = ledger.rowset_identity()
                self.assertEqual(
                    first["rowset_schema_version"],
                    1,
                )
                self.assertEqual(first["row_count"], 2)
                self.assertEqual(len(first["sha256"]), 64)
            with CaptureReplayLedger(path) as restarted:
                self.assertEqual(
                    restarted.check_and_record(entries), ("REPLAYED", 2)
                )
                self.assertEqual(restarted.rowset_identity(), first)

    def test_restart_rejects_deleted_capture_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(
                    ledger.check_and_record({
                        "capture-kept": "a" * 64,
                        "capture-deleted": "b" * 64,
                    }),
                    ("RECORDED", 2),
                )
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "DELETE FROM capture_replay WHERE capture_id = ?",
                    ("capture-deleted",),
                )
            with self.assertRaisesRegex(
                CaptureReplayLedgerIntegrityError,
                "REPLAY_LEDGER_ROWSET_MISMATCH",
            ):
                CaptureReplayLedger(path)

    def test_runtime_deleted_capture_row_stops_without_restoring_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            ledger = CaptureReplayLedger(path)
            try:
                first = self.call(replay_ledger=ledger)
                self.assertEqual(first["evidence"]["capture_replay_ledger_entries"], 2)
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "DELETE FROM capture_replay WHERE capture_id = ?",
                        ("capture-side-001",),
                    )
                self.assertEqual(
                    self.call(replay_ledger=ledger, now=101.5),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_ROWSET_MISMATCH",
                    },
                )
                self.assertEqual(ledger.entry_count(), 1)
            finally:
                ledger.close()

    def test_runtime_rowset_drift_after_preflight_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(
                    ledger.check_and_record({
                        "capture-kept": "a" * 64,
                        "capture-deleted": "b" * 64,
                    }),
                    ("RECORDED", 2),
                )
                original = ledger._rowset_matches_unlocked
                calls = 0

                def delete_after_preflight():
                    nonlocal calls
                    calls += 1
                    matched = original()
                    if calls == 1:
                        with sqlite3.connect(path) as connection:
                            connection.execute(
                                "DELETE FROM capture_replay WHERE capture_id = ?",
                                ("capture-deleted",),
                            )
                    return matched

                ledger._rowset_matches_unlocked = delete_after_preflight
                self.assertEqual(
                    ledger.check_and_record({"capture-new": "c" * 64}),
                    ("ROWSET_ERROR", 1),
                )
                with sqlite3.connect(path) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM capture_replay "
                            "WHERE capture_id = 'capture-new'"
                        ).fetchone()[0],
                        0,
                    )

    def test_existing_bound_ledger_without_rowset_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(
                    ledger.check_and_record({"capture-bound": "a" * 64}),
                    ("RECORDED", 1),
                )
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE replay_ledger_rowset")
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_ROWSET_METADATA_MISSING",
            ):
                CaptureReplayLedger(path)

    def test_rowset_metadata_schema_digest_binds_ddl_and_table_info(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                identity = ledger.rowset_schema_identity()
                expected = {
                    "ddl": " ".join(REPLAY_LEDGER_ROWSET_TABLE_SQL.split()),
                    "table_info": [
                        list(row) for row in REPLAY_LEDGER_ROWSET_TABLE_INFO
                    ],
                }
                expected_digest = hashlib.sha256(
                    json.dumps(
                        expected, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                self.assertEqual(identity, {**expected, "sha256": expected_digest})
                result = self.call(replay_ledger=ledger)
                self.assertEqual(
                    result["evidence"]["capture_replay_rowset_schema_sha256"],
                    expected_digest,
                )
            with CaptureReplayLedger(path) as restarted:
                self.assertEqual(
                    restarted.rowset_schema_identity()["sha256"],
                    expected_digest,
                )

    def test_restart_rejects_rowset_metadata_extra_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path):
                pass
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "ALTER TABLE replay_ledger_rowset ADD COLUMN unbound TEXT"
                )
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_ROWSET_METADATA_INVALID",
            ):
                CaptureReplayLedger(path)

    def test_restart_rejects_weakened_rowset_metadata_constraints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path):
                pass
            self.replace_rowset_table_without_constraints(path)
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_ROWSET_METADATA_INVALID",
            ):
                CaptureReplayLedger(path)

    def test_restart_rejects_duplicate_rowset_metadata_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path):
                pass
            self.replace_rowset_table_without_constraints(path, duplicate=True)
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_ROWSET_METADATA_INVALID",
            ):
                CaptureReplayLedger(path)

    def test_runtime_rowset_metadata_schema_drift_has_specific_stop_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            ledger = CaptureReplayLedger(path)
            try:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "ALTER TABLE replay_ledger_rowset "
                        "ADD COLUMN unbound TEXT"
                    )
                self.assertEqual(
                    self.call(replay_ledger=ledger, now=101.5),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_ROWSET_SCHEMA_MISMATCH",
                    },
                )
                self.assertEqual(ledger.entry_count(), 2)
            finally:
                ledger.close()

    def test_runtime_rowset_schema_drift_after_preflight_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                original = ledger._rowset_schema_matches_unlocked
                checks = 0

                def drift_after_preflight():
                    nonlocal checks
                    checks += 1
                    matched = original()
                    if checks == 1:
                        with sqlite3.connect(path) as connection:
                            connection.execute(
                                "ALTER TABLE replay_ledger_rowset "
                                "ADD COLUMN unbound TEXT"
                            )
                    return matched

                ledger._rowset_schema_matches_unlocked = drift_after_preflight
                statements = []
                ledger._connection.set_trace_callback(statements.append)
                result = ledger.check_and_record({"capture-race": "a" * 64})
                ledger._connection.set_trace_callback(None)
                self.assertEqual(result, ("ROWSET_SCHEMA_ERROR", 0))
                self.assertEqual(checks, 2)
                self.assertEqual(
                    sum(
                        statement.lstrip().upper().startswith("BEGIN")
                        for statement in statements
                    ),
                    1,
                )
                self.assertEqual(ledger.entry_count(), 0)

    def test_full_snapshot_rollback_is_accepted_without_anchor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            old_snapshot = Path(temp_dir) / "older-valid.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(
                    ledger.check_and_record({"capture-old": "a" * 64}),
                    ("RECORDED", 1),
                )
            shutil.copy2(path, old_snapshot)
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(
                    ledger.check_and_record({"capture-new": "b" * 64}),
                    ("RECORDED", 2),
                )
                newest_identity = ledger.rowset_identity()
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{path}{suffix}")
                if sidecar.exists():
                    sidecar.unlink()
            shutil.copy2(old_snapshot, path)

            with CaptureReplayLedger(path) as restored:
                restored_identity = restored.rowset_identity()
                self.assertEqual(restored.entry_count(), 1)
                self.assertEqual(
                    restored.check_and_record({"capture-old": "a" * 64}),
                    ("REPLAYED", 1),
                )
            self.assertNotEqual(restored_identity, newest_identity)

    def test_anchor_bootstrap_and_record_advance_are_compare_and_swap(self):
        anchor = FakeReplayAnchor()
        with CaptureReplayLedger(":memory:", anchor=anchor) as ledger:
            self.assertEqual(anchor.state.sequence, 0)
            self.assertEqual(
                ledger.check_and_record({"capture-anchor": "a" * 64}),
                ("RECORDED", 1),
            )
            self.assertEqual(anchor.state.sequence, 1)
            self.assertEqual(
                ledger.anchor_evidence(),
                {
                    "mode": "CONFIGURED_FIXTURE_OR_EXTERNAL",
                    **anchor.state.as_dict(),
                },
            )
        self.assertEqual(anchor.compare_and_swap_calls, 2)

    def test_anchor_ahead_rejects_restored_older_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            old_snapshot = Path(temp_dir) / "older-valid.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                ledger.check_and_record({"capture-old": "a" * 64})
            shutil.copy2(path, old_snapshot)
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                ledger.check_and_record({"capture-new": "b" * 64})
            shutil.copy2(old_snapshot, path)
            with self.assertRaisesRegex(
                CaptureReplayLedgerAnchorError,
                "REPLAY_LEDGER_SNAPSHOT_ROLLBACK",
            ):
                CaptureReplayLedger(path, anchor=anchor)

    def test_equal_anchor_sequence_with_wrong_digest_is_rejected(self):
        anchor = FakeReplayAnchor()
        with CaptureReplayLedger(":memory:", anchor=anchor):
            pass
        anchor.state = CaptureReplayAnchorState(
            sequence=anchor.state.sequence,
            rowset_sha256="f" * 64,
            policy_sha256=anchor.state.policy_sha256,
            capture_schema_sha256=anchor.state.capture_schema_sha256,
            rowset_schema_sha256=anchor.state.rowset_schema_sha256,
        )
        with self.assertRaisesRegex(
            CaptureReplayLedgerAnchorError,
            "REPLAY_LEDGER_ANCHOR_MISMATCH",
        ):
            CaptureReplayLedger(":memory:", anchor=anchor)

    def test_anchor_behind_existing_database_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                ledger.check_and_record({"capture-existing": "a" * 64})
            anchor = FakeReplayAnchor(
                CaptureReplayAnchorState(
                    sequence=0,
                    rowset_sha256="0" * 64,
                    policy_sha256="0" * 64,
                    capture_schema_sha256="0" * 64,
                    rowset_schema_sha256="0" * 64,
                )
            )
            with self.assertRaisesRegex(
                CaptureReplayLedgerAnchorError,
                "REPLAY_LEDGER_ANCHOR_BEHIND",
            ):
                CaptureReplayLedger(path, anchor=anchor)

    def test_failed_anchor_cas_leaves_committed_row_but_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            ledger = CaptureReplayLedger(path, anchor=anchor)
            try:
                anchor.fail_next_compare_and_swap = True
                self.assertEqual(
                    ledger.check_and_record({"capture-crash": "a" * 64}),
                    ("ANCHOR_ERROR", 1),
                )
                self.assertEqual(ledger.entry_count(), 1)
            finally:
                ledger.close()
            with CaptureReplayLedger(path, anchor=anchor) as recovering:
                self.assertIsNotNone(
                    recovering.pending_anchor_recovery_receipt()
                )
                self.assertEqual(
                    recovering.check_and_record(
                        {"capture-blocked": "b" * 64}
                    ),
                    ("ANCHOR_ERROR", 1),
                )

    def test_anchor_recovery_receipt_reconciles_db_ahead_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                self.assertEqual(
                    ledger.check_and_record({"capture-recover": "a" * 64}),
                    ("ANCHOR_ERROR", 1),
                )
                receipt = ledger.pending_anchor_recovery_receipt()
                self.assertEqual(receipt["expected"]["sequence"], 0)
                self.assertEqual(receipt["replacement"]["sequence"], 1)

            with CaptureReplayLedger(path, anchor=anchor) as recovering:
                self.assertEqual(
                    recovering.check_and_record({"capture-other": "b" * 64}),
                    ("ANCHOR_ERROR", 1),
                )
                result = recovering.recover_anchor(receipt)
                self.assertEqual(result["status"], "RECOVERED")
                self.assertEqual(anchor.state.sequence, 1)
                self.assertIsNone(
                    recovering.pending_anchor_recovery_receipt()
                )
                self.assertEqual(
                    recovering.check_and_record(
                        {"capture-recover": "a" * 64}
                    ),
                    ("REPLAYED", 1),
                )

    def test_anchor_recovery_rejects_tampered_receipt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                ledger.check_and_record({"capture-tamper": "a" * 64})
                receipt = ledger.pending_anchor_recovery_receipt()
                tampered = json.loads(json.dumps(receipt))
                tampered["replacement"]["rowset_sha256"] = "f" * 64
                with self.assertRaisesRegex(
                    CaptureReplayLedgerAnchorError,
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID",
                ):
                    ledger.recover_anchor(tampered)
                self.assertEqual(anchor.state.sequence, 0)
                self.assertEqual(
                    ledger.pending_anchor_recovery_receipt(), receipt
                )

    def test_anchor_recovery_rejects_stale_receipt_after_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                ledger.check_and_record({"capture-stale": "a" * 64})
                receipt = ledger.pending_anchor_recovery_receipt()
                self.assertEqual(
                    ledger.recover_anchor(receipt)["status"], "RECOVERED"
                )
                with self.assertRaisesRegex(
                    CaptureReplayLedgerAnchorError,
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_NOT_PENDING",
                ):
                    ledger.recover_anchor(receipt)

    def test_anchor_recovery_rejects_receipt_for_other_transition(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                ledger.check_and_record({"capture-current": "a" * 64})
                current = ledger.pending_anchor_recovery_receipt()
                other = json.loads(json.dumps(current))
                other["transition_id"] = "0" * 64
                with self.assertRaisesRegex(
                    CaptureReplayLedgerAnchorError,
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID",
                ):
                    ledger.recover_anchor(other)
                self.assertEqual(anchor.state.sequence, 0)

    def test_anchor_recovery_revalidates_persisted_commitments(self):
        mutations = {
            "rowset": (
                "UPDATE capture_replay SET envelope_sha256 = ?",
                ("b" * 64,),
            ),
            "policy": (
                "UPDATE replay_ledger_policy "
                "SET max_entries = max_entries + 1",
                (),
            ),
            "capture_schema": (
                "ALTER TABLE capture_replay ADD COLUMN attacker TEXT",
                (),
            ),
        }
        for name, (statement, parameters) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "replay.sqlite3"
                anchor = FakeReplayAnchor()
                with CaptureReplayLedger(path, anchor=anchor) as ledger:
                    anchor.fail_next_compare_and_swap = True
                    ledger.check_and_record({"capture-bound": "a" * 64})
                    receipt = ledger.pending_anchor_recovery_receipt()
                    with sqlite3.connect(path) as connection:
                        connection.execute(statement, parameters)
                    with self.assertRaisesRegex(
                        CaptureReplayLedgerAnchorError,
                        "REPLAY_LEDGER_ANCHOR_RECOVERY_STATE_MISMATCH",
                    ):
                        ledger.recover_anchor(receipt)
                    self.assertEqual(anchor.state.sequence, 0)

    def test_concurrent_anchor_recovery_has_one_cas_winner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = ConcurrentRecoveryAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                self.assertEqual(
                    ledger.check_and_record({"capture-race": "a" * 64}),
                    ("ANCHOR_ERROR", 1),
                )
                receipt = ledger.pending_anchor_recovery_receipt()
            first = CaptureReplayLedger(path, anchor=anchor)
            second = CaptureReplayLedger(path, anchor=anchor)
            try:
                calls_before_recovery = anchor.compare_and_swap_calls
                advances_before_recovery = anchor.successful_advances
                anchor.recovery_barrier = threading.Barrier(2)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(first.recover_anchor, receipt),
                        pool.submit(second.recover_anchor, receipt),
                    ]
                    results = [future.result() for future in futures]
                self.assertEqual(
                    sorted(result["status"] for result in results),
                    ["ALREADY_ADVANCED", "RECOVERED"],
                )
                self.assertEqual(
                    {result["transition_id"] for result in results},
                    {receipt["transition_id"]},
                )
                self.assertEqual(
                    anchor.compare_and_swap_calls - calls_before_recovery,
                    2,
                )
                self.assertEqual(
                    anchor.successful_advances - advances_before_recovery,
                    1,
                )
                self.assertEqual(anchor.state.sequence, 1)
                self.assertIsNone(first.pending_anchor_recovery_receipt())
                self.assertIsNone(second.pending_anchor_recovery_receipt())
            finally:
                first.close()
                second.close()

    def test_admission_is_blocked_after_advance_until_marker_clear(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = ConcurrentRecoveryAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                self.assertEqual(
                    ledger.check_and_record({"capture-pending": "a" * 64}),
                    ("ANCHOR_ERROR", 1),
                )
                receipt = ledger.pending_anchor_recovery_receipt()
            recovering = CaptureReplayLedger(path, anchor=anchor)
            admitting = CaptureReplayLedger(path, anchor=anchor)
            anchor.pause_after_advance = True
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(recovering.recover_anchor, receipt)
                    self.assertTrue(anchor.anchor_advanced.wait(timeout=5))
                    self.assertEqual(anchor.state.sequence, 1)
                    self.assertIsNotNone(
                        admitting.pending_anchor_recovery_receipt()
                    )
                    self.assertEqual(
                        admitting.check_and_record(
                            {"capture-blocked": "b" * 64}
                        ),
                        ("ANCHOR_ERROR", 1),
                    )
                    anchor.release_advance.set()
                    self.assertEqual(future.result()["status"], "RECOVERED")
                anchor.pause_after_advance = False
                self.assertIsNone(
                    admitting.pending_anchor_recovery_receipt()
                )
                self.assertEqual(
                    admitting.check_and_record(
                        {"capture-after-recovery": "c" * 64}
                    ),
                    ("RECORDED", 2),
                )
            finally:
                anchor.release_advance.set()
                recovering.close()
                admitting.close()
            with CaptureReplayLedger(path, anchor=anchor) as restarted:
                self.assertIsNone(
                    restarted.pending_anchor_recovery_receipt()
                )
                self.assertEqual(restarted.entry_count(), 2)
                self.assertEqual(anchor.state.sequence, 2)

    def test_failed_concurrent_recovery_keeps_marker_and_blocks_admission(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = ConcurrentRecoveryAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                ledger.check_and_record({"capture-retry": "a" * 64})
                receipt = ledger.pending_anchor_recovery_receipt()
                anchor.available = False
                with self.assertRaisesRegex(
                    CaptureReplayLedgerAnchorError,
                    "REPLAY_LEDGER_ANCHOR_UNAVAILABLE",
                ):
                    ledger.recover_anchor(receipt)
                self.assertEqual(
                    ledger.pending_anchor_recovery_receipt(), receipt
                )
                self.assertEqual(
                    ledger.check_and_record({"capture-blocked": "b" * 64}),
                    ("ANCHOR_ERROR", 1),
                )
                anchor.available = True
                self.assertEqual(
                    ledger.recover_anchor(receipt)["status"], "RECOVERED"
                )
                self.assertIsNone(
                    ledger.pending_anchor_recovery_receipt()
                )

    def test_restart_clears_exact_marker_after_anchor_advanced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                self.assertEqual(
                    ledger.check_and_record(
                        {"capture-post-advance-crash": "a" * 64}
                    ),
                    ("ANCHOR_ERROR", 1),
                )
                receipt = ledger.pending_anchor_recovery_receipt()
            anchor.state = CaptureReplayLedger._anchor_state_from_dict(
                receipt["replacement"]
            )

            with CaptureReplayLedger(path, anchor=anchor) as restarted:
                self.assertIsNone(
                    restarted.pending_anchor_recovery_receipt()
                )
                self.assertEqual(
                    restarted.check_and_record(
                        {"capture-post-advance-crash": "a" * 64}
                    ),
                    ("REPLAYED", 1),
                )
            with CaptureReplayLedger(path, anchor=anchor) as second_restart:
                self.assertIsNone(
                    second_restart.pending_anchor_recovery_receipt()
                )
                self.assertEqual(second_restart.entry_count(), 1)

    def test_restart_rejects_valid_marker_for_different_replacement(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                ledger.check_and_record({"capture-marker-mismatch": "a" * 64})
                receipt = ledger.pending_anchor_recovery_receipt()
            local_state = CaptureReplayLedger._anchor_state_from_dict(
                receipt["replacement"]
            )
            anchor.state = local_state
            wrong_replacement = CaptureReplayAnchorState(
                sequence=local_state.sequence,
                rowset_sha256="f" * 64,
                policy_sha256=local_state.policy_sha256,
                capture_schema_sha256=local_state.capture_schema_sha256,
                rowset_schema_sha256=local_state.rowset_schema_sha256,
            )
            wrong_receipt = CaptureReplayLedger._make_anchor_recovery_receipt(
                CaptureReplayLedger._anchor_state_from_dict(
                    receipt["expected"]
                ),
                wrong_replacement,
            )
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE replay_ledger_anchor_transition SET "
                    "transition_id = ?, receipt_json = ?, receipt_sha256 = ? "
                    "WHERE singleton = 1",
                    (
                        wrong_receipt["transition_id"],
                        json.dumps(
                            wrong_receipt,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        wrong_receipt["receipt_sha256"],
                    ),
                )

            with self.assertRaisesRegex(
                CaptureReplayLedgerAnchorError,
                "REPLAY_LEDGER_ANCHOR_RECOVERY_STATE_MISMATCH",
            ):
                CaptureReplayLedger(path, anchor=anchor)
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT transition_id "
                        "FROM replay_ledger_anchor_transition"
                    ).fetchone()[0],
                    wrong_receipt["transition_id"],
                )

    def test_restart_rejects_partial_same_sequence_anchor_and_keeps_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                ledger.check_and_record({"capture-partial-anchor": "a" * 64})
                receipt = ledger.pending_anchor_recovery_receipt()
            local_state = CaptureReplayLedger._anchor_state_from_dict(
                receipt["replacement"]
            )
            anchor.state = CaptureReplayAnchorState(
                sequence=local_state.sequence,
                rowset_sha256=local_state.rowset_sha256,
                policy_sha256="f" * 64,
                capture_schema_sha256=local_state.capture_schema_sha256,
                rowset_schema_sha256=local_state.rowset_schema_sha256,
            )

            with self.assertRaisesRegex(
                CaptureReplayLedgerAnchorError,
                "REPLAY_LEDGER_ANCHOR_MISMATCH",
            ):
                CaptureReplayLedger(path, anchor=anchor)
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT transition_id "
                        "FROM replay_ledger_anchor_transition"
                    ).fetchone()[0],
                    receipt["transition_id"],
                )

    def test_marker_clear_failure_keeps_startup_closed_until_retry_commits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            ledger = CaptureReplayLedger(path, anchor=anchor)
            try:
                anchor.fail_next_compare_and_swap = True
                self.assertEqual(
                    ledger.check_and_record(
                        {"capture-clear-failure": "a" * 64}
                    ),
                    ("ANCHOR_ERROR", 1),
                )
                receipt = ledger.pending_anchor_recovery_receipt()
                anchor.state = CaptureReplayLedger._anchor_state_from_dict(
                    receipt["replacement"]
                )
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "CREATE TRIGGER fail_anchor_marker_clear "
                        "BEFORE DELETE ON replay_ledger_anchor_transition "
                        "BEGIN SELECT RAISE(ABORT, 'marker clear fault'); END"
                    )
                self.assertEqual(
                    ledger.check_and_record(
                        {"capture-still-blocked": "b" * 64}
                    ),
                    ("ANCHOR_ERROR", 1),
                )
            finally:
                ledger.close()

            for _ in range(2):
                with self.assertRaisesRegex(
                    CaptureReplayLedgerAnchorError,
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_CLEAR_FAILED",
                ):
                    CaptureReplayLedger(path, anchor=anchor)
                with sqlite3.connect(path) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) "
                            "FROM replay_ledger_anchor_transition"
                        ).fetchone()[0],
                        1,
                    )

            with sqlite3.connect(path) as connection:
                connection.execute("DROP TRIGGER fail_anchor_marker_clear")
            with CaptureReplayLedger(path, anchor=anchor) as restarted:
                self.assertIsNone(
                    restarted.pending_anchor_recovery_receipt()
                )
                self.assertEqual(
                    restarted.check_and_record(
                        {"capture-clear-failure": "a" * 64}
                    ),
                    ("REPLAYED", 1),
                )
            with CaptureReplayLedger(path, anchor=anchor) as second_restart:
                self.assertIsNone(
                    second_restart.pending_anchor_recovery_receipt()
                )
                self.assertEqual(second_restart.entry_count(), 1)

    def test_marker_delete_process_crash_rolls_back_before_commit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                self.assertEqual(
                    ledger.check_and_record(
                        {"capture-clear-commit-crash": "a" * 64}
                    ),
                    ("ANCHOR_ERROR", 1),
                )
                receipt = ledger.pending_anchor_recovery_receipt()
            anchor.state = CaptureReplayLedger._anchor_state_from_dict(
                receipt["replacement"]
            )

            script = (
                Path(__file__).resolve().parents[1]
                / "ops"
                / "replay_ledger_anchor_marker_clear_commit_crash_probe.py"
            )
            child = subprocess.run(
                [sys.executable, script, "--crash-child", str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(child.returncode, 73, child.stderr)
            self.assertEqual(
                json.loads(child.stdout),
                {
                    "marker_count_inside_transaction": 0,
                    "phase": "AFTER_DELETE_BEFORE_COMMIT",
                },
            )
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) "
                        "FROM replay_ledger_anchor_transition"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("PRAGMA quick_check").fetchone()[0],
                    "ok",
                )

            with CaptureReplayLedger(path, anchor=anchor) as restarted:
                self.assertIsNone(
                    restarted.pending_anchor_recovery_receipt()
                )
                self.assertEqual(
                    restarted.check_and_record(
                        {"capture-clear-commit-crash": "a" * 64}
                    ),
                    ("REPLAYED", 1),
                )
            with CaptureReplayLedger(path, anchor=anchor) as second_restart:
                self.assertIsNone(
                    second_restart.pending_anchor_recovery_receipt()
                )
                self.assertEqual(second_restart.entry_count(), 1)

    def test_db_commit_process_crash_preserves_row_and_receipt_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            script = (
                Path(__file__).resolve().parents[1]
                / "ops"
                / "replay_ledger_anchor_db_commit_process_crash_probe.py"
            )
            child = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--crash-before-anchor-cas",
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(child.returncode, 74, child.stderr)
            self.assertEqual(
                json.loads(child.stdout),
                {
                    "capture_count_visible_to_second_connection": 1,
                    "marker_count_visible_to_second_connection": 1,
                    "phase": "AFTER_DB_COMMIT_BEFORE_ANCHOR_CAS",
                    "quick_check": "ok",
                    "replacement_sequence": 1,
                },
            )

            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM capture_replay"
                    ).fetchone()[0],
                    1,
                )
                marker = connection.execute(
                    "SELECT receipt_json "
                    "FROM replay_ledger_anchor_transition"
                ).fetchone()
                self.assertIsNotNone(marker)
                receipt = json.loads(marker[0])
                self.assertEqual(
                    connection.execute("PRAGMA quick_check").fetchone()[0],
                    "ok",
                )

            anchor = FakeReplayAnchor(
                CaptureReplayLedger._anchor_state_from_dict(
                    receipt["expected"]
                )
            )
            with CaptureReplayLedger(path, anchor=anchor) as restarted:
                self.assertEqual(
                    restarted.pending_anchor_recovery_receipt(), receipt
                )
                self.assertEqual(
                    restarted.check_and_record(
                        {"capture-must-stay-blocked": "b" * 64}
                    ),
                    ("ANCHOR_ERROR", 1),
                )
                recovery = restarted.recover_anchor(receipt)
                self.assertEqual(recovery["status"], "RECOVERED")
                self.assertEqual(recovery["sequence"], 1)
                self.assertIsNone(
                    restarted.pending_anchor_recovery_receipt()
                )
                self.assertEqual(
                    restarted.check_and_record(
                        {"capture-db-commit-crash": "a" * 64}
                    ),
                    ("REPLAYED", 1),
                )
            with CaptureReplayLedger(path, anchor=anchor) as second_restart:
                self.assertIsNone(
                    second_restart.pending_anchor_recovery_receipt()
                )
                self.assertEqual(second_restart.entry_count(), 1)

    def test_anchor_cas_process_crash_recovers_persisted_replacement_once(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_anchor_cas_process_crash_probe.py"
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
            evidence["anchor_mode"],
            "FILE_BACKED_SINGLE_WRITER_CRASH_FIXTURE_ONLY",
        )
        self.assertEqual(evidence["trusted_live_anchor"], "NOT_RUN")
        result = evidence["result"]
        self.assertEqual(result["child_exit_code"], 75)
        self.assertEqual(
            result["child_observation"]["phase"],
            "AFTER_DURABLE_ANCHOR_CAS_BEFORE_MARKER_CLEAR",
        )
        self.assertEqual(
            result["child_observation"]["anchor_sequence"], 1
        )
        self.assertEqual(
            result["child_observation"][
                "capture_count_visible_to_second_connection"
            ],
            1,
        )
        self.assertEqual(
            result["child_observation"][
                "marker_count_visible_to_second_connection"
            ],
            1,
        )
        self.assertEqual(result["after_crash"]["marker_count"], 1)
        self.assertEqual(result["persisted_anchor_sequence_after_crash"], 1)
        self.assertEqual(
            result["child_observation"]["anchor_file_sha256"],
            result["anchor_file_sha256"],
        )
        self.assertEqual(result["after_first_restart"]["marker_count"], 0)
        self.assertEqual(
            result["after_first_restart"]["anchor_clear_count"], 1
        )
        self.assertIsNone(result["pending_after_restart"])
        self.assertEqual(result["replay_after_restart"], ["REPLAYED", 1])
        self.assertEqual(result["second_restart"]["marker_count"], 0)
        self.assertEqual(
            result["second_restart"]["anchor_clear_count"], 1
        )
        self.assertIsNone(result["second_restart"]["pending"])
        self.assertEqual(
            result["second_restart"]["replay"], ["REPLAYED", 1]
        )

    def test_file_anchor_co_rollback_exposes_same_domain_limit(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_file_anchor_co_rollback_falsifier.py"
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
            evidence["anchor_mode"],
            "SAME_DOMAIN_FILE_FIXTURE_ONLY",
        )
        self.assertEqual(evidence["trusted_live_anchor"], "NOT_RUN")
        result = evidence["result"]
        self.assertEqual(result["sequence_one"]["capture_count"], 1)
        self.assertEqual(result["sequence_two"]["capture_count"], 2)
        self.assertEqual(
            result["database_only_rollback"],
            "REPLAY_LEDGER_SNAPSHOT_ROLLBACK",
        )
        self.assertEqual(
            result["anchor_only_rollback"],
            "REPLAY_LEDGER_ANCHOR_BEHIND",
        )
        self.assertEqual(
            result["co_rollback"]["startup"], "ACCEPTED_STALE_PAIR"
        )
        self.assertEqual(
            result["co_rollback"]["replay"], ["REPLAYED", 1]
        )
        self.assertEqual(result["co_rollback"]["capture_count"], 1)
        self.assertEqual(result["co_rollback"]["anchor_sequence"], 1)
        self.assertEqual(
            result["independent_witness"], "ROLLBACK_DETECTED"
        )
        self.assertNotEqual(
            result["sequence_one"]["database_sha256"],
            result["sequence_two"]["database_sha256"],
        )
        self.assertNotEqual(
            result["sequence_one"]["anchor_sha256"],
            result["sequence_two"]["anchor_sha256"],
        )

    def test_explicit_recovery_clear_failure_is_retryable_after_anchor_advance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.sqlite3"
            anchor = FakeReplayAnchor()
            with CaptureReplayLedger(path, anchor=anchor) as ledger:
                anchor.fail_next_compare_and_swap = True
                ledger.check_and_record(
                    {"capture-recovery-clear-failure": "a" * 64}
                )
                receipt = ledger.pending_anchor_recovery_receipt()
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "CREATE TRIGGER fail_anchor_marker_clear "
                        "BEFORE DELETE ON replay_ledger_anchor_transition "
                        "BEGIN SELECT RAISE(ABORT, 'marker clear fault'); END"
                    )
                with self.assertRaisesRegex(
                    CaptureReplayLedgerAnchorError,
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_CLEAR_FAILED",
                ):
                    ledger.recover_anchor(receipt)
                self.assertEqual(anchor.state.sequence, 1)
                self.assertEqual(
                    ledger.pending_anchor_recovery_receipt(), receipt
                )
                self.assertEqual(
                    ledger.check_and_record(
                        {"capture-still-blocked": "b" * 64}
                    ),
                    ("ANCHOR_ERROR", 1),
                )
                with self.assertRaisesRegex(
                    CaptureReplayLedgerAnchorError,
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_CLEAR_FAILED",
                ):
                    ledger.recover_anchor(receipt)
                with sqlite3.connect(path) as connection:
                    connection.execute("DROP TRIGGER fail_anchor_marker_clear")

            with CaptureReplayLedger(path, anchor=anchor) as restarted:
                self.assertIsNone(
                    restarted.pending_anchor_recovery_receipt()
                )
                self.assertEqual(restarted.entry_count(), 1)

    def test_anchor_unavailable_fails_closed_before_admission(self):
        anchor = FakeReplayAnchor()
        with CaptureReplayLedger(":memory:", anchor=anchor) as ledger:
            anchor.available = False
            self.assertEqual(
                ledger.check_and_record({"capture-offline": "a" * 64}),
                ("ANCHOR_ERROR", 0),
            )
            self.assertEqual(ledger.entry_count(), 0)

    def test_inspection_maps_anchor_failure_to_stop(self):
        anchor = FakeReplayAnchor()
        with CaptureReplayLedger(":memory:", anchor=anchor) as ledger:
            anchor.available = False
            result = self.call(replay_ledger=ledger)
        self.assertEqual(result["decision"], "STOP")
        self.assertEqual(result["reason"], "CAPTURE_REPLAY_ANCHOR_ERROR")

    def test_legacy_replay_ledger_schema_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="capture-legacy-") as directory:
            path = Path(directory) / "captures.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE capture_replay ("
                "capture_id TEXT PRIMARY KEY, envelope_sha256 TEXT NOT NULL)"
            )
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError, "LEGACY_REPLAY_LEDGER_SCHEMA"
            ):
                CaptureReplayLedger(path)

    def test_mixed_replay_ledger_schema_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="capture-mixed-") as directory:
            path = Path(directory) / "captures.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(REPLAY_LEDGER_CAPTURE_TABLE_SQL)
            connection.executemany(
                "INSERT INTO capture_replay VALUES (?, ?, ?, ?)",
                (("capture-current", CAPTURE_ENVELOPE_SCHEMA_VERSION, "a" * 64, "c" * 64),
                 ("capture-future", CAPTURE_ENVELOPE_SCHEMA_VERSION + 1, "b" * 64, "c" * 64)),
            )
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError, "MIXED_REPLAY_LEDGER_SCHEMA"
            ):
                CaptureReplayLedger(path)

    def test_runtime_replay_schema_drift_stops(self):
        with tempfile.TemporaryDirectory(prefix="capture-drift-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
                connection = sqlite3.connect(path)
                connection.execute(
                    "UPDATE capture_replay SET envelope_schema_version = ? "
                    "WHERE capture_id = ?",
                    (CAPTURE_ENVELOPE_SCHEMA_VERSION + 1, "capture-front-001"),
                )
                connection.commit()
                connection.close()
                self.assertEqual(
                    self.call(replay_ledger=ledger, now=101.5),
                    {"decision": "STOP", "reason": "CAPTURE_REPLAY_SCHEMA_MISMATCH"},
                )

    def test_replay_ledger_integrity_validation(self):
        with CaptureReplayLedger(":memory:") as ledger:
            self.assertEqual(ledger.check_and_record({" ": "a" * 64}), ("INVALID_ENTRY", 0))
            self.assertEqual(ledger.check_and_record({"ok": "A" * 64}), ("INVALID_ENTRY", 0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.db"
            connection = sqlite3.connect(path)
            connection.execute(REPLAY_LEDGER_CAPTURE_TABLE_SQL)
            connection.execute("INSERT INTO capture_replay VALUES (?, ?, ?, ?)", (" bad", CAPTURE_ENVELOPE_SCHEMA_VERSION, "a" * 64, "c" * 64))
            connection.commit(); connection.close()
            with self.assertRaisesRegex(CaptureReplayLedgerIntegrityError, "INVALID_REPLAY_LEDGER_ROW"):
                CaptureReplayLedger(path)

    def test_runtime_replay_row_corruption_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.db"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")
                connection = sqlite3.connect(path)
                connection.execute("UPDATE capture_replay SET envelope_sha256='invalid' WHERE capture_id='capture-front-001'")
                connection.commit(); connection.close()
                self.assertEqual(self.call(replay_ledger=ledger, now=101.5), {"decision": "STOP", "reason": "CAPTURE_REPLAY_INTEGRITY_ERROR"})

    def test_corrupt_sqlite_file_is_rejected_at_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.db"
            path.write_bytes(b"not a sqlite database")
            with self.assertRaisesRegex(CaptureReplayLedgerIntegrityError, "SQLITE_INTEGRITY_CHECK_FAILED"):
                CaptureReplayLedger(path)

    def test_file_replay_ledger_pins_wal_full_sync_and_busy_timeout(self):
        with tempfile.TemporaryDirectory(prefix="capture-durability-") as directory:
            path = Path(directory) / "ledger.db"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(
                    ledger.durability_evidence(),
                    {
                        "journal_mode": "wal",
                        "synchronous": 2,
                        "wal_autocheckpoint": 1000,
                        "busy_timeout_ms": 5000,
                    },
                )

    def test_durability_pragma_drift_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="capture-durability-drift-") as directory:
            path = Path(directory) / "ledger.db"
            with CaptureReplayLedger(path) as ledger:
                ledger._connection.execute("PRAGMA synchronous = OFF")
                self.assertEqual(
                    self.call(replay_ledger=ledger),
                    {"decision": "STOP", "reason": "CAPTURE_REPLAY_DURABILITY_ERROR"},
                )

    def test_restart_recovers_committed_row_and_discards_interrupted_writer(self):
        with tempfile.TemporaryDirectory(prefix="capture-wal-recovery-") as directory:
            path = Path(directory) / "ledger.db"
            committed_digest = "a" * 64
            with CaptureReplayLedger(path, max_entries=1000) as ledger:
                self.assertEqual(
                    ledger.check_and_record({"capture-committed": committed_digest}),
                    ("RECORDED", 1),
                )

            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os,sqlite3,sys;"
                        "c=sqlite3.connect(sys.argv[1],isolation_level=None);"
                        "assert c.execute('PRAGMA journal_mode').fetchone()[0]=='wal';"
                        "c.execute('PRAGMA cache_size=1');"
                        "c.execute('BEGIN IMMEDIATE');"
                        "p=c.execute('SELECT policy_sha256 FROM capture_replay LIMIT 1').fetchone()[0];"
                        "c.executemany('INSERT INTO capture_replay VALUES (?,?,?,?)',"
                        "[(f'interrupted-{i:04d}',1,'b'*64,p) for i in range(500)]);"
                        "os._exit(17)"
                    ),
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(child.returncode, 17, child.stderr)

            with CaptureReplayLedger(path, max_entries=1000) as restarted:
                self.assertEqual(restarted.entry_count(), 1)
                self.assertEqual(
                    restarted.check_and_record(
                        {"capture-committed": committed_digest}
                    ),
                    ("REPLAYED", 1),
                )
                rows = restarted._connection.execute(
                    "SELECT capture_id FROM capture_replay ORDER BY capture_id"
                ).fetchall()
                self.assertEqual(rows, [("capture-committed",)])

    def test_checkpoint_mode_validation_and_memory_semantics(self):
        with CaptureReplayLedger(":memory:") as ledger:
            self.assertEqual(
                ledger.checkpoint("PASSIVE"),
                {
                    "status": "NOT_APPLICABLE",
                    "mode": "PASSIVE",
                    "busy": 0,
                    "log_frames": 0,
                    "checkpointed_frames": 0,
                    "backlog_frames": 0,
                    "backlog_limit_frames": 1000,
                },
            )
            with self.assertRaisesRegex(ValueError, "checkpoint mode"):
                ledger.checkpoint("DELETE")

    def test_reader_snapshot_allows_partial_then_truncate_checkpoint_recovery(self):
        with tempfile.TemporaryDirectory(prefix="capture-checkpoint-") as directory:
            path = Path(directory) / "ledger.db"
            with CaptureReplayLedger(path, max_entries=1000) as ledger:
                self.assertEqual(
                    ledger.check_and_record({"capture-baseline": "a" * 64}),
                    ("RECORDED", 1),
                )
                reader = sqlite3.connect(path, isolation_level=None)
                try:
                    reader.execute("PRAGMA query_only = ON")
                    reader.execute("BEGIN")
                    self.assertEqual(
                        reader.execute(
                            "SELECT COUNT(*) FROM capture_replay"
                        ).fetchone(),
                        (1,),
                    )
                    entries = {
                        f"capture-checkpoint-{index:03d}": "b" * 64
                        for index in range(100)
                    }
                    self.assertEqual(
                        ledger.check_and_record(entries),
                        ("RECORDED", 101),
                    )
                    self.assertEqual(
                        reader.execute(
                            "SELECT COUNT(*) FROM capture_replay"
                        ).fetchone(),
                        (1,),
                    )
                    started = time.monotonic()
                    partial = ledger.checkpoint("PASSIVE")
                    elapsed = time.monotonic() - started
                    self.assertEqual(partial["status"], "PARTIAL")
                    self.assertEqual(partial["busy"], 0)
                    self.assertGreater(
                        partial["log_frames"],
                        partial["checkpointed_frames"],
                    )
                    self.assertLess(elapsed, 1.0)
                finally:
                    reader.execute("COMMIT")
                    reader.close()

                completed = ledger.checkpoint("TRUNCATE")
                self.assertEqual(
                    completed,
                    {
                        "status": "COMPLETE",
                        "mode": "TRUNCATE",
                        "busy": 0,
                        "log_frames": 0,
                        "checkpointed_frames": 0,
                        "backlog_frames": 0,
                        "backlog_limit_frames": 1000,
                    },
                )
                wal_path = Path(f"{path}-wal")
                self.assertTrue(not wal_path.exists() or wal_path.stat().st_size == 0)

            with CaptureReplayLedger(path, max_entries=1000) as restarted:
                self.assertEqual(restarted.entry_count(), 101)
                self.assertEqual(
                    restarted.checkpoint("TRUNCATE")["status"],
                    "COMPLETE",
                )

    def test_checkpoint_rejects_runtime_durability_drift(self):
        with tempfile.TemporaryDirectory(prefix="capture-checkpoint-drift-") as directory:
            path = Path(directory) / "ledger.db"
            with CaptureReplayLedger(path) as ledger:
                ledger._connection.execute("PRAGMA synchronous = OFF")
                with self.assertRaisesRegex(
                    CaptureReplayLedgerDurabilityError,
                    "REPLAY_LEDGER_DURABILITY_DRIFT",
                ):
                    ledger.checkpoint("PASSIVE")

    def test_replay_backlog_limit_configuration_is_validated(self):
        for invalid in (0, -1, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "max_wal_backlog_frames"):
                    CaptureReplayLedger(
                        ":memory:", max_wal_backlog_frames=invalid
                    )

    def test_reader_starvation_exceeding_backlog_limit_fails_closed_then_recovers(self):
        with tempfile.TemporaryDirectory(prefix="capture-backlog-") as directory:
            path = Path(directory) / "ledger.db"
            with CaptureReplayLedger(
                path, max_entries=1000, max_wal_backlog_frames=1
            ) as ledger:
                self.assertEqual(
                    ledger.check_and_record({"capture-baseline": "a" * 64}),
                    ("RECORDED", 1),
                )
                reader = sqlite3.connect(path, isolation_level=None)
                try:
                    reader.execute("PRAGMA query_only = ON")
                    reader.execute("BEGIN")
                    self.assertEqual(
                        reader.execute(
                            "SELECT COUNT(*) FROM capture_replay"
                        ).fetchone(),
                        (1,),
                    )
                    entries = {
                        f"capture-backlog-{index:03d}": "b" * 64
                        for index in range(200)
                    }
                    self.assertEqual(
                        ledger.check_and_record(entries),
                        ("RECORDED", 201),
                    )
                    limited = ledger.checkpoint("PASSIVE")
                    self.assertEqual(limited["status"], "LIMIT_EXCEEDED")
                    self.assertGreater(limited["backlog_frames"], 1)
                    self.assertEqual(limited["backlog_limit_frames"], 1)
                    self.assertEqual(
                        ledger.check_and_record({"capture-refused": "c" * 64}),
                        ("BACKLOG_LIMIT", 201),
                    )
                    self.assertEqual(ledger.entry_count(), 201)
                finally:
                    reader.execute("COMMIT")
                    reader.close()

                recovered = ledger.checkpoint("TRUNCATE")
                self.assertEqual(recovered["status"], "COMPLETE")
                self.assertEqual(recovered["backlog_frames"], 0)
                self.assertEqual(
                    ledger.check_and_record({"capture-recovered": "d" * 64}),
                    ("RECORDED", 202),
                )

            with CaptureReplayLedger(
                path, max_entries=1000, max_wal_backlog_frames=1
            ) as restarted:
                self.assertEqual(restarted.entry_count(), 202)

    def test_inspection_maps_replay_backlog_limit_to_stop(self):
        with tempfile.TemporaryDirectory(prefix="capture-backlog-inspect-") as directory:
            path = Path(directory) / "ledger.db"
            with CaptureReplayLedger(
                path, max_entries=1000, max_wal_backlog_frames=1
            ) as ledger:
                self.assertEqual(
                    ledger.check_and_record({"capture-baseline": "a" * 64}),
                    ("RECORDED", 1),
                )
                reader = sqlite3.connect(path, isolation_level=None)
                try:
                    reader.execute("BEGIN")
                    reader.execute(
                        "SELECT COUNT(*) FROM capture_replay"
                    ).fetchone()
                    self.assertEqual(
                        ledger.check_and_record({
                            f"capture-inspect-{index:03d}": "b" * 64
                            for index in range(200)
                        }),
                        ("RECORDED", 201),
                    )
                    self.assertEqual(
                        self.call(
                            {
                                "front": self.view(
                                    "front", capture_id="capture-front-backlog"
                                ),
                                "side": self.view(
                                    "side", capture_id="capture-side-backlog"
                                ),
                            },
                            replay_ledger=ledger,
                        ),
                        {
                            "decision": "STOP",
                            "reason": "CAPTURE_REPLAY_BACKLOG_LIMIT",
                        },
                    )
                finally:
                    reader.execute("COMMIT")
                    reader.close()

    def test_memory_ledger_startup_checkpoint_is_not_applicable(self):
        with CaptureReplayLedger(
            ":memory:", max_wal_backlog_frames=7
        ) as ledger:
            self.assertEqual(
                ledger.startup_checkpoint_evidence(),
                {
                    "status": "NOT_APPLICABLE",
                    "mode": "PASSIVE",
                    "busy": 0,
                    "log_frames": 0,
                    "checkpointed_frames": 0,
                    "backlog_frames": 0,
                    "backlog_limit_frames": 7,
                },
            )

    def test_clean_restart_records_complete_startup_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="capture-clean-restart-") as directory:
            path = Path(directory) / "ledger.db"
            with CaptureReplayLedger(
                path, max_wal_backlog_frames=1
            ) as ledger:
                self.assertEqual(
                    ledger.check_and_record({"capture-clean": "a" * 64}),
                    ("RECORDED", 1),
                )
            with CaptureReplayLedger(
                path, max_wal_backlog_frames=1
            ) as restarted:
                startup = restarted.startup_checkpoint_evidence()
                self.assertEqual(startup["status"], "COMPLETE")
                self.assertEqual(startup["backlog_frames"], 0)
                self.assertEqual(startup["backlog_limit_frames"], 1)

    def test_backlog_limit_survives_writer_restart_before_new_admission(self):
        with tempfile.TemporaryDirectory(prefix="capture-backlog-restart-") as directory:
            path = Path(directory) / "ledger.db"
            writer = CaptureReplayLedger(
                path, max_entries=1000, max_wal_backlog_frames=1
            )
            reader = None
            restarted = None
            try:
                self.assertEqual(
                    writer.check_and_record({"capture-baseline": "a" * 64}),
                    ("RECORDED", 1),
                )
                reader = sqlite3.connect(path, isolation_level=None)
                reader.execute("PRAGMA query_only = ON")
                reader.execute("BEGIN")
                self.assertEqual(
                    reader.execute(
                        "SELECT COUNT(*) FROM capture_replay"
                    ).fetchone(),
                    (1,),
                )
                self.assertEqual(
                    writer.check_and_record({
                        f"capture-restart-{index:03d}": "b" * 64
                        for index in range(200)
                    }),
                    ("RECORDED", 201),
                )
                before_close = writer.checkpoint("PASSIVE")
                self.assertEqual(before_close["status"], "LIMIT_EXCEEDED")
                writer.close()
                writer = None
                self.assertGreater(Path(f"{path}-wal").stat().st_size, 0)

                restarted = CaptureReplayLedger(
                    path, max_entries=1000, max_wal_backlog_frames=1
                )
                startup = restarted.startup_checkpoint_evidence()
                self.assertEqual(startup["status"], "LIMIT_EXCEEDED")
                self.assertGreater(startup["backlog_frames"], 1)
                self.assertEqual(
                    restarted.check_and_record(
                        {"capture-refused-after-restart": "c" * 64}
                    ),
                    ("BACKLOG_LIMIT", 201),
                )
                self.assertEqual(restarted.entry_count(), 201)

                reader.execute("COMMIT")
                reader.close()
                reader = None
                self.assertEqual(
                    restarted.checkpoint("TRUNCATE")["status"],
                    "COMPLETE",
                )
                self.assertEqual(
                    restarted.check_and_record(
                        {"capture-recovered-after-restart": "d" * 64}
                    ),
                    ("RECORDED", 202),
                )
            finally:
                if reader is not None:
                    reader.execute("ROLLBACK")
                    reader.close()
                if writer is not None:
                    writer.close()
                if restarted is not None:
                    restarted.close()

            with CaptureReplayLedger(
                path, max_entries=1000, max_wal_backlog_frames=1
            ) as final:
                self.assertEqual(final.entry_count(), 202)

    def test_new_entry_batch_limit_configuration_is_validated(self):
        for invalid in (0, -1, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    ValueError, "max_new_entries_per_batch"
                ):
                    CaptureReplayLedger(
                        ":memory:", max_new_entries_per_batch=invalid
                    )

    def test_oversized_new_batch_is_rejected_before_write_transaction(self):
        with CaptureReplayLedger(
            ":memory:",
            max_entries=20,
            max_new_entries_per_batch=2,
        ) as ledger:
            statements = []
            ledger._connection.set_trace_callback(statements.append)
            self.assertEqual(
                ledger.check_and_record({
                    "capture-batch-1": "a" * 64,
                    "capture-batch-2": "b" * 64,
                    "capture-batch-3": "c" * 64,
                }),
                ("BATCH_LIMIT", 0),
            )
            ledger._connection.set_trace_callback(None)
            self.assertFalse(any(
                statement.lstrip().upper().startswith("BEGIN")
                for statement in statements
            ))
            self.assertEqual(ledger.entry_count(), 0)

            first = {
                "capture-batch-1": "a" * 64,
                "capture-batch-2": "b" * 64,
            }
            third = {"capture-batch-3": "c" * 64}
            self.assertEqual(
                ledger.check_and_record(first), ("RECORDED", 2)
            )
            self.assertEqual(
                ledger.check_and_record(third), ("RECORDED", 3)
            )
            self.assertEqual(
                ledger.check_and_record({**first, **third}),
                ("REPLAYED", 3),
            )

            mixed = {
                "capture-batch-1": "a" * 64,
                "capture-new-1": "d" * 64,
                "capture-new-2": "e" * 64,
                "capture-new-3": "f" * 64,
            }
            statements = []
            ledger._connection.set_trace_callback(statements.append)
            self.assertEqual(
                ledger.check_and_record(mixed), ("BATCH_LIMIT", 3)
            )
            ledger._connection.set_trace_callback(None)
            self.assertFalse(any(
                statement.lstrip().upper().startswith("BEGIN")
                for statement in statements
            ))
            self.assertEqual(ledger.entry_count(), 3)

    def test_inspection_maps_new_entry_batch_limit_to_stop(self):
        with CaptureReplayLedger(
            ":memory:", max_new_entries_per_batch=1
        ) as ledger:
            self.assertEqual(
                self.call(replay_ledger=ledger),
                {
                    "decision": "STOP",
                    "reason": "CAPTURE_REPLAY_BATCH_LIMIT",
                },
            )
            self.assertEqual(ledger.entry_count(), 0)

    def test_replay_ledger_persists_admission_policy(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-") as directory:
            path = Path(directory) / "captures.sqlite3"
            expected = {
                "policy_schema_version": 1,
                "max_entries": 17,
                "max_wal_backlog_frames": 19,
                "max_new_entries_per_batch": 3,
            }
            with CaptureReplayLedger(
                path,
                max_entries=17,
                max_wal_backlog_frames=19,
                max_new_entries_per_batch=3,
            ) as ledger:
                self.assertEqual(ledger.policy_evidence(), expected)

            connection = sqlite3.connect(path)
            try:
                row = connection.execute(
                    "SELECT policy_schema_version, max_entries, "
                    "max_wal_backlog_frames, max_new_entries_per_batch "
                    "FROM replay_ledger_policy WHERE singleton = 1"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row, (1, 17, 19, 3))

            with CaptureReplayLedger(
                path,
                max_entries=17,
                max_wal_backlog_frames=19,
                max_new_entries_per_batch=3,
            ) as restarted:
                self.assertEqual(restarted.policy_evidence(), expected)

    def test_policy_digest_binds_canonical_schema_and_values(self):
        with CaptureReplayLedger(
            ":memory:",
            max_entries=17,
            max_wal_backlog_frames=19,
            max_new_entries_per_batch=3,
        ) as ledger:
            payload = {
                "ddl": " ".join(REPLAY_LEDGER_POLICY_TABLE_SQL.split()),
                "table_info": [
                    list(row) for row in REPLAY_LEDGER_POLICY_TABLE_INFO
                ],
                "values": {
                    "policy_schema_version": 1,
                    "max_entries": 17,
                    "max_wal_backlog_frames": 19,
                    "max_new_entries_per_batch": 3,
                },
            }
            expected = hashlib.sha256(
                json.dumps(
                    payload, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            self.assertEqual(ledger.policy_digest(), expected)

    def test_policy_digest_is_restart_stable_and_policy_sensitive(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-digest-") as directory:
            root = Path(directory)
            path = root / "captures.sqlite3"
            with CaptureReplayLedger(path, max_entries=17) as ledger:
                first = ledger.policy_digest()
            with CaptureReplayLedger(path, max_entries=17) as restarted:
                self.assertEqual(restarted.policy_digest(), first)
            with CaptureReplayLedger(
                root / "different.sqlite3", max_entries=18
            ) as different:
                self.assertNotEqual(different.policy_digest(), first)

    def test_inspection_exposes_admitted_policy_digest(self):
        with CaptureReplayLedger(":memory:") as ledger:
            first = self.call(replay_ledger=ledger)
            replay = self.call(replay_ledger=ledger)
            self.assertEqual(
                first["evidence"]["capture_replay_policy_sha256"],
                ledger.policy_digest(),
            )
            self.assertEqual(
                replay["evidence"]["capture_replay_policy_sha256"],
                first["evidence"]["capture_replay_policy_sha256"],
            )

    def test_policy_digest_rejects_runtime_policy_drift(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-digest-drift-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "UPDATE replay_ledger_policy "
                        "SET max_entries = max_entries + 1 "
                        "WHERE singleton = 1"
                    )
                with self.assertRaisesRegex(
                    CaptureReplayLedgerSchemaError,
                    "REPLAY_LEDGER_POLICY_DRIFT",
                ):
                    ledger.policy_digest()

    def test_replay_ledger_rejects_restart_policy_drift(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-drift-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(
                path,
                max_entries=17,
                max_wal_backlog_frames=19,
                max_new_entries_per_batch=3,
            ):
                pass

            drifted = (
                {"max_entries": 18},
                {"max_wal_backlog_frames": 20},
                {"max_new_entries_per_batch": 4},
            )
            baseline = {
                "max_entries": 17,
                "max_wal_backlog_frames": 19,
                "max_new_entries_per_batch": 3,
            }
            for override in drifted:
                with self.subTest(override=override):
                    with self.assertRaisesRegex(
                        CaptureReplayLedgerSchemaError,
                        "REPLAY_LEDGER_POLICY_DRIFT",
                    ):
                        CaptureReplayLedger(path, **(baseline | override))

            with CaptureReplayLedger(path, **baseline) as unchanged:
                self.assertEqual(
                    unchanged.policy_evidence(),
                    {"policy_schema_version": 1, **baseline},
                )

    def test_existing_ledger_without_policy_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-legacy-") as directory:
            path = Path(directory) / "captures.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(REPLAY_LEDGER_CAPTURE_TABLE_SQL)
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(
                CaptureReplayLedgerSchemaError,
                "REPLAY_LEDGER_POLICY_METADATA_MISSING",
            ):
                CaptureReplayLedger(path)

    def test_runtime_policy_value_drift_stops_without_writing(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-runtime-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.assertEqual(
                    self.call(replay_ledger=ledger)["decision"], "REVIEW"
                )
                self.assertEqual(ledger.entry_count(), 2)

                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "UPDATE replay_ledger_policy "
                        "SET max_entries = max_entries + 1 "
                        "WHERE singleton = 1"
                    )
                self.assertEqual(
                    self.call(replay_ledger=ledger, now=101.5),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_POLICY_DRIFT",
                    },
                )
                self.assertEqual(ledger.entry_count(), 2)

                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "UPDATE replay_ledger_policy SET max_entries = ? "
                        "WHERE singleton = 1",
                        (ledger.max_entries,),
                    )
                self.assertEqual(
                    self.call(replay_ledger=ledger, now=101.5)["decision"],
                    "REVIEW",
                )
                self.assertEqual(ledger.entry_count(), 2)

    def test_runtime_policy_drift_after_preflight_rolls_back(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-race-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                original = ledger._policy_evidence_unlocked
                reads = 0

                def mutate_after_first_policy_read():
                    nonlocal reads
                    evidence = original()
                    reads += 1
                    if reads == 1:
                        with sqlite3.connect(path) as connection:
                            connection.execute(
                                "UPDATE replay_ledger_policy "
                                "SET max_new_entries_per_batch = "
                                "max_new_entries_per_batch + 1 "
                                "WHERE singleton = 1"
                            )
                    return evidence

                ledger._policy_evidence_unlocked = (
                    mutate_after_first_policy_read
                )
                statements = []
                ledger._connection.set_trace_callback(statements.append)
                self.assertEqual(
                    ledger.check_and_record({"capture-policy-race": "a" * 64}),
                    ("POLICY_ERROR", 0),
                )
                ledger._connection.set_trace_callback(None)
                self.assertEqual(reads, 2)
                self.assertEqual(
                    sum(
                        statement.lstrip().upper().startswith("BEGIN")
                        for statement in statements
                    ),
                    1,
                )
                self.assertEqual(ledger.entry_count(), 0)

    def test_runtime_missing_policy_metadata_stops(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-missing-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                with sqlite3.connect(path) as connection:
                    connection.execute("DROP TABLE replay_ledger_policy")
                self.assertEqual(
                    self.call(replay_ledger=ledger),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_POLICY_DRIFT",
                    },
                )
                self.assertEqual(ledger.entry_count(), 0)

    def test_runtime_policy_extra_row_stops_without_writing(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-cardinality-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.replace_policy_table_without_constraints(path)
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "INSERT INTO replay_ledger_policy "
                        "SELECT 2, policy_schema_version, max_entries, "
                        "max_wal_backlog_frames, max_new_entries_per_batch "
                        "FROM replay_ledger_policy WHERE singleton = 1"
                    )
                self.assertEqual(
                    self.call(replay_ledger=ledger),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_POLICY_DRIFT",
                    },
                )
                self.assertEqual(ledger.entry_count(), 0)

    def test_runtime_policy_primary_key_shape_drift_stops(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-pk-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                self.replace_policy_table_without_constraints(path)
                self.assertEqual(
                    self.call(replay_ledger=ledger),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_POLICY_DRIFT",
                    },
                )
                self.assertEqual(ledger.entry_count(), 0)

    def test_runtime_policy_extra_column_stops(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-column-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "ALTER TABLE replay_ledger_policy "
                        "ADD COLUMN unbound_policy TEXT"
                    )
                self.assertEqual(
                    self.call(replay_ledger=ledger),
                    {
                        "decision": "STOP",
                        "reason": "CAPTURE_REPLAY_POLICY_DRIFT",
                    },
                )
                self.assertEqual(ledger.entry_count(), 0)

    def test_runtime_policy_schema_drift_after_preflight_rolls_back(self):
        with tempfile.TemporaryDirectory(prefix="capture-policy-schema-race-") as directory:
            path = Path(directory) / "captures.sqlite3"
            with CaptureReplayLedger(path) as ledger:
                schema_checks = 0

                def drift_after_first_schema_check():
                    nonlocal schema_checks
                    schema_checks += 1
                    if schema_checks == 1:
                        self.replace_policy_table_without_constraints(path)
                        return True
                    return False

                ledger._policy_schema_matches_unlocked = (
                    drift_after_first_schema_check
                )
                statements = []
                ledger._connection.set_trace_callback(statements.append)
                self.assertEqual(
                    ledger.check_and_record({"capture-schema-race": "a" * 64}),
                    ("POLICY_ERROR", 0),
                )
                ledger._connection.set_trace_callback(None)
                self.assertEqual(schema_checks, 2)
                self.assertEqual(
                    sum(
                        statement.lstrip().upper().startswith("BEGIN")
                        for statement in statements
                    ),
                    1,
                )
                self.assertEqual(ledger.entry_count(), 0)

    def test_capture_id_reuse_with_changed_envelope_stops(self):
        ledger = CaptureReplayLedger(":memory:")
        try:
            self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")

            changed_pixels = frame(False)
            changed_pixels[0, 0] = 1
            pixels_result = self.call({
                "front": self.view("front", pixels=changed_pixels),
                "side": self.view("side"),
            }, replay_ledger=ledger)
            self.assertEqual(
                pixels_result,
                {"decision": "STOP", "reason": "CAPTURE_ID_REPLAY_MISMATCH"},
            )

            time_result = self.call({
                "front": self.view("front", captured_at=100.01),
                "side": self.view("side"),
            }, replay_ledger=ledger)
            self.assertEqual(
                time_result,
                {"decision": "STOP", "reason": "CAPTURE_ID_REPLAY_MISMATCH"},
            )

            source_result = self.call({
                "front": self.view("front", source_id="camera-side-v1"),
                "side": self.view("side"),
            }, replay_ledger=ledger)
            self.assertEqual(
                source_result,
                {"decision": "REQUEST_VIEW", "reason": "VIEW_SOURCE_MISMATCH"},
            )
            self.assertEqual(ledger.entry_count(), 2)
        finally:
            ledger.close()

    def test_replay_ledger_capacity_is_fail_closed_and_atomic(self):
        with tempfile.TemporaryDirectory(prefix="capture-capacity-") as directory:
            path = Path(directory) / "captures.sqlite3"
            ledger = CaptureReplayLedger(path, max_entries=2)
            self.assertEqual(self.call(replay_ledger=ledger)["decision"], "REVIEW")

            result = self.call({
                "front": self.view("front", capture_id="capture-front-002"),
                "side": self.view("side", capture_id="capture-side-002"),
            }, replay_ledger=ledger)
            self.assertEqual(
                result,
                {"decision": "STOP", "reason": "CAPTURE_REPLAY_LEDGER_FULL"},
            )
            self.assertEqual(ledger.entry_count(), 2)
            ledger.close()

            restarted = CaptureReplayLedger(path, max_entries=2)
            self.assertEqual(restarted.entry_count(), 2)
            restarted.close()

    def test_concurrent_changed_replay_has_one_winner(self):
        with tempfile.TemporaryDirectory(prefix="capture-race-") as directory:
            path = Path(directory) / "captures.sqlite3"
            first_ledger = CaptureReplayLedger(path, max_entries=4)
            second_ledger = CaptureReplayLedger(path, max_entries=4)
            changed_pixels = frame(False)
            changed_pixels[0, 0] = 1
            changed_views = {
                "front": self.view("front", pixels=changed_pixels),
                "side": self.view("side"),
            }
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(self.call, self.views(), replay_ledger=first_ledger),
                        pool.submit(self.call, changed_views, replay_ledger=second_ledger),
                    ]
                    results = [future.result() for future in futures]
                outcomes = sorted((result["decision"], result["reason"])
                                  for result in results)
                self.assertEqual(outcomes, [
                    ("REVIEW", "HUMAN_REVIEW"),
                    ("STOP", "CAPTURE_ID_REPLAY_MISMATCH"),
                ])
                self.assertEqual(first_ledger.entry_count(), 2)
            finally:
                first_ledger.close()
                second_ledger.close()

    def test_batch_time_divergence_before_or_after_views_stops(self):
        views = {
            "front": self.view("front", captured_at=100.0),
            "side": self.view("side", captured_at=100.125),
        }
        for batch_time in (99.7, 100.5):
            with self.subTest(batch_time=batch_time):
                self.assertEqual(
                    self.call(views, captured_at=batch_time),
                    {"decision": "STOP", "reason": "BATCH_VIEW_TIME_DIVERGENCE"},
                )

    def test_batch_view_time_divergence_boundary_is_inclusive(self):
        views = {
            "front": self.view("front", captured_at=100.0),
            "side": self.view("side", captured_at=100.125),
        }
        earliest = 100.0
        latest = 100.125
        tolerance = MAX_BATCH_VIEW_TIME_DIVERGENCE_SECONDS
        for batch_time in (earliest - tolerance, latest + tolerance):
            with self.subTest(batch_time=batch_time):
                self.assertEqual(
                    self.call(views, captured_at=batch_time)["decision"],
                    "REVIEW",
                )
        for batch_time in (
            earliest - tolerance - 0.001,
            latest + tolerance + 0.001,
        ):
            with self.subTest(batch_time=batch_time):
                self.assertEqual(
                    self.call(views, captured_at=batch_time),
                    {"decision": "STOP", "reason": "BATCH_VIEW_TIME_DIVERGENCE"},
                )

    def test_batch_view_time_divergence_is_recorded(self):
        views = {
            "front": self.view("front", captured_at=100.0),
            "side": self.view("side", captured_at=100.125),
        }
        inside = self.call(views, captured_at=100.1)["evidence"]
        self.assertEqual(inside["batch_view_time_divergence_seconds"], 0.0)
        self.assertEqual(
            inside["batch_view_time_tolerance_seconds"],
            MAX_BATCH_VIEW_TIME_DIVERGENCE_SECONDS,
        )

        boundary = self.call(
            views,
            captured_at=100.0 - MAX_BATCH_VIEW_TIME_DIVERGENCE_SECONDS,
        )["evidence"]
        self.assertEqual(
            boundary["batch_view_time_divergence_seconds"],
            MAX_BATCH_VIEW_TIME_DIVERGENCE_SECONDS,
        )

    def test_invalid_per_view_capture_times_stop(self):
        for value in (None, "100", float("nan"), float("inf"), True):
            with self.subTest(value=value):
                result = self.call({
                    "front": self.view("front", captured_at=value),
                    "side": self.view("side"),
                })
                self.assertEqual(
                    result,
                    {"decision": "STOP", "reason": "INVALID_VIEW_CAPTURE_TIME"},
                )

    def test_stale_future_and_skewed_view_times_are_rejected(self):
        stale = self.call({
            "front": self.view("front", captured_at=95.0),
            "side": self.view("side"),
        })
        self.assertEqual(
            stale,
            {"decision": "STOP", "reason": "STALE_OR_FUTURE_VIEW"},
        )

        future = self.call({
            "front": self.view("front", captured_at=102.0),
            "side": self.view("side"),
        })
        self.assertEqual(
            future,
            {"decision": "STOP", "reason": "STALE_OR_FUTURE_VIEW"},
        )

        skewed = self.call({
            "front": self.view("front", captured_at=100.0),
            "side": self.view(
                "side", captured_at=100.0 + MAX_VIEW_CAPTURE_SKEW_SECONDS + 0.001
            ),
        })
        self.assertEqual(
            skewed,
            {"decision": "REQUEST_VIEW", "reason": "VIEW_CAPTURE_TIME_SKEW"},
        )

    def test_per_view_times_are_bound_and_recorded(self):
        views = {
            "front": self.view("front", captured_at=100.0),
            "side": self.view("side", captured_at=100.125),
        }
        result = self.call(views)
        self.assertEqual(result["decision"], "REVIEW")
        self.assertEqual(
            result["evidence"]["view_captured_at"],
            {"front": 100.0, "side": 100.125},
        )
        self.assertEqual(result["evidence"]["view_capture_skew_seconds"], 0.125)

        for name, view in views.items():
            envelope = {
                "calibration_digest": CALIBRATION_DIGEST,
                "capture_id": view.capture_id,
                "captured_at": 100.0,
                "logical_view": name,
                "opencv_version": OPENCV_VERSION,
                "package_version": PACKAGE_VERSION,
                "pixel_dtype": str(view.pixels.dtype),
                "pixel_shape": list(view.pixels.shape),
                "pipeline_version": PIPELINE_VERSION,
                "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
                "source_id": view.source_id,
                "view_captured_at": float(view.captured_at),
            }
            expected = hashlib.sha256(
                json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
                + b"\0"
                + view.pixels.tobytes()
            ).hexdigest()
            self.assertEqual(
                result["observations"][name]["capture_envelope_sha256"],
                expected,
            )

        changed = self.call({
            "front": self.view("front", captured_at=100.01),
            "side": self.view("side", captured_at=100.125),
        })
        self.assertNotEqual(
            result["observations"]["front"]["capture_envelope_sha256"],
            changed["observations"]["front"]["capture_envelope_sha256"],
        )

    def test_occlusion_requests_another_view(self):
        self.assertEqual(self.call(self.views(visibility=0.5))["reason"], "OCCLUDED_VIEW")

    def test_stale_and_future_frames_stop(self):
        self.assertEqual(self.call(now=106)["reason"], "STALE_OR_FUTURE_FRAME")
        self.assertEqual(self.call(now=99)["reason"], "STALE_OR_FUTURE_FRAME")

    def test_non_finite_capture_times_stop_before_image_processing(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(captured_at=value):
                result = inspect(self.views(), captured_at=value, now=101)
                self.assertEqual(
                    result,
                    {"decision": "STOP", "reason": "INVALID_CAPTURE_TIME"},
                )
            with self.subTest(now=value):
                result = inspect(self.views(), captured_at=100, now=value)
                self.assertEqual(
                    result,
                    {"decision": "STOP", "reason": "INVALID_CAPTURE_TIME"},
                )

    def test_non_numeric_capture_times_stop_instead_of_raising(self):
        for captured_at, now in (("100", 101), (100, None), (True, 101)):
            with self.subTest(captured_at=captured_at, now=now):
                result = inspect(self.views(), captured_at=captured_at, now=now)
                self.assertEqual(
                    result,
                    {"decision": "STOP", "reason": "INVALID_CAPTURE_TIME"},
                )

    def test_calibration_change_stops(self):
        self.assertEqual(self.call(calibration_digest="changed")["reason"],
                         "CALIBRATION_OR_PIPELINE_CHANGED")

    def test_calibration_digest_commits_to_view_source_map(self):
        profile = {
            "geometry": "synthetic-24x16-roi-8-4-16-12-v1",
            "view_source_ids": {
                "front": "camera-front-v1",
                "side": "camera-side-v1",
            },
        }
        expected = hashlib.sha256(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(CALIBRATION_DIGEST, expected)

        changed = dict(profile)
        changed["view_source_ids"] = dict(profile["view_source_ids"])
        changed["view_source_ids"]["side"] = "camera-side-v2"
        changed_digest = hashlib.sha256(
            json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertNotEqual(CALIBRATION_DIGEST, changed_digest)

    def test_geometry_only_legacy_digest_is_rejected(self):
        legacy_digest = hashlib.sha256(
            b"synthetic-24x16-roi-8-4-16-12-v1"
        ).hexdigest()
        self.assertEqual(
            self.call(calibration_digest=legacy_digest),
            {"decision": "STOP", "reason": "CALIBRATION_OR_PIPELINE_CHANGED"},
        )

    def test_pipeline_change_stops(self):
        self.assertEqual(self.call(pipeline_version="opencv5-threshold-v2")["reason"],
                         "CALIBRATION_OR_PIPELINE_CHANGED")

    def test_dependency_change_stops(self):
        self.assertEqual(self.call(expected_package="5.0.0.94")["reason"],
                         "DEPENDENCY_VERSION_CHANGED")

    def test_invalid_frame_stops(self):
        invalid = np.zeros((8, 8), dtype=np.uint8)
        self.assertEqual(self.call({"front": self.view("front", pixels=invalid),
                                    "side": self.view("side")})["reason"],
                         "INVALID_FRAME")

    def test_consequence_mismatch_is_detected(self):
        result = verify_consequence(False, View(frame(True)))
        self.assertEqual(result["closure"], "MISMATCH")
        self.assertEqual(result["physical_action"], "NONE")

    def test_consequence_version_change_is_mismatch(self):
        result = verify_consequence(
            False, View(frame(False)), calibration_digest=CALIBRATION_DIGEST,
            pipeline_version=PIPELINE_VERSION + "-changed",
        )
        self.assertEqual(result["reason"], "EVIDENCE_VERSION_CHANGED")
