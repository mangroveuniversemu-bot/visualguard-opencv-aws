"""Prepare a fail-closed review draft bound to the current public film bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

try:
    from ops.verify_public_film_evidence import (
        CONTRACT_PATH,
        EXPECTED_BOUNDARY,
        PublicFilmEvidenceError,
        probe_video_duration,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_public_film_evidence import (
        CONTRACT_PATH,
        EXPECTED_BOUNDARY,
        PublicFilmEvidenceError,
        probe_video_duration,
    )


ROOT = Path(__file__).resolve().parents[1]


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PublicFilmEvidenceError(code)


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicFilmEvidenceError("CONTRACT_READ_FAILED") from exc
    _require(isinstance(value, dict), "CONTRACT_OBJECT_REQUIRED")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_public_film_review_draft(
    video_path: Path,
    operator_id: str,
    *,
    root: Path = ROOT,
    duration_probe=probe_video_duration,
) -> dict[str, Any]:
    """Return a byte-bound draft that deliberately cannot pass final review."""
    video = video_path.resolve()
    _require(video.is_file(), "VIDEO_MISSING")
    size = video.stat().st_size
    _require(size > 0, "VIDEO_EMPTY")
    _require(bool(operator_id.strip()), "OPERATOR_ID_INVALID")

    contract_path = root / CONTRACT_PATH
    contract = _load_contract(contract_path)
    _require(contract.get("schema_version") == 1, "CONTRACT_SCHEMA_UNSUPPORTED")
    _require(contract.get("status") == "PREPARED_NOT_RUN", "CONTRACT_STATUS_DRIFT")
    _require(contract.get("claim_boundary") == EXPECTED_BOUNDARY, "CONTRACT_BOUNDARY_DRIFT")
    _require(contract.get("action_executed") is False, "CONTRACT_ACTION_OVERCLAIM")

    duration = duration_probe(video)
    _require(
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and math.isfinite(float(duration))
        and float(duration) > 0,
        "VIDEO_DURATION_INVALID",
    )
    expected = contract.get("expected_duration_seconds")
    tolerance = contract.get("duration_tolerance_seconds")
    _require(
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(tolerance, (int, float))
        and not isinstance(tolerance, bool)
        and abs(float(duration) - float(expected)) <= float(tolerance),
        "VIDEO_DURATION_MISMATCH",
    )

    return {
        "schema_version": 1,
        "status": "PREPARED_NOT_REVIEWED",
        "operator_id": operator_id.strip(),
        "reviewer_id": "",
        "contract_sha256": _sha256(contract_path),
        "video_sha256": _sha256(video),
        "video_size_bytes": size,
        "video_duration_seconds": round(float(duration), 3),
        "public_film_url": contract["public_film_url"],
        "observed_requirements": [],
        "claim_boundary": EXPECTED_BOUNDARY,
        "credentials_exposed": None,
        "review_instructions": (
            "A distinct human must watch the entire byte-identical file, fill reviewer_id, "
            "observed_requirements and credentials_exposed, then set status to "
            "INDEPENDENT_REVIEWED."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        print(json.dumps({"result": "BLOCKED", "reason": "OUTPUT_EXISTS"}, sort_keys=True))
        sys.exit(2)
    try:
        draft = prepare_public_film_review_draft(args.video, args.operator_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
    except (OSError, PublicFilmEvidenceError) as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        sys.exit(2)
    print(
        json.dumps(
            {
                "result": "PREPARED_NOT_REVIEWED",
                "output": str(args.output),
                "video_sha256": draft["video_sha256"],
                "video_size_bytes": draft["video_size_bytes"],
                "duration_seconds": draft["video_duration_seconds"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
