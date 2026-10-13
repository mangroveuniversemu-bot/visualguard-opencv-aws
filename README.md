# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut turns the persisted revoked-key rows into an explicit
monotonic revocation-list snapshot. A compare-and-swap update must name the
complete list, match the current epoch, add at least one identity, preserve
every prior revocation, and advance exactly one epoch under the same
`BEGIN IMMEDIATE` lock as append. Exact committed retries are idempotent;
rollback, removal, epoch gaps, no-op advances and stale competing writers fail
closed across restart. Competing append/revocation updates therefore have only
two serial outcomes: the append commits before revocation, or its old epoch is
rejected. HMAC remains a deterministic local fixture and does not prove an
independent trust domain.

## Reproduce

```bash
python -m pip install -r requirements-vision.txt pytest==9.0.2 ruff==0.14.13
python -m pytest -q tests/test_external_witness_revocation_epoch.py
python -m pytest -q tests/test_external_witness_domain_separation.py
python -m pytest -q tests/test_external_witness_algorithm_migration.py
python -m pytest -q tests/test_external_witness_policy_rollback.py
python -m pytest -q tests/test_external_witness_revocation_list_epoch.py
python -m pytest -q tests/test_external_witness_authenticity.py \
  tests/test_external_witness_key_rotation.py \
  tests/test_external_witness_revocation_epoch.py \
  tests/test_external_witness_domain_separation.py \
  tests/test_external_witness_algorithm_migration.py
python -m pytest -q tests/test_opencv5_inspection.py
python -m pytest -q
python ops/replay_ledger_witness_domain_separation_negative.py
python ops/replay_ledger_witness_algorithm_migration_negative.py
python ops/replay_ledger_witness_policy_rollback_negative.py
python ops/replay_ledger_witness_revocation_epoch_negative.py
python ops/replay_ledger_witness_revocation_list_epoch_negative.py
python run_demo.py
```

Fresh local results on 2026-10-14: revocation-list targeted tests 8/8 plus 3
subtests; scoped branch full suite 165/165 plus 55 subtests; changed-file Ruff,
format check, compileall, synthetic demo and the replayable CAS/rollback/race
probe PASS. See
`evidence/REPLAY_LEDGER_WITNESS_REVOCATION_LIST_EPOCH_ROLLBACK_CONCURRENCY_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK102,
  `REPLAY_LEDGER_WITNESS_POLICY_ROLLBACK_CONCURRENCY_NEGATIVE001`.
- Parent Drive artifact SHA-256:
  `abf14cf296d000a13fa185b67011903646e396fa9bf49ba43aec8264bde7293e`.
- IP classification: `DERIVED`; no private patent algorithm, customer data, or
  another submission's implementation was imported.
- Live external witness, asymmetric signing, managed KMS, AWS runtime, camera,
  physical disk, distributed multi-writer ordering, and physical action are
  not demonstrated.

## Deployment gate

Do not treat source import or local tests as AWS deployment. Deployment still
requires an authorized AWS identity, selected region, cost scope, and an
independently administered witness/key-revocation channel. No public release,
submission, paid provisioning, or automatic merge is authorized here.

