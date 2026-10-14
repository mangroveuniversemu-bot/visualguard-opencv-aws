# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut adds an abort/restart atomicity falsifier for the
authoritative trust-root-set CAS. A deterministic SQLite trigger aborts the
state-row update after active-root rows have already been changed inside the
transaction but before commit. Raw state, root and history rows must remain the
exact pre-rotation snapshot across restart; after the trigger is removed, one
retry must advance the epoch and history exactly once. HMAC remains a
deterministic local fixture and does not prove an independent trust domain.

## Reproduce

```bash
python -m pip install -r requirements-vision.txt pytest==9.0.2 ruff==0.14.13
python -m pytest -q tests/test_external_witness_revocation_epoch.py
python -m pytest -q tests/test_external_witness_domain_separation.py
python -m pytest -q tests/test_external_witness_algorithm_migration.py
python -m pytest -q tests/test_external_witness_policy_rollback.py
python -m pytest -q tests/test_external_witness_revocation_list_epoch.py
python -m pytest -q tests/test_external_witness_trust_root_set_epoch.py
python -m pytest -q tests/test_external_witness_trust_root_set_atomicity.py
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
python ops/replay_ledger_witness_trust_root_set_abort_restart_atomicity_negative.py
python run_demo.py
```

Fresh local results on 2026-10-14: atomicity targeted tests 3/3; scoped branch
full suite 178/178 plus 58 subtests; changed-file Ruff, format check, compileall,
synthetic demo and the abort/restart/retry probe PASS. See
`evidence/REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_ABORT_RESTART_ATOMICITY_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK111,
  `REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_EPOCH_ROLLBACK_CONCURRENCY_NEGATIVE001`.
- Parent commit: `2afc202bda256c695fcdfd8e15205e84acd330f2`.
- IP classification: `DERIVED`; no private patent algorithm, customer data, or
  another submission's implementation was imported.
- Live external witness, asymmetric signing, managed KMS, AWS runtime, camera,
  process kill, physical disk/power loss, distributed multi-writer ordering,
  and physical action are not demonstrated.

## Deployment gate

Do not treat source import or local tests as AWS deployment. Deployment still
requires an authorized AWS identity, selected region, cost scope, and an
independently administered witness/key-revocation channel. No public release,
submission, paid provisioning, or automatic merge is authorized here.


