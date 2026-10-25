"""Validate the credential-safe VisualGuard AWS demo capture packet."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from ops.verify_demo_evidence_contract import AWS_CLAIM, verify_contract
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_demo_evidence_contract import AWS_CLAIM, verify_contract

ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = Path("evidence/VISUALGUARD_AWS_DEMO_CAPTURE_PACKET002.json")
CONTRACT_PATH = Path("evidence/VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json")
AWS_EVIDENCE_PATH = Path("evidence/AWS_EXECUTION_20261026_40223113044.json")
OPERATOR_TEMPLATE = Path("evidence/final-demo-video-evidence-receipt.template.json")
REVIEWER_TEMPLATE = Path("evidence/final-demo-video-review-receipt.template.json")
VIDEO_MODE = "MIXED_SYNTHETIC_REPLAY_AND_AWS_LAMBDA"
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
SECRET_PATTERNS = {
    "AWS_ACCESS_KEY": re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "AWS_ACCOUNT_ID": re.compile(
        r"(?:aws[ _-]?account|account[ _-]?id|account)\D{0,8}\d{12}",
        re.IGNORECASE,
    ),
    "AWS_ROLE_ARN": re.compile(r"arn:aws:iam::\d{12}:role/"),
    "AWS_SIGNED_QUERY": re.compile(r"X-Amz-(?:Credential|Security-Token|Signature)="),
    "AUTHORIZATION_HEADER": re.compile(
        r"Authorization\s*:\s*(?:Bearer|AWS4-HMAC-SHA256)", re.IGNORECASE
    ),
    "GITHUB_TOKEN": re.compile(r"gh[opsu]_[A-Za-z0-9]{20,}"),
}


class PacketError(ValueError):
    """The capture packet cannot safely advance to recording."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PacketError(f"JSON_READ_FAILED:{path.name}") from exc
    if not isinstance(value, dict):
        raise PacketError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _step(steps: Any, name: str) -> dict[str, Any]:
    if not isinstance(steps, list):
        raise PacketError("AWS_STEPS_MISSING")
    for step in steps:
        if isinstance(step, dict) and step.get("step") == name:
            return step
    raise PacketError(f"AWS_STEP_MISSING:{name}")


def _check_no_secrets(value: Any) -> None:
    rendered = json.dumps(value, sort_keys=True)
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(rendered):
            raise PacketError(f"SECRET_PATTERN_DETECTED:{name}")


def _validate_templates(root: Path, segment_ids: list[str]) -> None:
    operator = _load(root / OPERATOR_TEMPLATE)
    reviewer = _load(root / REVIEWER_TEMPLATE)
    if operator.get("schema_version") != 2:
        raise PacketError("OPERATOR_TEMPLATE_SCHEMA_DRIFT")
    if operator.get("cut") != "VISUALGUARD_DEMO_VIDEO_FINAL_BYTES_BINDING_GATE002":
        raise PacketError("OPERATOR_TEMPLATE_CUT_DRIFT")
    if operator.get("status") != "PREPARED_NOT_RECORDED":
        raise PacketError("OPERATOR_TEMPLATE_PREMATURE_RECORDING_CLAIM")
    if operator.get("evidence_mode") != VIDEO_MODE:
        raise PacketError("OPERATOR_TEMPLATE_EVIDENCE_MODE_DRIFT")
    if operator.get("action_executed") is not False:
        raise PacketError("OPERATOR_TEMPLATE_ACTION_OVERCLAIM")
    if operator.get("attestation") != EXPECTED_ATTESTATION:
        raise PacketError("OPERATOR_TEMPLATE_ATTESTATION_DRIFT")
    if operator.get("segment_observations") != []:
        raise PacketError("OPERATOR_TEMPLATE_MUST_START_EMPTY")
    if reviewer.get("schema_version") != 2:
        raise PacketError("REVIEWER_TEMPLATE_SCHEMA_DRIFT")
    if reviewer.get("status") != "PREPARED_NOT_REVIEWED":
        raise PacketError("REVIEWER_TEMPLATE_PREMATURE_REVIEW_CLAIM")
    if reviewer.get("attestation") != EXPECTED_ATTESTATION:
        raise PacketError("REVIEWER_TEMPLATE_ATTESTATION_DRIFT")
    if reviewer.get("observed_segment_ids") != []:
        raise PacketError("REVIEWER_TEMPLATE_MUST_START_EMPTY")
    if reviewer.get("credentials_exposed") is not False:
        raise PacketError("REVIEWER_TEMPLATE_CREDENTIAL_BOUNDARY_DRIFT")
    if operator.get("operator_id") == reviewer.get("reviewer_id"):
        raise PacketError("TEMPLATE_IDENTITIES_NOT_DISTINCT")
    if not segment_ids:
        raise PacketError("CONTRACT_SEGMENTS_MISSING")


def verify_capture_packet(packet_path: Path, root: Path = ROOT) -> dict[str, Any]:
    packet = _load(packet_path)
    if packet.get("schema_version") != 1:
        raise PacketError("PACKET_SCHEMA_UNSUPPORTED")
    if packet.get("cut") != "VISUALGUARD_AWS_DEMO_CAPTURE_PACKET002":
        raise PacketError("PACKET_CUT_INVALID")
    if packet.get("status") != "PREPARED_NOT_RECORDED":
        raise PacketError("PACKET_PREMATURE_RECORDING_CLAIM")
    if packet.get("capture_surface") != "LOCAL_REPOSITORY_RENDER_ONLY":
        raise PacketError("CAPTURE_SURFACE_UNSAFE")
    for flag in ("aws_console_capture_allowed", "browser_network_panel_allowed"):
        if packet.get(flag) is not False:
            raise PacketError(f"UNSAFE_CAPTURE_FLAG:{flag}")
    if packet.get("secrets_required") is not False:
        raise PacketError("SECRETS_MUST_NOT_BE_REQUIRED")
    if (
        packet.get("recording") != "NOT_RUN"
        or packet.get("independent_review") != "NOT_RUN"
    ):
        raise PacketError("PACKET_CANNOT_CLAIM_MEDIA_OR_REVIEW")
    _check_no_secrets(packet)

    contract_result = verify_contract(root / CONTRACT_PATH, root)
    contract = _load(root / CONTRACT_PATH)
    aws = _load(root / AWS_EVIDENCE_PATH)
    bindings = packet.get("bound_artifacts")
    if not isinstance(bindings, list) or len(bindings) != 2:
        raise PacketError("BOUND_ARTIFACTS_INVALID")
    expected_bindings = {
        str(CONTRACT_PATH): _sha256(root / CONTRACT_PATH),
        str(AWS_EVIDENCE_PATH): _sha256(root / AWS_EVIDENCE_PATH),
    }
    actual_bindings = {
        item.get("path"): item.get("sha256")
        for item in bindings
        if isinstance(item, dict)
    }
    if actual_bindings != expected_bindings:
        raise PacketError("BOUND_ARTIFACT_DIGEST_DRIFT")

    expected_boundary = {
        "aws": AWS_CLAIM,
        "public_endpoint": "NOT_AUTHORIZED",
        "camera": "NOT_RUN",
        "field_accuracy": "NOT_ESTABLISHED",
        "physical_action": "NONE",
        "action_executed": False,
        "reserved_concurrency": "UNAVAILABLE_FOR_ACCOUNT",
    }
    if packet.get("claim_boundary") != expected_boundary:
        raise PacketError("CLAIM_BOUNDARY_DRIFT")

    steps = aws.get("deployment", {}).get("steps")
    pushed = _step(steps, "image_pushed")
    concurrency = _step(steps, "reserved_concurrency")
    reports = _step(steps, "cloudwatch_report_lines")
    negative = aws.get("supplemental_negative_control", {})
    expected_identifiers = {
        "source_commit": aws.get("source_commit"),
        "evidence_commit": "3442e3aa0e8d6003c538ecd2045cd65b2e697710",
        "workflow_run": 40223113044,
        "workflow_job": 121258766517,
        "artifact_id": 12610292181,
        "artifact_sha256": "8c3e70164fe27368a1f10fb8616c2055c27d4a081374822c1d40db2702859ae6",
        "image_digest": pushed.get("image_digest"),
        "supplemental_request_id": "5e91ad05-2270-4828-b1dc-619fc4ebdd62",
    }
    if packet.get("allowed_public_identifiers") != expected_identifiers:
        raise PacketError("PUBLIC_IDENTIFIER_BINDING_DRIFT")
    if concurrency.get("status") != "UNAVAILABLE_FOR_ACCOUNT":
        raise PacketError("RESERVED_CONCURRENCY_OVERCLAIM")
    if reports.get("count") != 3:
        raise PacketError("CLOUDWATCH_REPORT_COUNT_DRIFT")
    if expected_identifiers["supplemental_request_id"] not in str(
        negative.get("aws_log_tail", "")
    ):
        raise PacketError("SUPPLEMENTAL_REQUEST_ID_DRIFT")

    segments = packet.get("capture_segments")
    contract_segments = contract.get("segments")
    if not isinstance(segments, list) or not isinstance(contract_segments, list):
        raise PacketError("CAPTURE_SEGMENTS_INVALID")
    packet_ids = [item.get("id") for item in segments if isinstance(item, dict)]
    contract_ids = [item.get("id") for item in contract_segments]
    if packet_ids != contract_ids:
        raise PacketError("CAPTURE_SEGMENT_SEQUENCE_DRIFT")
    if sum(item.get("duration_seconds", 0) for item in segments) != 180:
        raise PacketError("CAPTURE_DURATION_DRIFT")
    if any(not item.get("required_overlay") for item in segments):
        raise PacketError("CAPTURE_OVERLAY_MISSING")
    _validate_templates(root, contract_ids)
    return {
        "status": "PASS",
        "cut": packet["cut"],
        "packet_status": packet["status"],
        "capture_surface": packet["capture_surface"],
        "duration_seconds": 180,
        "segment_count": len(segments),
        "bound_artifact_count": len(bindings),
        "secret_patterns_detected": 0,
        "contract": contract_result["status"],
        "aws": AWS_CLAIM,
        "public_endpoint": "NOT_AUTHORIZED",
        "camera": "NOT_RUN",
        "action_executed": False,
        "recording": "NOT_RUN",
        "independent_review": "NOT_RUN",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("packet", nargs="?", type=Path, default=PACKET_PATH)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = verify_capture_packet(args.packet, args.root)
    except (PacketError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
