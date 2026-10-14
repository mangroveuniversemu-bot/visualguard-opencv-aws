# Trust-root-set abort/restart atomicity negative control

## Claim under test

A failed trust-root-set rotation must not leave the active root rows, epoch
record, or append-only root-history ledger in different logical versions. A
restart must observe the complete pre-rotation snapshot, and removing the
injected failure must permit exactly one normal epoch advance.

## Failure boundary

The deterministic SQLite trigger aborts the state-row UPDATE after the
transaction has already issued DELETE/INSERT mutations for the active root
rows and before COMMIT. This exercises rollback of a partially executed SQL
transaction; it is not a simulated exception before persistence work.

## Fresh acceptance result

- targeted tests: PASS 3/3;
- scoped full suite: PASS 178/178 plus 58 subtests;
- changed-file Ruff and format check: PASS;
- compileall, synthetic demo and replayable probe: PASS;
- repository-wide Ruff: BASELINE_FAIL, four pre-existing E402/E702 findings
  outside this cut's changed files.

The probe observed the exact injected error, byte-equivalent logical snapshots
before and after abort, epoch 1 after restart, an accepted epoch-1 append, one
successful retry to epoch 2, history epochs 0/1/2, rejection of the removed
root, and SQLite quick_check=ok.

## Reproduce

    python -m pytest -q tests/test_external_witness_trust_root_set_atomicity.py
    python -m pytest -q
    python ops/replay_ledger_witness_trust_root_set_abort_restart_atomicity_negative.py

## Scope

Evidence mode is LOCAL_DETERMINISTIC_HMAC_SQLITE_FIXTURE; IP classification is
DERIVED. This does not demonstrate a real independently administered witness,
process kill or physical disk/power failure, distributed writers, AWS
deployment, camera input, or physical action.
