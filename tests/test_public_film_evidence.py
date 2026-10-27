"""Fail-closed tests for the current public VisualGuard film gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ops.verify_public_film_evidence import (
    CONTRACT_PATH,
    EXPECTED_BOUNDARY,
    REQUIRED_OBSERVATIONS,
    PublicFilmEvidenceError,
    verify_public_film_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def _bundle(tmp_path: Path):
    video = tmp_path / "public-film.mp4"
    video.write_bytes(b"fixture-video-bytes")
    contract_path = ROOT / CONTRACT_PATH
    review = {
        "schema_version": 1,
        "status": "INDEPENDENT_REVIEWED",
        "operator_id": "owner-operator",
        "reviewer_id": "reviewer-beta",
        "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "video_size_bytes": video.stat().st_size,
        "public_film_url": "https://youtu.be/AEDHXknTBy8",
        "observed_requirements": list(REQUIRED_OBSERVATIONS),
        "claim_boundary": EXPECTED_BOUNDARY,
        "credentials_exposed": False,
    }
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    return video, review_path, review


def _verify(video: Path, review_path: Path, duration: float = 140.0):
    return verify_public_film_evidence(
        video,
        review_path,
        root=ROOT,
        duration_probe=lambda _path: duration,
    )


def test_current_public_film_passes_with_distinct_reviewer(tmp_path: Path) -> None:
    video, review_path, _review = _bundle(tmp_path)
    result = _verify(video, review_path)
    assert result["result"] == "PASS"
    assert result["independent_review"] == "PASS"
    assert result["public_endpoint"] == "PUBLIC_AWS_JUDGE_UI_DEPLOYED"
    assert result["camera"] == "NOT_VERIFIED"
    assert result["action_executed"] is False


def test_missing_video_fails_closed(tmp_path: Path) -> None:
    video, review_path, _review = _bundle(tmp_path)
    video.unlink()
    with pytest.raises(PublicFilmEvidenceError, match="VIDEO_MISSING"):
        _verify(video, review_path)


def test_substituted_video_bytes_fail_closed(tmp_path: Path) -> None:
    video, review_path, _review = _bundle(tmp_path)
    video.write_bytes(b"substituted")
    with pytest.raises(PublicFilmEvidenceError, match="VIDEO_DIGEST_MISMATCH"):
        _verify(video, review_path)


def test_wrong_duration_fails_closed(tmp_path: Path) -> None:
    video, review_path, _review = _bundle(tmp_path)
    with pytest.raises(PublicFilmEvidenceError, match="VIDEO_DURATION_MISMATCH"):
        _verify(video, review_path, duration=138.9)


def test_missing_required_observation_fails_closed(tmp_path: Path) -> None:
    video, review_path, review = _bundle(tmp_path)
    review["observed_requirements"].pop()
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(PublicFilmEvidenceError, match="REQUIRED_OBSERVATIONS_INVALID"):
        _verify(video, review_path)


def test_same_operator_and_reviewer_fails_closed(tmp_path: Path) -> None:
    video, review_path, review = _bundle(tmp_path)
    review["reviewer_id"] = review["operator_id"]
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(PublicFilmEvidenceError, match="REVIEW_NOT_INDEPENDENT"):
        _verify(video, review_path)


def test_field_accuracy_overclaim_fails_closed(tmp_path: Path) -> None:
    video, review_path, review = _bundle(tmp_path)
    review["claim_boundary"] = {
        **EXPECTED_BOUNDARY,
        "field_accuracy_claimed": True,
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(PublicFilmEvidenceError, match="CLAIM_BOUNDARY_INVALID"):
        _verify(video, review_path)


def test_credential_exposure_fails_closed(tmp_path: Path) -> None:
    video, review_path, review = _bundle(tmp_path)
    review["credentials_exposed"] = True
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(PublicFilmEvidenceError, match="REVIEW_CREDENTIAL_EXPOSURE"):
        _verify(video, review_path)
