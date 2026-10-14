"""Bound the rollback claim of a trust-root-history file anchor.

The latest anchor detects a rolled-back SQLite history.  If an attacker can
roll back both SQLite and the colocated file anchor to a matching old pair,
the verifier has no independent freshness fact and accepts the stale pair.
This is a falsifier for same-domain storage, not live witness evidence.
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

from vision.opencv5_inspection import (  # noqa: E402
    CaptureReplayLedgerSchemaError,
    CaptureReplayWitnessRevocationStore,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_A = "fixture-hmac-root-2026-11"
KEY_B = "fixture-hmac-root-2026-12"
KEY_C = "fixture-hmac-root-2027-01"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sqlite_snapshot(source: Path, destination: Path) -> None:
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)


def sqlite_state(path: Path) -> dict[str, int | str]:
    with sqlite3.connect(path) as connection:
        state = connection.execute(
            "SELECT trust_root_epoch, root_set_sha256 "
            "FROM replay_ledger_witness_trust_root_state WHERE singleton = 1"
        ).fetchone()
        return {
            "quick_check": str(connection.execute("PRAGMA quick_check").fetchone()[0]),
            "trust_root_epoch": int(state[0]),
            "root_set_sha256": str(state[1]),
        }


def write_anchor(path: Path, checkpoint: dict[str, int | str]) -> None:
    path.write_text(
        json.dumps(checkpoint, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def verify_case(database: Path, anchor: Path) -> str:
    checkpoint = json.loads(anchor.read_text(encoding="utf-8"))
    try:
        with CaptureReplayWitnessRevocationStore(database) as store:
            store.verify_trust_root_history_checkpoint(checkpoint)
    except CaptureReplayLedgerSchemaError as error:
        return str(error)
    return "ACCEPTED_MATCHING_PAIR"


def exercise(root: Path) -> dict[str, object]:
    live_database = root / "live.sqlite3"
    with CaptureReplayWitnessRevocationStore(live_database) as store:
        store.cas_update_trust_root_set(
            expected_epoch=0,
            replacement_epoch=1,
            trusted_roots=((PROVIDER_ID, KEY_A), (PROVIDER_ID, KEY_B)),
        )
        checkpoint_one = store.trust_root_history_checkpoint()
    database_one = root / "epoch-one.sqlite3"
    anchor_one = root / "epoch-one-anchor.json"
    sqlite_snapshot(live_database, database_one)
    write_anchor(anchor_one, checkpoint_one)

    with CaptureReplayWitnessRevocationStore(live_database) as store:
        store.cas_update_trust_root_set(
            expected_epoch=1,
            replacement_epoch=2,
            trusted_roots=((PROVIDER_ID, KEY_B), (PROVIDER_ID, KEY_C)),
        )
        checkpoint_two = store.trust_root_history_checkpoint()
    database_two = root / "epoch-two.sqlite3"
    anchor_two = root / "epoch-two-anchor.json"
    sqlite_snapshot(live_database, database_two)
    write_anchor(anchor_two, checkpoint_two)

    database_only = root / "database-only.sqlite3"
    database_only_anchor = root / "database-only-anchor.json"
    shutil.copy2(database_one, database_only)
    shutil.copy2(anchor_two, database_only_anchor)

    anchor_only = root / "anchor-only.sqlite3"
    anchor_only_anchor = root / "anchor-only-anchor.json"
    shutil.copy2(database_two, anchor_only)
    shutil.copy2(anchor_one, anchor_only_anchor)

    co_rollback = root / "co-rollback.sqlite3"
    co_rollback_anchor = root / "co-rollback-anchor.json"
    shutil.copy2(database_one, co_rollback)
    shutil.copy2(anchor_one, co_rollback_anchor)

    return {
        "epoch_one": {
            **sqlite_state(database_one),
            "anchor_sha256": sha256(anchor_one),
            "database_sha256": sha256(database_one),
            "checkpoint": checkpoint_one,
        },
        "epoch_two": {
            **sqlite_state(database_two),
            "anchor_sha256": sha256(anchor_two),
            "database_sha256": sha256(database_two),
            "checkpoint": checkpoint_two,
        },
        "database_only_rollback": verify_case(database_only, database_only_anchor),
        "anchor_only_rollback": verify_case(anchor_only, anchor_only_anchor),
        "co_rollback": {
            **sqlite_state(co_rollback),
            "verification": verify_case(co_rollback, co_rollback_anchor),
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory(
        prefix="trust-root-history-anchor-falsifier-"
    ) as temp_dir:
        print(
            json.dumps(
                {
                    "anchor_mode": "LOCAL_FILE_ANCHOR_FIXTURE",
                    "falsifier": "COHERENT_TRUST_ROOT_HISTORY_AND_ANCHOR_ROLLBACK",
                    "live_external_witness": "NOT_RUN",
                    "result": exercise(Path(temp_dir)),
                    "seed": "NONE",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
