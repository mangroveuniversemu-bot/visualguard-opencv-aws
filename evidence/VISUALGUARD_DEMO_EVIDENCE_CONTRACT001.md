# VisualGuard demo evidence contract

This bounded submission asset defines a six-segment, 180-second demo plan. It
is **PREPARED_NOT_RECORDED**. The plan binds the OpenCV 5 synthetic replay and
the blocked AWS read-only preflight by SHA-256 so evidence drift cannot be
silently presented.

The executable verifier rejects a missing segment, duration overrun, path
escape, artifact digest drift, incomplete eight-case matrix, physical-action
claim, recorded-video claim, or any upgrade of the current AWS/camera state.
The accepted disclosure remains: OpenCV 5 fixed-array replay executed locally;
AWS API, deployment, endpoint, live camera, and physical action are
`NOT_RUN`/`NOT_DEPLOYED`/`NONE`.

Reproduce with:

    python ops/verify_demo_evidence_contract.py
    python -m pytest -q tests/test_demo_evidence_contract.py

Passing this contract proves only that the prepared demo script is internally
consistent with the bound repository evidence. It does not prove that a video
was recorded, that a camera or AWS resource was used, that sources are
authentic, or that field accuracy is adequate.
