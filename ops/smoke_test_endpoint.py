"""Exercise a running VisualGuard endpoint and record what it actually returned.

The local mode sends the full synthetic sample matrix, a capture-ID
substitution, and a malformed request. The public AWS mode deliberately sends
one synthetic inference, checks the global daily-quota headers, and verifies
the public page, health route, and sample catalog without consuming the daily
allowance during read-only checks.
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


def _request_bytes(base: str, method: str, path: str, body: bytes | None = None):
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
            content_type = response.headers.get("Content-Type", "")
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read()
        content_type = error.headers.get("Content-Type", "")
        response_headers = {key.lower(): value for key, value in error.headers.items()}
    elapsed = round((time.perf_counter() - started) * 1000.0, 1)
    return status, content_type, payload, elapsed, response_headers


def _request(base: str, method: str, path: str, body: bytes | None = None):
    status, content_type, payload, elapsed, headers = _request_bytes(base, method, path, body)
    return status, json.loads(payload), elapsed, content_type, headers


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


def run(base: str, *, expected_environment: str | None = None) -> dict[str, object]:
    checks = []

    def check(name, passed, **detail):
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", **detail})

    status, health, elapsed, _, _ = _request(base, "GET", "/healthz")
    environment = (health.get("execution_environment") or {}).get("platform")
    check(
        "healthz",
        status == 200
        and health.get("runtime_matches_contract") is True
        and (expected_environment is None or environment == expected_environment),
        http_status=status,
        latency_ms=elapsed,
        runtime=health.get("runtime"),
        execution_environment=environment,
        expected_environment=expected_environment,
    )
    status, content_type, page, elapsed, _ = _request_bytes(base, "GET", "/")
    html = page.decode("utf-8", errors="replace")
    check(
        "public_ui",
        status == 200
        and "text/html" in content_type.lower()
        and '<html lang="en">' in html
        and "VisualGuard Inspector" in html
        and 'fetch("/healthz")' in html
        and 'fetch("/v1/samples")' in html
        and 'fetch("/v1/inspect"' in html,
        http_status=status,
        content_type=content_type,
        latency_ms=elapsed,
        same_origin_api=True,
    )
    status, samples, elapsed, _, _ = _request(base, "GET", "/v1/samples")
    check(
        "public_ui_sample_catalog",
        status == 200 and len(samples.get("samples", [])) == 8,
        http_status=status,
        latency_ms=elapsed,
        sample_count=len(samples.get("samples", [])),
    )
    run_id = uuid.uuid4().hex[:12]
    public_aws = expected_environment == "AWS_LAMBDA"
    cases = CASES[:1] if public_aws else CASES
    quota_evidence = None
    for name, decision, action in cases:
        status, result, elapsed, _, headers = _request(
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
        if public_aws:
            try:
                limit = int(headers.get("x-daily-quota-limit", ""))
                remaining = int(headers.get("x-daily-quota-remaining", ""))
                quota_passed = limit == 5 and 0 <= remaining < limit
            except ValueError:
                limit, remaining, quota_passed = None, None, False
            quota_evidence = {
                "check": "shared_daily_quota",
                "status": "PASS" if quota_passed else "FAIL",
                "limit": limit,
                "remaining_after_smoke": remaining,
                "timezone": headers.get("x-daily-quota-reset-timezone"),
                "inspection_requests_used_by_this_smoke": 1,
            }
            check(
                "shared_daily_quota",
                quota_passed
                and quota_evidence["timezone"] == "Asia/Taipei",
                limit=limit,
                remaining_after_smoke=remaining,
                timezone=quota_evidence["timezone"],
                inspection_requests_used_by_this_smoke=1,
            )
    if not public_aws:
        status, result, elapsed, _, _ = _request(
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
        status, result, elapsed, _, _ = _request(base, "POST", "/v1/inspect", b"{not json")
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
        "quota_evidence": quota_evidence,
        "inspection_requests_used": 1 if public_aws else len(CASES) + 2,
        "physical_action": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--expected-environment",
        help="Require the runtime reported by /healthz (for example AWS_LAMBDA)",
    )
    parser.add_argument("--output", help="Optional JSON evidence path")
    args = parser.parse_args()
    report = run(args.base_url, expected_environment=args.expected_environment)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
