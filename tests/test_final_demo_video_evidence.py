"""Fail-closed tests for final VisualGuard demo-video evidence."""

from __future__ import annotations

import hashlib
import json

import pytest

from ops.verify_demo_evidence_contract import AWS_CLAIM
from ops.verify_final_demo_video_evidence import (
    CONTRACT_PATH,
    EXPECTED_ATTESTATION,
    ROOT,
    VIDEO_EVIDENCE_MODE,
    verify_final_video_evidence,
)


def _write_bundle(tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"synthetic-test-video-bytes")
    contract_path = ROOT / CONTRACT_PATH
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract_sha256 = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    video_sha256 = hashlib.sha256(video.read_bytes()).hexdigest()
    cursor = 0
    observations = []
    for segment in contract["segments"]:
        end = cursor + segment["duration_seconds"]
        observations.append(
            {
                "id": segment["id"],
                "start_seconds": cursor,
                "end_seconds": end,
                "operator_observed": True,
            }
        )
        cursor = end
    receipt = {
        "schema_version": 2,
        "cut": "VISUALGUARD_DEMO_VIDEO_FINAL_BYTES_BINDING_GATE002",
        "status": "RECORDED",
        "provenance": "DERIVED",
        "evidence_mode": VIDEO_EVIDENCE_MODE,
        "action_executed": False,
        "operator_id": "operator-alpha",
        "contract_sha256": contract_sha256,
        "video": {
            "sha256": video_sha256,
            "size_bytes": video.stat().st_size,
            "duration_seconds": 180.0,
        },
        "segment_observations": observations,
        "attestation": EXPECTED_ATTESTATION,
    }
    review = {
        "schema_version": 2,
        "status": "INDEPENDENT_REVIEWED",
        "reviewer_id": "reviewer-beta",
        "video_sha256": video_sha256,
        "contract_sha256": contract_sha256,
        "observed_segment_ids": [segment["id"] for segment in contract["segments"]],
        "attestation": EXPECTED_ATTESTATION,
        "credentials_exposed": False,
    }
    receipt_path = tmp_path / "receipt.json"
    review_path = tmp_path / "review.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    return video, receipt_path, review_path, receipt, review


def _verify(video, receipt_path, review_path, duration=180.0):
    return verify_final_video_evidence(
        video,
        receipt_path,
        review_path,
        duration_probe=lambda _path: duration,
    )


def test_final_video_passes_with_distinct_reviewer(tmp_path):
    video, receipt_path, review_path, _receipt, _review = _write_bundle(tmp_path)
    result = _verify(video, receipt_path, review_path)
    assert result["result"] == "PASS"
    assert result["independent_review"] == "PASS"
    assert result["segment_count"] == 6
    assert result["aws"] == AWS_CLAIM
    assert result["public_endpoint"] == "NOT_AUTHORIZED"
    assert result["camera"] == "NOT_RUN"
    assert result["action_executed"] is False


def test_missing_video_fails_closed(tmp_path):
    video, receipt_path, review_path, _receipt, _review = _write_bundle(tmp_path)
    video.unlink()
    with pytest.raises(ValueError, match="VIDEO_MISSING"):
        _verify(video, receipt_path, review_path)


def test_substituted_video_bytes_fail_closed(tmp_path):
    video, receipt_path, review_path, _receipt, _review = _write_bundle(tmp_path)
    video.write_bytes(b"substituted-after-receipt")
    with pytest.raises(ValueError, match="VIDEO_DIGEST_MISMATCH"):
        _verify(video, receipt_path, review_path)


def test_duration_overrun_fails_closed(tmp_path):
    video, receipt_path, review_path, _receipt, _review = _write_bundle(tmp_path)
    with pytest.raises(ValueError, match="VIDEO_DURATION_EXCEEDED"):
        _verify(video, receipt_path, review_path, duration=180.1)


def test_missing_segment_observation_fails_closed(tmp_path):
    video, receipt_path, review_path, receipt, _review = _write_bundle(tmp_path)
    receipt["segment_observations"].pop()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="SEGMENT_OBSERVATIONS_INVALID"):
        _verify(video, receipt_path, review_path)


def test_public_aws_claim_overreach_fails_closed(tmp_path):
    video, receipt_path, review_path, receipt, _review = _write_bundle(tmp_path)
    receipt["attestation"] = {
        **EXPECTED_ATTESTATION,
        "public_aws_endpoint_claimed": True,
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="ATTESTATION_BOUNDARY_INVALID"):
        _verify(video, receipt_path, review_path)


def test_same_operator_and_reviewer_fails_closed(tmp_path):
    video, receipt_path, review_path, receipt, review = _write_bundle(tmp_path)
    review["reviewer_id"] = receipt["operator_id"]
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="REVIEW_NOT_INDEPENDENT"):
        _verify(video, receipt_path, review_path)


def test_review_digest_mismatch_fails_closed(tmp_path):
    video, receipt_path, review_path, _receipt, review = _write_bundle(tmp_path)
    review["video_sha256"] = "0" * 64
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="REVIEW_VIDEO_DIGEST_MISMATCH"):
        _verify(video, receipt_path, review_path)
