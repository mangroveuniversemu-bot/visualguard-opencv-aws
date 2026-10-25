"""Render the credential-safe VisualGuard AWS demo storyboard."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any

try:
    from ops.verify_demo_capture_packet import (
        CONTRACT_PATH,
        PACKET_PATH,
        PacketError,
        _check_no_secrets,
        _load,
        _sha256,
        verify_capture_packet,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_demo_capture_packet import (
        CONTRACT_PATH,
        PACKET_PATH,
        PacketError,
        _check_no_secrets,
        _load,
        _sha256,
        verify_capture_packet,
    )

ROOT = Path(__file__).resolve().parents[1]
STORYBOARD_PATH = Path("evidence/VISUALGUARD_AWS_DEMO_STORYBOARD001.html")
CUT = "VISUALGUARD_AWS_DEMO_LOCAL_STORYBOARD_RENDER001"

TITLES = {
    "problem_and_scope": "The bounded problem",
    "opencv5_clear_path": "OpenCV 5 clear path",
    "negative_controls": "Negative controls",
    "bounded_follow_up": "Bounded follow-up",
    "aws_disclosure": "Private AWS execution",
    "falsifier_and_next_gate": "Falsifier and next gate",
}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _render_identifiers(packet: dict[str, Any]) -> str:
    public = packet["allowed_public_identifiers"]
    identifiers = [
        ("Source commit", public["source_commit"]),
        ("Evidence commit", public["evidence_commit"]),
        ("Workflow run", public["workflow_run"]),
        ("Artifact SHA-256", public["artifact_sha256"]),
        ("Image digest", public["image_digest"]),
        ("Supplemental RequestId", public["supplemental_request_id"]),
    ]
    return "".join(
        f"<dt>{_esc(label)}</dt><dd><code>{_esc(value)}</code></dd>"
        for label, value in identifiers
    )


def render_storyboard(root: Path = ROOT) -> str:
    """Return deterministic self-contained HTML after validating source evidence."""
    verify_capture_packet(root / PACKET_PATH, root)
    packet = _load(root / PACKET_PATH)
    contract = _load(root / CONTRACT_PATH)
    contract_by_id = {item["id"]: item for item in contract["segments"]}

    elapsed = 0
    scenes: list[str] = []
    for index, segment in enumerate(packet["capture_segments"], start=1):
        segment_id = segment["id"]
        contract_segment = contract_by_id[segment_id]
        duration = segment["duration_seconds"]
        start, end = elapsed, elapsed + duration
        elapsed = end
        claims = "".join(
            f"<li>{_esc(claim)}</li>" for claim in contract_segment["claims"]
        )
        identifiers = (
            f'<dl class="identifiers">{_render_identifiers(packet)}</dl>'
            if segment_id == "aws_disclosure"
            else ""
        )
        scenes.append(
            f'''<section class="scene" data-segment-id="{_esc(segment_id)}"
  data-duration-seconds="{duration}" data-start-second="{start}"
  data-end-second="{end}">
  <header><span class="counter">{index}/6</span><span>{start:03d}–{end:03d}s</span></header>
  <div class="body">
    <p class="mode">{_esc(contract_segment["evidence_mode"])}</p>
    <h2>{_esc(TITLES[segment_id])}</h2>
    <ul>{claims}</ul>
    {identifiers}
  </div>
  <footer>{_esc(segment["required_overlay"])}</footer>
</section>'''
        )

    if elapsed != contract["max_duration_seconds"]:
        raise PacketError("STORYBOARD_DURATION_DRIFT")

    metadata = {
        "schema_version": 1,
        "cut": CUT,
        "status": "PREPARED_NOT_RECORDED",
        "capture_surface": "LOCAL_REPOSITORY_RENDER_ONLY",
        "duration_seconds": elapsed,
        "segment_count": len(scenes),
        "packet_sha256": _sha256(root / PACKET_PATH),
        "contract_sha256": _sha256(root / CONTRACT_PATH),
        "aws": packet["claim_boundary"]["aws"],
        "public_endpoint": "NOT_AUTHORIZED",
        "camera": "NOT_RUN",
        "physical_action": "NONE",
        "action_executed": False,
        "recording": "NOT_RUN",
        "independent_review": "NOT_RUN",
    }
    metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VisualGuard AWS demo storyboard</title>
<style>
:root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
* {{ box-sizing: border-box; }}
html {{ scroll-snap-type: y mandatory; background: #06121c; color: #f3f8fb; }}
body {{ margin: 0; }}
.scene {{ min-height: 100vh; padding: 5vh 7vw 4vh; display: grid; grid-template-rows: auto 1fr auto;
  scroll-snap-align: start; background: radial-gradient(circle at 85% 12%, #164b65 0, #0b2535 28%, #06121c 72%); }}
header {{ display: flex; justify-content: space-between; color: #a9cad8; font-variant-numeric: tabular-nums; }}
.counter, .mode {{ color: #58d6bf; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
.body {{ align-self: center; max-width: 1050px; }}
h2 {{ margin: .15em 0 .45em; font-size: clamp(3rem, 8vw, 7rem); line-height: .95; }}
ul {{ max-width: 900px; font-size: clamp(1.2rem, 2.2vw, 2rem); line-height: 1.45; }}
li + li {{ margin-top: .45em; }}
.identifiers {{ display: grid; grid-template-columns: minmax(10rem, 14rem) 1fr; gap: .35rem 1rem;
  margin-top: 1.5rem; padding: 1rem; background: #071018cc; border: 1px solid #2b7183; border-radius: 12px; }}
dt {{ color: #9ccbd7; }} dd {{ margin: 0; overflow-wrap: anywhere; }}
footer {{ justify-self: stretch; padding: .85rem 1rem; text-align: center; border: 2px solid #58d6bf;
  background: #062d33; color: #d9fff8; font-weight: 900; letter-spacing: .04em; }}
code {{ color: #e2f6a5; }}
</style>
<script id="storyboard-metadata" type="application/json">{metadata_json}</script>
</head>
<body>
{"".join(scenes)}
</body>
</html>
"""
    _check_no_secrets(document)
    return document


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=STORYBOARD_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else args.root / args.output
    try:
        rendered = render_storyboard(args.root)
        if args.check:
            if not output.exists() or output.read_text(encoding="utf-8") != rendered:
                raise PacketError("STORYBOARD_OUTPUT_DRIFT")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8")
    except (PacketError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "cut": CUT,
                "mode": "CHECK" if args.check else "WRITE",
                "output": str(output.relative_to(args.root)),
                "sha256": _sha256_text(rendered),
                "duration_seconds": 180,
                "segment_count": 6,
                "recording": "NOT_RUN",
                "aws_call": "NOT_RUN",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
