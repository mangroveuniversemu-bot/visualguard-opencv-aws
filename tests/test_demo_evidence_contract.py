"""Fail-closed acceptance tests for the VisualGuard demo evidence contract."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest

from ops.verify_demo_evidence_contract import (
    AWS_CLAIM,
    ContractError,
    _validate_aws_execution,
    verify_contract,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json"
AWS_EVIDENCE = ROOT / "evidence" / "AWS_EXECUTION_20261026_40223113044.json"


def _verify_mutation(mutate):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutate(manifest)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return verify_contract(path, ROOT)


def _mutated_aws(mutate):
    evidence = json.loads(AWS_EVIDENCE.read_text(encoding="utf-8"))
    mutate(evidence)
    return _validate_aws_execution(evidence)


def test_prepared_contract_passes_with_bounded_disclosures():
    result = verify_contract(MANIFEST, ROOT)
    assert result["status"] == "PASS"
    assert result["duration_seconds"] == 180
    assert result["segment_count"] == 6
    assert result["artifact_count"] == 2
    assert result["aws"] == AWS_CLAIM
    assert result["public_endpoint"] == "NOT_AUTHORIZED"
    assert result["camera"] == "NOT_RUN"
    assert result["action_executed"] is False


def test_missing_required_segment_fails_closed():
    with pytest.raises(ContractError, match="segment coverage mismatch"):
        _verify_mutation(lambda value: value["segments"].pop())


def test_duration_overrun_fails_closed():
    with pytest.raises(ContractError, match="exceeds"):
        _verify_mutation(lambda value: value["segments"][0].update(duration_seconds=21))


def test_recorded_video_claim_fails_closed():
    with pytest.raises(ContractError, match="must not claim a recorded demo"):
        _verify_mutation(lambda value: value.update(status="RECORDED"))


def test_public_aws_claim_fails_closed():
    with pytest.raises(ContractError, match="bounded private AWS claim"):
        _verify_mutation(lambda value: value.update(aws_claim="PUBLIC_AWS_ENDPOINT"))


def test_artifact_digest_drift_fails_closed():
    with pytest.raises(ContractError, match="artifact digest drift"):
        _verify_mutation(
            lambda value: value["segments"][1]["artifacts"][0].update(sha256="0" * 64)
        )


def test_artifact_path_escape_fails_closed():
    with pytest.raises(ContractError, match="escapes repository root"):
        _verify_mutation(
            lambda value: value["segments"][1]["artifacts"][0].update(
                path="../outside.json"
            )
        )


def test_public_function_url_fails_closed():
    with pytest.raises(ContractError, match="public endpoint claim"):
        _mutated_aws(lambda value: value["deployment"].update(public_url=True))


def test_reserved_concurrency_overclaim_fails_closed():
    def mutate(value):
        step = next(
            item
            for item in value["deployment"]["steps"]
            if item["step"] == "reserved_concurrency"
        )
        step["status"] = "CONFIGURED"

    with pytest.raises(ContractError, match="reserved concurrency"):
        _mutated_aws(mutate)


def test_missing_cloudwatch_report_fails_closed():
    def mutate(value):
        step = next(
            item
            for item in value["deployment"]["steps"]
            if item["step"] == "cloudwatch_report_lines"
        )
        step["lines"].pop()

    with pytest.raises(ContractError, match="three CloudWatch"):
        _mutated_aws(mutate)


def test_missing_view_action_execution_fails_closed():
    with pytest.raises(ContractError, match="missing-view negative control"):
        _mutated_aws(
            lambda value: value["supplemental_negative_control"]["parsed_body"][
                "follow_up"
            ].update(action_executed=True)
        )
