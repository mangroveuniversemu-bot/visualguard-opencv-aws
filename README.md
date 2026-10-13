# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut adds versioned witness algorithm/key-epoch migration.
A v3 attestation signs `key_epoch` alongside the existing witness domain. The
first accepted v3 append persists the active signature algorithm, key ID and
key epoch in SQLite. A compare-and-swap migration updates that policy and the
signed store domain under the same `BEGIN IMMEDIATE` lock as append. After
restart, legacy v2 downgrade and cross-algorithm replay fail closed; a
competing old append and migration serialize to one final active policy. HMAC
SHA-256/SHA-512 remain deterministic local fixtures and do not prove an
independent trust domain.

## Reproduce

```bash
python -m pip install -r requirements-vision.txt pytest==9.0.2 ruff==0.14.13
python -m pytest -q tests/test_external_witness_revocation_epoch.py
python -m pytest -q tests/test_external_witness_domain_separation.py
python -m pytest -q tests/test_external_witness_algorithm_migration.py
python -m pytest -q tests/test_external_witness_authenticity.py \
  tests/test_external_witness_key_rotation.py \
  tests/test_external_witness_revocation_epoch.py \
  tests/test_external_witness_domain_separation.py \
  tests/test_external_witness_algorithm_migration.py
python -m pytest -q tests/test_opencv5_inspection.py
python -m pytest -q
python ops/replay_ledger_witness_domain_separation_negative.py
python ops/replay_ledger_witness_algorithm_migration_negative.py
python ops/replay_ledger_witness_revocation_epoch_negative.py
python run_demo.py
```

Fresh local results on 2026-10-13: algorithm migration 5/5; witness
compatibility 31/31 plus 5 subtests; OpenCV 120/120 plus 47 subtests; scoped
branch full suite 151/151 plus 52 subtests; changed-file Ruff, format check,
compileall and demo PASS. An unscoped local staging-tree run found a duplicate
test module under the retained CHECK094 package; the Git branch itself has one
copy and `pytest -q tests` is the authoritative source-tree run. See
`evidence/REPLAY_LEDGER_WITNESS_ALGORITHM_MIGRATION_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK094,
  `REPLAY_LEDGER_WITNESS_DOMAIN_SEPARATION_NEGATIVE001`.
- Parent Drive artifact SHA-256:
  `fde454e9f4f0c66eb8a8c9312edfb9df74ca9fae07d7f30a7cb2904b2787c085`.
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

