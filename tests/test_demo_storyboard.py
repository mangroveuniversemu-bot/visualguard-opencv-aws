from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from ops.render_demo_storyboard import STORYBOARD_PATH, render_storyboard
from ops.verify_demo_capture_packet import (
    AWS_EVIDENCE_PATH,
    CONTRACT_PATH,
    OPERATOR_TEMPLATE,
    PACKET_PATH,
    REVIEWER_TEMPLATE,
    PacketError,
)

ROOT = Path(__file__).resolve().parents[1]
JUDGING_MATRIX_PATH = Path("evidence/CHECK126_JUDGING_NEGATIVE_CONTROL_MATRIX.json")


class StoryboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scenes: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "section" and values.get("class") == "scene":
            self.scenes.append({key: value or "" for key, value in attrs})


def _packet() -> dict:
    return json.loads((ROOT / PACKET_PATH).read_text(encoding="utf-8"))


def test_checked_in_storyboard_is_reproducible() -> None:
    assert (ROOT / STORYBOARD_PATH).read_text(encoding="utf-8") == render_storyboard(
        ROOT
    )


def test_storyboard_has_exact_packet_sequence_and_timing() -> None:
    rendered = render_storyboard(ROOT)
    parser = StoryboardParser()
    parser.feed(rendered)
    packet = _packet()
    assert [item["data-segment-id"] for item in parser.scenes] == [
        item["id"] for item in packet["capture_segments"]
    ]
    assert [int(item["data-duration-seconds"]) for item in parser.scenes] == [
        item["duration_seconds"] for item in packet["capture_segments"]
    ]
    assert sum(int(item["data-duration-seconds"]) for item in parser.scenes) == 180
    assert parser.scenes[-1]["data-end-second"] == "180"


def test_storyboard_exposes_only_bounded_public_identifiers() -> None:
    rendered = render_storyboard(ROOT)
    public = _packet()["allowed_public_identifiers"]
    for key in (
        "source_commit",
        "evidence_commit",
        "workflow_run",
        "artifact_sha256",
        "image_digest",
        "supplemental_request_id",
    ):
        assert str(public[key]) in rendered
    assert str(public["workflow_job"]) not in rendered
    assert str(public["artifact_id"]) not in rendered
    assert "AWS_CONSOLE_ACCOUNT_HEADER" not in rendered
    assert "FULL_IAM_ROLE_ARN" not in rendered


def test_storyboard_keeps_non_claims_visible() -> None:
    rendered = render_storyboard(ROOT)
    for boundary in (
        "PRIVATE AWS / SYNTHETIC INPUT / NO ACTION EXECUTED",
        "SYNTHETIC REPLAY — CAMERA NOT RUN",
        "NO PUBLIC URL / LIVE CAMERA / PHYSICAL ACTION",
    ):
        assert boundary in rendered
    assert '"recording":"NOT_RUN"' in rendered
    assert '"independent_review":"NOT_RUN"' in rendered


def test_storyboard_rejects_claim_upgrade(tmp_path: Path) -> None:
    for relative in (
        PACKET_PATH,
        CONTRACT_PATH,
        AWS_EVIDENCE_PATH,
        JUDGING_MATRIX_PATH,
        OPERATOR_TEMPLATE,
        REVIEWER_TEMPLATE,
    ):
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    packet_path = tmp_path / PACKET_PATH
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["claim_boundary"]["public_endpoint"] = "PUBLIC"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(PacketError, match="CLAIM_BOUNDARY_DRIFT"):
        render_storyboard(tmp_path)
