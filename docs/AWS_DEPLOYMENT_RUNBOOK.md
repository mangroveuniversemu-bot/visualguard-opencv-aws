# AWS deployment runbook and execution readback

Execution update (2026-10-26): one private `AWS_IAM` Lambda was deployed and
invoked in `us-east-1` under the owner's one-time approval. Source commit
`832b1b476ce88e3fa95e83ac5749f64af0f4bd63`, workflow run `40223113044`,
and sanitized evidence
`evidence/AWS_EXECUTION_20261026_40223113044.json` are the canonical record.
Reserved concurrency 2 was rejected by the account quota and is not configured.
The owner has approved the public Function URL. Public rollout still requires
the daily-quota table and its narrowly scoped Lambda permission below.

Original target: the smallest meaningful AWS component. One Lambda container
function (`visualguard-inspector`) built from one ECR repository
(`visualguard`), invoked through the AWS API, with an `AWS_IAM` Function URL
by default. The private workflow path has now been executed once; the public workflow path remains NOT_RUN.

## Who does what

| Step | Owner | Claude |
|---|---|---|
| 1. OIDC provider, deploy role, runtime role, budget alert | owner, AWS Console | provides the templates in `ops/aws/` |
| 2. Repository secrets and variables | owner, GitHub settings | names listed below |
| 3. Read-only preflight | owner pushes tag `aws-preflight-1`, or asks Claude to | reads the run, records evidence |
| 4. Private deploy | owner approves cost scope, then tag `aws-deploy-private-1` | records evidence, updates status |
| 5. Public judge URL (approved 2026-10-27) | after quota table and role permission are ready, tag `aws-deploy-public-1` | deploys the endpoint and runs one-inference smoke test |

No AWS access keys are created or stored. GitHub Actions exchanges its OIDC
token for short-lived role credentials.

## Judge-facing page after public approval

The Lambda Function URL serves the all-English UI at `/`. The page reads
`/healthz` and `/v1/samples`, and submits image pairs to `POST /v1/inspect` on
that same origin. This is one public AWS URL, not a localhost preview or a
separate login site; the browser sends ordinary unsigned requests. The page
shows the reported OpenCV version and runtime. All visitors share five
`POST /v1/inspect` attempts per Taiwan calendar day, resetting at midnight
Asia/Taipei. Malformed or otherwise failed inspection POSTs consume a slot;
health and sample GET requests do not. A full quota or unavailable quota store
blocks further inference (429 or 503). Public smoke testing uses one inference
request; the local test suite carries the broader sample matrix and negative
controls.

The current endpoint remains `AWS_IAM` until the approved public rollout.
Public mode changes it to `NONE` and grants `Principal: "*"` only the two
Function URL invocation permissions. Anyone with the URL can invoke the
inspection service without signing in, subject to the shared daily quota.

## 1. AWS Console (owner)

Replace `${ACCOUNT_ID}` and `${REGION}` in the templates.

1. **IAM → Identity providers → Add provider → OpenID Connect**
   - URL `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`.
2. **Runtime role** `visualguard-lambda-runtime`
   - Trust: `ops/aws/lambda-runtime-trust.template.json`.
   - Permissions: AWS managed `AWSLambdaBasicExecutionRole` (CloudWatch Logs),
     plus the single-table policy in
     `ops/aws/dynamodb-daily-quota-runtime-policy.template.json`.
3. **Daily quota table** `visualguard-daily-quota` in `us-east-1`
   - On-demand capacity; partition key `quota_date` (String); one counter per
     Taiwan calendar date. The Lambda runtime role receives no scan, read,
     delete or table-management permission.
   - Create the table before the public deploy:

     ```bash
     aws dynamodb create-table --table-name visualguard-daily-quota \
       --billing-mode PAY_PER_REQUEST \
       --attribute-definitions AttributeName=quota_date,AttributeType=S \
       --key-schema AttributeName=quota_date,KeyType=HASH \
       --tags Key=project,Value=visualguard --region us-east-1
     ```

   - Replace `${REGION}` and `${ACCOUNT_ID}` in the policy template, then
     attach it to `visualguard-lambda-runtime` as an inline policy. This adds
     permission to update only this table.
4. **Deploy role** `visualguard-github-deploy`
   - Trust: `ops/aws/github-oidc-trust.template.json`. It allows only this
     repository's `claude/practical-ride-st6n28` branch and `aws-*` tags.
   - Preflight only: attach just the `PreflightReadRuntimeRole` statement
     from `ops/aws/github-deploy-policy.template.json`.
   - Deploy: attach the whole `github-deploy-policy.template.json`.
   - Public URL only: also attach `github-public-url-addendum.template.json`.
5. **Billing → Budgets**: a monthly cost budget with an email alert at the
   owner's cap.

## 2. GitHub repository settings (owner)

| Kind | Name | Value |
|---|---|---|
| Secret | `VISUALGUARD_AWS_DEPLOY_ROLE_ARN` | ARN of `visualguard-github-deploy` |
| Secret | `VISUALGUARD_AWS_RUNTIME_ROLE_ARN` | ARN of `visualguard-lambda-runtime` |
| Secret | `VISUALGUARD_AWS_ACCOUNT_ID` | 12-digit account ID |
| Variable | `VISUALGUARD_AWS_REGION` | for example `us-east-1` |
| Variable | `VISUALGUARD_AWS_COST_SCOPE` | `free-tier`, `zero-new-cost` or `existing-budget` |

Secrets are used for the ARNs and account ID so they are masked in public
logs.

## 3–5. Run

```bash
git tag aws-preflight-1 claude/practical-ride-st6n28 && git push origin aws-preflight-1
# after the preflight evidence is reviewed and cost scope is approved:
git tag aws-deploy-private-1 claude/practical-ride-st6n28 && git push origin aws-deploy-private-1
# only if a public judge URL is approved:
git tag aws-deploy-public-1 claude/practical-ride-st6n28 && git push origin aws-deploy-public-1
```

The workflow is `.github/workflows/aws-lambda.yml`. It is never scheduled.
`workflow_dispatch` only becomes available after the file is on the default
branch, which is why tags are the trigger here.

Preview the exact deploy commands at any time without AWS calls:

```bash
python ops/aws_lambda_deploy.py --mode preview
```

`--mode execute` refuses unless all of these hold:

- the confirmation phrase matches;
- the read-only preflight is `READY` in the same process;
- the target is `lambda-container`;
- `VISUALGUARD_ARTIFACT_SHA256` equals `git archive HEAD | sha256sum`.

The image is built from that archive, not from the working tree.

## Evidence produced

Uploaded as a workflow artifact `aws-evidence-<mode>-<run_id>`, with the
account ID masked:

- `preflight.json`: `sts get-caller-identity` and `iam get-role` results;
- `deploy.json`: source commit, source archive SHA-256, ECR image digest,
  function URL auth type, the `aws lambda invoke` health result, and CloudWatch
  `REPORT` lines; the public smoke test performs the one live inspection call;
- `public-smoke.json` (public mode only): unsigned UI/API checks against the
  public URL, requiring `AWS_LAMBDA` and daily-quota headers. It sends one
  real inference request to preserve the shared allowance.

Only these AWS-side records upgrade `AWS`, `DEPLOYMENT` or `ENDPOINT` status.
The response field `execution_environment` is self-reported and never counts.

## Cost controls and estimate

- 1024 MB memory and 30 s timeout. The previous deploy attempt to set reserved
  concurrency to 2 was rejected by this account's quota, so there is currently
  no per-function concurrency throttle.
- DynamoDB uses pay-per-request with one small row per day. The AWS price page
  lists US East on-demand writes at USD 0.625 per million 1 KB writes; five
  successful counter updates each day cost about USD 0.0001 per 30-day month,
  before storage and failed conditional checks.
- ECR tags are immutable, and a lifecycle rule keeps 3 images.
- There is no provisioned concurrency, NAT gateway, load balancer or
  always-on compute.
- **Estimate (verify on AWS pricing pages):** judging-level traffic usually
  stays inside the Lambda free tier. ECR storage for one ~0.5 GB image is
  roughly USD 0.05 per month beyond any free allowance. CloudWatch Logs
  volume is a few KB per request.
- The monthly budget is an alert, not an automatic spending stop. The five-per-
  day limit stops OpenCV inference, but repeated rejected requests still invoke
  Lambda and attempt a conditional DynamoDB update. The public endpoint has no
  hard dollar cap.

## Teardown

```bash
aws lambda delete-function-url-config --function-name visualguard-inspector
aws lambda delete-function --function-name visualguard-inspector
aws ecr delete-repository --repository-name visualguard --force
aws logs delete-log-group --log-group-name /aws/lambda/visualguard-inspector
```

The deploy role has no delete permissions on purpose. The owner runs
teardown.
