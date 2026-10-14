"""Verify the judging demo plan without upgrading local evidence to live claims."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_SEGMENTS = {
    "problem_and_scope",
    "opencv5_clear_path",
    "negative_controls",
    "bounded_follow_up",
    "aws_disclosure",
    "falsifier_and_next_gate",
}
ALLOWED_MODES = {
    "PUBLIC_REFERENCE",
    "LOCAL_HTTP_FIXTURE",
    "SYNTHETIC_REPLAY",
    "AWS_READ_ONLY_PREFLIGHT",
}


class ContractError(ValueError):
    """Raised when a demo plan overstates or loses its evidence."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON artifact must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ContractError("artifact path must be a non-empty string")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ContractError(f"artifact escapes repository root: {relative}") from exc
    if not candidate.is_file():
        raise ContractError(f"artifact does not exist: {relative}")
    return candidate


def _validate_matrix(matrix: dict[str, Any]) -> None:
    if matrix.get("evidence_mode") != "SYNTHETIC_REPLAY":
        raise ContractError("OpenCV matrix must remain SYNTHETIC_REPLAY")
    if matrix.get("input") != "FIXED_SYNTHETIC_ARRAYS":
        raise ContractError("OpenCV matrix input must remain fixed synthetic arrays")
    runtime = matrix.get("runtime")
    if not isinstance(runtime, dict) or not str(
        runtime.get("opencv_version", "")
    ).startswith("5."):
        raise ContractError("OpenCV 5 runtime evidence is missing")
    if matrix.get("aws") != "NOT_RUN" or matrix.get("camera") != "NOT_RUN":
        raise ContractError(
            "synthetic matrix must not claim live AWS or camera evidence"
        )
    if matrix.get("physical_action") != "NONE":
        raise ContractError("synthetic matrix must not claim a physical action")
    cases = matrix.get("cases")
    if not isinstance(cases, dict) or set(cases) != {
        "alarm",
        "calibration_drift",
        "clear",
        "consequence_mismatch",
        "missing_view",
        "occluded",
        "stale",
        "version_drift",
    }:
        raise ContractError("required eight-case OpenCV matrix is incomplete")
    for case_id, case in cases.items():
        follow_up = case.get("follow_up") if isinstance(case, dict) else None
        if (
            not isinstance(follow_up, dict)
            or follow_up.get("action_executed") is not False
        ):
            raise ContractError(f"case {case_id} does not prove non-execution")
        if follow_up.get("physical_action") != "NONE":
            raise ContractError(f"case {case_id} overstates a physical action")


def _validate_aws_preflight(preflight: dict[str, Any]) -> None:
    if preflight.get("evidence_mode") != "AWS_READ_ONLY_PREFLIGHT":
        raise ContractError("AWS evidence must remain read-only preflight evidence")
    if preflight.get("status") != "BLOCKED":
        raise ContractError("this prepared plan is bound to the blocked AWS preflight")
    if preflight.get("commands_run") != []:
        raise ContractError("blocked preflight must not imply AWS commands ran")
    if preflight.get("action_executed") is not False:
        raise ContractError("blocked preflight must record action_executed=false")
    live_state = preflight.get("live_state")
    if not isinstance(live_state, dict):
        raise ContractError("AWS live-state disclosure is missing")
    for field in ("aws_api", "deployment", "endpoint", "camera"):
        if live_state.get(field) not in {"NOT_RUN", "NOT_DEPLOYED"}:
            raise ContractError(f"blocked preflight overstates live field: {field}")


def verify_contract(manifest_path: Path, root: Path) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    if manifest.get("schema_version") != 1:
        raise ContractError("unsupported demo contract schema")
    if manifest.get("status") != "PREPARED_NOT_RECORDED":
        raise ContractError("contract must not claim a recorded demo")
    if manifest.get("aws_claim") != "NOT_RUN":
        raise ContractError("prepared demo must disclose AWS as NOT_RUN")
    if manifest.get("camera_claim") != "NOT_RUN":
        raise ContractError("prepared demo must disclose live camera as NOT_RUN")
    if manifest.get("action_executed") is not False:
        raise ContractError("prepared demo must record action_executed=false")

    max_duration = manifest.get("max_duration_seconds")
    if not isinstance(max_duration, int) or max_duration <= 0 or max_duration > 180:
        raise ContractError(
            "max duration must be an integer no greater than 180 seconds"
        )
    segments = manifest.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ContractError("demo segments are missing")
    ids: set[str] = set()
    duration = 0
    referenced: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict):
            raise ContractError("each segment must be an object")
        segment_id = segment.get("id")
        if not isinstance(segment_id, str) or not segment_id or segment_id in ids:
            raise ContractError("segment ids must be unique non-empty strings")
        ids.add(segment_id)
        seconds = segment.get("duration_seconds")
        if not isinstance(seconds, int) or seconds <= 0:
            raise ContractError(f"invalid duration for segment {segment_id}")
        duration += seconds
        if segment.get("evidence_mode") not in ALLOWED_MODES:
            raise ContractError(f"invalid evidence mode for segment {segment_id}")
        claims = segment.get("claims")
        if (
            not isinstance(claims, list)
            or not claims
            or not all(isinstance(claim, str) and claim.strip() for claim in claims)
        ):
            raise ContractError(f"segment {segment_id} has no bounded claims")
        artifacts = segment.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise ContractError(f"invalid artifacts for segment {segment_id}")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ContractError(
                    f"invalid artifact binding for segment {segment_id}"
                )
            relative = artifact.get("path")
            expected = artifact.get("sha256")
            path = _artifact_path(root, relative)
            if not isinstance(expected, str) or len(expected) != 64:
                raise ContractError(f"invalid SHA-256 binding for {relative}")
            if _sha256(path) != expected:
                raise ContractError(f"artifact digest drift: {relative}")
            referenced.add(str(relative))

    if ids != REQUIRED_SEGMENTS:
        missing = sorted(REQUIRED_SEGMENTS - ids)
        extra = sorted(ids - REQUIRED_SEGMENTS)
        raise ContractError(
            f"segment coverage mismatch; missing={missing}; extra={extra}"
        )
    if duration > max_duration:
        raise ContractError(f"demo duration {duration}s exceeds {max_duration}s")

    matrix_path = "evidence/CHECK126_JUDGING_NEGATIVE_CONTROL_MATRIX.json"
    preflight_path = "evidence/CHECK129_AWS_DEPLOYMENT_PREFLIGHT.json"
    if matrix_path not in referenced or preflight_path not in referenced:
        raise ContractError(
            "OpenCV matrix and AWS preflight must both be evidence-bound"
        )
    _validate_matrix(_load_json(root / matrix_path))
    _validate_aws_preflight(_load_json(root / preflight_path))
    return {
        "status": "PASS",
        "contract": manifest.get("cut"),
        "duration_seconds": duration,
        "segment_count": len(segments),
        "artifact_count": len(referenced),
        "manifest_sha256": _sha256(manifest_path),
        "aws": "NOT_RUN",
        "camera": "NOT_RUN",
        "action_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path("evidence/VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json"),
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        result = verify_contract(args.manifest, args.root)
    except ContractError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
