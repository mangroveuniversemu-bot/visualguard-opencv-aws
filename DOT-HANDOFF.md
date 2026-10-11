# DOT handoff

Repository: `mangroveuniversemu-bot/visualguard-opencv-aws`

Stage: **SOURCE_IMPORT_PENDING**. Target: **AWS**.

## Required inputs

- Complete CHECK076 source archive and dependencies
- AWS programmatic identity with scoped deployment/runtime permissions
- Selected AWS region and an agreed resource/cost scope
- Substantive OpenCV 5 analysis and a meaningful component actually running on AWS

## Ordered work

1. Recover and verify the CHECK076 source package.
2. Import code, dependencies and source manifest on a branch.
3. Run the existing checks and record the exact commit and input provenance.
4. Deploy the smallest meaningful AWS component after access and resource scope are ready.
5. Capture normal, warning and missing-view/request-more-images cases with AWS execution logs.

## Completion report

- Source package provenance and exact imported commit.
- Exact build/run commands and relevant existing checks with actual results.
- Deployment destination, revision and working endpoint or build access.
- Real execution evidence, remaining blocker and next action.

This initial GitHub setup does not restart a schedule and does not constitute cloud deployment or a submitted entry.

## Recovered source package — review required

`visualguard-check076-source.zip` contains 65 VisualGuard files copied without modification from the downloaded CHECK076 archive, plus provenance manifests. Original archive SHA-256: `13cf2f2a9af99f0f2ff6ac875451b6452baacc68434213c899bdf3017bbb6978`. Selected bundle SHA-256: `796b7eee335e4d75364b15d2278b8f52ac5d40323b95ab09ad293514944aaf5b`. Of 235 original manifest entries, 6 do not match the archive bytes, including the vision implementation and its tests. Source acceptance remains **REVIEW_REQUIRED**; tests have not been rerun.

[Original CHECK076 Drive archive](https://drive.google.com/file/d/13n98bPRr7Dt-8b980T3ygdQNR93JQcYh/view). Reconcile these mismatches against the canonical checkpoint before accepting, testing or deploying the source. `SOURCE-COPY-MANIFEST.json` verifies the copied bytes only; it does not resolve the original mismatch. The archive excludes other competition implementations.
