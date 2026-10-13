"""Crash after deleting the anchor marker but before the SQLite commit."""

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


CRASH_EXIT_CODE = 73


class CrashFixtureAnchor(CaptureReplayAnchor):
    """Deterministic in-memory anchor; not a live trusted provider."""

    def __init__(self) -> None:
        self.state: CaptureReplayAnchorState | None = None
        self.fail_next_cas = False

    def read(self) -> CaptureReplayAnchorState | None:
        return self.state

    def compare_and_swap(
        self,
        expected: CaptureReplayAnchorState | None,
        replacement: CaptureReplayAnchorState,
    ) -> bool:
        if self.fail_next_cas:
            self.fail_next_cas = False
            return False
        if self.state != expected:
            return False
        self.state = replacement
        return True


def marker_count(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM replay_ledger_anchor_transition"
            ).fetchone()[0]
        )


def crash_child(path: Path) -> None:
    """Delete inside an open transaction, prove it, then skip COMMIT."""
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("DELETE FROM replay_ledger_anchor_transition")
    inside_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM replay_ledger_anchor_transition"
        ).fetchone()[0]
    )
    print(
        json.dumps(
            {
                "marker_count_inside_transaction": inside_count,
                "phase": "AFTER_DELETE_BEFORE_COMMIT",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    os._exit(CRASH_EXIT_CODE)


def exercise(root: Path) -> dict[str, object]:
    path = root / "marker-clear-commit-crash.sqlite3"
    anchor = CrashFixtureAnchor()
    with CaptureReplayLedger(path, anchor=anchor) as ledger:
        anchor.fail_next_cas = True
        failed_admission = ledger.check_and_record(
            {"capture-clear-commit-crash": "a" * 64}
        )
        receipt = ledger.pending_anchor_recovery_receipt()
    assert receipt is not None
    anchor.state = CaptureReplayLedger._anchor_state_from_dict(receipt["replacement"])
    marker_before_crash = marker_count(path)

    child = subprocess.run(
        [sys.executable, __file__, "--crash-child", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    child_observation = json.loads(child.stdout.strip())
    if child.returncode != CRASH_EXIT_CODE:
        raise AssertionError(
            f"unexpected crash child exit {child.returncode}: {child.stderr}"
        )

    with sqlite3.connect(path) as connection:
        post_crash_marker_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM replay_ledger_anchor_transition"
            ).fetchone()[0]
        )
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]

    with CaptureReplayLedger(path, anchor=anchor) as restarted:
        marker_after_recovery = marker_count(path)
        pending_after_recovery = restarted.pending_anchor_recovery_receipt()
        replay_after_recovery = restarted.check_and_record(
            {"capture-clear-commit-crash": "a" * 64}
        )
    with CaptureReplayLedger(path, anchor=anchor) as second_restart:
        second_restart_state = {
            "marker_count": marker_count(path),
            "pending": second_restart.pending_anchor_recovery_receipt(),
            "row_count": second_restart.entry_count(),
        }

    return {
        "child_exit_code": child.returncode,
        "child_observation": child_observation,
        "failed_initial_admission": failed_admission,
        "marker_after_recovery": marker_after_recovery,
        "marker_before_crash": marker_before_crash,
        "pending_after_recovery": pending_after_recovery,
        "post_crash_marker_count": post_crash_marker_count,
        "quick_check": quick_check,
        "replay_after_recovery": replay_after_recovery,
        "second_restart": second_restart_state,
        "transition_id": receipt["transition_id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crash-child", type=Path)
    args = parser.parse_args()
    if args.crash_child is not None:
        crash_child(args.crash_child)

    with tempfile.TemporaryDirectory(
        prefix="anchor-marker-clear-commit-crash-probe-"
    ) as temp_dir:
        print(
            json.dumps(
                {
                    "anchor_mode": "DETERMINISTIC_CRASH_FIXTURE_ONLY",
                    "crash_mode": "SUBPROCESS_OS_EXIT_BEFORE_COMMIT",
                    "result": exercise(Path(temp_dir)),
                    "seed": "NONE",
                    "trusted_live_anchor": "NOT_RUN",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
