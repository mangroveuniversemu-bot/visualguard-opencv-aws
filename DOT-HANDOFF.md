# DOT handoff

Repository: `mangroveuniversemu-bot/visualguard-opencv-aws`

Stage: **SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on
`claude/practical-ride-st6n28`, a fast-forward continuation of
`codex/witness-revocation-epoch-20261013` at `a32af35`. AWS, live camera,
independent witness, recorded video and physical action remain
**NOT_RUN**. `main` is untouched.

## Current bounded cut

`VISUALGUARD_OPENCV5_SCENE_ENDPOINT001`

- Parent checkpoint: CHECK136. This lane adds CHECK137 (evaluation) and
  CHECK138 (local container smoke).
- IP classification: `DERIVED`.
- Evidence modes: `SYNTHETIC_SCENE_EVALUATION`, `LOCAL_CONTAINER`,
  `HOSTED_CI`, `LAMBDA_EMULATOR`.

What changed, and why it matters for eligibility:

1. **Substantive OpenCV 5 workload.** `vision/scene_analysis.py` replaces
   threshold-only analysis of a 24×16 array with full-frame quality gates
   and lit-indicator detection. It is still bound to the replay ledger and
   still feeds the unchanged `plan_follow_up`.
2. **Measured against baselines.** `ops/evaluate_scene_pipeline.py` compares
   the pipeline with two baselines and an ablation on dev and held-out test
   splits.
3. **Runnable endpoint.** `service/`, the `Dockerfile` and
   `ops/smoke_test_endpoint.py` provide the endpoint, the image and a smoke
   client that works for local and AWS targets alike.
4. **AWS deploy kit, prepared only.** `ops/aws/*.template.json`,
   `ops/aws_lambda_deploy.py` and `.github/workflows/aws-lambda.yml`. AWS
   access is through OIDC with no stored keys; the workflow runs only from
   an `aws-*` tag or manual dispatch.

## Fresh evidence

- Full suite: PASS 243/243 plus 116 subtests (session host, Python 3.13.16).
- Hosted CI run `39808657344`: test + container jobs PASS at `b3049dd`.
- CHECK137 held-out test, 540 pairs: pipeline 94.26% exact with 0/210
  unsafe misses. Naive red-count baseline: 50%, 60 unsafe misses. Legacy
  brightness baseline: 31.85%, 76 unsafe misses.
- Known failures: round red sticker false-stops 30/30; one motion-blur seed
  gives REVIEW.
- CHECK138: read-only HTTP container smoke 9/9. The Lambda image answers
  through the Runtime Interface Emulator, which also makes the
  self-reported environment read `AWS_LAMBDA` locally. That is not AWS
  evidence.
- Gate 1 regressions re-run at `a32af35`: `run_demo.py` exit 0; contract
  verifier PASS (manifest `fdf2ac2e…`); final-video tests 8/8; final-video
  probe `BLOCKED / VIDEO_MISSING / exit 2`; AWS preflight exit 2.

## Blockers

- **AWS (eligibility):** the session container has no usable AWS
  credential. Its `AWS_ACCESS_KEY_ID`/`SECRET` values are 14 characters, not
  valid AWS formats, so they look like placeholders; this was not verified
  by an API call. There is no region and no `aws` CLI. The cloud session
  has no browser pane linked to the owner's desktop.
- **Video:** not recorded. No distinct reviewer yet. The 180 s contract
  still binds only CHECK126/CHECK129.

## CEO decisions required

1. Complete the AWS Console steps (OIDC provider, two roles, budget) and the
   GitHub secrets and variables in `docs/AWS_DEPLOYMENT_RUNBOOK.md`.
2. Approve the region and cost scope. Then authorize tag `aws-preflight-1`
   and afterwards `aws-deploy-private-1`.
3. Public judge URL (a public release) or live screen-share.
4. Replace the demo contract with v002 (draft in `docs/SUBMISSION_GAP.md`)
   or keep CHECK133.

## Exact next action

The owner completes runbook step 1 and pastes back only the account ID,
region, role ARNs and cost cap. Then push tag `aws-preflight-1` and read
the `aws-evidence-preflight-*` artifact. Until then keep `AWS = NOT_RUN`,
`DEPLOYMENT = NOT_RUN`, `ENDPOINT = NOT_DEPLOYED`.
