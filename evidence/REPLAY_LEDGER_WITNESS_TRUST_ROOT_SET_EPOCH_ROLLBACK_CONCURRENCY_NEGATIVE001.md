# Replay ledger witness trust-root-set epoch negative control

## Contract

- SQLite persists one authoritative trust-root-set epoch, the complete active
  provider/key identity set, and an append-only history of snapshot digests.
- `cas_update_trust_root_set` compares the expected epoch and complete
  replacement snapshot inside `BEGIN IMMEDIATE`.
- A valid rotation advances exactly one epoch and installs a non-empty set.
  The exact committed retry is idempotent.
- Epoch rollback, gaps, no-op advances, stale competing CAS writers, and
  reactivation of a historical snapshot fail closed without changing state.
- Once initialized, the witness signature binds `trust_root_epoch`; missing,
  stale and future epochs fail closed, as does a provider/key identity outside
  the active set.
- Verification and append share the SQLite writer boundary with rotation, so
  their winning order is serial and persists after restart.

## Fresh execution

- Targeted trust-root-set tests: 10 passed plus 3 subtests.
- Scoped source-tree suite: 175 passed plus 58 subtests.
- OpenCV: 5.0.0 (`opencv-python-headless==5.0.0.93`).
- Python: 3.12.14; SQLite: 3.53.1; NumPy: 2.5.3; pytest: 9.0.2;
  Ruff: 0.14.13.
- Seed: NONE.

The replayable probe initialized the old root at epoch 1 and raced its append
against rotation to a replacement root at epoch 2. This execution observed
rotation first, so the old append failed with
`REPLAY_LEDGER_WITNESS_TRUST_ROOT_EPOCH_STALE`. After restart, the replacement
root and epoch 2 remained authoritative, the removed root at the current epoch
failed with `REPLAY_LEDGER_WITNESS_TRUST_ROOT_UNKNOWN`, and attempting to
restore the epoch-1 snapshot under epoch 3 failed with
`REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_ROLLBACK`.

## Commands

```text
python -m pytest -q tests/test_external_witness_trust_root_set_epoch.py
python -m pytest -q
python ops/replay_ledger_witness_trust_root_set_epoch_negative.py
ruff check <changed Python files>
ruff format --check <changed Python files>
python -m compileall -q vision tests ops run_demo.py
python run_demo.py
```

## Retained limitations

The witness keys are same-host HMAC fixtures. Live external witness,
asymmetric signing, managed KMS, AWS runtime, camera, physical-disk crash
behavior, distributed multi-writer ordering and physical action were NOT_RUN.
Matching an active provider/key identity and epoch does not prove the external
administrator, key custody, or real-world source authenticity.
