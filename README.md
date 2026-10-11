# VisualGuard — OpenCV 5 on AWS

Private GitHub preparation repository for **OpenCV AI Competition 2026, powered by AWS**.

## Current status

**SOURCE_IMPORT_PENDING** — repository setup only; application deployment has not been completed.

User-reported historical CHECK076: 119 OpenCV checks and 179 full-suite checks; synthetic inputs only. This repository has not reproduced those results.

## Source provenance

Recover the complete CHECK076 source archive and manifest. Do not transplant EvidencePilot or Nebius as VisualGuard.

No working application is included in this initial preparation commit. Do not treat the existence of this repository as successful runtime, CI or cloud evidence.

## Target platform

AWS

## Before execution

- Complete CHECK076 source archive and dependencies
- AWS programmatic identity with scoped deployment/runtime permissions
- Selected AWS region and an agreed resource/cost scope
- Substantive OpenCV 5 analysis and a meaningful component actually running on AWS

## DOT next steps

1. Recover and verify the CHECK076 source package.
2. Import code, dependencies and source manifest on a branch.
3. Run the existing checks and record the exact commit and input provenance.
4. Deploy the smallest meaningful AWS component after access and resource scope are ready.
5. Capture normal, warning and missing-view/request-more-images cases with AWS execution logs.

See `DOT-HANDOFF.md` and `deployment.json` for the current handoff. `.env.example` contains empty configuration placeholders only. Supply credentials through an authorized execution environment; do not commit them.

## Competition reference

[Official competition requirements](https://opencv26.devpost.com/)

Repository creation does not register or submit an entry. Publication and platform eligibility are separate steps.

## Recovered source package — review required

`visualguard-check076-source.zip` contains 65 VisualGuard files copied without modification from the downloaded CHECK076 archive, plus provenance manifests. Original archive SHA-256: `13cf2f2a9af99f0f2ff6ac875451b6452baacc68434213c899bdf3017bbb6978`. Selected bundle SHA-256: `796b7eee335e4d75364b15d2278b8f52ac5d40323b95ab09ad293514944aaf5b`. Of 235 original manifest entries, 6 do not match the archive bytes, including the vision implementation and its tests. Source acceptance remains **REVIEW_REQUIRED**; tests have not been rerun.

[Original CHECK076 Drive archive](https://drive.google.com/file/d/13n98bPRr7Dt-8b980T3ygdQNR93JQcYh/view). Reconcile these mismatches against the canonical checkpoint before accepting, testing or deploying the source. `SOURCE-COPY-MANIFEST.json` verifies the copied bytes only; it does not resolve the original mismatch. The archive excludes other competition implementations.
