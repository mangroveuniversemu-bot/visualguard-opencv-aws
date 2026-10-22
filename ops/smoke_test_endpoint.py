"""Exercise a running VisualGuard endpoint and record what it actually returned.

The same script is meant for the local container and, once authorized, the
AWS endpoint, so both produce comparable evidence. It sends synthetic sample
pairs, a capture-ID substitution, and a malformed request, then checks that
each decision and planned follow-up matches the fail-closed contract. It
never asserts where the endpoint runs; the caller records that separately.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision.synthetic_scenes import SCENARIOS_BY_NAME, render_scene  # noqa: E402

CASES = (
    ("normal_green_clear", "REVIEW", "QUEUE_HUMAN_REVIEW"),
    ("alarm_red_side_only", "STOP", "HOLD_AUTOMATION"),
    ("normal_green_with_glare", "REVIEW", "QUEUE_HUMAN_REVIEW"),
    ("normal_green_with_red_sticker", "REVIEW", "QUEUE_HUMAN_REVIEW"),
    ("normal_defocus", "REQUEST_VIEW", "REQUEST_NEW_CAPTURE"),
    ("alarm_lamp_occluded", "REQUEST_VIEW", "REQUEST_NEW_CAPTURE"),
)


def _request(base: str, method: str, path: str, body: bytes | None = None):
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read()
    elapsed = round((time.perf_counter() - started) * 1000.0, 1)
    return status, json.loads(payload), elapsed


def _pair_body(name: str, batch: str) -> bytes:
    rendered = render_scene(SCENARIOS_BY_NAME[name], split="test", index=0)
    views = {}
    for view, pixels in rendered.views.items():
        ok, encoded = cv2.imencode(".png", pixels)
        if not ok:
            raise RuntimeError("PNG encode failed")
        views[view] = {
            "image_base64": base64.b64encode(encoded.tobytes()).decode(),
            "source_id": f"camera-{view}-v1",
            "capture_id": f"{batch}-{view}",
        }
    return json.dumps({"views": views}).encode()


def run(base: str) -> dict[str, object]:
    checks = []

    def check(name, passed, **detail):
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", **detail})

    status, health, elapsed = _request(base, "GET", "/healthz")
    check(
        "healthz",
        status == 200 and health.get("runtime_matches_contract") is True,
        http_status=status,
        latency_ms=elapsed,
        runtime=health.get("runtime"),
        execution_environment=health.get("execution_environment"),
    )
    run_id = uuid.uuid4().hex[:12]
    for name, decision, action in CASES:
        status, result, elapsed = _request(
            base, "POST", "/v1/inspect", _pair_body(name, f"{run_id}-{name}")
        )
        check(
            f"inspect:{name}",
            status == 200
            and result.get("decision") == decision
            and result.get("follow_up", {}).get("planned_action") == action
            and result.get("follow_up", {}).get("action_executed") is False,
            http_status=status,
            latency_ms=elapsed,
            decision=result.get("decision"),
            reason=result.get("reason"),
            planned_action=result.get("follow_up", {}).get("planned_action"),
            server_analyze_ms=result.get("timings_ms", {}).get("analyze"),
        )
    status, result, elapsed = _request(
        base,
        "POST",
        "/v1/inspect",
        _pair_body("alarm_red_both_views", f"{run_id}-normal_green_clear"),
    )
    check(
        "negative:capture_id_substitution",
        result.get("reason") == "CAPTURE_ID_REPLAY_MISMATCH"
        and result.get("decision") == "STOP",
        http_status=status,
        latency_ms=elapsed,
        decision=result.get("decision"),
        reason=result.get("reason"),
    )
    status, result, elapsed = _request(base, "POST", "/v1/inspect", b"{not json")
    check(
        "negative:malformed_json",
        status == 400
        and result.get("decision") == "STOP"
        and result.get("follow_up", {}).get("planned_action") == "HOLD_AUTOMATION",
        http_status=status,
        latency_ms=elapsed,
        decision=result.get("decision"),
        reason=result.get("reason"),
    )
    passed = all(item["status"] == "PASS" for item in checks)
    return {
        "schema_version": 1,
        "evidence_mode": "ENDPOINT_SMOKE_TEST_SYNTHETIC_INPUT",
        "base_url": base,
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "physical_action": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", help="Optional JSON evidence path")
    args = parser.parse_args()
    report = run(args.base_url)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
