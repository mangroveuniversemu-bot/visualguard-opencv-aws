"""Verify the VisualGuard judging demo plan without upgrading its claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
    "AWS_LAMBDA_EXECUTION_SYNTHETIC_INPUT",
}
AWS_CLAIM = "PRIVATE_AWS_LAMBDA_SYNTHETIC_INPUT_EXECUTED"


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
            "local matrix must not be upgraded to AWS or camera evidence"
        )
    if matrix.get("physical_action") != "NONE":
        raise ContractError("synthetic matrix must not claim a physical action")
    cases = matrix.get("cases")
    required = {
        "alarm",
        "calibration_drift",
        "clear",
        "consequence_mismatch",
        "missing_view",
        "occluded",
        "stale",
        "version_drift",
    }
    if not isinstance(cases, dict) or set(cases) != required:
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


def _step(steps: object, name: str) -> dict[str, Any]:
    if not isinstance(steps, list):
        raise ContractError("AWS deployment steps are missing")
    matches = [
        item for item in steps if isinstance(item, dict) and item.get("step") == name
    ]
    if len(matches) != 1:
        raise ContractError(f"AWS step must occur exactly once: {name}")
    return matches[0]


def _validate_aws_execution(evidence: dict[str, Any]) -> None:
    if evidence.get("status") != "AWS_PRIVATE_SYNTHETIC_EXECUTION_VERIFIED":
        raise ContractError(
            "AWS evidence status is not the bounded private execution state"
        )
    source_commit = evidence.get("source_commit")
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
    ):
        raise ContractError("AWS source commit is missing or invalid")

    deployment = evidence.get("deployment")
    if not isinstance(deployment, dict):
        raise ContractError("AWS deployment record is missing")
    if deployment.get("source_commit") != source_commit:
        raise ContractError("AWS source commit binding is inconsistent")
    if deployment.get("evidence_mode") != "AWS_LAMBDA_EXECUTION_SYNTHETIC_INPUT":
        raise ContractError(
            "AWS evidence mode overstates or loses the synthetic input scope"
        )
    if deployment.get("status") != "DEPLOYED_AND_INVOKED":
        raise ContractError("private Lambda was not both deployed and invoked")
    if deployment.get("public_url") is not False:
        raise ContractError("public endpoint claim is not authorized")

    live_state = deployment.get("live_state")
    expected_live = {
        "aws_api": "EXECUTED",
        "camera": "NOT_RUN",
        "deployment": "EXECUTED",
        "endpoint": "DEPLOYED_PRIVATE_AWS_IAM",
        "physical_action": "NONE",
    }
    if live_state != expected_live:
        raise ContractError("AWS live-state boundary is invalid")

    steps = deployment.get("steps")
    function_url = _step(steps, "function_url")
    if function_url.get("auth_type") != "AWS_IAM":
        raise ContractError("Function URL must remain AWS_IAM protected")
    concurrency = _step(steps, "reserved_concurrency")
    if concurrency.get("status") != "UNAVAILABLE_FOR_ACCOUNT":
        raise ContractError("reserved concurrency must not be claimed as configured")

    results = _step(steps, "lambda_invocations").get("results")
    if not isinstance(results, dict):
        raise ContractError("Lambda invocation results are missing")
    expected = {
        "healthz": {"status_code": 200},
        "inspect_alarm": {
            "status_code": 200,
            "decision": "STOP",
            "planned_action": "HOLD_AUTOMATION",
        },
        "inspect_clear": {
            "status_code": 200,
            "decision": "REVIEW",
            "planned_action": "QUEUE_HUMAN_REVIEW",
        },
    }
    for case_id, required in expected.items():
        case = results.get(case_id)
        if not isinstance(case, dict) or any(
            case.get(key) != value for key, value in required.items()
        ):
            raise ContractError(f"AWS invocation result is invalid: {case_id}")

    reports = _step(steps, "cloudwatch_report_lines")
    lines = reports.get("lines")
    if reports.get("count") != 3 or not isinstance(lines, list) or len(lines) != 3:
        raise ContractError("three CloudWatch REPORT lines are required")
    if not all(isinstance(line, str) and "REPORT RequestId:" in line for line in lines):
        raise ContractError("CloudWatch REPORT line binding is invalid")

    negative = evidence.get("supplemental_negative_control")
    if not isinstance(negative, dict) or negative.get("pass") is not True:
        raise ContractError("AWS missing-view negative control is missing")
    if negative.get("source_commit") != source_commit:
        raise ContractError("AWS negative control source binding is inconsistent")
    parsed = negative.get("parsed_body")
    follow_up = parsed.get("follow_up") if isinstance(parsed, dict) else None
    if (
        not isinstance(parsed, dict)
        or parsed.get("decision") != "REQUEST_VIEW"
        or parsed.get("reason") != "INCOMPLETE_COVERAGE"
        or not isinstance(follow_up, dict)
        or follow_up.get("planned_action") != "REQUEST_NEW_CAPTURE"
        or follow_up.get("action_executed") is not False
    ):
        raise ContractError("AWS missing-view negative control is invalid")
    log_tail = negative.get("aws_log_tail")
    if not isinstance(log_tail, str) or "REPORT RequestId:" not in log_tail:
        raise ContractError("AWS negative control lacks a Lambda REPORT RequestId")


def verify_contract(manifest_path: Path, root: Path) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    if manifest.get("schema_version") != 2:
        raise ContractError("unsupported demo contract schema")
    if manifest.get("cut") != "VISUALGUARD_DEMO_EVIDENCE_CONTRACT002":
        raise ContractError("unexpected demo contract cut")
    if manifest.get("status") != "PREPARED_NOT_RECORDED":
        raise ContractError("contract must not claim a recorded demo")
    if manifest.get("aws_claim") != AWS_CLAIM:
        raise ContractError("contract must use the bounded private AWS claim")
    if manifest.get("public_endpoint_claim") != "NOT_AUTHORIZED":
        raise ContractError("contract must not imply a public endpoint")
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
        raise ContractError(
            "segment coverage mismatch; "
            f"missing={sorted(REQUIRED_SEGMENTS - ids)}; extra={sorted(ids - REQUIRED_SEGMENTS)}"
        )
    if duration > max_duration:
        raise ContractError(f"demo duration {duration}s exceeds {max_duration}s")

    matrix_path = "evidence/CHECK126_JUDGING_NEGATIVE_CONTROL_MATRIX.json"
    aws_path = "evidence/AWS_EXECUTION_20261026_40223113044.json"
    if matrix_path not in referenced or aws_path not in referenced:
        raise ContractError(
            "local matrix and AWS execution must both be evidence-bound"
        )
    _validate_matrix(_load_json(root / matrix_path))
    _validate_aws_execution(_load_json(root / aws_path))
    return {
        "status": "PASS",
        "contract": manifest.get("cut"),
        "duration_seconds": duration,
        "segment_count": len(segments),
        "artifact_count": len(referenced),
        "manifest_sha256": _sha256(manifest_path),
        "aws": AWS_CLAIM,
        "public_endpoint": "NOT_AUTHORIZED",
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
