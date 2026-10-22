"""HTTP service and Lambda adapter: routing, fail-closed errors, replay control."""

from __future__ import annotations

import base64
import http.client
import json
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from io import StringIO
from pathlib import Path

import cv2

from service import app as service_app
from service import lambda_handler
from vision.synthetic_scenes import SCENARIOS_BY_NAME, render_scene


def png_b64(pixels) -> str:
    ok, encoded = cv2.imencode(".png", pixels)
    assert ok
    return base64.b64encode(encoded.tobytes()).decode()


def inspect_body(name: str, batch: str, **extra) -> bytes:
    rendered = render_scene(SCENARIOS_BY_NAME[name], split="dev", index=0)
    views = {
        view: {
            "image_base64": png_b64(pixels),
            "source_id": f"camera-{view}-v1",
            "capture_id": f"{batch}-{view}",
        }
        for view, pixels in rendered.views.items()
    }
    return json.dumps({"views": views, **extra}).encode()


class ServiceCore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.service = service_app.Service(Path(self._tmp.name) / "ledger.sqlite3")
        self._quiet = redirect_stdout(StringIO())
        self.log = self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        self.service.close()
        self._tmp.cleanup()

    def call(self, method, path, body=b""):
        status, headers, payload = self.service.handle(method, path, body)
        return status, headers, payload

    def test_alarm_pair_plans_hold_with_trace_and_overlay(self):
        status, headers, payload = self.call(
            "POST",
            "/v1/inspect",
            inspect_body("alarm_red_side_only", "a", annotate=True),
        )
        result = json.loads(payload)
        self.assertEqual(status, 200)
        self.assertEqual(result["decision"], "STOP")
        self.assertEqual(result["reason"], "ALARM")
        self.assertEqual(result["follow_up"]["planned_action"], "HOLD_AUTOMATION")
        self.assertFalse(result["follow_up"]["action_executed"])
        self.assertEqual(
            [step["step"] for step in result["trace"]], ["perceive", "decide", "plan"]
        )
        self.assertIn("annotated_png_base64", result["views"]["side"])
        self.assertEqual(result["evidence"]["capture_time_source"], "SERVER_RECEIVE")
        self.assertEqual(
            result["execution_environment"]["evidence_class"], "SELF_REPORTED"
        )
        self.assertIn("X-Request-Id", headers)
        log = [json.loads(line) for line in self.log.getvalue().splitlines()]
        self.assertEqual(log[-1]["decision"], "STOP")
        self.assertNotIn("image_base64", self.log.getvalue())

    def test_clear_and_degraded_pairs_route_differently(self):
        for name, decision, action in (
            ("normal_green_clear", "REVIEW", "QUEUE_HUMAN_REVIEW"),
            ("normal_defocus", "REQUEST_VIEW", "REQUEST_NEW_CAPTURE"),
        ):
            with self.subTest(scenario=name):
                _, _, payload = self.call(
                    "POST", "/v1/inspect", inspect_body(name, name)
                )
                result = json.loads(payload)
                self.assertEqual(result["decision"], decision)
                self.assertEqual(result["follow_up"]["planned_action"], action)

    def test_capture_id_reuse_with_substituted_images_stops(self):
        self.call("POST", "/v1/inspect", inspect_body("normal_green_clear", "dup"))
        _, _, payload = self.call(
            "POST", "/v1/inspect", inspect_body("alarm_red_both_views", "dup")
        )
        result = json.loads(payload)
        self.assertEqual(result["decision"], "STOP")
        self.assertEqual(result["reason"], "CAPTURE_ID_REPLAY_MISMATCH")

    def test_malformed_requests_fail_closed_with_hold(self):
        cases = (
            (b"not json", 400, "INVALID_JSON"),
            (b"{}", 400, "VIEWS_OBJECT_REQUIRED"),
            (
                json.dumps({"views": {"front": {"image_base64": "@@@"}}}).encode(),
                400,
                "IMAGE_BASE64_INVALID",
            ),
            (
                json.dumps(
                    {
                        "views": {
                            "front": {"image_base64": base64.b64encode(b"x").decode()}
                        }
                    }
                ).encode(),
                422,
                "IMAGE_DECODE_FAILED",
            ),
            (
                json.dumps({"captured_at": "yesterday", "views": {}}).encode(),
                400,
                "CAPTURED_AT_INVALID",
            ),
        )
        for body, status_code, code in cases:
            with self.subTest(code=code):
                status, _, payload = self.call("POST", "/v1/inspect", body)
                result = json.loads(payload)
                self.assertEqual(status, status_code)
                self.assertEqual(result["error"], code)
                self.assertEqual(result["decision"], "STOP")
                self.assertEqual(
                    result["follow_up"]["planned_action"], "HOLD_AUTOMATION"
                )

    def test_oversized_and_wrong_method_and_unknown_route(self):
        status, _, payload = self.service.handle(
            "POST", "/v1/inspect", b"", body_too_large=True
        )
        self.assertEqual(
            (status, json.loads(payload)["error"]), (413, "BODY_TOO_LARGE")
        )
        self.assertEqual(self.call("GET", "/v1/inspect")[0], 405)
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("GET", "/v1/samples/../../etc")[0], 404)

    def test_missing_view_requests_new_capture(self):
        body = json.loads(inspect_body("normal_green_clear", "one"))
        del body["views"]["side"]
        _, _, payload = self.call("POST", "/v1/inspect", json.dumps(body).encode())
        result = json.loads(payload)
        self.assertEqual(result["decision"], "REQUEST_VIEW")
        self.assertEqual(result["reason"], "INCOMPLETE_COVERAGE")

    def test_non_native_resolution_is_resized_and_recorded(self):
        rendered = render_scene(
            SCENARIOS_BY_NAME["normal_green_clear"], split="dev", index=0
        )
        views = {
            view: {
                "image_base64": png_b64(cv2.resize(pixels, (1280, 960))),
                "source_id": f"camera-{view}-v1",
                "capture_id": f"hires-{view}",
            }
            for view, pixels in rendered.views.items()
        }
        _, _, payload = self.call(
            "POST", "/v1/inspect", json.dumps({"views": views}).encode()
        )
        result = json.loads(payload)
        self.assertEqual(result["views"]["front"]["original_shape"], [960, 1280])
        self.assertTrue(result["views"]["front"]["resized"])

    def test_health_samples_and_index(self):
        status, _, payload = self.call("GET", "/healthz")
        health = json.loads(payload)
        self.assertEqual(status, 200)
        self.assertTrue(health["runtime_matches_contract"])
        self.assertEqual(health["runtime"]["pipeline_version"], "opencv5-scene-v1")
        samples = json.loads(self.call("GET", "/v1/samples")[2])["samples"]
        self.assertIn("normal_round_red_sticker", samples)
        sample = json.loads(self.call("GET", f"/v1/samples/{samples[0]}")[2])
        self.assertEqual(sample["input_mode"], "SYNTHETIC_SCENE")
        status, headers, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"never executed", page)


class HttpServerRoundTrip(unittest.TestCase):
    def test_real_socket_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            service = service_app.Service(Path(tmp) / "ledger.sqlite3")
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), service_app.make_handler(service)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                request = urllib.request.Request(
                    base + "/v1/inspect",
                    data=inspect_body("alarm_red_both_views", "sock"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    result = json.loads(response.read())
                self.assertEqual(result["decision"], "STOP")
                # Declared oversize is refused before the body is read.
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1], timeout=30
                )
                connection.putrequest("POST", "/v1/inspect")
                connection.putheader(
                    "Content-Length", str(service_app.MAX_BODY_BYTES + 1)
                )
                connection.endheaders()
                oversized = connection.getresponse()
                self.assertEqual(oversized.status, 413)
                self.assertEqual(json.loads(oversized.read())["decision"], "STOP")
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                service.close()


class LambdaAdapter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        lambda_handler._SERVICE = service_app.Service(
            Path(self._tmp.name) / "ledger.sqlite3"
        )
        self._quiet = redirect_stdout(StringIO())
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        lambda_handler._SERVICE.close()
        lambda_handler._SERVICE = None
        self._tmp.cleanup()

    def event(self, method, path, body=b"", *, b64=False):
        return {
            "version": "2.0",
            "rawPath": path,
            "requestContext": {"http": {"method": method}},
            "body": base64.b64encode(body).decode() if b64 else body.decode(),
            "isBase64Encoded": b64,
        }

    def test_function_url_events_reach_the_same_core(self):
        response = lambda_handler.handler(
            self.event(
                "POST",
                "/v1/inspect",
                inspect_body("alarm_red_both_views", "l"),
                b64=True,
            )
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["decision"], "STOP")
        health = lambda_handler.handler(self.event("GET", "/healthz"))
        self.assertEqual(health["statusCode"], 200)

    def test_bad_base64_body_fails_closed(self):
        event = self.event("POST", "/v1/inspect")
        event.update(body="%%%", isBase64Encoded=True)
        response = lambda_handler.handler(event)
        result = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(result["decision"], "STOP")


if __name__ == "__main__":
    unittest.main()
