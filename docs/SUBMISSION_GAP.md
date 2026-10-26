# VisualGuard submission readiness

Snapshot: 2026-10-27 (Asia/Taipei). This file tracks evidence and remaining judge-access gates; it does not claim the project has been submitted.

**Project:** VisualGuard — Two Views. One Next Step.  
**Solo team display name:** YOUNG-FU  
**Current submission state:** Devpost draft; not submitted.  
**Current code branch:** claude/practical-ride-st6n28. The repository is still private while GitHub requires the owner to re-authenticate before changing visibility.

## Deadline and official requirements

The [competition overview](https://opencv26.devpost.com/) and [rules](https://opencv26.devpost.com/rules) show a deadline of October 26, 2026 at 11:45 p.m. PDT in the page header. The overview body says 11:59 p.m. Pacific Time, a 14-minute difference. Use the earlier cutoff: October 27 at 14:45 Taiwan time. Recheck the live Devpost page immediately before submission.

The official final-entry checklist asks for a technical report; a public or private judge-accessible repository/archive; pinned dependencies and build, deployment, and test instructions; an architecture diagram; a working web endpoint or arranged live screen-share; a public or unlisted video no longer than five minutes showing the team, working application, architecture, and principal results; and appropriate evaluation evidence with failures or limitations.

## Current readiness

| Requirement | Evidence now | Remaining gate |
|---|---|---|
| OpenCV 5 image analysis | Full-frame two-view quality checks and red-indicator detection are documented in README and TECHNICAL_REPORT.md. | Evaluation uses generated inputs; field accuracy is unverified. |
| AWS component | Private AWS_IAM Lambda in us-east-1. Four recorded health, alarm, clear, and missing-view invocations use synthetic or empty inputs. Evidence: evidence/AWS_EXECUTION_20261026_40223113044.json; workflow 40223113044; deployed source 832b1b4. | No public judge endpoint. Arrange judge access or a live screen-share; do not share AWS credentials. |
| Architecture | docs/ARCHITECTURE.md contains the system and workflow diagram. | Confirm the rendered diagram is visible in the judge’s browsing context. |
| Technical report | docs/TECHNICAL_REPORT.md describes the implementation, AWS execution, evaluation, failures, limits, and reproduction steps. | None for document presence; reviewer acceptance is not claimed. |
| Evaluation | 540 generated pairs; 94.26% exact-decision agreement. Known failure: 30/30 round red-sticker cases produced false STOP; one motion-blur case was misrouted. | Synthetic results only; no ground-truth factory or camera evaluation. |
| Dependencies and instructions | Pinned requirement files, Docker targets, deployment runbook, and reproduction commands are in the repository. | A fresh clean-machine install was not re-run during this documentation update. |
| Code access | The project is on claude/practical-ride-st6n28. Devpost permits a private repository if judges can access it. | Repo remains private. Owner-approved public visibility change is waiting on GitHub’s owner re-authentication, or arrange another judge-access route. |
| Demo video | Public 2:20 owner-review film: https://youtu.be/AEDHXknTBy8. | Before submission, verify the actual film visibly covers the solo team, working app, architecture, and principal results. It is not independently reviewed or bound to the older CHECK146 video contract. |
| Live demonstration | Local HTTP viewer and private IAM-protected Lambda are available. | No public endpoint; arrange a screen-share or judge access before the deadline. |
| Devpost entry | Draft project: https://devpost.com/software/visualguard-two-views-one-next-step. Title, story, diagram, repository link, video, and tags have been prepared. | Final form review and submission are reserved for the owner. |
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
- [ ] Resolve judge access to the private repository and private AWS demo, either through owner-approved access or an arranged screen-share.
- [ ] Watch the full video against the four required items: team, working application, architecture, and principal results.
- [ ] Confirm the final draft links point to the intended branch, evidence, and video.
- [ ] Owner reviews the final form and submits it.

No code, AWS configuration, or main branch was changed as part of this readiness update.
