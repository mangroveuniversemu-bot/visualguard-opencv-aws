from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.verify_deployment_state import DeploymentStateError, verify_deployment_state

ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path: Path) -> Path:
    state = json.loads((ROOT / "deployment.json").read_text(encoding="utf-8"))
    state_path = tmp_path / "deployment.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    evidence = tmp_path / state["current_public_deployment"]["readback_evidence"]
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}", encoding="utf-8")
    return state_path


def _mutate(path: Path, callback) -> None:
    state = json.loads(path.read_text(encoding="utf-8"))
    callback(state)
    path.write_text(json.dumps(state), encoding="utf-8")


def test_checked_in_deployment_state_passes() -> None:
    result = verify_deployment_state()
    assert result["status"] == "PASS"
    assert result["auth_type"] == "NONE"
    assert result["deployment_check_inference_requests"] == 0
    assert result["camera_accuracy"] == "NOT_VERIFIED"
    assert result["physical_action"] == "NONE"


def test_rejects_stale_private_endpoint(tmp_path: Path) -> None:
    state_path = _fixture(tmp_path)
    _mutate(
        state_path,
        lambda value: value["live_state"].__setitem__(
            "endpoint", "DEPLOYED_PRIVATE_AWS_IAM"
        ),
    )
    with pytest.raises(DeploymentStateError, match="LIVE_ENDPOINT_DRIFT"):
        verify_deployment_state(state_path, tmp_path)


def test_rejects_auth_drift(tmp_path: Path) -> None:
    state_path = _fixture(tmp_path)
    _mutate(
        state_path,
        lambda value: value["endpoint"].__setitem__("auth_type", "AWS_IAM"),
    )
    with pytest.raises(DeploymentStateError, match="ENDPOINT_STATE_DRIFT"):
        verify_deployment_state(state_path, tmp_path)


def test_rejects_deployment_check_quota_overclaim(tmp_path: Path) -> None:
    state_path = _fixture(tmp_path)
    _mutate(
        state_path,
        lambda value: value["current_public_deployment"].__setitem__(
            "deployment_check_inference_requests", 1
        ),
    )
    with pytest.raises(DeploymentStateError, match="DEPLOYMENT_CHECK_QUOTA_OVERCLAIM"):
        verify_deployment_state(state_path, tmp_path)


def test_rejects_camera_accuracy_overclaim(tmp_path: Path) -> None:
    state_path = _fixture(tmp_path)
    _mutate(
        state_path,
        lambda value: value["current_public_deployment"].__setitem__(
            "camera_accuracy", "VERIFIED"
        ),
    )
    with pytest.raises(DeploymentStateError, match="CAMERA_ACCURACY_OVERCLAIM"):
        verify_deployment_state(state_path, tmp_path)
