from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.verify_judge_evidence_index import (
    INDEX_PATH,
    IndexError,
    verify_index,
)

ROOT = Path(__file__).resolve().parents[1]


def _copy_index_fixture(tmp_path: Path) -> Path:
    for relative in (
        INDEX_PATH,
        Path("evidence/AWS_EXECUTION_20261026_40223113044.json"),
        Path("evidence/CHECK126_JUDGING_NEGATIVE_CONTROL_MATRIX.json"),
        Path(
            "evidence/CHECK136_VISUALGUARD_DEMO_VIDEO_FINAL_BYTES_BINDING_GATE001.json"
        ),
        Path("evidence/VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json"),
        Path("evidence/VISUALGUARD_AWS_DEMO_CAPTURE_PACKET002.json"),
        Path("evidence/VISUALGUARD_AWS_DEMO_STORYBOARD001.html"),
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    return tmp_path / INDEX_PATH


def _mutate(path: Path, callback) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    callback(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_checked_in_judge_index_passes() -> None:
    result = verify_index()
    assert result["status"] == "PASS"
    assert result["artifact_count"] == 6
    assert result["aws_demonstrated_case_count"] == 4
    assert result["local_negative_control_count"] == 8
    assert result["video"] == "PREPARED_NOT_RECORDED"
    assert result["competition_submission"] == "NOT_RUN"


def test_rejects_artifact_omission(tmp_path: Path) -> None:
    index_path = _copy_index_fixture(tmp_path)
    _mutate(index_path, lambda value: value["required_artifacts"].pop())
    with pytest.raises(IndexError, match="REQUIRED_ARTIFACT_SET_DRIFT"):
        verify_index(index_path, tmp_path)


def test_rejects_artifact_digest_drift(tmp_path: Path) -> None:
    index_path = _copy_index_fixture(tmp_path)
    matrix = tmp_path / "evidence/CHECK126_JUDGING_NEGATIVE_CONTROL_MATRIX.json"
    matrix.write_bytes(matrix.read_bytes() + b"\n")
    with pytest.raises(IndexError, match="ARTIFACT_DIGEST_DRIFT"):
        verify_index(index_path, tmp_path)


def test_rejects_public_endpoint_upgrade(tmp_path: Path) -> None:
    index_path = _copy_index_fixture(tmp_path)
    _mutate(
        index_path,
        lambda value: value["claim_boundary"].__setitem__("public_endpoint", "PUBLIC"),
    )
    with pytest.raises(IndexError, match="CLAIM_BOUNDARY_DRIFT"):
        verify_index(index_path, tmp_path)


def test_rejects_reserved_concurrency_overclaim(tmp_path: Path) -> None:
    index_path = _copy_index_fixture(tmp_path)
    _mutate(
        index_path,
        lambda value: value["claim_boundary"].__setitem__(
            "reserved_concurrency", "CONFIGURED"
        ),
    )
    with pytest.raises(IndexError, match="CLAIM_BOUNDARY_DRIFT"):
        verify_index(index_path, tmp_path)


def test_rejects_video_completion_overclaim(tmp_path: Path) -> None:
    index_path = _copy_index_fixture(tmp_path)
    _mutate(
        index_path,
        lambda value: value["claim_boundary"].__setitem__("video", "RECORDED"),
    )
    with pytest.raises(IndexError, match="CLAIM_BOUNDARY_DRIFT"):
        verify_index(index_path, tmp_path)


def test_rejects_secret_shaped_value(tmp_path: Path) -> None:
    index_path = _copy_index_fixture(tmp_path)
    _mutate(
        index_path,
        lambda value: value.__setitem__("debug", "AKIAABCDEFGHIJKLMNOP"),
    )
    with pytest.raises(IndexError, match="SECRET_PATTERN_DETECTED:AWS_ACCESS_KEY"):
        verify_index(index_path, tmp_path)
