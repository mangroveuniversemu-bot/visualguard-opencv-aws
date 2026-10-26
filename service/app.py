"""VisualGuard HTTP service: OpenCV 5 two-view inspection endpoint and demo UI.

Standard-library HTTP only. One request core (``Service.handle``) serves the
local ``http.server`` process, the container image, and the AWS Lambda
adapter, so every surface runs the same pipeline and the same fail-closed
rules. The service plans follow-up steps but never executes an external or
physical action.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
import threading
import time
import uuid
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision import scene_analysis as sa  # noqa: E402
from vision.follow_up import plan_follow_up  # noqa: E402
from vision.opencv5_inspection import VIEW_SOURCE_IDS, CaptureReplayLedger  # noqa: E402
from vision.synthetic_scenes import SCENARIOS_BY_NAME, render_scene  # noqa: E402
from service.daily_quota import (
    DEFAULT_QUOTA_TABLE,
    QUOTA_LIMIT,
    DailyInferenceQuota,
    QuotaReached,
    QuotaUnavailable,
)

MAX_BODY_BYTES = 8 * 1024 * 1024
MIN_IMAGE_SIDE = 160
MAX_IMAGE_SIDE = 4096
DEFAULT_LEDGER_PATH = "/tmp/visualguard/capture-replay.sqlite3"
SAMPLE_SCENARIOS = (
    "normal_green_clear",
    "alarm_red_side_only",
    "normal_green_with_glare",
    "normal_green_with_red_sticker",
    "normal_defocus",
    "normal_lens_occluded",
    "alarm_lamp_occluded",
    "normal_round_red_sticker",
)
INDEX_HTML = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")


class RequestError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def execution_environment() -> dict[str, str]:
    """Self-reported runtime markers. Not proof of AWS execution."""
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        platform = "AWS_LAMBDA"
    elif os.environ.get("ECS_CONTAINER_METADATA_URI_V4"):
        platform = "AWS_ECS"
    else:
        platform = os.environ.get("VISUALGUARD_EXECUTION_ENV", "LOCAL")
    return {
        "platform": platform,
        "region": os.environ.get("AWS_REGION", ""),
        "evidence_class": "SELF_REPORTED",
    }


def _encode_png(pixels: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".png", pixels)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _decode_image(payload: object) -> tuple[np.ndarray, list[int], bool]:
    if not isinstance(payload, str) or not payload:
        raise RequestError(400, "IMAGE_BASE64_REQUIRED")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise RequestError(400, "IMAGE_BASE64_INVALID") from error
    pixels = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise RequestError(422, "IMAGE_DECODE_FAILED")
    height, width = pixels.shape[:2]
    if not (
        MIN_IMAGE_SIDE <= height <= MAX_IMAGE_SIDE
        and MIN_IMAGE_SIDE <= width <= MAX_IMAGE_SIDE
    ):
        raise RequestError(422, "IMAGE_DIMENSIONS_OUT_OF_RANGE")
    resized = (height, width) != (sa.FRAME_HEIGHT, sa.FRAME_WIDTH)
    if resized:
        pixels = cv2.resize(
            pixels, (sa.FRAME_WIDTH, sa.FRAME_HEIGHT), interpolation=cv2.INTER_AREA
        )
    return np.ascontiguousarray(pixels), [int(height), int(width)], resized


def _optional_time(value: object, fallback: float) -> tuple[float, str]:
    if value is None:
        return fallback, "SERVER_RECEIVE"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError(400, "CAPTURED_AT_INVALID")
    return float(value), "CLIENT"


@lru_cache(maxsize=len(SAMPLE_SCENARIOS))
def sample_payload(name: str) -> dict[str, object]:
    scenario = SCENARIOS_BY_NAME[name]
    rendered = render_scene(scenario, split="dev", index=0)
    return {
        "scenario": name,
        "expected": scenario.expected,
        "note": scenario.note,
        "input_mode": "SYNTHETIC_SCENE",
        "views": {
            view: {
                "image_base64": _encode_png(pixels),
                "source_id": VIEW_SOURCE_IDS[view],
            }
            for view, pixels in rendered.views.items()
        },
    }


class Service:
    def __init__(self, ledger_path: str | Path, clock=time.time, daily_quota=None):
        Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)
        self.ledger = CaptureReplayLedger(ledger_path)
        self.clock = clock
        self.daily_quota = daily_quota
        self._log_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> Service:
        quota = None
        if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            import boto3

            quota = DailyInferenceQuota(
                boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION")),
                table_name=os.environ.get(
                    "VISUALGUARD_DAILY_QUOTA_TABLE", DEFAULT_QUOTA_TABLE
                ),
            )
        return cls(
            os.environ.get("VISUALGUARD_LEDGER_PATH", DEFAULT_LEDGER_PATH),
            daily_quota=quota,
        )

    def close(self) -> None:
        self.ledger.close()

    def _log(self, record: dict[str, object]) -> None:
        with self._log_lock:
            print(json.dumps(record, sort_keys=True), flush=True)

    def handle(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        body_too_large: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        route = path.split("?", 1)[0]
        decision = reason = None
        quota_remaining = None
        try:
            if method == "GET" and route == "/":
                status, content_type, payload = 200, "text/html", INDEX_HTML.encode()
            elif method == "GET" and route == "/healthz":
                status, content_type = 200, "application/json"
                payload = self._json(self.health())
            elif method == "GET" and route == "/v1/samples":
                status, content_type = 200, "application/json"
                payload = self._json({"samples": list(SAMPLE_SCENARIOS)})
            elif method == "GET" and route.startswith("/v1/samples/"):
                name = route.rsplit("/", 1)[1]
                if name not in SAMPLE_SCENARIOS:
                    raise RequestError(404, "SAMPLE_NOT_FOUND")
                status, content_type = 200, "application/json"
                payload = self._json(sample_payload(name))
            elif route == "/v1/inspect":
                if method != "POST":
                    raise RequestError(405, "METHOD_NOT_ALLOWED")
                if body_too_large or len(body) > MAX_BODY_BYTES:
                    raise RequestError(413, "BODY_TOO_LARGE")
                if self.daily_quota is not None:
                    try:
                        quota_remaining = self.daily_quota.claim()
                    except QuotaReached as error:
                        quota_remaining = 0
                        raise RequestError(429, "DAILY_INFERENCE_LIMIT_REACHED") from error
                    except QuotaUnavailable as error:
                        raise RequestError(503, "DAILY_QUOTA_UNAVAILABLE") from error
                result = self.inspect(body, request_id)
                decision, reason = result["decision"], result["reason"]
                status, content_type, payload = (
                    200,
                    "application/json",
                    self._json(result),
                )
            else:
                raise RequestError(404, "NOT_FOUND")
        except RequestError as error:
            status, content_type = error.status, "application/json"
            body_out: dict[str, object] = {"error": error.code}
            if route == "/v1/inspect":
                decision, reason = "STOP", error.code
                failed = {"decision": "STOP", "reason": error.code}
                body_out.update(
                    failed,
                    follow_up=plan_follow_up(failed),
                    physical_action="NONE",
                )
            payload = self._json(body_out)
        self._log(
            {
                "event": "request",
                "request_id": request_id,
                "method": method,
                "path": route,
                "status": status,
                "decision": decision,
                "reason": reason,
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "execution_environment": execution_environment()["platform"],
            }
        )
        headers = {
            "Content-Type": f"{content_type}; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Request-Id": request_id,
        }
        if self.daily_quota is not None:
            headers["X-Daily-Quota-Limit"] = str(QUOTA_LIMIT)
            if quota_remaining is not None:
                headers["X-Daily-Quota-Remaining"] = str(quota_remaining)
            headers["X-Daily-Quota-Reset-Timezone"] = "Asia/Taipei"
        return status, headers, payload

    @staticmethod
    def _json(value: object) -> bytes:
        return json.dumps(value, sort_keys=True).encode()

    def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "runtime": sa.runtime_evidence(),
            "runtime_matches_contract": sa.runtime_matches_contract(),
            "execution_environment": execution_environment(),
            "live_state": {"camera": "NOT_RUN", "physical_action": "NONE"},
        }

    def inspect(self, body: bytes, request_id: str) -> dict[str, object]:
        received_at = float(self.clock())
        try:
            request = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestError(400, "INVALID_JSON") from error
        if not isinstance(request, dict) or not isinstance(request.get("views"), dict):
            raise RequestError(400, "VIEWS_OBJECT_REQUIRED")
        annotate = request.get("annotate", False) is True
        captured_at, capture_time_source = _optional_time(
            request.get("captured_at"), received_at
        )
        decode_started = time.perf_counter()
        views: dict[str, sa.SceneView] = {}
        inputs: dict[str, dict[str, object]] = {}
        for name, item in request["views"].items():
            if not isinstance(name, str) or not isinstance(item, dict):
                raise RequestError(400, "VIEW_OBJECT_INVALID")
            pixels, original_shape, resized = _decode_image(item.get("image_base64"))
            view_time, _ = _optional_time(item.get("captured_at"), captured_at)
            views[name] = sa.SceneView(
                pixels,
                source_id=item.get("source_id"),
                capture_id=item.get("capture_id"),
                captured_at=view_time,
            )
            inputs[name] = {"original_shape": original_shape, "resized": resized}
        decode_ms = (time.perf_counter() - decode_started) * 1000.0

        analyze_started = time.perf_counter()
        result = sa.analyze_scene(
            views,
            captured_at=captured_at,
            now=received_at,
            replay_ledger=self.ledger,
        )
        analyze_ms = (time.perf_counter() - analyze_started) * 1000.0
        follow_up = plan_follow_up(result)

        view_results = result.get("views", {})
        for name, view_result in view_results.items():
            view_result.update(inputs.get(name, {}))
            if annotate:
                view_result["annotated_png_base64"] = _encode_png(
                    sa.annotate(views[name].pixels, view_result)
                )
        trace = [
            {
                "step": "perceive",
                "tool": "opencv5_scene_analysis",
                "summary": {
                    name: {
                        "usable": vr["quality"]["usable"],
                        "failures": vr["quality"]["failures"],
                        "lit_red_indicators": len(vr["detections"]),
                    }
                    for name, vr in view_results.items()
                },
            },
            {
                "step": "decide",
                "decision": result["decision"],
                "reason": result["reason"],
            },
            {
                "step": "plan",
                "planned_action": follow_up["planned_action"],
                "action_executed": follow_up["action_executed"],
                "requires_human": follow_up["planned_action"]
                in {"QUEUE_HUMAN_REVIEW", "HOLD_AUTOMATION"},
            },
        ]
        return {
            "request_id": request_id,
            "decision": result["decision"],
            "reason": result["reason"],
            "follow_up": follow_up,
            "trace": trace,
            "views": view_results,
            "evidence": {
                **result.get("evidence", {}),
                "capture_time_source": capture_time_source,
                "received_at": received_at,
            },
            "timings_ms": {
                "decode": round(decode_ms, 3),
                "analyze": round(analyze_ms, 3),
            },
            "execution_environment": execution_environment(),
            "live_state": {"camera": "NOT_RUN", "physical_action": "NONE"},
            "physical_action": "NONE",
        }


def make_handler(service: Service) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "VisualGuard/1"

        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                status, headers, payload = service.handle(
                    method, self.path, body_too_large=True
                )
                self.close_connection = True
            else:
                body = self.rfile.read(length) if length else b""
                status, headers, payload = service.handle(method, self.path, body)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802 - http.server naming
            self._dispatch("POST")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return  # structured JSON logs are emitted by Service.handle

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    args = parser.parse_args()
    service = Service.from_env()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print(
        json.dumps(
            {
                "event": "listening",
                "host": args.host,
                "port": server.server_address[1],
                "runtime": sa.runtime_evidence(),
                "execution_environment": execution_environment(),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
