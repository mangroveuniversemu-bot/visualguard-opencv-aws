# Submission gap matrix

Snapshot: 2026-10-26. Requirements are taken from search-result summaries of
the official OpenCV and Devpost pages, which could not be fetched directly
from this environment. **Re-check them on Devpost before submitting.**
Reported deadline: 2026-10-26 23:59 PT (unverified).

| Requirement | Before this cut | Now | Gap / risk |
|---|---|---|---|
| OpenCV 5 used for substantive image analysis | threshold + countNonZero on a 24×16 array | full-frame quality gates and indicator detection using 15+ OpenCV ops; `config_sha256` bound | 🟡 synthetic inputs only |
| Meaningful AWS component | none; preflight blocked | private AWS_IAM Lambda deployed and invoked from `832b1b4`; AWS evidence committed at `3442e3a` | 🟢 synthetic-input AWS execution only |
| Working web endpoint or live demo | none | HTTP service + private AWS_IAM Lambda; health/alarm/clear/missing-view invocations recorded | 🟡 no public judge URL; public release remains an owner decision |
| Measurable evaluation + baseline | 8-case routing matrix | 540-pair held-out test, 3 comparators, ablation, failure table | 🟡 synthetic; no field data |
| Failure cases documented | yes, for ledger internals | vision failures listed in `TECHNICAL_REPORT.md` §4 | 🟢 |
| Architecture diagram | none | `ARCHITECTURE.md` (system + agent loop, mermaid) | 🟢 |
| Agentic track: OpenCV output changes a later action | `plan_follow_up` | `/v1/inspect` returns a perceive/decide/plan trace and the planned action | 🟢 planned only; 🟡 no external tool call |
| Observability | none | three workflow CloudWatch `REPORT` lines plus supplemental RequestId `5e91ad05-2270-4828-b1dc-619fc4ebdd62` | 🟢 for the four synthetic AWS cases only |
| Human control | action never executed | unchanged | 🟢 |
| Limitations / responsible use | README | `TECHNICAL_REPORT.md` §6 | 🟢 |
| Demo video (≤ 5 min, judge-accessible) | 180 s contract, not recorded | v002 binds CHECK126 plus the sanitized AWS execution evidence | 🔴 not recorded or independently reviewed |
| Team, title, Devpost write-up | — | not started | 🔴 owner |

## Shortest path to an eligible submission

1. Use contract v002 to record the six-segment 180-second demo without
   exposing AWS credentials or implying live-camera evidence.
2. A distinct human reviews the final media bytes and runs
   `ops/verify_final_demo_video_evidence.py`.
3. Decide private screen-share versus a public judge URL. A public Function
   URL still requires separate owner approval.
4. Owner verifies current Devpost rules and submits. Do not repeat the paid
   deployment under the expired one-time allowance.

## Demo v002 storyboard (contract prepared, video not recorded)

| s | Segment | Shows | Evidence |
|---|---|---|---|
| 0–20 | Problem and scope | bounded decisions; nothing is executed | `TECHNICAL_REPORT.md` §1 |
| 20–50 | OpenCV clear path | fixed synthetic clear pair → REVIEW | CHECK126 |
| 50–95 | Negative controls | eight-case local matrix, all action_executed=false | CHECK126 |
| 95–120 | Bounded follow-up | review, recapture or hold; no physical action | CHECK126 |
| 120–160 | AWS | private Lambda health/alarm/clear/missing-view plus REPORT lines | AWS execution evidence |
| 160–180 | Limits | private only, reserved concurrency unavailable, no camera/field result | AWS execution evidence |
