"""Fail-closed consistency checks for the current VisualGuard deployment state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path("deployment.json")
PUBLIC_STATUS = "PUBLIC_AWS_JUDGE_UI_DEPLOYED"
PUBLIC_ENDPOINT = "PUBLIC_AWS_FUNCTION_URL"


class DeploymentStateError(ValueError):
    """The current deployment state is missing or internally contradictory."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentStateError("STATE_JSON_READ_FAILED") from exc
    if not isinstance(value, dict):
        raise DeploymentStateError("STATE_OBJECT_REQUIRED")
    return value


def verify_deployment_state(
    state_path: Path = STATE_PATH, root: Path = ROOT
) -> dict[str, Any]:
    path = root / state_path if not state_path.is_absolute() else state_path
    state = _load(path)
    current = state.get("current_public_deployment", {})
    endpoint = state.get("endpoint", {})
    deploy_kit = state.get("aws_deploy_kit", {})
    preflight = state.get("aws_preflight", {})
    live = state.get("live_state", {})
    video = state.get("final_video_evidence_gate", {})

    if current.get("status") != PUBLIC_STATUS:
        raise DeploymentStateError("CURRENT_STATUS_DRIFT")
    public_url = current.get("public_url")
    if not isinstance(public_url, str) or not public_url.startswith("https://"):
        raise DeploymentStateError("PUBLIC_URL_INVALID")
    if current.get("auth_type") != "NONE":
        raise DeploymentStateError("CURRENT_AUTH_DRIFT")
    if current.get("deployment_check_inference_requests") != 0:
        raise DeploymentStateError("DEPLOYMENT_CHECK_QUOTA_OVERCLAIM")

    if (
        endpoint.get("status") != PUBLIC_STATUS
        or endpoint.get("aws_endpoint") != PUBLIC_ENDPOINT
        or endpoint.get("public_url") != public_url
        or endpoint.get("auth_type") != "NONE"
    ):
        raise DeploymentStateError("ENDPOINT_STATE_DRIFT")
    if (
        deploy_kit.get("status") != "PUBLIC_DEPLOYED_AND_READBACK_VERIFIED"
        or deploy_kit.get("current_function_url_auth") != "NONE"
        or deploy_kit.get("public_url_authorization") != "COMPLETED_BY_OWNER"
    ):
        raise DeploymentStateError("DEPLOY_KIT_STATE_DRIFT")
    if preflight.get("endpoint") != PUBLIC_ENDPOINT:
        raise DeploymentStateError("PREFLIGHT_ENDPOINT_DRIFT")
    if live.get("endpoint") != PUBLIC_ENDPOINT:
        raise DeploymentStateError("LIVE_ENDPOINT_DRIFT")
    if video.get("public_endpoint_claim") != PUBLIC_ENDPOINT:
        raise DeploymentStateError("VIDEO_ENDPOINT_DRIFT")
    if current.get("camera_accuracy") != "NOT_VERIFIED":
        raise DeploymentStateError("CAMERA_ACCURACY_OVERCLAIM")

    evidence = current.get("readback_evidence")
    if not isinstance(evidence, str) or not (root / evidence).is_file():
        raise DeploymentStateError("READBACK_EVIDENCE_MISSING")

    return {
        "status": "PASS",
        "cut": state.get("current_cut"),
        "public_url": public_url,
        "auth_type": "NONE",
        "deployment_check_inference_requests": 0,
        "camera_accuracy": "NOT_VERIFIED",
        "physical_action": current.get("physical_action"),
    }


if __name__ == "__main__":
    print(json.dumps(verify_deployment_state(), sort_keys=True))
