# DOT handoff

Repository: `mangroveuniversemu-bot/visualguard-opencv-aws`

Stage: **SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on
`codex/witness-revocation-epoch-20261013`. AWS, live camera, independent
witness, recorded video, and physical action remain **NOT_RUN**.

## Current bounded cut

`VISUALGUARD_DEMO_VIDEO_FINAL_BYTES_BINDING_GATE001`

- Parent portfolio checkpoint: CHECK135.
- Parent lane checkpoint: CHECK133.
- Parent commit: `244b4e620a7e7672bd08c2b90fafd507ca35760b`.
- IP classification: `DERIVED`.
- Evidence modes: `SYNTHETIC_REPLAY` and `AWS_READ_ONLY_PREFLIGHT`.

The new executable gate retains that contract and additionally binds exact
final video bytes, byte size, real-media duration, per-segment observations,
and a distinct reviewer's receipt. It rejects missing/substituted video,
duration overrun, incomplete observation, AWS/camera/deployment overclaim,
same-person review, and review digest drift.

## Fresh local evidence

- final-video gate targeted tests: PASS 8/8;
- scoped branch full suite: PASS 214/214 plus 66 subtests;
- changed-file Ruff format/lint and compileall: PASS;
- underlying contract verifier: PASS; 180 seconds, 6 segments, 2 bound
  artifacts; manifest SHA-256:
  `fdf2ac2eba921b5aad52829dee632bb0062fd7c66b1025125e8eb6d5de377fb2`;
- actual missing-video probe: `BLOCKED`, reason `VIDEO_MISSING`, exit 2;
- hosted GitHub Actions run `38654945975`, job `116162376099`: PASS at
  functional commit `9051a943b3f40a4e3a7e57cc86213d39f701448a`;
- AWS API, deployment, endpoint, camera, recorded video, and physical action:
  **NOT_RUN** / **NOT_DEPLOYED** / **PREPARED_NOT_RECORDED** / **NONE**.

## Unknowns, blockers, and resume condition

The gate is executable but no video or independent review exists. Its current
result is intentionally blocked, not a video PASS. It does not establish field
accuracy, source authenticity, live camera, AWS integration, or safe actuation.
AWS remains blocked on owner-authorized identity, region/account/role, cost
scope, immutable artifact binding, and the read-only preflight.

## Exact next action

Record the bounded six-segment demo only through a human-controlled process,
complete the operator receipt, obtain a distinct reviewer receipt, and run
`ops/verify_final_demo_video_evidence.py` against the exact final bytes. Until
that succeeds, retain `PREPARED_NOT_RECORDED` / `PREPARED_NOT_REVIEWED` and all
AWS/camera/deployment `NOT_RUN` fields. If no recording/reviewer is available,
rotate to the next portfolio lane rather than manufacture evidence.
