"""Preview or execute the smallest VisualGuard AWS deployment (Lambda container).

``--mode preview`` (default) makes no AWS or Docker call: it prints the exact
plan, resource names, cost controls and the commands ``execute`` would run.

``--mode execute`` refuses to run unless all of the following hold:

* the confirmation phrase is supplied exactly;
* the fail-closed read-only preflight (``ops/aws_deployment_preflight.py``)
  returns READY in this process, including ``sts get-caller-identity`` and
  ``iam get-role`` against the configured account and runtime role;
* the deploy target is ``lambda-container``;
* ``VISUALGUARD_ARTIFACT_SHA256`` equals the SHA-256 of ``git archive HEAD``,
  binding the deployment to the exact committed source.

It then pushes the Lambda image to one immutable ECR repository, creates or
updates one function by image digest, attaches a Function URL (``AWS_IAM``
unless a public URL is separately confirmed), invokes it through the AWS
API, and reads its CloudWatch ``REPORT`` lines as execution evidence. The
account ID is masked in the evidence file.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.aws_deployment_preflight import evaluate_preflight  # noqa: E402

FUNCTION_NAME = "visualguard-inspector"
REPOSITORY = "visualguard"
MEMORY_MB = 1024
TIMEOUT_SECONDS = 30
RESERVED_CONCURRENCY = 2
CONFIRM_PRIVATE = "DEPLOY_LAMBDA_PRIVATE_URL"
CONFIRM_PUBLIC = "PUBLIC_URL_APPROVED_BY_OWNER"
LIFECYCLE_POLICY = {
    "rules": [
        {
            "rulePriority": 1,
            "description": "Keep the three most recent images only (cost control).",
            "selection": {
                "tagStatus": "any",
                "countType": "imageCountMoreThan",
                "countNumber": 3,
            },
            "action": {"type": "expire"},
        }
    ]
}

Runner = Callable[..., subprocess.CompletedProcess]


def _run(command: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=900, **kwargs
    )


def source_archive_sha256(root: Path = ROOT) -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    return commit, hashlib.sha256(archive).hexdigest()


def mask_account(text: str, account_id: str) -> str:
    return (
        text.replace(account_id, "********" + account_id[-4:]) if account_id else text
    )


def plan(environ: Mapping[str, str], *, public_url: bool) -> dict[str, object]:
    region = environ.get("AWS_REGION", "<AWS_REGION>")
    account = environ.get("VISUALGUARD_AWS_ACCOUNT_ID", "<ACCOUNT_ID>")
    role = environ.get("VISUALGUARD_AWS_RUNTIME_ROLE_ARN", "<RUNTIME_ROLE_ARN>")
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    image = f"{registry}/{REPOSITORY}"
    commands = [
        "aws sts get-caller-identity  # via preflight",
        "aws iam get-role --role-name <runtime role>  # via preflight",
        f"aws ecr describe-repositories --repository-names {REPOSITORY}",
        f"aws ecr create-repository --repository-name {REPOSITORY} "
        "--image-tag-mutability IMMUTABLE "
        "--image-scanning-configuration scanOnPush=true  # only if missing",
        f"aws ecr put-lifecycle-policy --repository-name {REPOSITORY} "
        "--lifecycle-policy-text <keep 3 images>",
        f"aws ecr get-login-password | docker login --username AWS "
        f"--password-stdin {registry}",
        f"docker build --target lambda --platform linux/amd64 --provenance=false "
        f"-t {image}:<commit> .",
        f"docker push {image}:<commit>",
        f"aws ecr describe-images --repository-name {REPOSITORY} "
        "--image-ids imageTag=<commit>",
        f"aws lambda create-function --function-name {FUNCTION_NAME} "
        f"--package-type Image --code ImageUri={image}@<digest> --role {role} "
        f"--memory-size {MEMORY_MB} --timeout {TIMEOUT_SECONDS} "
        "--architectures x86_64  # or update-function-code if it exists",
        f"aws lambda put-function-concurrency --function-name {FUNCTION_NAME} "
        f"--reserved-concurrent-executions {RESERVED_CONCURRENCY}  # best effort",
        f"aws lambda create-function-url-config OR update-function-url-config "
        f"--function-name {FUNCTION_NAME} --auth-type "
        f"{'NONE' if public_url else 'AWS_IAM'}",
    ]
    if public_url:
        commands += [
            f"aws lambda add-permission --function-name {FUNCTION_NAME} "
            "--statement-id public-url --action lambda:InvokeFunctionUrl "
            "--principal '*' --function-url-auth-type NONE",
            f"aws lambda add-permission --function-name {FUNCTION_NAME} "
            "--statement-id public-url-invoke --action lambda:InvokeFunction "
            "--principal '*' --invoked-via-function-url",
        ]
    commands += [
        f"aws lambda invoke --function-name {FUNCTION_NAME} "
        "--payload <Function URL event: GET /healthz> "
        "# consumes no inference slot",
        f"aws logs filter-log-events --log-group-name /aws/lambda/{FUNCTION_NAME} "
        "--filter-pattern REPORT",
    ]
    return {
        "mode": "PREVIEW",
        "aws_calls_made": False,
        "target": "lambda-container",
        "region": region,
        "resources": {
            "ecr_repository": REPOSITORY,
            "lambda_function": FUNCTION_NAME,
            "runtime_role": role,
            "daily_quota_table": "visualguard-daily-quota",
            "daily_inference_limit": 5,
            "daily_limit_timezone": "Asia/Taipei",
            "function_url_auth": "NONE (public)" if public_url else "AWS_IAM (private)",
        },
        "cost_controls": [
            f"memory {MEMORY_MB} MB, timeout {TIMEOUT_SECONDS} s",
            f"reserved concurrency {RESERVED_CONCURRENCY} where the account allows it",
            "5 /v1/inspect POST attempts/day enforced by conditional DynamoDB updates",
            "the daily inference limit is not a hard cap on public Lambda request charges",
            "successful DynamoDB writes at the limit: about USD 0.0001 per 30 days in us-east-1",
            "ECR lifecycle keeps 3 images; tags immutable",
            "no provisioned concurrency, no NAT, no load balancer, no always-on compute",
            "owner budget alert is a prerequisite (set in AWS Billing)",
        ],
        "cost_estimate": (
            "At 5 successful 1 KB DynamoDB updates/day in us-east-1, the shared "
            "quota writes are about USD 0.0001 per 30-day month at the current "
            "on-demand rate, before storage and failed conditional requests. This "
            "does not cap Lambda charges from repeated public requests."
        ),
        "public_release": public_url,
        "commands": commands,
    }


class DeployError(RuntimeError):
    pass


def _aws(runner: Runner, region: str, *args: str) -> dict:
    result = runner(
        ["aws", *args, "--region", region, "--output", "json", "--no-cli-pager"]
    )
    if result.returncode != 0:
        raise DeployError(
            f"aws {args[0]} {args[1]} failed: {result.stderr.strip()[:300]}"
        )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def _function_url_event(method: str, path: str, body: bytes = b"") -> dict:
    return {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "body": base64.b64encode(body).decode(),
        "isBase64Encoded": True,
    }


def execute(
    environ: Mapping[str, str],
    *,
    confirm: str,
    public_url: bool,
    confirm_public: str,
    runner: Runner = _run,
    preflight_runner=None,
    source_digest: Callable[[], tuple[str, str]] = source_archive_sha256,
) -> dict[str, object]:
    if confirm != CONFIRM_PRIVATE:
        raise DeployError("CONFIRMATION_PHRASE_MISSING")
    if public_url and confirm_public != CONFIRM_PUBLIC:
        raise DeployError("PUBLIC_URL_NOT_APPROVED")
    if environ.get("VISUALGUARD_AWS_DEPLOY_TARGET") != "lambda-container":
        raise DeployError("DEPLOY_TARGET_NOT_LAMBDA_CONTAINER")
    deployment = json.loads((ROOT / "deployment.json").read_text(encoding="utf-8"))
    preflight = (
        evaluate_preflight(deployment, environ, preflight_runner)
        if preflight_runner is not None
        else evaluate_preflight(deployment, environ)
    )
    if preflight["status"] != "READY":
        raise DeployError("PREFLIGHT_NOT_READY")
    commit, digest = source_digest()
    if digest != environ.get("VISUALGUARD_ARTIFACT_SHA256"):
        raise DeployError("ARTIFACT_SHA256_DOES_NOT_MATCH_GIT_ARCHIVE_HEAD")

    region = environ["AWS_REGION"]
    account = environ["VISUALGUARD_AWS_ACCOUNT_ID"]
    role = environ["VISUALGUARD_AWS_RUNTIME_ROLE_ARN"]
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    image = f"{registry}/{REPOSITORY}"
    steps: list[dict[str, object]] = []

    def step(name: str, **detail):
        steps.append(
            {
                "step": name,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **detail,
            }
        )

    describe = runner(
        [
            "aws",
            "ecr",
            "describe-repositories",
            "--repository-names",
            REPOSITORY,
            "--region",
            region,
            "--output",
            "json",
            "--no-cli-pager",
        ]
    )
    if describe.returncode != 0:
        _aws(
            runner,
            region,
            "ecr",
            "create-repository",
            "--repository-name",
            REPOSITORY,
            "--image-tag-mutability",
            "IMMUTABLE",
            "--image-scanning-configuration",
            "scanOnPush=true",
        )
        step("ecr_repository", status="CREATED")
    else:
        step("ecr_repository", status="EXISTS")
    _aws(
        runner,
        region,
        "ecr",
        "put-lifecycle-policy",
        "--repository-name",
        REPOSITORY,
        "--lifecycle-policy-text",
        json.dumps(LIFECYCLE_POLICY),
    )
    password = runner(["aws", "ecr", "get-login-password", "--region", region])
    if password.returncode != 0:
        raise DeployError("ECR_LOGIN_FAILED")
    login = runner(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=password.stdout,
    )
    if login.returncode != 0:
        raise DeployError("DOCKER_LOGIN_FAILED")
    tag = f"{image}:{commit}"
    with tempfile.TemporaryDirectory(prefix="visualguard-src-") as context:
        # Build from the bound commit's archive, never from the working tree.
        archive = subprocess.run(
            ["git", "archive", "--format=tar", commit],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        subprocess.run(["tar", "-x", "-C", context], input=archive, check=True)
        build = runner(
            [
                "docker",
                "build",
                "--target",
                "lambda",
                "--platform",
                "linux/amd64",
                "--provenance=false",
                "-t",
                tag,
                context,
            ]
        )
    if build.returncode != 0:
        raise DeployError("DOCKER_BUILD_FAILED")
    push = runner(["docker", "push", tag])
    if push.returncode != 0:
        raise DeployError("DOCKER_PUSH_FAILED")
    images = _aws(
        runner,
        region,
        "ecr",
        "describe-images",
        "--repository-name",
        REPOSITORY,
        "--image-ids",
        f"imageTag={commit}",
    )
    image_digest = images["imageDetails"][0]["imageDigest"]
    image_uri = f"{image}@{image_digest}"
    step("image_pushed", commit=commit, image_digest=image_digest)

    exists = runner(
        [
            "aws",
            "lambda",
            "get-function",
            "--function-name",
            FUNCTION_NAME,
            "--region",
            region,
            "--output",
            "json",
            "--no-cli-pager",
        ]
    )
    if exists.returncode == 0:
        _aws(
            runner,
            region,
            "lambda",
            "update-function-code",
            "--function-name",
            FUNCTION_NAME,
            "--image-uri",
            image_uri,
        )
        step("lambda_function", status="UPDATED")
    else:
        _aws(
            runner,
            region,
            "lambda",
            "create-function",
            "--function-name",
            FUNCTION_NAME,
            "--package-type",
            "Image",
            "--code",
            f"ImageUri={image_uri}",
            "--role",
            role,
            "--memory-size",
            str(MEMORY_MB),
            "--timeout",
            str(TIMEOUT_SECONDS),
            "--architectures",
            "x86_64",
            "--environment",
            "Variables={VISUALGUARD_EXECUTION_ENV=AWS_LAMBDA}",
            "--tags",
            f"project=visualguard,commit={commit[:12]}",
        )
        step("lambda_function", status="CREATED")
    # A new function starts Pending; an update sets LastUpdateStatus. Wait
    # for both before configuring or invoking it.
    wait_exits = {}
    for waiter in ("function-active-v2", "function-updated-v2"):
        waited = runner(
            ["aws", "lambda", "wait", waiter, "--function-name", FUNCTION_NAME]
            + ["--region", region]
        )
        wait_exits[waiter] = waited.returncode
    if any(wait_exits.values()):
        raise DeployError("LAMBDA_NOT_READY")
    step("lambda_ready", wait_exits=wait_exits)
    concurrency = runner(
        [
            "aws",
            "lambda",
            "put-function-concurrency",
            "--function-name",
            FUNCTION_NAME,
            "--reserved-concurrent-executions",
            str(RESERVED_CONCURRENCY),
            "--region",
            region,
            "--output",
            "json",
            "--no-cli-pager",
        ]
    )
    step(
        "reserved_concurrency",
        status="SET" if concurrency.returncode == 0 else "UNAVAILABLE_FOR_ACCOUNT",
        detail=concurrency.stderr.strip()[:200],
    )

    url_config = runner(
        [
            "aws",
            "lambda",
            "get-function-url-config",
            "--function-name",
            FUNCTION_NAME,
            "--region",
            region,
            "--output",
            "json",
            "--no-cli-pager",
        ]
    )
    if url_config.returncode != 0:
        url_config_json = _aws(
            runner,
            region,
            "lambda",
            "create-function-url-config",
            "--function-name",
            FUNCTION_NAME,
            "--auth-type",
            "NONE" if public_url else "AWS_IAM",
        )
    else:
        url_config_json = json.loads(url_config.stdout)
        desired_auth_type = "NONE" if public_url else "AWS_IAM"
        if url_config_json.get("AuthType") != desired_auth_type:
            url_config_json = _aws(
                runner,
                region,
                "lambda",
                "update-function-url-config",
                "--function-name",
                FUNCTION_NAME,
                "--auth-type",
                desired_auth_type,
            )
    if public_url:
        for sid, action, extra in (
            (
                "public-url",
                "lambda:InvokeFunctionUrl",
                ["--function-url-auth-type", "NONE"],
            ),
            (
                "public-url-invoke",
                "lambda:InvokeFunction",
                ["--invoked-via-function-url"],
            ),
        ):
            runner(
                [
                    "aws",
                    "lambda",
                    "add-permission",
                    "--function-name",
                    FUNCTION_NAME,
                    "--statement-id",
                    sid,
                    "--action",
                    action,
                    "--principal",
                    "*",
                    *extra,
                    "--region",
                    region,
                    "--output",
                    "json",
                    "--no-cli-pager",
                ]
            )
    step(
        "function_url",
        auth_type=url_config_json.get("AuthType"),
        url=url_config_json.get("FunctionUrl"),
    )

    invocations = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, event in (("healthz", _function_url_event("GET", "/healthz")),):
            payload = Path(tmp) / f"{name}.json"
            payload.write_text(json.dumps(event), encoding="utf-8")
            out = Path(tmp) / f"{name}.out.json"
            result = runner(
                [
                    "aws",
                    "lambda",
                    "invoke",
                    "--function-name",
                    FUNCTION_NAME,
                    "--cli-binary-format",
                    "raw-in-base64-out",
                    "--payload",
                    f"file://{payload}",
                    str(out),
                    "--region",
                    region,
                    "--output",
                    "json",
                    "--no-cli-pager",
                ]
            )
            response = json.loads(out.read_text()) if out.exists() else {}
            body = json.loads(response.get("body") or "{}")
            invocations[name] = {
                "cli_exit": result.returncode,
                "status_code": response.get("statusCode"),
                "decision": body.get("decision"),
                "reason": body.get("reason"),
                "planned_action": (body.get("follow_up") or {}).get("planned_action"),
                "execution_environment": body.get("execution_environment"),
                "runtime": body.get("runtime"),
            }
    step("lambda_invocations", results=invocations)

    report_lines: list[str] = []
    for _ in range(12):
        logs = runner(
            [
                "aws",
                "logs",
                "filter-log-events",
                "--log-group-name",
                f"/aws/lambda/{FUNCTION_NAME}",
                "--filter-pattern",
                "REPORT",
                "--start-time",
                str(int((time.time() - 900) * 1000)),
                "--region",
                region,
                "--output",
                "json",
                "--no-cli-pager",
            ]
        )
        if logs.returncode == 0:
            report_lines = [
                e["message"].strip() for e in json.loads(logs.stdout).get("events", [])
            ]
            if len(report_lines) >= len(invocations):
                break
        time.sleep(5)
    step("cloudwatch_report_lines", count=len(report_lines), lines=report_lines[-5:])

    passed = invocations["healthz"]["status_code"] == 200 and bool(report_lines)
    evidence = {
        "schema_version": 1,
        "cut": "VISUALGUARD_AWS_LAMBDA_DEPLOYMENT001",
        "evidence_mode": "AWS_LAMBDA_EXECUTION_SYNTHETIC_INPUT",
        "status": "DEPLOYED_AND_INVOKED" if passed else "DEPLOYED_CHECKS_FAILED",
        "source_commit": commit,
        "source_archive_sha256": digest,
        "region": region,
        "function": FUNCTION_NAME,
        "image_uri": image_uri,
        "public_url": public_url,
        "preflight": preflight,
        "steps": steps,
        "live_state": {
            "aws_api": "EXECUTED",
            "deployment": "EXECUTED",
            "endpoint": "DEPLOYED_PUBLIC" if public_url else "DEPLOYED_PRIVATE_AWS_IAM",
            "camera": "NOT_RUN",
            "physical_action": "NONE",
        },
    }
    return json.loads(mask_account(json.dumps(evidence), account))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preview", "execute"), default="preview")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--public-url", action="store_true")
    parser.add_argument("--confirm-public", default="")
    parser.add_argument("--output", help="Optional JSON evidence path")
    args = parser.parse_args()
    if args.mode == "preview":
        result = plan(os.environ, public_url=args.public_url)
        code = 0
    else:
        try:
            result = execute(
                os.environ,
                confirm=args.confirm,
                public_url=args.public_url,
                confirm_public=args.confirm_public,
            )
            code = 0 if result["status"] == "DEPLOYED_AND_INVOKED" else 1
        except DeployError as error:
            result = {
                "mode": "EXECUTE",
                "status": "REFUSED_OR_FAILED",
                "reason": str(error),
            }
            code = 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
