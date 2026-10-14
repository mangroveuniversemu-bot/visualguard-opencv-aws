"""Replay the judge-facing OpenCV negative-control and action-routing matrix."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision.follow_up import plan_follow_up  # noqa: E402
from vision.opencv5_inspection import (  # noqa: E402
    CaptureReplayLedger,
    View,
    frame,
    inspect,
    runtime_evidence,
    verify_consequence,
)


def view(
    name: str,
    *,
    alarm: bool = False,
    visible_fraction: float = 1.0,
    capture_id: str,
) -> View:
    return View(
        frame(alarm),
        visible_fraction=visible_fraction,
        source_id=f"camera-{name}-v1",
        capture_id=capture_id,
        captured_at=100.0,
    )


def views(case: str, *, alarm: bool = False, visible_fraction: float = 1.0):
    return {
        "front": view(
            "front",
            visible_fraction=visible_fraction,
            capture_id=f"{case}-front",
        ),
        "side": view(
            "side",
            alarm=alarm,
            visible_fraction=visible_fraction,
            capture_id=f"{case}-side",
        ),
    }


def record(inspection: dict, *, consequence: dict | None = None) -> dict:
    result = {
        "inspection": {
            "decision": inspection["decision"],
            "reason": inspection["reason"],
        },
        "follow_up": plan_follow_up(
            inspection,
            consequence_result=consequence,
        ),
    }
    if consequence is not None:
        result["consequence"] = {
            "closure": consequence["closure"],
            "reason": consequence["reason"],
        }
    return result


def exercise(root: Path) -> dict[str, object]:
    with CaptureReplayLedger(root / "captures.sqlite3") as ledger:
        clear_inspection = inspect(
            views("clear"),
            captured_at=100,
            now=101,
            replay_ledger=ledger,
        )
        matrix = {
            "clear": record(clear_inspection),
            "alarm": record(
                inspect(
                    views("alarm", alarm=True),
                    captured_at=100,
                    now=101,
                    replay_ledger=ledger,
                )
            ),
            "missing_view": record(
                inspect(
                    {"front": view("front", capture_id="missing-front")},
                    captured_at=100,
                    now=101,
                    replay_ledger=ledger,
                )
            ),
            "occluded": record(
                inspect(
                    views("occluded", visible_fraction=0.5),
                    captured_at=100,
                    now=101,
                    replay_ledger=ledger,
                )
            ),
            "stale": record(
                inspect(
                    views("stale"),
                    captured_at=100,
                    now=106,
                    replay_ledger=ledger,
                )
            ),
            "calibration_drift": record(
                inspect(
                    views("calibration-drift"),
                    captured_at=100,
                    now=101,
                    calibration_digest="changed-calibration",
                    replay_ledger=ledger,
                )
            ),
            "version_drift": record(
                inspect(
                    views("version-drift"),
                    captured_at=100,
                    now=101,
                    expected_package="5.0.0.94",
                    replay_ledger=ledger,
                )
            ),
        }
        consequence = verify_consequence(False, View(frame(True)))
        matrix["consequence_mismatch"] = record(
            clear_inspection,
            consequence=consequence,
        )
        return matrix


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="opencv5-negative-controls-") as temporary:
        output = {
            "evidence_mode": "SYNTHETIC_REPLAY",
            "provenance": "DERIVED",
            "input": "FIXED_SYNTHETIC_ARRAYS",
            "runtime": runtime_evidence(),
            "cases": exercise(Path(temporary)),
            "aws": "NOT_RUN",
            "camera": "NOT_RUN",
            "physical_action": "NONE",
            "seed": "NONE",
        }
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
