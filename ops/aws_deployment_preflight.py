"""Fail-closed, read-only AWS deployment preflight for VisualGuard.

The probe deliberately stops before any AWS call unless the owner authorization,
region, account, runtime role, deployment target, cost scope, and artifact digest
are explicit.  When those gates are present it performs only identity and IAM
read calls; it never creates, updates, invokes, or deletes AWS resources.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Mapping, Sequence


AWS_REGION_RE = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
ACCOUNT_ID_RE = re.compile(r"^\d{12}$")
ROLE_ARN_RE = re.compile(r"^arn:(?:aws|aws-us-gov|aws-cn):iam::(\d{12}):role/(.+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_TARGETS = {"apprunner", "ecs-fargate", "lambda-container"}
ALLOWED_COST_SCOPES = {"existing-budget", "free-tier", "zero-new-cost"}

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _check(code: str, passed: bool, detail: str) -> dict[str, str]:
    return {"code": code, "status": "PASS" if passed else "BLOCK", "detail": detail}


def _required_env(environ: Mapping[str, str], name: str) -> str:
    return environ.get(name, "").strip()


def evaluate_preflight(
    deployment: Mapping[str, object],
    environ: Mapping[str, str],
    runner: Runner = _default_runner,
) -> dict[str, object]:
    """Evaluate deployment gates and, only when complete, make read-only AWS calls."""

    checks: list[dict[str, str]] = []
    stage = str(deployment.get("stage", ""))
    source_ready = bool(deployment.get("source_imported")) and stage == (
        "SOURCE_IMPORTED_AND_LOCALLY_VERIFIED"
    )
    checks.append(
        _check(
            "source_ready",
            source_ready,
            "Source is imported and locally verified."
            if source_ready
            else "Source gate is incomplete.",
        )
    )

    authorized = _required_env(environ, "VISUALGUARD_AWS_OWNER_AUTHORIZED") == "true"
    checks.append(
        _check(
            "owner_authorization",
            authorized,
            "Explicit owner authorization is present."
            if authorized
            else "Set VISUALGUARD_AWS_OWNER_AUTHORIZED=true only in an owner-authorized runtime.",
        )
    )

    region = _required_env(environ, "AWS_REGION") or _required_env(
        environ, "AWS_DEFAULT_REGION"
    )
    approved_region = _required_env(environ, "VISUALGUARD_AWS_APPROVED_REGION")
    region_ok = bool(AWS_REGION_RE.fullmatch(region)) and approved_region == region
    checks.append(
        _check(
            "region_approval",
            region_ok,
            "Selected region matches the approved region."
            if region_ok
            else "AWS_REGION and VISUALGUARD_AWS_APPROVED_REGION must be the same valid region.",
        )
    )

    account_id = _required_env(environ, "VISUALGUARD_AWS_ACCOUNT_ID")
    account_ok = bool(ACCOUNT_ID_RE.fullmatch(account_id))
    checks.append(
        _check(
            "account_scope",
            account_ok,
            "A 12-digit expected account is configured."
            if account_ok
            else "VISUALGUARD_AWS_ACCOUNT_ID must name the authorized account.",
        )
    )

    role_arn = _required_env(environ, "VISUALGUARD_AWS_RUNTIME_ROLE_ARN")
    role_match = ROLE_ARN_RE.fullmatch(role_arn)
    role_ok = bool(role_match and role_match.group(1) == account_id)
    checks.append(
        _check(
            "runtime_role_scope",
            role_ok,
            "Runtime role belongs to the expected account."
            if role_ok
            else "Runtime role ARN is missing, invalid, or belongs to another account.",
        )
    )

    target = _required_env(environ, "VISUALGUARD_AWS_DEPLOY_TARGET")
    target_ok = target in ALLOWED_TARGETS
    checks.append(
        _check(
            "deployment_target",
            target_ok,
            f"Deployment target is {target}."
            if target_ok
            else "Choose one explicit target: apprunner, ecs-fargate, or lambda-container.",
        )
    )

    cost_scope = _required_env(environ, "VISUALGUARD_AWS_COST_SCOPE")
    cost_ok = cost_scope in ALLOWED_COST_SCOPES
    checks.append(
        _check(
            "cost_scope",
            cost_ok,
            f"Cost scope is {cost_scope}."
            if cost_ok
            else "Cost scope must be existing-budget, free-tier, or zero-new-cost.",
        )
    )

    artifact_sha = _required_env(environ, "VISUALGUARD_ARTIFACT_SHA256")
    artifact_ok = bool(SHA256_RE.fullmatch(artifact_sha))
    checks.append(
        _check(
            "artifact_binding",
            artifact_ok,
            "A lowercase SHA-256 artifact binding is configured."
            if artifact_ok
            else "VISUALGUARD_ARTIFACT_SHA256 must bind deployment to immutable bytes.",
        )
    )

    static_ready = all(item["status"] == "PASS" for item in checks)
    aws_api_state = "NOT_RUN"
    commands_run: list[str] = []

    if static_ready:
        version = runner(("aws", "--version"))
        commands_run.append("aws --version")
        cli_ok = version.returncode == 0
        checks.append(
            _check(
                "aws_cli",
                cli_ok,
                "AWS CLI is available."
                if cli_ok
                else "AWS CLI is unavailable or failed.",
            )
        )

        if cli_ok:
            identity = runner(
                (
                    "aws",
                    "sts",
                    "get-caller-identity",
                    "--output",
                    "json",
                    "--no-cli-pager",
                    "--region",
                    region,
                )
            )
            commands_run.append("aws sts get-caller-identity")
            try:
                identity_json = (
                    json.loads(identity.stdout) if identity.returncode == 0 else {}
                )
            except json.JSONDecodeError:
                identity_json = {}
            identity_ok = identity_json.get("Account") == account_id
            checks.append(
                _check(
                    "caller_identity",
                    identity_ok,
                    "Caller identity matches the expected account."
                    if identity_ok
                    else "Caller identity could not be verified in the expected account.",
                )
            )
            aws_api_state = (
                "READ_ONLY_PROBE"
                if identity.returncode == 0
                else "READ_ONLY_PROBE_FAILED"
            )

            if identity_ok and role_match:
                role_name = role_match.group(2)
                role = runner(
                    (
                        "aws",
                        "iam",
                        "get-role",
                        "--role-name",
                        role_name,
                        "--output",
                        "json",
                        "--no-cli-pager",
                        "--region",
                        region,
                    )
                )
                commands_run.append("aws iam get-role")
                try:
                    role_json = json.loads(role.stdout) if role.returncode == 0 else {}
                except json.JSONDecodeError:
                    role_json = {}
                returned_arn = role_json.get("Role", {}).get("Arn")
                checks.append(
                    _check(
                        "runtime_role_readback",
                        returned_arn == role_arn,
                        "Runtime role readback matches the configured ARN."
                        if returned_arn == role_arn
                        else "Runtime role was not readable or did not match the configured ARN.",
                    )
                )

    status = (
        "READY" if checks and all(c["status"] == "PASS" for c in checks) else "BLOCKED"
    )
    return {
        "schema_version": 1,
        "cut": "VISUALGUARD_AWS_DEPLOYMENT_PREFLIGHT001",
        "provenance": "DERIVED",
        "evidence_mode": "AWS_READ_ONLY_PREFLIGHT",
        "status": status,
        "checks": checks,
        "commands_run": commands_run,
        "live_state": {
            "aws_api": aws_api_state,
            "deployment": "NOT_RUN",
            "endpoint": "NOT_DEPLOYED",
            "camera": "NOT_RUN",
            "physical_action": "NONE",
        },
        "action_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", default="deployment.json")
    parser.add_argument("--output", help="Optional JSON evidence path")
    args = parser.parse_args()

    deployment = json.loads(Path(args.deployment).read_text(encoding="utf-8"))
    result = evaluate_preflight(deployment, os.environ)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
