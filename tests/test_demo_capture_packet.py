from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.verify_demo_capture_packet import (
    PACKET_PATH,
    PacketError,
    verify_capture_packet,
)

ROOT = Path(__file__).resolve().parents[1]


def _packet() -> dict:
    return json.loads((ROOT / PACKET_PATH).read_text(encoding="utf-8"))


def _write(tmp_path: Path, packet: dict) -> Path:
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet), encoding="utf-8")
    return path


def test_prepared_packet_passes_without_recording_or_aws_call() -> None:
    result = verify_capture_packet(ROOT / PACKET_PATH, ROOT)
    assert result["status"] == "PASS"
    assert result["recording"] == "NOT_RUN"
    assert result["independent_review"] == "NOT_RUN"
    assert result["secret_patterns_detected"] == 0


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("status", "RECORDED", "PACKET_PREMATURE_RECORDING_CLAIM"),
        ("aws_console_capture_allowed", True, "UNSAFE_CAPTURE_FLAG"),
        ("secrets_required", True, "SECRETS_MUST_NOT_BE_REQUIRED"),
    ],
)
def test_packet_rejects_unsafe_state(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    packet = _packet()
    packet[field] = value
    with pytest.raises(PacketError, match=reason):
        verify_capture_packet(_write(tmp_path, packet), ROOT)


def test_packet_rejects_access_key_pattern(tmp_path: Path) -> None:
    packet = _packet()
    packet["unsafe_note"] = "AKIAABCDEFGHIJKLMNOP"
    with pytest.raises(PacketError, match="SECRET_PATTERN_DETECTED:AWS_ACCESS_KEY"):
        verify_capture_packet(_write(tmp_path, packet), ROOT)


def test_packet_rejects_account_id_pattern(tmp_path: Path) -> None:
    packet = _packet()
    packet["unsafe_note"] = "account 123456789012"
    with pytest.raises(PacketError, match="SECRET_PATTERN_DETECTED:AWS_ACCOUNT_ID"):
        verify_capture_packet(_write(tmp_path, packet), ROOT)


def test_packet_rejects_public_endpoint_upgrade(tmp_path: Path) -> None:
    packet = _packet()
    packet["claim_boundary"]["public_endpoint"] = "PUBLIC"
    with pytest.raises(PacketError, match="CLAIM_BOUNDARY_DRIFT"):
        verify_capture_packet(_write(tmp_path, packet), ROOT)


def test_packet_rejects_artifact_digest_drift(tmp_path: Path) -> None:
    packet = _packet()
    packet["bound_artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(PacketError, match="BOUND_ARTIFACT_DIGEST_DRIFT"):
        verify_capture_packet(_write(tmp_path, packet), ROOT)


def test_packet_rejects_segment_reordering(tmp_path: Path) -> None:
    packet = _packet()
    packet["capture_segments"] = list(reversed(packet["capture_segments"]))
    with pytest.raises(PacketError, match="CAPTURE_SEGMENT_SEQUENCE_DRIFT"):
        verify_capture_packet(_write(tmp_path, packet), ROOT)
