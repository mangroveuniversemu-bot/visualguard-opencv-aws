# DOT handoff

Repository: `mangroveuniversemu-bot/visualguard-opencv-aws`

Stage: **SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on
`codex/witness-revocation-epoch-20261013`. AWS, live camera, independent
witness, and physical action remain **NOT_RUN**.

## Current bounded cut

`REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_EXTERNAL_ANCHOR_CO_ROLLBACK_FALSIFIER_NEGATIVE001`

- Parent checkpoint: CHECK119.
- Parent commit: `9df8063cbd37b92748333ddf1bbad9a4c647bab4`.
- IP classification: `DERIVED`.
- Evidence mode: `LOCAL_FILE_ANCHOR_FIXTURE`.

The store now exports and verifies a versioned trust-root-history checkpoint.
The latest checkpoint rejects an older database and an older checkpoint rejects
a newer database. The bounded falsifier also proves that rolling back the
SQLite history and colocated checkpoint together yields
`ACCEPTED_MATCHING_PAIR`. This is a valuable claim boundary, not live external
witness evidence.

## Fresh evidence

- external-anchor targeted tests: PASS 5/5;
- trust-root regression slice: PASS 23/23 plus 3 subtests;
- scoped full suite: PASS 188/188 plus 58 subtests;
- changed-file Ruff and format check: PASS;
- compileall, synthetic demo, and replayable co-rollback probe: PASS execution;
- coordinated rollback resistance: **FALSIFIED** for a same-domain file anchor.

## Blockers and resume condition

Authorized AWS identity, selected region/cost scope, and an independently
administered monotonic or immutable witness remain unavailable. Resume live
validation only when those inputs are authorized. Do not treat local checkpoint
equality, HMAC fixtures, or SQLite `quick_check=ok` as source authenticity.

## Exact next action

Rotate to
`PAYPAL_PROVIDER_EVIDENCE_TRUST_ROOT_HISTORY_EXTERNAL_ANCHOR_CO_ROLLBACK_FALSIFIER_NEGATIVE001`
unless a higher-priority fresh canonical checkpoint changes routing.
