# Trust-root history external-anchor co-rollback falsifier

## Claim under test

A checkpoint stored outside SQLite can detect rollback only while the supplied
checkpoint is fresher than, and independently protected from, the database.

## Implementation

`CaptureReplayWitnessRevocationStore` now exports a versioned checkpoint that
binds the trust-root epoch, root-set SHA-256, and history-chain head. The
verification API fails closed on malformed or non-matching checkpoints. The
replayable probe snapshots epoch one, advances to epoch two, and evaluates:

1. epoch-one SQLite plus the epoch-two checkpoint;
2. epoch-two SQLite plus the epoch-one checkpoint; and
3. epoch-one SQLite plus the matching epoch-one checkpoint.

## Fresh acceptance result

- targeted external-anchor tests: PASS 5/5;
- trust-root regression slice: PASS 23/23 plus 3 subtests;
- scoped full suite: PASS 188/188 plus 58 subtests;
- changed-file Ruff and format check: PASS;
- compileall, synthetic demo, and replayable probe: PASS execution.

Both one-sided rollback cases return
`REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_ANCHOR_MISMATCH`. The coordinated
rollback case has SQLite `quick_check=ok` and returns
`ACCEPTED_MATCHING_PAIR`. That acceptance is the expected falsifier: a
colocated file checkpoint does not supply independent freshness.

## Reproduce

    python -m pytest -q tests/test_external_witness_trust_root_history_external_anchor.py
    python -m pytest -q
    python ops/replay_ledger_witness_trust_root_history_external_anchor_co_rollback_falsifier.py

## Scope

Evidence mode is `LOCAL_FILE_ANCHOR_FIXTURE`; IP classification is `DERIVED`.
Live external witness, asymmetric signing, managed KMS, AWS, camera, physical
storage/power failure, distributed writers, and physical action are `NOT_RUN`.
Checkpoint equality does not authenticate the source, resist an attacker who
controls both stores, or prove pre-migration truth.
