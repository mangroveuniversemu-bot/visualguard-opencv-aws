"""Crash after the DB commit and before the anchor compare-and-swap."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision.opencv5_inspection import (  # noqa: E402
    CaptureReplayAnchor,
    CaptureReplayAnchorState,
    CaptureReplayLedger,
)


CRASH_EXIT_CODE = 74
CAPTURE_ID = "capture-db-commit-crash"
CAPTURE_DIGEST = "a" * 64


class RecoveryFixtureAnchor(CaptureReplayAnchor):
    """Deterministic in-memory anchor; not a live trusted provider."""

    def __init__(self, state: CaptureReplayAnchorState) -> None:
        self.state = state

    def read(self) -> CaptureReplayAnchorState:
        return self.state

    def compare_and_swap(
        self,
        expected: CaptureReplayAnchorState,
        replacement: CaptureReplayAnchorState,
    ) -> bool:
        if self.state != expected:
            return False
        self.state = replacement
        return True


class CrashBeforeCasAnchor(CaptureReplayAnchor):
    """Exit on the post-commit CAS after proving DB visibility."""

    def __init__(self, path: Path, state: CaptureReplayAnchorState) -> None:
        self.path = path
        self.state = state

    def read(self) -> CaptureReplayAnchorState:
        return self.state

    def compare_and_swap(
        self,
        expected: CaptureReplayAnchorState,
        replacement: CaptureReplayAnchorState,
    ) -> bool:
        if self.state != expected:
            return False
        with sqlite3.connect(self.path) as observer:
            observation = {
                "capture_count_visible_to_second_connection": int(
                    observer.execute("SELECT COUNT(*) FROM capture_replay").fetchone()[
                        0
                    ]
                ),
                "marker_count_visible_to_second_connection": int(
                    observer.execute(
                        "SELECT COUNT(*) FROM replay_ledger_anchor_transition"
                    ).fetchone()[0]
                ),
                "phase": "AFTER_DB_COMMIT_BEFORE_ANCHOR_CAS",
                "quick_check": observer.execute("PRAGMA quick_check").fetchone()[0],
                "replacement_sequence": replacement.sequence,
            }
        print(json.dumps(observation, sort_keys=True), flush=True)
        os._exit(CRASH_EXIT_CODE)


def crash_child(path: Path) -> None:
    with CaptureReplayLedger(path) as unanchored:
        empty_state = unanchored._local_anchor_state_unlocked()
    anchor = CrashBeforeCasAnchor(path, empty_state)
    with CaptureReplayLedger(path, anchor=anchor) as ledger:
        ledger.check_and_record({CAPTURE_ID: CAPTURE_DIGEST})
    raise AssertionError("anchor CAS crash point was not reached")


def database_state(path: Path) -> dict[str, object]:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT receipt_json FROM replay_ledger_anchor_transition"
        ).fetchone()
        return {
            "capture_count": int(
                connection.execute("SELECT COUNT(*) FROM capture_replay").fetchone()[0]
            ),
            "marker_count": int(
                connection.execute(
                    "SELECT COUNT(*) FROM replay_ledger_anchor_transition"
                ).fetchone()[0]
            ),
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "receipt": json.loads(row[0]) if row is not None else None,
        }


def exercise(root: Path) -> dict[str, object]:
    path = root / "db-commit-process-crash.sqlite3"
    child = subprocess.run(
        [sys.executable, __file__, "--crash-before-anchor-cas", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if child.returncode != CRASH_EXIT_CODE:
        raise AssertionError(
            f"unexpected crash child exit {child.returncode}: {child.stderr}"
        )
    child_observation = json.loads(child.stdout.strip())
    after_crash = database_state(path)
    receipt = after_crash["receipt"]
    assert isinstance(receipt, dict)
    anchor = RecoveryFixtureAnchor(
        CaptureReplayLedger._anchor_state_from_dict(receipt["expected"])
    )

    with CaptureReplayLedger(path, anchor=anchor) as restarted:
        pending_before_recovery = restarted.pending_anchor_recovery_receipt()
        admission_before_recovery = restarted.check_and_record(
            {"capture-must-stay-blocked": "b" * 64}
        )
        recovery = restarted.recover_anchor(receipt)
        marker_after_recovery = database_state(path)["marker_count"]
        replay_after_recovery = restarted.check_and_record({CAPTURE_ID: CAPTURE_DIGEST})
    with CaptureReplayLedger(path, anchor=anchor) as second_restart:
        second_restart_state = {
            "capture_count": second_restart.entry_count(),
            "marker_count": database_state(path)["marker_count"],
            "pending": second_restart.pending_anchor_recovery_receipt(),
        }

    return {
        "admission_before_recovery": admission_before_recovery,
        "after_crash": after_crash,
        "child_exit_code": child.returncode,
        "child_observation": child_observation,
        "marker_after_recovery": marker_after_recovery,
        "pending_before_recovery": pending_before_recovery,
        "recovery": recovery,
        "replay_after_recovery": replay_after_recovery,
        "second_restart": second_restart_state,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crash-before-anchor-cas", type=Path)
    args = parser.parse_args()
    if args.crash_before_anchor_cas is not None:
        crash_child(args.crash_before_anchor_cas)

    with tempfile.TemporaryDirectory(
        prefix="anchor-db-commit-process-crash-probe-"
    ) as temp_dir:
        print(
            json.dumps(
                {
                    "anchor_mode": "DETERMINISTIC_CRASH_FIXTURE_ONLY",
                    "crash_mode": "SUBPROCESS_OS_EXIT_AFTER_DB_COMMIT",
                    "result": exercise(Path(temp_dir)),
                    "seed": "NONE",
                    "trusted_live_anchor": "NOT_RUN",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
