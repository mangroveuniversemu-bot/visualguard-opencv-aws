# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut adds a monotonic witness-policy migration epoch. A v4
attestation signs `migration_epoch` alongside the v3 algorithm/key epoch and
existing witness domain. Existing SQLite policy rows are upgraded to epoch 0;
each compare-and-swap migration must advance exactly one epoch under the same
`BEGIN IMMEDIATE` lock as append. Once the epoch advances, v3, rollback and
stale/future-epoch attestations fail closed after restart. A competing current
append and rollback attempt serialize to one terminal epoch-1 policy. HMAC
SHA-256/SHA-512 remain deterministic local fixtures and do not prove an
independent trust domain.

## Reproduce

```bash
python -m pip install -r requirements-vision.txt pytest==9.0.2 ruff==0.14.13
python -m pytest -q tests/test_external_witness_revocation_epoch.py
python -m pytest -q tests/test_external_witness_domain_separation.py
python -m pytest -q tests/test_external_witness_algorithm_migration.py
python -m pytest -q tests/test_external_witness_policy_rollback.py
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
python run_demo.py
```

Fresh local results on 2026-10-13: rollback plus adjacent migration tests
11/11; scoped branch full suite 157/157 plus 52 subtests; changed-file Ruff,
format check, compileall, synthetic demo and both replayable migration probes
PASS. See
`evidence/REPLAY_LEDGER_WITNESS_POLICY_ROLLBACK_CONCURRENCY_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK098,
  `REPLAY_LEDGER_WITNESS_ALGORITHM_MIGRATION_NEGATIVE001`.
- Parent Drive artifact SHA-256:
  `52d766154dcb3556e3ee8aa25756ea7c992bd3d7800d424369459152d18cbd99`.
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

