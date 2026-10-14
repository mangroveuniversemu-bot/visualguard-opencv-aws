"""Fail-closed coverage for the read-only AWS deployment preflight."""

from __future__ import annotations

import json
import subprocess
import unittest

from ops.aws_deployment_preflight import evaluate_preflight


DEPLOYMENT = {
    "stage": "SOURCE_IMPORTED_AND_LOCALLY_VERIFIED",
    "source_imported": True,
}
READY_ENV = {
    "VISUALGUARD_AWS_OWNER_AUTHORIZED": "true",
    "AWS_REGION": "us-west-2",
    "VISUALGUARD_AWS_APPROVED_REGION": "us-west-2",
    "VISUALGUARD_AWS_ACCOUNT_ID": "123456789012",
    "VISUALGUARD_AWS_RUNTIME_ROLE_ARN": (
        "arn:aws:iam::123456789012:role/visualguard-runtime"
    ),
    "VISUALGUARD_AWS_DEPLOY_TARGET": "lambda-container",
    "VISUALGUARD_AWS_COST_SCOPE": "zero-new-cost",
    "VISUALGUARD_ARTIFACT_SHA256": "a" * 64,
}


class AwsDeploymentPreflightCases(unittest.TestCase):
    def test_missing_authorization_and_scope_blocks_before_aws(self):
        calls = []

        def runner(command):
            calls.append(command)
            raise AssertionError("AWS must not be called before static gates pass")

        result = evaluate_preflight(DEPLOYMENT, {}, runner)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["commands_run"], [])
        self.assertEqual(result["live_state"]["aws_api"], "NOT_RUN")
        self.assertEqual(calls, [])

    def test_region_must_match_owner_approved_region(self):
        environ = dict(READY_ENV, VISUALGUARD_AWS_APPROVED_REGION="us-east-1")
        result = evaluate_preflight(DEPLOYMENT, environ, self._unexpected_runner)
        check = self._check(result, "region_approval")
        self.assertEqual(check["status"], "BLOCK")
        self.assertEqual(result["commands_run"], [])

    def test_role_must_belong_to_expected_account(self):
        environ = dict(
            READY_ENV,
            VISUALGUARD_AWS_RUNTIME_ROLE_ARN=(
                "arn:aws:iam::999999999999:role/visualguard-runtime"
            ),
        )
        result = evaluate_preflight(DEPLOYMENT, environ, self._unexpected_runner)
        self.assertEqual(self._check(result, "runtime_role_scope")["status"], "BLOCK")

    def test_missing_cli_blocks_without_api_calls(self):
        calls = []

        def runner(command):
            calls.append(tuple(command))
            return subprocess.CompletedProcess(command, 127, "", "not found")

        result = evaluate_preflight(DEPLOYMENT, READY_ENV, runner)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(calls, [("aws", "--version")])
        self.assertEqual(result["live_state"]["aws_api"], "NOT_RUN")

    def test_wrong_caller_account_blocks_and_skips_role_readback(self):
        calls = []

        def runner(command):
            calls.append(tuple(command))
            if tuple(command) == ("aws", "--version"):
                return subprocess.CompletedProcess(command, 0, "aws-cli/2", "")
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"Account": "999999999999", "Arn": "arn:aws:iam::x:user/y"}),
                "",
            )

        result = evaluate_preflight(DEPLOYMENT, READY_ENV, runner)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "caller_identity")["status"], "BLOCK")
        self.assertEqual(len(calls), 2)

    def test_ready_path_uses_only_allowlisted_read_commands(self):
        calls = []

        def runner(command):
            command = tuple(command)
            calls.append(command)
            if command == ("aws", "--version"):
                return subprocess.CompletedProcess(command, 0, "aws-cli/2", "")
            if command[1:3] == ("sts", "get-caller-identity"):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps({"Account": "123456789012"}),
                    "",
                )
            if command[1:3] == ("iam", "get-role"):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {"Role": {"Arn": READY_ENV["VISUALGUARD_AWS_RUNTIME_ROLE_ARN"]}}
                    ),
                    "",
                )
            raise AssertionError(command)

        result = evaluate_preflight(DEPLOYMENT, READY_ENV, runner)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["live_state"]["aws_api"], "READ_ONLY_PROBE")
        self.assertEqual(result["live_state"]["deployment"], "NOT_RUN")
        self.assertFalse(result["action_executed"])
        self.assertEqual(
            result["commands_run"],
            ["aws --version", "aws sts get-caller-identity", "aws iam get-role"],
        )
        for command in calls[1:]:
            self.assertIn(
                command[1:3], {("sts", "get-caller-identity"), ("iam", "get-role")}
            )

    @staticmethod
    def _unexpected_runner(command):
        raise AssertionError(f"unexpected AWS command: {command}")

    @staticmethod
    def _check(result, code):
        return next(check for check in result["checks"] if check["code"] == code)


if __name__ == "__main__":
    unittest.main()
