"""AWS Lambda adapter (Function URL / API Gateway HTTP API payload v2.0).

It forwards to the same ``Service.handle`` core as the HTTP server. The
replay ledger lives in the instance's ``/tmp``, so replay protection is per
execution environment, not global across concurrent Lambda instances.
"""

from __future__ import annotations

import base64
import binascii

from service.app import Service

_SERVICE: Service | None = None


def _service() -> Service:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = Service.from_env()
    return _SERVICE


def handler(event: dict, context: object = None) -> dict[str, object]:
    http = (event.get("requestContext") or {}).get("http") or {}
    method = http.get("method") or event.get("httpMethod") or "GET"
    path = event.get("rawPath") or event.get("path") or "/"
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(raw_body, validate=True)
        except (binascii.Error, ValueError):
            # An undecodable body reaches the core as empty and fails closed
            # there (INVALID_JSON -> STOP / HOLD_AUTOMATION for /v1/inspect).
            body = b""
    else:
        body = raw_body.encode()
    status, headers, payload = _service().handle(method, path, body)
    # Bind browser-visible results to the actual Lambda invocation, separately
    # from the application request ID used by the shared HTTP service.
    aws_request_id = getattr(context, "aws_request_id", None)
    if aws_request_id:
        headers["X-Aws-Request-Id"] = str(aws_request_id)
    return {
        "statusCode": status,
        "headers": headers,
        "body": payload.decode(),
        "isBase64Encoded": False,
    }
