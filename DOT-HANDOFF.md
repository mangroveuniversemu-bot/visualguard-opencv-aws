# DOT handoff

Repository: `mangroveuniversemu-bot/visualguard-opencv-aws`

Stage: **SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on
`codex/witness-revocation-epoch-20261013`. AWS, live camera, independent
witness, and physical action remain **NOT_RUN**.

## Current bounded cut

`VISUALGUARD_AWS_DEPLOYMENT_PREFLIGHT001`

- Parent checkpoint: CHECK126.
- Parent commit: `7f9447cb1df02901ba0e6797d950b3b2708cd605`.
- IP classification: `DERIVED`.
- Evidence mode: `AWS_READ_ONLY_PREFLIGHT`.

The new preflight is deliberately fail-closed. It makes no AWS call until
owner authorization, region/account/role, deployment target, cost scope, and
artifact digest are all explicit. Its only allowlisted AWS operations are
`sts:GetCallerIdentity` and `iam:GetRole`; it cannot create, update, invoke, or
delete resources.

The replayable matrix runs eight fixed-array OpenCV controls and converts each
inspection result into a bounded follow-up plan. Clear evidence queues human
review; missing or occluded views request a new capture; alarm, stale capture,
calibration drift, dependency drift, and consequence mismatch hold automation.
Every row records `action_executed=false` and `physical_action=NONE`.

## Fresh evidence

- AWS preflight targeted tests: PASS 6/6, including missing authorization,
  region mismatch, cross-account role, missing CLI, wrong caller account, and
  a fully mocked read-only success path;
- real local preflight: BLOCKED before AWS API; no AWS variables or AWS CLI
  were present;
- AWS API, deployment, endpoint, camera, and physical action: **NOT_RUN**;
- judging-matrix targeted tests: PASS 5/5;
- matrix plus OpenCV regression slice: PASS 125/125 plus 55 subtests;
- scoped branch full suite: PASS 193/193 plus 66 subtests;
- changed-file Ruff and format check: PASS;
- compileall and replayable eight-case matrix probe: PASS execution;
- OpenCV output changes the planned downstream workflow action: demonstrated
  locally; external action execution: **NONE**.

## Blockers and resume condition

Authorized AWS identity, selected region/account/role/cost scope and immutable
artifact binding, live camera input, and an independently administered
monotonic or immutable witness remain unavailable.
The matrix is deterministic local evidence, not a field-accuracy or deployment
claim.

## Exact next action

Publish the verified commit and checkpoint, then rotate to PayPal unless a
newer canonical checkpoint changes routing. Resume AWS only in an
owner-authorized runtime, rerun the read-only preflight, and preserve its JSON
output before any provisioning decision.
