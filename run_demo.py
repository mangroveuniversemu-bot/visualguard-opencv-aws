"""Run the three offline demonstrations and write reproducibility evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

from coding.patch_review import BASELINE, CORRECT, REGRESSION, SUITE_DIGEST, digest, review_patch
from coding.sandbox_adapter import contract_summary
from coding.workspace_contract import (
    RecoveryExpectation,
    build_manifest,
    contract_summary as workspace_contract_summary,
    recovery_receipt,
    reviewed_workspace,
)
from vision.inspection import frame, inspect, verify_effect
from vision.opencv5_inspection import (
    CaptureReplayLedger,
    View as OpenCVView,
    frame as opencv_frame,
    inspect as opencv_inspect,
    runtime_evidence as opencv_runtime_evidence,
    verify_consequence,
)
from payments.paypal_sandbox import (
    PROVIDER as PAYPAL_PROVIDER,
    ReconciliationEvidence,
    contract_summary as paypal_contract_summary,
)
from payments.review import FixtureIdentityVerifier, Principal, SQLiteReview, fingerprint


def main():
    root = Path(__file__).resolve().parent
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    test_command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    tests_started = time.monotonic()
    tests = subprocess.run(test_command, cwd=root, capture_output=True, text=True)
    tests_wall_seconds = time.monotonic() - tests_started
    test_output = tests.stdout + tests.stderr
    passed_tests = sum(line.endswith(" ... ok") for line in test_output.splitlines())
    (evidence / "tests.log").write_text(test_output)
    repair = review_patch({"ledger.py": CORRECT}, expected_base=digest(BASELINE), expected_suite=SUITE_DIGEST)
    bad = review_patch({"ledger.py": REGRESSION}, expected_base=digest(BASELINE), expected_suite=SUITE_DIGEST)
    workspace_manifest = build_manifest(reviewed_workspace())
    recovery_expectation = RecoveryExpectation(
        manifest_sha256=workspace_manifest["manifest_sha256"],
        source_sha256=digest(BASELINE), suite_sha256=SUITE_DIGEST,
        policy_sha256=workspace_manifest["policy_sha256"],
    )
    fixture_provider_result = {
        "fixture": True, "status": "EXECUTED_IN_OPENSHELL", "deleted": True,
        "manifest_sha256": recovery_expectation.manifest_sha256,
        "source_sha256": recovery_expectation.source_sha256,
        "suite_sha256": recovery_expectation.suite_sha256,
        "policy_sha256": recovery_expectation.policy_sha256,
    }
    recovery = recovery_receipt(
        fixture_provider_result, recovery_expectation,
        current_source_sha256=digest(BASELINE), candidate_applied=False,
    )
    vision = {
        "clear": inspect({"front": frame(False), "side": frame(False)}, captured_at=100, now=101),
        "occluded": inspect({"front": frame(False)}, captured_at=100, now=101),
        "side_alarm": inspect({"front": frame(False), "side": frame(True)}, captured_at=100, now=101),
        "post_action_mismatch": verify_effect(False, frame(True)),
    }
    opencv_replay_ledger = CaptureReplayLedger(":memory:")
    opencv5_vision = {
        "clear": opencv_inspect(
            {"front": OpenCVView(opencv_frame(False), source_id="camera-front-v1",
                                 capture_id="demo-clear-front", captured_at=100.0),
             "side": OpenCVView(opencv_frame(False), source_id="camera-side-v1",
                                capture_id="demo-clear-side", captured_at=100.0)},
            captured_at=100, now=101, replay_ledger=opencv_replay_ledger,
        ),
        "occluded": opencv_inspect(
            {"front": OpenCVView(opencv_frame(False), visible_fraction=0.5,
                                 source_id="camera-front-v1",
                                 capture_id="demo-occluded-front", captured_at=100.0),
             "side": OpenCVView(opencv_frame(False), source_id="camera-side-v1",
                                capture_id="demo-occluded-side", captured_at=100.0)},
            captured_at=100, now=101, replay_ledger=opencv_replay_ledger,
        ),
        "side_alarm": opencv_inspect(
            {"front": OpenCVView(opencv_frame(False), source_id="camera-front-v1",
                                 capture_id="demo-alarm-front", captured_at=100.0),
             "side": OpenCVView(opencv_frame(True), source_id="camera-side-v1",
                                capture_id="demo-alarm-side", captured_at=100.0)},
            captured_at=100, now=101, replay_ledger=opencv_replay_ledger,
        ),
        "post_action_mismatch": verify_consequence(
            False, OpenCVView(opencv_frame(True))
        ),
        "runtime": opencv_runtime_evidence(),
        "input": "FIXED_SYNTHETIC_ARRAYS",
        "physical_action": "NONE",
    }
    opencv_replay_ledger.close()
    order = {"id": "INV-42", "payee": "synthetic_supplier", "amount_cents": 4200, "currency": "USD"}
    identities = FixtureIdentityVerifier({
        "proposer-session": Principal("member-alice", "PROPOSER"),
        "approver-session": Principal("member-bob", "APPROVER"),
    })
    with tempfile.TemporaryDirectory(prefix="payment-fixture-") as directory:
        database = Path(directory) / "payments.sqlite3"
        payment = SQLiteReview(database, identities, nonce_factory=lambda: "demo-nonce")
        approval = payment.approve(
            order, proposer_session="proposer-session",
            approver_session="approver-session", expires=200,
        )
        first = payment.execute(
            order, approval=approval, operation="op1", now=100,
            simulate_timeout=True,
        )
        restarted = SQLiteReview(
            database, identities, nonce_factory=lambda: "restart-nonce"
        )
        retry = restarted.execute(order, approval=approval, operation="op1", now=101)
        fixture_evidence = ReconciliationEvidence(
            operation="op1", order_id=order["id"], fingerprint=fingerprint(order),
            status="CAPTURED", source="ORDER_QUERY", provider=PAYPAL_PROVIDER,
            environment="FIXTURE", verified=True,
            request_sha256="a" * 64, response_sha256="b" * 64,
        )
        resolved = restarted.reconcile("op1", evidence=fixture_evidence)
        payment_calls = restarted.mock_calls
    sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(root.rglob("*.py"))}
    result = {"run_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
              "platform": platform.platform(), "seed": None, "randomness": "NONE; fixed synthetic fixtures",
              "source_sha256": sources, "suite_sha256": SUITE_DIGEST,
              "tests_returncode": tests.returncode,
              "tests": {"command": "python -m unittest discover -s tests -v",
                        "passed": passed_tests, "status": "PASS" if tests.returncode == 0 else "FAIL",
                        "wall_seconds": round(tests_wall_seconds, 6),
                        "stdout_stderr_sha256": hashlib.sha256(test_output.encode()).hexdigest()},
              "coding": {"good_patch": repair, "bad_patch": bad}, "vision": vision,
              "opencv5_vision": opencv5_vision,
              "sandbox_adapter": contract_summary(),
              "workspace_contract": workspace_contract_summary(),
              "recovery_fixture": recovery,
              "paypal_sandbox_contract": paypal_contract_summary(),
              "dependency_status": {
                  "cv2": "AVAILABLE" if importlib.util.find_spec("cv2") else "NOT_INSTALLED",
                  "OpenCV5": opencv_runtime_evidence(),
              },
              "payments": {"first": first, "retry": retry, "reconciled": resolved,
                           "mock_calls": payment_calls, "storage": "SQLITE_FILE_BACKED",
                           "identity": "SERVER_VERIFIED_FIXTURE_SESSIONS",
                           "restart_replay_equal": first == retry,
                           "reconciliation_evidence": fixture_evidence.as_dict(),
                           "real_money_moved": "NOT_RUN"},
              "live": {"Nebius": "NOT_RUN", "NVIDIA_model": "NOT_RUN",
                       "OpenShell": "NOT_RUN", "Tavily": "NOT_RUN",
                       "OpenCV5": "LOCAL_SYNTHETIC_RUN",
                       "AWS": "NOT_RUN", "PayPal": "NOT_RUN"},
              "limitations": ["Closed reviewed fixtures only; no model generated code executed.",
                              "OpenShell adapter, workspace manifest and recovery receipt were tested with fixtures only; live gateway, policy enforcement, staging and audit export remain NOT_RUN.",
                              "No hostile-code sandbox claim; subprocess timeout is not isolation.",
                              "OpenCV 5.0.0 runs locally on fixed synthetic arrays; no camera, AWS deployment, device control or physical validation was run.",
                              "Payment state is file-backed SQLite and fixture sessions pass through a server-side verifier. The PayPal Sandbox adapter, postback webhook verifier and UNKNOWN reconciliation contract use fixture transports only; Sandbox network calls, production authentication and real money remain NOT_RUN.",
                              "Fixed tests are not held-out evaluation, real error rates, customer savings or certification."]}
    (evidence / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"tests_returncode": tests.returncode, "coding_before": repair["before"]["passed"],
                      "coding_after": repair["after"]["passed"], "coding_total": repair["after"]["total"],
                      "bad_patch": bad["verdict"], "vision": {k:v.get("decision",v.get("closure")) for k,v in vision.items()},
                      "opencv5_vision": {k:v.get("decision",v.get("closure")) for k,v in opencv5_vision.items() if isinstance(v, dict) and k != "runtime"},
                      "opencv5_version": opencv5_vision["runtime"]["opencv_version"],
                      "workspace_manifest": workspace_manifest["manifest_sha256"],
                      "recovery_fixture": recovery["status"],
                      "payment_calls": payment_calls,
                      "payment_restart_replay": first == retry,
                      "paypal_contract": "FIXTURE_ONLY",
                      "tests_passed": passed_tests,
                      "live": "NOT_RUN"}))
    return tests.returncode


if __name__ == "__main__":
    raise SystemExit(main())
