# VisualGuard judge evidence index

Status: `VERIFIED_INDEX_VIDEO_NOT_RECORDED`

This page is a navigation layer over immutable evidence already checked into this branch. It does not run AWS, redeploy Lambda, create a public endpoint, or claim a completed video.

## What the evidence establishes

| Evidence surface | Established | Boundary |
| --- | --- | --- |
| Private AWS Lambda | OpenCV 5.0.0 health returned HTTP 200; alarm returned `STOP / HOLD_AUTOMATION`; clear input returned `REVIEW / QUEUE_HUMAN_REVIEW`; empty views returned `REQUEST_VIEW / REQUEST_NEW_CAPTURE` | Synthetic inputs only; Function URL remained `AWS_IAM`; no field-accuracy claim |
| CloudWatch | Three REPORT records plus the supplemental negative-control Request ID are bound to the AWS receipt | Not a public endpoint or live-camera receipt |
| Local OpenCV replay | Eight fixed negative-control cases cover alarm, calibration drift, consequence mismatch, missing/occluded/stale input, version drift, and the clear review path | `SYNTHETIC_REPLAY`; source match is not source truth |
| Demo packet | Six credential-safe segments total 180 seconds and expose only bounded identifiers | Recording and independent review remain `NOT_RUN` |
| Final-video gate | Verification fails closed while final bytes and two distinct human receipts are absent | `PREPARED_NOT_RECORDED / PREPARED_NOT_REVIEWED` |

## Verify locally

```bash
python ops/verify_judge_evidence_index.py
python -m pytest -q tests/test_judge_evidence_index.py
```

The verifier recomputes six artifact SHA-256 digests and rejects missing artifacts, identifier drift, unsafe claim upgrades, false reserved-concurrency claims, and premature video/reviewer completion.

## Exact next gate

Record the six existing storyboard segments, bind the exact video bytes in a completed operator receipt, obtain a distinct reviewer receipt, and run:

```bash
python ops/verify_final_demo_video_evidence.py \
  --video <final-video> \
  --operator-receipt <completed-operator-receipt.json> \
  --reviewer-receipt <completed-reviewer-receipt.json>
```

Until that succeeds, live camera, field accuracy, public access, physical action, final video, and competition submission are not established.
