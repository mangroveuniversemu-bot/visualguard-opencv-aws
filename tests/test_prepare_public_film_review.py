"""Tests for the fail-closed public-film review draft generator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ops.prepare_public_film_review import prepare_public_film_review_draft
from ops.verify_public_film_evidence import (
    CONTRACT_PATH,
    PublicFilmEvidenceError,
    verify_public_film_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def test_draft_binds_exact_bytes_without_claiming_review(tmp_path: Path) -> None:
    video = tmp_path / "public-film.mp4"
    video.write_bytes(b"exact-public-film-bytes")

    draft = prepare_public_film_review_draft(
        video,
        "owner-operator",
        root=ROOT,
        duration_probe=lambda _path: 140.0,
    )

    assert draft["status"] == "PREPARED_NOT_REVIEWED"
    assert draft["reviewer_id"] == ""
    assert draft["observed_requirements"] == []
    assert draft["credentials_exposed"] is None
    assert draft["video_sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert draft["video_size_bytes"] == video.stat().st_size
    assert draft["video_duration_seconds"] == 140.0
    assert (
        draft["contract_sha256"] == hashlib.sha256((ROOT / CONTRACT_PATH).read_bytes()).hexdigest()
    )


def test_generated_draft_fails_final_verifier_closed(tmp_path: Path) -> None:
    video = tmp_path / "public-film.mp4"
    video.write_bytes(b"exact-public-film-bytes")
    draft = prepare_public_film_review_draft(
        video,
        "owner-operator",
        root=ROOT,
        duration_probe=lambda _path: 140.0,
    )
    review = tmp_path / "review.json"
    review.write_text(json.dumps(draft), encoding="utf-8")

    with pytest.raises(PublicFilmEvidenceError, match="REVIEW_INCOMPLETE"):
        verify_public_film_evidence(
            video,
            review,
            root=ROOT,
            duration_probe=lambda _path: 140.0,
        )


@pytest.mark.parametrize("duration", [138.9, 141.1, float("nan"), True])
def test_invalid_or_out_of_contract_duration_fails_closed(tmp_path: Path, duration: float) -> None:
    video = tmp_path / "public-film.mp4"
    video.write_bytes(b"exact-public-film-bytes")

    with pytest.raises(PublicFilmEvidenceError, match="VIDEO_DURATION"):
        prepare_public_film_review_draft(
            video,
            "owner-operator",
            root=ROOT,
            duration_probe=lambda _path: duration,
        )


def test_missing_video_and_blank_operator_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(PublicFilmEvidenceError, match="VIDEO_MISSING"):
        prepare_public_film_review_draft(
            tmp_path / "missing.mp4",
            "owner-operator",
            root=ROOT,
            duration_probe=lambda _path: 140.0,
        )

    video = tmp_path / "public-film.mp4"
    video.write_bytes(b"exact-public-film-bytes")
    with pytest.raises(PublicFilmEvidenceError, match="OPERATOR_ID_INVALID"):
        prepare_public_film_review_draft(
            video,
            "   ",
            root=ROOT,
            duration_probe=lambda _path: 140.0,
        )
