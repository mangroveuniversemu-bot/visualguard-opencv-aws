# Replay ledger witness algorithm migration negative control

## Contract

- Witness version 3 signs a non-negative `key_epoch` in addition to the v2
  application, purpose, ledger, environment and signature-algorithm domain.
- The first accepted v3 append persists exactly one active
  `(signature_algorithm, key_id, key_epoch)` policy in SQLite.
- `migrate_algorithm` is a compare-and-swap transition. It updates the active
  policy and the domain algorithm inside one `BEGIN IMMEDIATE` transaction,
  sharing the serialization boundary used by witness append and revocation.
- A v2 attestation cannot downgrade a store after policy initialization.
- An old algorithm/key epoch cannot replay after migration and SQLite restart.

## Fresh execution

- Targeted migration tests: 5 passed.
- Witness compatibility: 31 passed plus 5 subtests.
- OpenCV path: 120 passed plus 47 subtests, using OpenCV 5.0.0 from
  `opencv-python-headless==5.0.0.93`.
- Scoped branch suite: 151 passed plus 52 subtests.
- Ruff check, Ruff format check, compileall and synthetic demo: PASS.
- Seed: NONE.

The replayable probe persisted SHA-512/key epoch 1, reopened the SQLite file,
rejected the SHA-256/key epoch 0 witness with
`REPLAY_LEDGER_WITNESS_ALGORITHM_POLICY_MISMATCH`, rejected the v2 downgrade
with `REPLAY_LEDGER_WITNESS_ALGORITHM_MIGRATION_REQUIRED`, and accepted the
new policy. A concurrent old append and migration serialized to the new final
policy; the losing old append returned the policy-mismatch code in the retained
probe. The alternate permitted ordering is that the old replay commits before
the migration, after which the migration still becomes the sole active policy.

## Retained falsifier

An unscoped `pytest -q` against the local staging directory failed collection
because the preserved `CHECK094_PACKAGE` contains a second file with the same
test-module basename. That package directory is not in the Git branch. The
authoritative source-tree command `pytest -q tests` passed 151 tests plus 52
subtests.

## Limits

HMAC SHA-256/SHA-512 are same-host shared-secret fixtures. External witness,
asymmetric signing, managed KMS, AWS, camera, physical disk, distributed
multi-writer ordering and physical action were NOT_RUN.
