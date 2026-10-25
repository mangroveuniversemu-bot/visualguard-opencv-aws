# DOT handoff

Repository: `mangroveuniversemu-bot/visualguard-opencv-aws`

Stage: **PRIVATE_AWS_SYNTHETIC_EXECUTION_VERIFIED** on
`claude/practical-ride-st6n28`. The bounded AWS deployment already occurred at
source commit `832b1b476ce88e3fa95e83ac5749f64af0f4bd63`; do not redeploy under
the expired one-time US$1 allowance.

## Current bounded cut

`VISUALGUARD_AWS_DEMO_CAPTURE_PACKET002`

- Parent checkpoint: CHECK141.
- Parent HEAD: `d3034ba6a0945210a5a24cbe3609f174d8901fd4`.
- IP classification: `DERIVED`.
- Evidence class: `AWS_PRIVATE_LAMBDA_SYNTHETIC_INPUT`.
- Recording and independent review: `NOT_RUN`.

The capture packet binds contract v002 and the sanitized AWS execution JSON by
SHA-256, limits capture to local repository surfaces, requires all six
disclosure overlays, and rejects credential/account-ID patterns, public
endpoint upgrades, reserved-concurrency overclaims, digest drift and segment
reordering. Receipt templates now use schema v2, matching the final-video
verifier.

## Evidence boundaries

Proved: private AWS_IAM Lambda synthetic-input execution, OpenCV 5 health,
alarm, clear and missing-view outcomes, three CloudWatch REPORT lines and the
supplemental RequestId.

Not proved: live camera, field accuracy, public availability, physical action,
recorded video, independent review or competition submission. Reserved
concurrency was unavailable for the account and is not configured.

## Exact next action

A human operator records the 180-second six-segment video from local repository
surfaces only, fills the schema-v2 operator receipt, and gives the exact same
video bytes to a distinct reviewer. Then run
`ops/verify_final_demo_video_evidence.py`. Any public endpoint, additional AWS
spend, submission or merge still requires separate owner authorization.
