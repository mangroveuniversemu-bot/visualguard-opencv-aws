# Submission gap matrix

Snapshot: 2026-10-22. Requirements are taken from search-result summaries of
the official OpenCV and Devpost pages, which could not be fetched directly
from this environment. **Re-check them on Devpost before submitting.**
Reported deadline: 2026-10-26 23:59 PT (unverified).

| Requirement | Before this cut | Now | Gap / risk |
|---|---|---|---|
| OpenCV 5 used for substantive image analysis | threshold + countNonZero on a 24×16 array | full-frame quality gates and indicator detection using 15+ OpenCV ops; `config_sha256` bound | 🟡 synthetic inputs only |
| Meaningful AWS component | none; preflight blocked | Lambda image, deploy script, IAM templates, OIDC workflow prepared | 🔴 **eligibility blocker:** owner AWS setup and approval needed |
| Working web endpoint or live demo | none | HTTP service + demo page; local container and hosted CI smoke 9/9 | 🔴 no AWS URL yet; 🟡 a public URL is a release decision |
| Measurable evaluation + baseline | 8-case routing matrix | 540-pair held-out test, 3 comparators, ablation, failure table | 🟡 synthetic; no field data |
| Failure cases documented | yes, for ledger internals | vision failures listed in `TECHNICAL_REPORT.md` §4 | 🟢 |
| Architecture diagram | none | `ARCHITECTURE.md` (system + agent loop, mermaid) | 🟢 |
| Agentic track: OpenCV output changes a later action | `plan_follow_up` | `/v1/inspect` returns a perceive/decide/plan trace and the planned action | 🟢 planned only; 🟡 no external tool call |
| Observability | none | one JSON log line per request; CloudWatch `REPORT` captured by deploy | 🟡 AWS-side not yet observed |
| Human control | action never executed | unchanged | 🟢 |
| Limitations / responsible use | README | `TECHNICAL_REPORT.md` §6 | 🟢 |
| Demo video (≤ 5 min, judge-accessible) | 180 s contract, not recorded | unchanged; contract still binds only CHECK126/CHECK129 | 🔴 not recorded; contract does not show the new pipeline or AWS |
| Team, title, Devpost write-up | — | not started | 🔴 owner |

## Shortest path to an eligible submission

1. **Owner, about 15 minutes:** AWS Console steps 1–4 in
   `AWS_DEPLOYMENT_RUNBOOK.md`, plus GitHub secrets and variables.
2. Tag `aws-preflight-1`. Review the evidence.
3. Approve the cost scope. Tag `aws-deploy-private-1`. This gives the first
   real AWS execution evidence.
4. Decide public URL versus a judge screen-share. If public, tag
   `aws-deploy-public-1`.
5. Decide whether to replace the 180 s demo contract with a v002 that binds
   CHECK137/CHECK138 and the AWS evidence.
6. A human records the video, and a different person reviews it. Run
   `ops/verify_final_demo_video_evidence.py`.
7. Owner submits on Devpost.

## Proposed demo v002 storyboard (draft, not a contract)

| s | Segment | Shows | Evidence |
|---|---|---|---|
| 0–20 | Problem and scope | bounded decisions; nothing is executed | `TECHNICAL_REPORT.md` §1 |
| 20–60 | Live inspect | demo page: clear → REVIEW, alarm → STOP, glare and sticker rejected | CHECK138 / AWS deploy |
| 60–95 | Quality gates | defocus and occluded-alarm → REQUEST_VIEW; ablation shows why | CHECK137 |
| 95–125 | Evaluation | test-split table versus baselines; the round-sticker failure | CHECK137 |
| 125–160 | AWS | Lambda invoke + CloudWatch REPORT lines, OIDC deploy run | AWS deploy evidence |
| 160–180 | Limits | synthetic data, no camera, per-instance replay ledger | `TECHNICAL_REPORT.md` §6 |
