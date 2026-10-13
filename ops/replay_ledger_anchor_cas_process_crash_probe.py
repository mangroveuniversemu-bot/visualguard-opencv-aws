"""Crash after a durable fixture-anchor CAS and before marker clearance.

The file-backed anchor here is deliberately a local, single-writer test
fixture.  It exercises process-crash ordering; it is not an authenticated or
independent monotonic provider.
"""

from __future__ import annotations

import argparse
import hashlib
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


CRASH_EXIT_CODE = 75
CAPTURE_ID = "capture-anchor-cas-crash"
CAPTURE_DIGEST = "a" * 64


class FileBackedFixtureAnchor(CaptureReplayAnchor):
    """Single-writer durable fixture using fsync and atomic replacement."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> CaptureReplayAnchorState | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return CaptureReplayLedger._anchor_state_from_dict(payload)

    def _write_durable(self, state: CaptureReplayAnchorState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        encoded = json.dumps(
            state.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def compare_and_swap(
        self,
        expected: CaptureReplayAnchorState | None,
        replacement: CaptureReplayAnchorState,
    ) -> bool:
        if self.read() != expected:
            return False
        self._write_durable(replacement)
        return True

    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class CrashAfterDurableCasAnchor(FileBackedFixtureAnchor):
    """Exit once the sequence-one replacement is durable and observable."""

    def __init__(self, path: Path, database: Path) -> None:
        super().__init__(path)
        self.database = database

    def compare_and_swap(
        self,
        expected: CaptureReplayAnchorState | None,
        replacement: CaptureReplayAnchorState,
    ) -> bool:
        advanced = super().compare_and_swap(expected, replacement)
        if not advanced or replacement.sequence != 1:
            return advanced
        persisted = self.read()
        with sqlite3.connect(self.database) as observer:
            observation = {
                "anchor_file_sha256": self.sha256(),
                "anchor_sequence": persisted.sequence,
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
                "phase": "AFTER_DURABLE_ANCHOR_CAS_BEFORE_MARKER_CLEAR",
                "quick_check": observer.execute("PRAGMA quick_check").fetchone()[0],
            }
        print(json.dumps(observation, sort_keys=True), flush=True)
        os._exit(CRASH_EXIT_CODE)


def crash_child(database: Path, anchor_path: Path) -> None:
    anchor = CrashAfterDurableCasAnchor(anchor_path, database)
    with CaptureReplayLedger(database, anchor=anchor) as ledger:
        ledger.check_and_record({CAPTURE_ID: CAPTURE_DIGEST})
    raise AssertionError("post-anchor-CAS crash point was not reached")


def database_state(path: Path) -> dict[str, object]:
    with sqlite3.connect(path) as connection:
        audit_exists = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'anchor_clear_audit'"
        ).fetchone()
        return {
            "anchor_clear_count": (
                int(
                    connection.execute(
                        "SELECT COUNT(*) FROM anchor_clear_audit"
                    ).fetchone()[0]
                )
                if audit_exists is not None
                else 0
            ),
            "capture_count": int(
                connection.execute("SELECT COUNT(*) FROM capture_replay").fetchone()[0]
            ),
            "marker_count": int(
                connection.execute(
                    "SELECT COUNT(*) FROM replay_ledger_anchor_transition"
                ).fetchone()[0]
            ),
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        }


def install_clear_audit(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE anchor_clear_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT
            );
            CREATE TRIGGER audit_anchor_clear
            AFTER DELETE ON replay_ledger_anchor_transition
            BEGIN
                INSERT INTO anchor_clear_audit(id) VALUES (NULL);
            END;
            """
        )


def exercise(root: Path) -> dict[str, object]:
    database = root / "anchor-cas-process-crash.sqlite3"
    anchor_path = root / "fixture-anchor.json"
    child = subprocess.run(
        [
            sys.executable,
            __file__,
            "--crash-after-anchor-cas",
            str(database),
            str(anchor_path),
        ],
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
    anchor = FileBackedFixtureAnchor(anchor_path)
    after_crash = database_state(database)
    persisted_after_crash = anchor.read()
    assert persisted_after_crash is not None
    install_clear_audit(database)

    with CaptureReplayLedger(database, anchor=anchor) as restarted:
        after_first_restart = database_state(database)
        pending_after_restart = restarted.pending_anchor_recovery_receipt()
        replay_after_restart = restarted.check_and_record({CAPTURE_ID: CAPTURE_DIGEST})
        anchor_after_restart = restarted.anchor_evidence()

    with CaptureReplayLedger(database, anchor=anchor) as second_restart:
        second_restart_state = {
            **database_state(database),
            "pending": second_restart.pending_anchor_recovery_receipt(),
            "replay": second_restart.check_and_record({CAPTURE_ID: CAPTURE_DIGEST}),
        }

    return {
        "after_crash": after_crash,
        "after_first_restart": after_first_restart,
        "anchor_after_restart": anchor_after_restart,
        "anchor_file_sha256": anchor.sha256(),
        "child_exit_code": child.returncode,
        "child_observation": child_observation,
        "pending_after_restart": pending_after_restart,
        "persisted_anchor_sequence_after_crash": (persisted_after_crash.sequence),
        "replay_after_restart": replay_after_restart,
        "second_restart": second_restart_state,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--crash-after-anchor-cas",
        nargs=2,
        metavar=("DATABASE", "ANCHOR"),
        type=Path,
    )
    args = parser.parse_args()
    if args.crash_after_anchor_cas is not None:
        database, anchor_path = args.crash_after_anchor_cas
        crash_child(database, anchor_path)

    with tempfile.TemporaryDirectory(
        prefix="anchor-cas-process-crash-probe-"
    ) as temp_dir:
        print(
            json.dumps(
                {
                    "anchor_mode": ("FILE_BACKED_SINGLE_WRITER_CRASH_FIXTURE_ONLY"),
                    "crash_mode": ("SUBPROCESS_OS_EXIT_AFTER_DURABLE_ANCHOR_CAS"),
                    "result": exercise(Path(temp_dir)),
                    "seed": "NONE",
                    "trusted_live_anchor": "NOT_RUN",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
