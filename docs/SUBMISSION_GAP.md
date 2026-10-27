> Current public AWS deployment: see [2026-10-27 live demo update](AWS_PUBLIC_DEMO_20261027.md). The private deployment and pending gates below describe earlier checkpoints.

# VisualGuard submission readiness

Snapshot: 2026-10-27 (Asia/Taipei). This file tracks evidence and remaining judge-access gates; it does not claim the project has been submitted.

**Project:** VisualGuard — Two Views. One Next Step.  
**Solo team display name:** YOUNG-FU  
**Current submission state:** Submitted; anonymous public readback verified on 2026-10-27.  
**Current code branch:** claude/practical-ride-st6n28. The repository is public. The no-login judge paths now include both the static GitHub Pages saved replay and the public AWS Function URL documented in `AWS_PUBLIC_DEMO_20261027.md`. Loading a sample performs GET requests only; inference requires an explicit **Inspect on AWS** action and uses the shared daily quota.

## Deadline and official requirements

The [competition overview](https://opencv26.devpost.com/) and [rules](https://opencv26.devpost.com/rules) show a deadline of October 26, 2026 at 11:45 p.m. PDT in the page header. The overview body says 11:59 p.m. Pacific Time, a 14-minute difference. Use the earlier cutoff: October 27 at 14:45 Taiwan time. Recheck the live Devpost page immediately before submission.

The official final-entry checklist asks for a technical report; a public or private judge-accessible repository/archive; pinned dependencies and build, deployment, and test instructions; an architecture diagram; a working web endpoint or arranged live screen-share; a public or unlisted video no longer than five minutes showing the team, working application, architecture, and principal results; and appropriate evaluation evidence with failures or limitations.

## Current readiness

| Requirement | Evidence now | Remaining gate |
|---|---|---|
| OpenCV 5 image analysis | Full-frame two-view quality checks and red-indicator detection are documented in README and TECHNICAL_REPORT.md. | Evaluation uses generated inputs; field accuracy is unverified. |
| AWS component | Public Lambda Function URL in us-east-1, deployed from `0030066b2733d877678bf0f2bc4c06970bb29714`; deployment run 40454177734 and CI run 40453839498 succeeded. GET-only anonymous readback is bound in `evidence/AWS_PUBLIC_READBACK_20261027.json`; the earlier private invocation evidence remains separately preserved. | Inputs are synthetic and field accuracy is unverified. The five-attempt Asia/Taipei daily quota limits inference attempts, not all AWS cost. |
| Architecture | docs/ARCHITECTURE.md contains the system and workflow diagram. | Confirm the rendered diagram is visible in the judge’s browsing context. |
| Technical report | docs/TECHNICAL_REPORT.md describes the implementation, AWS execution, evaluation, failures, limits, and reproduction steps. | None for document presence; reviewer acceptance is not claimed. |
| Evaluation | 540 generated pairs; 94.26% exact-decision agreement. Known failure: 30/30 round red-sticker cases produced false STOP; one motion-blur case was misrouted. | Synthetic results only; no ground-truth factory or camera evaluation. |
| Dependencies and instructions | Pinned requirement files, Docker targets, deployment runbook, and reproduction commands are in the repository. | A fresh clean-machine install was not re-run during this documentation update. |
| Code access | The project is public on claude/practical-ride-st6n28. | Read the published source and CI results back before final form review. |
| Demo video | Public 2:20 owner-review film: https://youtu.be/AEDHXknTBy8. | Before submission, verify the actual film visibly covers the solo team, working app, architecture, and principal results. It is not independently reviewed or bound to the older CHECK146 video contract. |
| Live demonstration | The static GitHub Pages replay and the public no-login AWS judge UI are both available. The AWS page exposes health, samples, explicit inference, decisions, next actions, and AWS request IDs. | CHECK156 verified GET-only availability; it did not spend inference quota or establish camera/field accuracy. |
| Devpost entry | Public submission: https://devpost.com/software/visualguard-two-views-one-next-step. Anonymous readback shows `SUBMITTED TO` the OpenCV AI Competition 2026, with repository and no-login judge-page links. | Submission is complete; any later edit or withdrawal remains owner-controlled. |
| Special tracks | No COOL-on-Graviton performance claim is made. | Do not claim COOL eligibility without verified Graviton execution and comparative measurements. Agentic Vision eligibility also needs evidence that a visual result drives a subsequent plan, tool call, action, or human-approval request. |

## Evidence links

- [Repository](https://github.com/mangroveuniversemu-bot/visualguard-opencv-aws/tree/claude/practical-ride-st6n28)
- [README](https://github.com/mangroveuniversemu-bot/visualguard-opencv-aws/blob/claude/practical-ride-st6n28/README.md)
- [Architecture](https://github.com/mangroveuniversemu-bot/visualguard-opencv-aws/blob/claude/practical-ride-st6n28/docs/ARCHITECTURE.md)
- [Technical report](https://github.com/mangroveuniversemu-bot/visualguard-opencv-aws/blob/claude/practical-ride-st6n28/docs/TECHNICAL_REPORT.md)
- [AWS execution evidence](https://github.com/mangroveuniversemu-bot/visualguard-opencv-aws/blob/claude/practical-ride-st6n28/evidence/AWS_EXECUTION_20261026_40223113044.json)
- [Owner-review video](https://youtu.be/AEDHXknTBy8)
- [Devpost draft](https://devpost.com/software/visualguard-two-views-one-next-step)

## Finalization checklist

- [ ] Recheck the deadline and required fields on the live Devpost page.
- [ ] Verify the public repository branch and CI checks.
- [x] Public AWS judge UI was deployed by an owner-authorized actor and anonymously read back; do not redeploy or expand permissions without fresh scope.
- [ ] Watch the full video against the four required items: team, working application, architecture, and principal results.
- [x] Confirm the public submission links point to the intended feature branch and no-login judge page.
- [x] Owner submitted the entry; anonymous public readback shows the competition association.

This documentation update records the existing anonymous AWS and submission readbacks only; it does not change AWS configuration, run inference, or consume the shared quota.
