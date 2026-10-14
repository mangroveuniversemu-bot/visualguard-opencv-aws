# VisualGuard final video evidence binding gate

This gate accepts a final demo only when all of the following refer to the
same bytes:

- `ffprobe` finds a real video stream no longer than 180 seconds;
- the video SHA-256 and byte size match the operator receipt;
- the checked-in demo contract SHA-256 matches the operator receipt;
- all six contract segments are observed on a contiguous timeline;
- a distinct reviewer attests to the same video, contract, segment sequence,
  and bounded claim disclosures.

The accepted claim boundary remains `SYNTHETIC_REPLAY`: fixed synthetic arrays
run through OpenCV 5. Live camera, AWS API, AWS deployment, field accuracy,
source authenticity, physical action, and credential exposure are not claimed.
The blocked AWS preflight is disclosure evidence, not AWS execution evidence.

Prepared templates intentionally fail until a real final video and independent
review exist. Run:

```bash
python ops/verify_final_demo_video_evidence.py \
  --video .local/final-demo.mp4 \
  --receipt .local/final-demo-receipt.json \
  --review .local/final-demo-review.json
```

Expected current result: `BLOCKED` with `VIDEO_MISSING`. Do not change
`PREPARED_NOT_RECORDED` or any `NOT_RUN` field from template-only evidence.
