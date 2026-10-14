# DOT handoff

Repository: `mangroveuniversemu-bot/visualguard-opencv-aws`

Stage: **SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on
`codex/witness-revocation-epoch-20261013`. AWS, live camera, independent
witness, recorded video, and physical action remain **NOT_RUN**.

## Current bounded cut

`VISUALGUARD_DEMO_EVIDENCE_CONTRACT001`

- Parent checkpoint: CHECK129.
- Parent commit: `135c07ee9f0110c9688c6cc6f4b8854e0b0a8679`.
- IP classification: `DERIVED`.
- Evidence modes: `SYNTHETIC_REPLAY` and `AWS_READ_ONLY_PREFLIGHT`.

The new executable contract binds the checked-in OpenCV 5 eight-case matrix
and blocked AWS preflight by SHA-256. It requires six demo segments totaling no
more than 180 seconds and rejects missing coverage, duration overrun, path
escape, digest drift, incomplete controls, physical-action claims, recorded
video claims, and any upgrade of AWS/camera evidence.

## Fresh evidence

- contract verifier: PASS; 180 seconds, 6 segments, 2 bound artifacts;
- demo-contract targeted tests: PASS 7/7;
- contract plus judging matrix and OpenCV regression slice: PASS 132/132 plus
  55 subtests;
- scoped branch full suite: PASS 206/206 plus 66 subtests;
- changed-file Ruff format/lint and compileall: PASS;
- hosted GitHub Actions run `38633479920`, job `116090670297`: PASS at
  `82b7d742a81df3b533438af3182f44febbfebd2e`;
- preserved falsifier: run `38633333775` failed before tests because the pip
  cache had no dependency-file path; commit `82b7d742...` bound it to
  `requirements-vision.txt`, after which every hosted step passed;
- manifest SHA-256:
  `fdf2ac2eba921b5aad52829dee632bb0062fd7c66b1025125e8eb6d5de377fb2`;
- AWS API, deployment, endpoint, camera, recorded video, and physical action:
  **NOT_RUN** / **NOT_DEPLOYED** / **PREPARED_NOT_RECORDED** / **NONE**.

## Unknowns, blockers, and resume condition

The contract proves internal consistency of a prepared script, not that a
video exists or that field accuracy, source authenticity, AWS integration, or
safe actuation is established. AWS remains blocked on owner-authorized
identity, region/account/role, cost scope, immutable artifact binding, and the
read-only preflight. A live-camera run and independently administered witness
are also unavailable.

## Exact next action

Rotate to PayPal. Resume this lane only for a human-controlled video
capture/review or when the authorized AWS configuration exists; preserve new
video/AWS evidence separately before changing any `NOT_RUN` claim.
