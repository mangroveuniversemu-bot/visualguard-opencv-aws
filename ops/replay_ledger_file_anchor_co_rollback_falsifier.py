"""Prove that a same-domain file anchor cannot prevent coherent rollback.

The probe snapshots SQLite and its local file-backed fixture anchor at sequence
one, advances both to sequence two, and then restores the old pair together.
The ledger accepts the stale but internally consistent pair.  Restoring only
one side is retained as a negative control and fails closed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.replay_ledger_anchor_cas_process_crash_probe import (  # noqa: E402
    FileBackedFixtureAnchor,
)
from vision.opencv5_inspection import (  # noqa: E402
    CaptureReplayLedger,
    CaptureReplayLedgerAnchorError,
)


FIRST_CAPTURE_ID = "capture-file-anchor-rollback-one"
SECOND_CAPTURE_ID = "capture-file-anchor-rollback-two"
FIRST_DIGEST = "a" * 64
SECOND_DIGEST = "b" * 64


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sqlite_state(path: Path) -> dict[str, int | str]:
    with sqlite3.connect(path) as connection:
        return {
            "capture_count": int(
                connection.execute("SELECT COUNT(*) FROM capture_replay").fetchone()[0]
            ),
            "marker_count": int(
                connection.execute(
                    "SELECT COUNT(*) FROM replay_ledger_anchor_transition"
                ).fetchone()[0]
            ),
            "quick_check": str(connection.execute("PRAGMA quick_check").fetchone()[0]),
        }


def snapshot_pair(
    database: Path,
    anchor_path: Path,
    destination: Path,
) -> tuple[Path, Path]:
    destination.mkdir(parents=True)
    snapshot_database = destination / "replay.sqlite3"
    snapshot_anchor = destination / "fixture-anchor.json"
    shutil.copy2(database, snapshot_database)
    shutil.copy2(anchor_path, snapshot_anchor)
    return snapshot_database, snapshot_anchor


def restore_case(
    root: Path,
    name: str,
    database_source: Path,
    anchor_source: Path,
) -> tuple[Path, Path]:
    case = root / name
    return snapshot_pair(database_source, anchor_source, case)


def startup_error(database: Path, anchor_path: Path) -> str:
    try:
        with CaptureReplayLedger(
            database,
            anchor=FileBackedFixtureAnchor(anchor_path),
        ):
            return "UNEXPECTED_ACCEPT"
    except CaptureReplayLedgerAnchorError as error:
        return str(error)


def exercise(root: Path) -> dict[str, object]:
    live = root / "live"
    live.mkdir()
    database = live / "replay.sqlite3"
    anchor_path = live / "fixture-anchor.json"
    anchor = FileBackedFixtureAnchor(anchor_path)

    with CaptureReplayLedger(database, anchor=anchor) as ledger:
        first_result = ledger.check_and_record({FIRST_CAPTURE_ID: FIRST_DIGEST})
        first_checkpoint = ledger.checkpoint("TRUNCATE")
        first_anchor_state = ledger.anchor_evidence()
    first_database, first_anchor = snapshot_pair(
        database, anchor_path, root / "sequence-one"
    )
    sequence_one = {
        **sqlite_state(first_database),
        "admission": first_result,
        "anchor_sequence": first_anchor_state["sequence"],
        "anchor_sha256": sha256(first_anchor),
        "database_sha256": sha256(first_database),
        "wal_checkpoint": first_checkpoint,
    }

    with CaptureReplayLedger(database, anchor=anchor) as ledger:
        second_result = ledger.check_and_record({SECOND_CAPTURE_ID: SECOND_DIGEST})
        second_checkpoint = ledger.checkpoint("TRUNCATE")
        second_anchor_state = ledger.anchor_evidence()
    second_database, second_anchor = snapshot_pair(
        database, anchor_path, root / "sequence-two"
    )
    sequence_two = {
        **sqlite_state(second_database),
        "admission": second_result,
        "anchor_sequence": second_anchor_state["sequence"],
        "anchor_sha256": sha256(second_anchor),
        "database_sha256": sha256(second_database),
        "wal_checkpoint": second_checkpoint,
    }

    old_database, current_anchor = restore_case(
        root,
        "database-only-rollback",
        first_database,
        second_anchor,
    )
    database_only_rollback = startup_error(old_database, current_anchor)

    current_database, old_anchor = restore_case(
        root,
        "anchor-only-rollback",
        second_database,
        first_anchor,
    )
    anchor_only_rollback = startup_error(current_database, old_anchor)

    rolled_database, rolled_anchor = restore_case(
        root,
        "co-rollback",
        first_database,
        first_anchor,
    )
    rolled_anchor_fixture = FileBackedFixtureAnchor(rolled_anchor)
    with CaptureReplayLedger(
        rolled_database, anchor=rolled_anchor_fixture
    ) as restarted:
        co_rollback = {
            **sqlite_state(rolled_database),
            "anchor_sequence": restarted.anchor_evidence()["sequence"],
            "replay": restarted.check_and_record({FIRST_CAPTURE_ID: FIRST_DIGEST}),
            "startup": "ACCEPTED_STALE_PAIR",
        }

    latest_state = FileBackedFixtureAnchor(second_anchor).read()
    restored_state = rolled_anchor_fixture.read()
    assert latest_state is not None and restored_state is not None
    independent_witness = (
        "ROLLBACK_DETECTED"
        if latest_state.sequence > restored_state.sequence
        and latest_state != restored_state
        else "ROLLBACK_NOT_DETECTED"
    )

    return {
        "anchor_only_rollback": anchor_only_rollback,
        "co_rollback": co_rollback,
        "database_only_rollback": database_only_rollback,
        "independent_witness": independent_witness,
        "sequence_one": sequence_one,
        "sequence_two": sequence_two,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(
        prefix="file-anchor-co-rollback-falsifier-"
    ) as temp_dir:
        print(
            json.dumps(
                {
                    "anchor_mode": "SAME_DOMAIN_FILE_FIXTURE_ONLY",
                    "falsifier": "COHERENT_SQLITE_AND_ANCHOR_ROLLBACK",
                    "result": exercise(Path(temp_dir)),
                    "seed": "NONE",
                    "trusted_live_anchor": "NOT_RUN",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
