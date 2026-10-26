"""Fail-closed verification for the VisualGuard judge evidence index."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = Path("evidence/VISUALGUARD_JUDGE_EVIDENCE_INDEX001.json")
EXPECTED_BOUNDARY = {
    "aws": "PRIVATE_AWS_LAMBDA_SYNTHETIC_INPUT_EXECUTED",
    "opencv": "5.0.0",
    "public_endpoint": "NOT_AUTHORIZED",
    "camera": "NOT_RUN",
    "field_accuracy": "NOT_ESTABLISHED",
    "physical_action": "NONE",
    "action_executed": False,
    "reserved_concurrency": "UNAVAILABLE_FOR_ACCOUNT",
    "video": "PREPARED_NOT_RECORDED",
    "independent_review": "PREPARED_NOT_REVIEWED",
    "competition_submission": "NOT_RUN",
}
EXPECTED_PATHS = {
    "evidence/AWS_EXECUTION_20261026_40223113044.json",
    "evidence/CHECK126_JUDGING_NEGATIVE_CONTROL_MATRIX.json",
    "evidence/VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json",
    "evidence/VISUALGUARD_AWS_DEMO_CAPTURE_PACKET002.json",
    "evidence/VISUALGUARD_AWS_DEMO_STORYBOARD001.html",
    "evidence/CHECK136_VISUALGUARD_DEMO_VIDEO_FINAL_BYTES_BINDING_GATE001.json",
}
SECRET_PATTERNS = {
    "AWS_ACCESS_KEY": re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "AWS_ACCOUNT_ID": re.compile(r"arn:aws:iam::\d{12}:"),
    "SIGNED_QUERY": re.compile(r"X-Amz-(?:Credential|Security-Token|Signature)="),
    "AUTHORIZATION": re.compile(
        r"Authorization\s*:\s*(?:Bearer|AWS4-HMAC-SHA256)", re.IGNORECASE
    ),
    "GITHUB_TOKEN": re.compile(r"gh[opsu]_[A-Za-z0-9]{20,}"),
}


class IndexError(ValueError):
    """The index cannot be trusted as a judge-facing evidence map."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndexError(f"JSON_READ_FAILED:{path.name}") from exc
    if not isinstance(value, dict):
        raise IndexError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _step(aws: dict[str, Any], name: str) -> dict[str, Any]:
    steps = aws.get("deployment", {}).get("steps")
    if not isinstance(steps, list):
        raise IndexError("AWS_STEPS_MISSING")
    for step in steps:
        if isinstance(step, dict) and step.get("step") == name:
            return step
    raise IndexError(f"AWS_STEP_MISSING:{name}")


def _assert_safe_index(index: dict[str, Any]) -> None:
    rendered = json.dumps(index, sort_keys=True)
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(rendered):
            raise IndexError(f"SECRET_PATTERN_DETECTED:{name}")


def verify_index(index_path: Path = INDEX_PATH, root: Path = ROOT) -> dict[str, Any]:
    index = _load(root / index_path if not index_path.is_absolute() else index_path)
    if index.get("schema_version") != 1:
        raise IndexError("INDEX_SCHEMA_UNSUPPORTED")
    if index.get("cut") != "VISUALGUARD_JUDGE_EVIDENCE_INDEX001":
        raise IndexError("INDEX_CUT_INVALID")
    if index.get("status") != "VERIFIED_INDEX_VIDEO_NOT_RECORDED":
        raise IndexError("INDEX_STATUS_OVERCLAIM")
    if index.get("claim_boundary") != EXPECTED_BOUNDARY:
        raise IndexError("CLAIM_BOUNDARY_DRIFT")
    _assert_safe_index(index)

    artifacts = index.get("required_artifacts")
    if not isinstance(artifacts, list):
        raise IndexError("REQUIRED_ARTIFACTS_MISSING")
    paths = [item.get("path") for item in artifacts if isinstance(item, dict)]
    if set(paths) != EXPECTED_PATHS or len(paths) != len(EXPECTED_PATHS):
        raise IndexError("REQUIRED_ARTIFACT_SET_DRIFT")
    for item in artifacts:
        relative = item.get("path")
        if not isinstance(relative, str):
            raise IndexError("ARTIFACT_PATH_INVALID")
        actual = _sha256(root / relative)
        if item.get("sha256") != actual:
            raise IndexError(f"ARTIFACT_DIGEST_DRIFT:{relative}")

    aws = _load(root / "evidence/AWS_EXECUTION_20261026_40223113044.json")
    matrix = _load(root / "evidence/CHECK126_JUDGING_NEGATIVE_CONTROL_MATRIX.json")
    contract = _load(root / "evidence/VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json")
    packet = _load(root / "evidence/VISUALGUARD_AWS_DEMO_CAPTURE_PACKET002.json")
    video_gate = _load(
        root
        / "evidence/CHECK136_VISUALGUARD_DEMO_VIDEO_FINAL_BYTES_BINDING_GATE001.json"
    )

    pushed = _step(aws, "image_pushed")
    invoked = _step(aws, "lambda_invocations").get("results", {})
    reports = _step(aws, "cloudwatch_report_lines")
    concurrency = _step(aws, "reserved_concurrency")
    supplemental = aws.get("supplemental_negative_control", {})
    receipt = index.get("aws_receipt", {})
    expected_receipt = {
        "source_commit": "832b1b476ce88e3fa95e83ac5749f64af0f4bd63",
        "evidence_commit": "3442e3aa0e8d6003c538ecd2045cd65b2e697710",
        "workflow_run": 40223113044,
        "workflow_job": 121258766517,
        "artifact_id": 12610292181,
        "artifact_sha256": "8c3e70164fe27368a1f10fb8616c2055c27d4a081374822c1d40db2702859ae6",
        "image_digest": "sha256:78d00e60f73ec608d65c054b220cd1bfaa8293ad752849dff6352aabd9324ddd",
        "cloudwatch_report_count": 3,
        "supplemental_request_id": "5e91ad05-2270-4828-b1dc-619fc4ebdd62",
    }
    if receipt != expected_receipt:
        raise IndexError("AWS_RECEIPT_DRIFT")
    if aws.get("source_commit") != receipt["source_commit"]:
        raise IndexError("AWS_SOURCE_COMMIT_DRIFT")
    if pushed.get("image_digest") != receipt["image_digest"]:
        raise IndexError("AWS_IMAGE_DIGEST_DRIFT")
    if reports.get("count") != receipt["cloudwatch_report_count"]:
        raise IndexError("CLOUDWATCH_REPORT_COUNT_DRIFT")
    if receipt["supplemental_request_id"] not in str(supplemental.get("aws_log_tail")):
        raise IndexError("SUPPLEMENTAL_REQUEST_ID_DRIFT")
    if concurrency.get("status") != "UNAVAILABLE_FOR_ACCOUNT":
        raise IndexError("RESERVED_CONCURRENCY_OVERCLAIM")

    expected_invocations = {
        "healthz": (200, None, None),
        "inspect_alarm": (200, "STOP", "HOLD_AUTOMATION"),
        "inspect_clear": (200, "REVIEW", "QUEUE_HUMAN_REVIEW"),
    }
    for name, expected in expected_invocations.items():
        value = invoked.get(name, {})
        actual = (
            value.get("status_code"),
            value.get("decision"),
            value.get("planned_action"),
        )
        if actual != expected:
            raise IndexError(f"AWS_INVOCATION_DRIFT:{name}")
    parsed = supplemental.get("parsed_body", {})
    follow_up = parsed.get("follow_up", {})
    if (
        parsed.get("decision") != "REQUEST_VIEW"
        or parsed.get("reason") != "INCOMPLETE_COVERAGE"
        or follow_up.get("planned_action") != "REQUEST_NEW_CAPTURE"
        or follow_up.get("action_executed") is not False
    ):
        raise IndexError("AWS_NEGATIVE_CONTROL_DRIFT")

    cases = matrix.get("cases")
    expected_cases = index.get("demonstrated_cases", {}).get(
        "local_synthetic_negative_controls"
    )
    if (
        matrix.get("evidence_mode") != "SYNTHETIC_REPLAY"
        or matrix.get("aws") != "NOT_RUN"
    ):
        raise IndexError("LOCAL_MATRIX_MODE_DRIFT")
    if not isinstance(cases, dict) or sorted(cases) != sorted(expected_cases or []):
        raise IndexError("NEGATIVE_CONTROL_CASE_SET_DRIFT")
    if any(
        item.get("follow_up", {}).get("action_executed") is not False
        for item in cases.values()
    ):
        raise IndexError("NEGATIVE_CONTROL_ACTION_OVERCLAIM")

    if (
        contract.get("status") != "PREPARED_NOT_RECORDED"
        or contract.get("aws_claim") != EXPECTED_BOUNDARY["aws"]
        or contract.get("public_endpoint_claim") != "NOT_AUTHORIZED"
        or contract.get("camera_claim") != "NOT_RUN"
        or contract.get("action_executed") is not False
    ):
        raise IndexError("DEMO_CONTRACT_DRIFT")
    packet_boundary = packet.get("claim_boundary", {})
    if (
        packet.get("recording") != "NOT_RUN"
        or packet.get("independent_review") != "NOT_RUN"
    ):
        raise IndexError("CAPTURE_PACKET_MEDIA_OVERCLAIM")
    if packet_boundary.get("reserved_concurrency") != "UNAVAILABLE_FOR_ACCOUNT":
        raise IndexError("CAPTURE_PACKET_CONCURRENCY_OVERCLAIM")
    result = video_gate.get("result", {})
    if (
        result.get("gate_status") != "PREPARED_NOT_RECORDED"
        or result.get("review_status") != "PREPARED_NOT_REVIEWED"
        or result.get("actual_probe_reason") != "VIDEO_MISSING"
    ):
        raise IndexError("FINAL_VIDEO_GATE_OVERCLAIM")

    return {
        "status": "PASS",
        "cut": index["cut"],
        "artifact_count": len(artifacts),
        "aws_receipt": "PRIVATE_AWS_LAMBDA_SYNTHETIC_INPUT_EXECUTED",
        "aws_demonstrated_case_count": 4,
        "local_negative_control_count": len(cases),
        "public_endpoint": "NOT_AUTHORIZED",
        "camera": "NOT_RUN",
        "action_executed": False,
        "video": "PREPARED_NOT_RECORDED",
        "independent_review": "PREPARED_NOT_REVIEWED",
        "competition_submission": "NOT_RUN",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("index", nargs="?", type=Path, default=INDEX_PATH)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = verify_index(args.index, args.root)
    except (IndexError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
