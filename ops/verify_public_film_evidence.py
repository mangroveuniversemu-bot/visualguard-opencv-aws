"""Bind the current public VisualGuard film bytes to an independent review."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("evidence/VISUALGUARD_PUBLIC_FILM_REVIEW_GATE001.json")
REQUIRED_OBSERVATIONS = (
    "solo_team",
    "working_application",
    "architecture",
    "principal_results",
)
EXPECTED_BOUNDARY = {
    "synthetic_inputs_disclosed": True,
    "public_aws_endpoint_disclosed": True,
    "live_camera_claimed": False,
    "field_accuracy_claimed": False,
    "physical_action_claimed": False,
    "credentials_visible": False,
}


class PublicFilmEvidenceError(ValueError):
    """The film or review does not satisfy the current public-film contract."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PublicFilmEvidenceError(code)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicFilmEvidenceError(f"JSON_READ_FAILED:{path.name}") from exc
    _require(isinstance(value, dict), f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video_duration(video_path: Path) -> float:
    """Inspect actual media with ffprobe and require a video stream."""
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        probe = json.loads(completed.stdout)
        duration = float(probe["format"]["duration"])
        streams = probe.get("streams", [])
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise PublicFilmEvidenceError("VIDEO_PROBE_FAILED") from exc
    _require(math.isfinite(duration) and duration > 0, "VIDEO_DURATION_INVALID")
    _require(
        any(stream.get("codec_type") == "video" for stream in streams),
        "VIDEO_STREAM_MISSING",
    )
    return round(duration, 3)


def verify_public_film_evidence(
    video_path: Path,
    review_path: Path,
    *,
    root: Path = ROOT,
    duration_probe: Callable[[Path], float] = probe_video_duration,
) -> dict[str, Any]:
    """Fail closed unless current film bytes and an independent review agree."""
    resolved_video = video_path.resolve()
    _require(resolved_video.is_file(), "VIDEO_MISSING")
    size = resolved_video.stat().st_size
    _require(size > 0, "VIDEO_EMPTY")

    contract_path = root / CONTRACT_PATH
    contract = _load(contract_path)
    review = _load(review_path)
    video_sha256 = _sha256(resolved_video)
    contract_sha256 = _sha256(contract_path)
    duration = duration_probe(resolved_video)

    _require(contract.get("schema_version") == 1, "CONTRACT_SCHEMA_UNSUPPORTED")
    _require(contract.get("status") == "PREPARED_NOT_RUN", "CONTRACT_STATUS_DRIFT")
    _require(
        contract.get("public_film_url") == "https://youtu.be/AEDHXknTBy8",
        "PUBLIC_FILM_URL_DRIFT",
    )
    _require(
        contract.get("public_endpoint_status") == "PUBLIC_AWS_JUDGE_UI_DEPLOYED",
        "PUBLIC_ENDPOINT_STATUS_DRIFT",
    )
    _require(
        contract.get("source_commit") == "0030066b2733d877678bf0f2bc4c06970bb29714",
        "SOURCE_COMMIT_DRIFT",
    )
    _require(
        contract.get("required_observations") == list(REQUIRED_OBSERVATIONS),
        "CONTRACT_OBSERVATIONS_DRIFT",
    )
    _require(
        contract.get("claim_boundary") == EXPECTED_BOUNDARY,
        "CONTRACT_BOUNDARY_DRIFT",
    )
    _require(contract.get("action_executed") is False, "CONTRACT_ACTION_OVERCLAIM")
    expected_duration = contract.get("expected_duration_seconds")
    tolerance = contract.get("duration_tolerance_seconds")
    _require(
        isinstance(expected_duration, (int, float))
        and isinstance(tolerance, (int, float))
        and abs(duration - float(expected_duration)) <= float(tolerance),
        "VIDEO_DURATION_MISMATCH",
    )

    _require(review.get("schema_version") == 1, "REVIEW_SCHEMA_UNSUPPORTED")
    _require(review.get("status") == "INDEPENDENT_REVIEWED", "REVIEW_INCOMPLETE")
    _require(
        review.get("contract_sha256") == contract_sha256, "CONTRACT_DIGEST_MISMATCH"
    )
    _require(review.get("video_sha256") == video_sha256, "VIDEO_DIGEST_MISMATCH")
    _require(review.get("video_size_bytes") == size, "VIDEO_SIZE_MISMATCH")
    _require(
        review.get("public_film_url") == contract["public_film_url"],
        "REVIEW_FILM_URL_MISMATCH",
    )
    operator_id = review.get("operator_id")
    reviewer_id = review.get("reviewer_id")
    _require(
        isinstance(operator_id, str) and operator_id.strip(), "OPERATOR_ID_INVALID"
    )
    _require(
        isinstance(reviewer_id, str) and reviewer_id.strip(), "REVIEWER_ID_INVALID"
    )
    _require(operator_id != reviewer_id, "REVIEW_NOT_INDEPENDENT")
    _require(
        review.get("observed_requirements") == list(REQUIRED_OBSERVATIONS),
        "REQUIRED_OBSERVATIONS_INVALID",
    )
    _require(
        review.get("claim_boundary") == EXPECTED_BOUNDARY, "CLAIM_BOUNDARY_INVALID"
    )
    _require(review.get("credentials_exposed") is False, "REVIEW_CREDENTIAL_EXPOSURE")

    return {
        "result": "PASS",
        "cut": contract["cut"],
        "provenance": contract["provenance"],
        "evidence_mode": "LOCAL_MEDIA_BYTES_AND_HUMAN_REVIEW",
        "video_sha256": video_sha256,
        "contract_sha256": contract_sha256,
        "video_size_bytes": size,
        "duration_seconds": duration,
        "observed_requirements": list(REQUIRED_OBSERVATIONS),
        "independent_review": "PASS",
        "public_endpoint": "PUBLIC_AWS_JUDGE_UI_DEPLOYED",
        "public_film_url": contract["public_film_url"],
        "camera": "NOT_VERIFIED",
        "field_accuracy": "NOT_VERIFIED",
        "physical_action": "NONE",
        "action_executed": False,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_public_film_evidence(args.video, args.review)
    except PublicFilmEvidenceError as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        sys.exit(2)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
