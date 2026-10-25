"""Bind final VisualGuard video bytes to the checked-in demo contract and review."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from ops.verify_demo_evidence_contract import AWS_CLAIM, verify_contract
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_demo_evidence_contract import AWS_CLAIM, verify_contract


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("evidence/VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json")
VIDEO_EVIDENCE_MODE = "MIXED_SYNTHETIC_REPLAY_AND_AWS_LAMBDA"
EXPECTED_ATTESTATION = {
    "synthetic_replay_disclosed": True,
    "fixed_synthetic_arrays_disclosed": True,
    "opencv5_runtime_claimed": True,
    "private_aws_lambda_synthetic_execution_claimed": True,
    "public_aws_endpoint_claimed": False,
    "reserved_concurrency_claimed": False,
    "live_camera_claimed": False,
    "physical_action_claimed": False,
    "field_accuracy_claimed": False,
    "source_authenticity_claimed": False,
    "credentials_visible": False,
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON_READ_FAILED:{path.name}") from exc
    _require(isinstance(value, dict), f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video_duration(video_path: Path) -> float:
    """Inspect real media with ffprobe and require at least one video stream."""
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
        raise ValueError("VIDEO_PROBE_FAILED") from exc
    _require(math.isfinite(duration) and duration > 0, "VIDEO_DURATION_INVALID")
    _require(
        any(stream.get("codec_type") == "video" for stream in streams),
        "VIDEO_STREAM_MISSING",
    )
    return round(duration, 3)


def _verify_segments(
    receipt: dict[str, Any], contract: dict[str, Any], duration: float
) -> None:
    observations = receipt.get("segment_observations")
    planned = contract["segments"]
    _require(
        isinstance(observations, list) and len(observations) == len(planned),
        "SEGMENT_OBSERVATIONS_INVALID",
    )
    cursor = 0.0
    for observation, expected in zip(observations, planned, strict=True):
        _require(isinstance(observation, dict), "SEGMENT_OBSERVATION_INVALID")
        _require(observation.get("id") == expected["id"], "SEGMENT_SEQUENCE_INVALID")
        start = observation.get("start_seconds")
        end = observation.get("end_seconds")
        _require(
            isinstance(start, (int, float)) and isinstance(end, (int, float)),
            "SEGMENT_TIME_INVALID",
        )
        _require(abs(float(start) - cursor) <= 0.05, "SEGMENT_TIMELINE_GAP")
        _require(float(end) > float(start), "SEGMENT_DURATION_INVALID")
        _require(observation.get("operator_observed") is True, "SEGMENT_NOT_OBSERVED")
        cursor = float(end)
    _require(cursor <= duration + 0.05, "SEGMENT_EXCEEDS_VIDEO")
    _require(duration - cursor <= 2.0, "VIDEO_TAIL_UNREVIEWED")


def verify_final_video_evidence(
    video_path: Path,
    receipt_path: Path,
    review_path: Path,
    *,
    root: Path = ROOT,
    duration_probe: Callable[[Path], float] = probe_video_duration,
) -> dict[str, Any]:
    """Fail closed unless video, contract, operator receipt, and review agree."""
    video_path = video_path.resolve()
    _require(video_path.is_file(), "VIDEO_MISSING")
    size = video_path.stat().st_size
    _require(size > 0, "VIDEO_EMPTY")

    contract_path = root / CONTRACT_PATH
    contract_result = verify_contract(contract_path, root)
    contract = _load_json(contract_path)
    receipt = _load_json(receipt_path)
    review = _load_json(review_path)
    video_sha256 = _sha256(video_path)
    contract_sha256 = _sha256(contract_path)
    duration = duration_probe(video_path)
    _require(math.isfinite(duration) and duration > 0, "VIDEO_DURATION_INVALID")
    _require(
        duration <= float(contract["max_duration_seconds"]), "VIDEO_DURATION_EXCEEDED"
    )

    _require(receipt.get("schema_version") == 2, "RECEIPT_SCHEMA_UNSUPPORTED")
    _require(
        receipt.get("cut") == "VISUALGUARD_DEMO_VIDEO_FINAL_BYTES_BINDING_GATE002",
        "CUT_INVALID",
    )
    _require(receipt.get("status") == "RECORDED", "VIDEO_STATUS_NOT_RECORDED")
    _require(receipt.get("provenance") == "DERIVED", "PROVENANCE_INVALID")
    _require(
        receipt.get("evidence_mode") == VIDEO_EVIDENCE_MODE, "EVIDENCE_MODE_INVALID"
    )
    _require(receipt.get("action_executed") is False, "ACTION_EXECUTION_OVERCLAIMED")
    _require(
        receipt.get("contract_sha256") == contract_sha256, "CONTRACT_DIGEST_MISMATCH"
    )
    video = receipt.get("video")
    _require(isinstance(video, dict), "VIDEO_RECEIPT_INVALID")
    _require(video.get("sha256") == video_sha256, "VIDEO_DIGEST_MISMATCH")
    _require(video.get("size_bytes") == size, "VIDEO_SIZE_MISMATCH")
    reported_duration = video.get("duration_seconds")
    _require(
        isinstance(reported_duration, (int, float))
        and abs(float(reported_duration) - duration) <= 0.05,
        "VIDEO_DURATION_MISMATCH",
    )
    _require(
        receipt.get("attestation") == EXPECTED_ATTESTATION,
        "ATTESTATION_BOUNDARY_INVALID",
    )
    operator_id = receipt.get("operator_id")
    _require(
        isinstance(operator_id, str) and operator_id.strip(), "OPERATOR_ID_INVALID"
    )
    _verify_segments(receipt, contract, duration)

    _require(review.get("schema_version") == 2, "REVIEW_SCHEMA_UNSUPPORTED")
    _require(review.get("status") == "INDEPENDENT_REVIEWED", "REVIEW_INCOMPLETE")
    reviewer_id = review.get("reviewer_id")
    _require(
        isinstance(reviewer_id, str) and reviewer_id.strip(), "REVIEWER_ID_INVALID"
    )
    _require(reviewer_id != operator_id, "REVIEW_NOT_INDEPENDENT")
    _require(review.get("video_sha256") == video_sha256, "REVIEW_VIDEO_DIGEST_MISMATCH")
    _require(
        review.get("contract_sha256") == contract_sha256,
        "REVIEW_CONTRACT_DIGEST_MISMATCH",
    )
    _require(
        review.get("attestation") == EXPECTED_ATTESTATION, "REVIEW_BOUNDARY_INVALID"
    )
    _require(
        review.get("observed_segment_ids")
        == [segment["id"] for segment in contract["segments"]],
        "REVIEW_SEGMENTS_INVALID",
    )
    _require(review.get("credentials_exposed") is False, "REVIEW_CREDENTIAL_EXPOSURE")

    return {
        "result": "PASS",
        "cut": receipt["cut"],
        "provenance": receipt["provenance"],
        "evidence_mode": receipt["evidence_mode"],
        "video_status": receipt["status"],
        "action_executed": False,
        "video_sha256": video_sha256,
        "contract_sha256": contract_sha256,
        "video_size_bytes": size,
        "duration_seconds": duration,
        "segment_count": len(contract["segments"]),
        "independent_review": "PASS",
        "contract_result": contract_result["status"],
        "aws": AWS_CLAIM,
        "public_endpoint": "NOT_AUTHORIZED",
        "camera": "NOT_RUN",
        "physical_action": "NONE",
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_final_video_evidence(args.video, args.receipt, args.review)
    except ValueError as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        sys.exit(2)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
