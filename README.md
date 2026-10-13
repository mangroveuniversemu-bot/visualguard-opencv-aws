# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut adds an authoritative trust-root-set snapshot and
monotonic epoch. A compare-and-swap rotation must name the complete non-empty
provider/key identity set, match the current epoch, and advance exactly one
epoch under the same `BEGIN IMMEDIATE` lock as witness append. Exact committed
retries are idempotent; stale writers, gaps, no-op advances, epoch rollback,
and reactivation of any historical snapshot fail closed across restart. Once
initialized, the signed witness must bind the current root epoch and its
provider/key identity must be in the active set. Competing append/rotation
updates therefore have only serial outcomes. HMAC remains a deterministic
local fixture and does not prove an independent trust domain.

## Reproduce

```bash
python -m pip install -r requirements-vision.txt pytest==9.0.2 ruff==0.14.13
python -m pytest -q tests/test_external_witness_revocation_epoch.py
python -m pytest -q tests/test_external_witness_domain_separation.py
python -m pytest -q tests/test_external_witness_algorithm_migration.py
python -m pytest -q tests/test_external_witness_policy_rollback.py
python -m pytest -q tests/test_external_witness_revocation_list_epoch.py
python -m pytest -q tests/test_external_witness_trust_root_set_epoch.py
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
python ops/replay_ledger_witness_trust_root_set_epoch_negative.py
python run_demo.py
```

Fresh local results on 2026-10-14: trust-root-set targeted tests 10/10 plus 3
subtests; scoped branch full suite 175/175 plus 58 subtests; changed-file Ruff,
format check, compileall, synthetic demo and the replayable
epoch/rollback/restart/race probe PASS. See
`evidence/REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_EPOCH_ROLLBACK_CONCURRENCY_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK106,
  `REPLAY_LEDGER_WITNESS_REVOCATION_LIST_EPOCH_ROLLBACK_CONCURRENCY_NEGATIVE001`.
- Parent Drive artifact SHA-256:
  `63be074318cc6df51f3449e30109d69e35887990516c2e12da88fd58e2961618`.
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

