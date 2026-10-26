"""Lambda deploy kit: preview makes no calls; execute is gated and evidenced.

A fake runner stands in for the AWS CLI and Docker. Its ``lambda invoke``
routes the event through the real ``service.lambda_handler`` in-process, so
the recorded decisions come from the actual pipeline, not from canned data.
No AWS call is made by these tests.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from ops import aws_lambda_deploy as deploy
from service import app as service_app
from service import lambda_handler

ACCOUNT = "123456789012"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/visualguard-lambda-runtime"


def completed(command, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, code, stdout, stderr)


class FakeAws:
    def __init__(self, existing_url_auth=None):
        self.commands: list[list[str]] = []
        self.existing_url_auth = existing_url_auth

    def __call__(self, command, **kwargs):
        command = list(command)
        self.commands.append(command)
        head = tuple(command[:3])
        if command[:2] == ["aws", "--version"]:
            return completed(command, stdout="aws-cli/2 fake")
        if head == ("aws", "sts", "get-caller-identity"):
            return completed(command, stdout=json.dumps({"Account": ACCOUNT}))
        if head == ("aws", "iam", "get-role"):
            return completed(command, stdout=json.dumps({"Role": {"Arn": ROLE}}))
        if head in {
            ("aws", "ecr", "describe-repositories"),
            ("aws", "lambda", "get-function"),
        }:
            return completed(command, 254, stderr="ResourceNotFoundException")
        if head == ("aws", "lambda", "get-function-url-config"):
            if self.existing_url_auth is None:
                return completed(command, 254, stderr="ResourceNotFoundException")
            return completed(
                command,
                stdout=json.dumps(
                    {
                        "AuthType": self.existing_url_auth,
                        "FunctionUrl": "https://example.lambda-url",
                    }
                ),
            )
        if head == ("aws", "ecr", "get-login-password"):
            return completed(command, stdout="not-a-real-password")
        if head == ("aws", "ecr", "describe-images"):
            return completed(
                command,
                stdout=json.dumps(
                    {"imageDetails": [{"imageDigest": "sha256:" + "d" * 64}]}
                ),
            )
        if head == ("aws", "lambda", "put-function-concurrency"):
            return completed(command, 254, stderr="below its minimum value of [10]")
        if head == ("aws", "lambda", "create-function-url-config"):
            return completed(
                command,
                stdout=json.dumps(
                    {"AuthType": "AWS_IAM", "FunctionUrl": "https://example.lambda-url"}
                ),
            )
        if head == ("aws", "lambda", "update-function-url-config"):
            auth_type = command[command.index("--auth-type") + 1]
            return completed(
                command,
                stdout=json.dumps(
                    {
                        "AuthType": auth_type,
                        "FunctionUrl": "https://example.lambda-url",
                    }
                ),
            )
        if head == ("aws", "lambda", "invoke"):
            payload = next(a for a in command if a.startswith("file://"))[7:]
            out = command[command.index(f"file://{payload}") + 1]
            event = json.loads(Path(payload).read_text())
            Path(out).write_text(json.dumps(lambda_handler.handler(event)))
            return completed(command, stdout=json.dumps({"StatusCode": 200}))
        if head == ("aws", "logs", "filter-log-events"):
            events = [
                {"message": f"REPORT RequestId: {i} Duration: 90 ms\n"}
                for i in range(3)
            ]
            return completed(command, stdout=json.dumps({"events": events}))
        return completed(command, stdout="{}")

    def calls(self, *prefix):
        return [c for c in self.commands if tuple(c[: len(prefix)]) == prefix]


class DeployKit(unittest.TestCase):
    def setUp(self):
        self.commit, self.digest = deploy.source_archive_sha256()
        self.env = {
            "VISUALGUARD_AWS_OWNER_AUTHORIZED": "true",
            "AWS_REGION": "us-east-1",
            "VISUALGUARD_AWS_APPROVED_REGION": "us-east-1",
            "VISUALGUARD_AWS_ACCOUNT_ID": ACCOUNT,
            "VISUALGUARD_AWS_RUNTIME_ROLE_ARN": ROLE,
            "VISUALGUARD_AWS_DEPLOY_TARGET": "lambda-container",
            "VISUALGUARD_AWS_COST_SCOPE": "free-tier",
            "VISUALGUARD_ARTIFACT_SHA256": self.digest,
        }
        self._tmp = tempfile.TemporaryDirectory()
        lambda_handler._SERVICE = service_app.Service(
            Path(self._tmp.name) / "l.sqlite3"
        )
        self._quiet = redirect_stdout(StringIO())
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        lambda_handler._SERVICE.close()
        lambda_handler._SERVICE = None
        self._tmp.cleanup()

    def run_execute(self, env=None, *, existing_url_auth=None, **kwargs):
        fake = FakeAws(existing_url_auth=existing_url_auth)
        kwargs.setdefault("confirm", deploy.CONFIRM_PRIVATE)
        kwargs.setdefault("public_url", False)
        kwargs.setdefault("confirm_public", "")
        result = deploy.execute(
            env or self.env, runner=fake, preflight_runner=fake, **kwargs
        )
        return result, fake

    def test_preview_makes_no_calls_and_defaults_private(self):
        plan = deploy.plan(self.env, public_url=False)
        self.assertFalse(plan["aws_calls_made"])
        self.assertFalse(plan["public_release"])
        self.assertTrue(any("--auth-type AWS_IAM" in c for c in plan["commands"]))
        self.assertFalse(any("add-permission" in c for c in plan["commands"]))

    def test_execute_refusals_happen_before_any_deploy_command(self):
        cases = {
            "CONFIRMATION_PHRASE_MISSING": ({}, {"confirm": "yes"}),
            "PUBLIC_URL_NOT_APPROVED": ({}, {"public_url": True}),
            "DEPLOY_TARGET_NOT_LAMBDA_CONTAINER": (
                {"VISUALGUARD_AWS_DEPLOY_TARGET": "apprunner"},
                {},
            ),
            "PREFLIGHT_NOT_READY": ({"VISUALGUARD_AWS_OWNER_AUTHORIZED": "false"}, {}),
            "ARTIFACT_SHA256_DOES_NOT_MATCH_GIT_ARCHIVE_HEAD": (
                {"VISUALGUARD_ARTIFACT_SHA256": "0" * 64},
                {},
            ),
        }
        for reason, (env_patch, kwargs) in cases.items():
            with self.subTest(reason=reason):
                fake = FakeAws()
                with self.assertRaises(deploy.DeployError) as caught:
                    deploy.execute(
                        {**self.env, **env_patch},
                        confirm=kwargs.get("confirm", deploy.CONFIRM_PRIVATE),
                        public_url=kwargs.get("public_url", False),
                        confirm_public="",
                        runner=fake,
                        preflight_runner=fake,
                    )
                self.assertEqual(str(caught.exception), reason)
                self.assertEqual(fake.calls("aws", "ecr"), [])
                self.assertEqual(fake.calls("aws", "lambda"), [])
                self.assertEqual(fake.calls("docker"), [])

    def test_private_deploy_binds_digest_masks_account_and_records_invocations(self):
        result, fake = self.run_execute()
        self.assertEqual(result["status"], "DEPLOYED_AND_INVOKED")
        self.assertNotIn(ACCOUNT, json.dumps(result))
        self.assertIn("@sha256:" + "d" * 64, result["image_uri"])
        self.assertEqual(result["source_archive_sha256"], self.digest)
        self.assertEqual(result["live_state"]["endpoint"], "DEPLOYED_PRIVATE_AWS_IAM")
        steps = {step["step"]: step for step in result["steps"]}
        invocations = steps["lambda_invocations"]["results"]
        self.assertEqual(set(invocations), {"healthz"})
        self.assertEqual(
            steps["reserved_concurrency"]["status"], "UNAVAILABLE_FOR_ACCOUNT"
        )
        self.assertGreaterEqual(steps["cloudwatch_report_lines"]["count"], 2)
        self.assertEqual(fake.calls("aws", "lambda", "add-permission"), [])
        build = fake.calls("docker", "build")[0]
        self.assertNotEqual(build[-1], str(deploy.ROOT))
        create = fake.calls("aws", "lambda", "create-function")[0]
        self.assertIn(
            f"ImageUri={result['image_uri'].replace('********' + ACCOUNT[-4:], ACCOUNT)}",
            create,
        )

    def test_public_url_requires_second_phrase_and_adds_permissions(self):
        result, fake = self.run_execute(
            public_url=True,
            confirm_public=deploy.CONFIRM_PUBLIC,
            existing_url_auth="AWS_IAM",
        )
        self.assertEqual(len(fake.calls("aws", "lambda", "add-permission")), 2)
        update = fake.calls("aws", "lambda", "update-function-url-config")[0]
        self.assertEqual(update[update.index("--auth-type") + 1], "NONE")
        self.assertEqual(
            {step["step"]: step for step in result["steps"]}["function_url"]["auth_type"],
            "NONE",
        )
        invoke_permission = fake.calls("aws", "lambda", "add-permission")[1]
        self.assertIn("--invoked-via-function-url", invoke_permission)

    def test_public_url_keeps_existing_none_auth_without_reconfiguration(self):
        _, fake = self.run_execute(
            public_url=True,
            confirm_public=deploy.CONFIRM_PUBLIC,
            existing_url_auth="NONE",
        )
        self.assertEqual(fake.calls("aws", "lambda", "update-function-url-config"), [])


if __name__ == "__main__":
    unittest.main()
