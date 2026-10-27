# Public AWS demo — 2026-10-27

This addendum records the public AWS rollout after the private execution
checkpoint of 2026-10-26. Older private-only descriptions in the repository
remain dated historical records; they do not describe the public deployment
listed here.

[Current architecture](AWS_PUBLIC_ARCHITECTURE_20261027.png) · [Updated technical report](VisualGuard-Technical-Report-AWS-Live-20261027.pdf)

## Open the application

[VisualGuard on AWS Lambda](https://zkdmdpnivndaqlsxgm4umbjwjy0akezq.lambda-url.us-east-1.on.aws/)
serves the English application and its inspection API from the same origin.
No account or AWS credentials are required by a visitor.

1. Select a sample pair or upload a front and side image. The page previews
   both views; selecting a sample does not run inference.
2. Select **Inspect on AWS** to submit the pair to the deployed OpenCV service.
3. Read the decision, reasons, image-quality findings, and recommended next
   step. For `REQUEST_VIEW`, replace the requested view and explicitly submit
   another inspection.
4. Expand the evidence to inspect the cloud response. The actual AWS Request ID
   is displayed separately from the application's own request ID.

The UI adapts to mobile and desktop screens. `REVIEW`, `STOP`, and
`REQUEST_VIEW` are recommendations for a human operator. No equipment actuator
is connected and `action_executed` remains false.

## Deployment record

| Item | Observed value |
| --- | --- |
| AWS region | `us-east-1` |
| Function | `visualguard-inspector` |
| Final deployed source | `0030066b2733d877678bf0f2bc4c06970bb29714` |
| Final release | `aws-deploy-public-20261027-final` |
| Final deployment workflow | [GitHub Actions run 40454177734](https://github.com/mangroveuniversemu-bot/visualguard-opencv-aws/actions/runs/40454177734) — succeeded |
| Source CI | [GitHub Actions run 40453839498](https://github.com/mangroveuniversemu-bot/visualguard-opencv-aws/actions/runs/40453839498) — succeeded |
| Function URL authentication | `NONE` |
| Deployment job | Succeeded |
| Public health response | HTTP `200` |
| Anonymous readback | `2026-10-27T13:16:51+08:00`; health HTTP `200`, UI HTTP `200` |
| Anonymous health AWS Request ID | `3beaded8-c5cb-4c9f-9812-2313a02d8946` |
| UI integrity readback | Downloaded HTML SHA-256 exactly matched `service/index.html` at the final source |
| Final deployment check | GET requests only; zero inference POSTs |
| One-time quota-counter reset | Completed after owner approval; DynamoDB console readback for `2026-10-27` showed `calls=1`, leaving 4 attempts around 13:11 Asia/Taipei |

The [anonymous readback record](../evidence/AWS_PUBLIC_READBACK_20261027.json) binds the public responses and UI hash.
The remaining count is a dated observation, not a promise about availability
after other visitors use the application.

The final source preserves native PNG previews for synthetic samples, permits
up to 1 MiB per prepared sample image, prepares uploaded photos as JPEGs of
up to 240 KiB each, and limits the browser's encoded request to 3 MiB. This
fixes the earlier sample-preview size issue while retaining a bounded upload.

Actual public AWS inspection responses observed during the initial rollout
from source `48518bcfbd7c911b3dc915c63e4548096e352f9d` included:

| Synthetic input | HTTP status | Decision | Reported latency |
| --- | --- | --- | --- |
| Normal green pair | `200` | `REVIEW` | `685.8 ms` |
| Side-view alarm pair | `200` | `STOP` | `470.9 ms` |

These are cloud executions over synthetic images. They do not establish
accuracy on a real camera feed or field acceptance.

## Shared daily quota and initial smoke recovery

The public inspection API uses the DynamoDB table `visualguard-daily-quota`
to enforce one shared allowance of five `/v1/inspect` POST attempts per
Asia/Taipei calendar day. Health checks and sample GET requests do not consume
an inspection. A quota-store failure blocks inference. The five-attempt
allowance is shared by all visitors rather than renewed per browser.

The initial [workflow run 40452795741](https://github.com/mangroveuniversemu-bot/visualguard-opencv-aws/actions/runs/40452795741)
was **FAILED overall**, although its deployment step and health checks
succeeded. Its public smoke step omitted the one-inference mode flag, ran
the full case matrix, admitted five inspection attempts, and was then blocked
by the shared quota. CloudWatch execution Request ID
`4e8fb0b1-1036-4889-9059-b03fb53c47b3` is part of that initial rollout's
execution evidence. The failed workflow is not a successful full public
smoke run.

The final deployment uses read-only GET checks, sends zero inference POSTs,
and succeeded in run `40454177734`. The separately approved one-time reset
was completed and read back as `calls=1`; no inference was sent between that
reset and the final anonymous readback above.

This daily inference allowance does not cap all AWS costs: page requests,
Lambda invocations, logging, and rejected requests can still incur usage.

## Interaction references

Two prior Devpost winners informed the presentation choices:

- [Nomi — AWS & NVIDIA Hackathon 2025 Grand Prize](https://devpost.com/software/nomi-aoim58)
  presents readable insights and explicitly identifies its sample-data
  frontend. VisualGuard likewise identifies the input and execution mode and
  keeps saved evidence distinct from a newly returned cloud response.
- [Skyrchitect — AWS & NVIDIA Hackathon 2025 Second Place](https://devpost.com/software/skyrchitect-6d37yf)
  describes a multi-step creation flow and structured, inspectable results.
  VisualGuard uses the focused sequence of adding views, explicitly inspecting
  on AWS, and reviewing the next action, with technical evidence available on
  demand.

These references guided interaction choices. Their awards do not demonstrate
that a particular visual style causes a project to win, and their deployment
claims are not evidence for VisualGuard.

## Remaining evidence boundaries

The existing 540-pair evaluation is synthetic. The known red-sticker false
`STOP` cases remain relevant. Archived exhibition footage provides visual
context; it does not establish live-camera integration. The public cloud
rollout does not change the status of physical control, independently labeled
field evaluation, or the older CHECK146 film-review contract. This deployment
addendum does not certify the current Devpost submission status.
