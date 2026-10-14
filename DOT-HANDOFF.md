# DOT handoff

Repository: `mangroveuniversemu-bot/visualguard-opencv-aws`

Stage: **SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on
`codex/witness-revocation-epoch-20261013`. AWS, live camera, independent
witness, and physical action remain **NOT_RUN**.

## Current bounded cut

`VISUALGUARD_JUDGING_GAP_NEGATIVE_CONTROLS001`

- Parent checkpoint: CHECK123.
- Parent commit: `375a860815b64340bdebbb04fd54bc946bcf3be5`.
- IP classification: `DERIVED`.
- Evidence mode: `SYNTHETIC_REPLAY`.

The replayable matrix runs eight fixed-array OpenCV controls and converts each
inspection result into a bounded follow-up plan. Clear evidence queues human
review; missing or occluded views request a new capture; alarm, stale capture,
calibration drift, dependency drift, and consequence mismatch hold automation.
Every row records `action_executed=false` and `physical_action=NONE`.

## Fresh evidence

- judging-matrix targeted tests: PASS 5/5;
- matrix plus OpenCV regression slice: PASS 125/125 plus 55 subtests;
- scoped branch full suite: PASS 193/193 plus 66 subtests;
- changed-file Ruff and format check: PASS;
- compileall and replayable eight-case matrix probe: PASS execution;
- OpenCV output changes the planned downstream workflow action: demonstrated
  locally; external action execution: **NONE**.

## Blockers and resume condition

Authorized AWS identity, selected region/cost scope, live camera input, and an
independently administered monotonic or immutable witness remain unavailable.
The matrix is deterministic local evidence, not a field-accuracy or deployment
claim.

## Exact next action

Run the complete branch suite, publish the verified commit and checkpoint, then
rotate to PayPal unless a newer canonical checkpoint changes routing.
