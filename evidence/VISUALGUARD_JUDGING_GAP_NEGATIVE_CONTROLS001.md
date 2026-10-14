# VisualGuard judging-gap negative controls

## Claim under test

The real OpenCV 5 path changes a later workflow decision across normal,
warning, evidence-quality, version-drift, and consequence-mismatch cases.

## Implementation

`plan_follow_up` is a pure, non-executing adapter over inspection and optional
consequence evidence. The replayable matrix covers:

1. clear views -> `QUEUE_HUMAN_REVIEW`;
2. alarm -> `HOLD_AUTOMATION`;
3. missing view -> `REQUEST_NEW_CAPTURE`;
4. occluded view -> `REQUEST_NEW_CAPTURE`;
5. stale capture -> `HOLD_AUTOMATION`;
6. calibration drift -> `HOLD_AUTOMATION`;
7. package-version drift -> `HOLD_AUTOMATION`; and
8. consequence mismatch -> `HOLD_AUTOMATION`.

Malformed inspection or consequence evidence also fails closed. No matrix row
performs an external or physical action.

## Fresh acceptance result

- targeted judging-matrix tests: PASS 5/5;
- matrix plus OpenCV regression slice: PASS 125/125 plus 55 subtests;
- scoped branch full suite: PASS 193/193 plus 66 subtests;
- changed-file Ruff and format check: PASS;
- compileall and replayable probe: PASS execution;
- probe SHA-256:
  `636e95a34888d11e6a9133dcf8ff071170487a369e613b4d59ddda5267bdf40d`.

## Reproduce

    python -m pytest -q tests/test_judging_negative_control_matrix.py
    python -m pytest -q tests/test_opencv5_inspection.py
    python ops/opencv5_judging_negative_control_matrix.py

## Scope

Evidence mode is `SYNTHETIC_REPLAY`; provenance is `DERIVED`; inputs are fixed
synthetic arrays; seed is `NONE`. Runtime evidence records OpenCV 5.0.0 and
`opencv-python-headless` 5.0.0.93. AWS, live camera, live endpoint, and physical
action are `NOT_RUN`/`NONE`. This matrix does not establish field accuracy,
source authenticity, AWS integration, or safe autonomous actuation.
