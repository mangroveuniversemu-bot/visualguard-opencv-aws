# VisualGuard private-AWS demo capture packet

Status: **PREPARED_NOT_RECORDED**. This packet does not authorize another AWS
deployment, Lambda invocation, public URL, submission, or expenditure.

Record only checked-in repository evidence and local replay outputs. Do not
record the AWS Console. The packet binds the completed private Lambda evidence
while keeping live camera, field accuracy, public availability and physical
action outside the claim.

## Before recording

1. Run `python ops/verify_demo_capture_packet.py`. It must return `PASS`,
   `secret_patterns_detected=0`, `recording=NOT_RUN`, and
   `independent_review=NOT_RUN`.
2. Close AWS Console tabs, browser developer tools, password managers and
   terminals containing environment values. Do not show account headers, role
   ARNs, cookies, signed URLs, request headers or `.env` values.
3. Record only a local render of the capture packet, local replay, and the
   sanitized AWS evidence. Keep the required overlay visible for each segment.
4. Use the six segments in packet order. Their durations total exactly 180
   seconds. Do not upgrade the bounded claim.

## After recording

Copy the operator template outside the repository, fill the real video digest,
byte size, `ffprobe` duration, opaque operator ID and six observed time ranges,
then set status to `RECORDED`. A different human reviews the exact same bytes,
fills the reviewer template with a distinct opaque ID and all six segment IDs,
then sets status to `INDEPENDENT_REVIEWED`.

Run:

    python ops/verify_final_demo_video_evidence.py \
      --video .local/final-demo.mp4 \
      --receipt .local/final-demo-receipt.json \
      --review .local/final-demo-review.json

Passing proves byte identity, bounded claims and distinct review. It does not
prove source authenticity, field accuracy, live camera use, public
availability, physical action or competition submission.

## Immediate falsifiers

- credential-like content or a 12-digit account ID in the packet;
- recording an AWS account header, role switcher, network header or signed URL;
- claiming reserved concurrency, public access, live camera, field accuracy or
  executed action;
- missing overlays, reordered segments, digest drift or same-person review;
- any final video byte that differs from the reviewed digest.
