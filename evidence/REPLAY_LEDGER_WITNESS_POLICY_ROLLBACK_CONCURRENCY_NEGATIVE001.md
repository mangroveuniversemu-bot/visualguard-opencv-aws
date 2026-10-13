# Replay ledger witness-policy rollback concurrency negative control

## Contract

- Witness version 4 signs a non-negative `migration_epoch` alongside the v3
  algorithm/key epoch and the existing witness domain.
- Existing algorithm-policy rows are deterministically upgraded to migration
  epoch 0. The epoch is durable SQLite state, not process memory.
- `migrate_algorithm` compares the complete current policy and advances the
  migration epoch by exactly one inside `BEGIN IMMEDIATE`.
- A rollback (`replacement_migration_epoch <= current`) and an epoch gap fail
  closed without changing the active policy.
- After the first migration, unsigned-epoch v3 and stale/future v4 witnesses
  cannot append, including after SQLite restart.
- Append and rollback use the same SQLite writer serialization boundary, so
  the retained race has one authoritative terminal policy.

## Fresh execution

- Targeted rollback plus adjacent migration tests: 11 passed.
- Scoped source-tree suite: 157 passed plus 52 subtests.
- OpenCV: 5.0.0 (`opencv-python-headless==5.0.0.93`).
- NumPy: 2.5.3; pytest: 9.0.2; Ruff: 0.14.13; SQLite: 3.53.1.
- Seed: NONE.

The replayable rollback probe upgraded the old schema to epoch 0, migrated to
SHA-512/key epoch 1/migration epoch 1, rejected a CAS rollback with
`REPLAY_LEDGER_WITNESS_POLICY_ROLLBACK`, and after restart rejected a correctly
signed active-key witness carrying epoch 0 with
`REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_STALE`. In the concurrent case, the
epoch-1 append committed and the rollback failed; restart retained exactly one
terminal policy `(HMAC-SHA512, fixture-hmac-sha512-epoch-1, 1, 1)` and two
attestations (bootstrap plus current epoch).

## Commands

```text
python -m pytest -q tests/test_external_witness_algorithm_migration.py tests/test_external_witness_policy_rollback.py
python -m pytest -q
python ops/replay_ledger_witness_algorithm_migration_negative.py
python ops/replay_ledger_witness_policy_rollback_negative.py
ruff check <changed Python files>
ruff format --check <changed Python files>
python -m compileall -q vision tests ops run_demo.py
python run_demo.py
```

## Limits

HMAC SHA-256/SHA-512 are same-host shared-secret fixtures. Live external
witness, asymmetric signing, managed KMS, AWS runtime, camera, physical disk,
distributed multi-writer ordering and physical action were NOT_RUN.
