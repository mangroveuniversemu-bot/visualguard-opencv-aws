# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut exports and verifies a versioned trust-root-history
checkpoint containing the active epoch, root-set digest, and chain head. A
fresh external checkpoint rejects a rolled-back SQLite history, and a stale
checkpoint rejects a newer database. The negative probe also preserves the
critical falsifier: SQLite and a colocated file checkpoint rolled back together
remain internally consistent and are accepted. The local file is therefore a
fixture for the verification contract, not an independent freshness source or
live external witness.

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
python -m pytest -q tests/test_external_witness_trust_root_history_integrity.py
python -m pytest -q tests/test_external_witness_trust_root_history_external_anchor.py
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
python ops/replay_ledger_witness_trust_root_history_tamper_restart_negative.py
python ops/replay_ledger_witness_trust_root_history_external_anchor_co_rollback_falsifier.py
python run_demo.py
```

Fresh local results on 2026-10-14: external-anchor targeted tests 5/5;
trust-root regression slice 23/23 plus 3 subtests; scoped branch full suite
188/188 plus 58 subtests; changed-file Ruff, format check, compileall, synthetic
demo and the co-rollback falsifier probe PASS as executions. The security
falsifier result is `ACCEPTED_MATCHING_PAIR`, not a rollback-resistance PASS.
See
`evidence/REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_EXTERNAL_ANCHOR_CO_ROLLBACK_FALSIFIER_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK119,
  `REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_TAMPER_RESTART_FAIL_CLOSED_NEGATIVE001`.
- Parent commit: `9df8063cbd37b92748333ddf1bbad9a4c647bab4`.
- IP classification: `DERIVED`; no private patent algorithm, customer data, or
  another submission's implementation was imported.
- Live external witness, asymmetric signing, managed KMS, AWS runtime, camera,
  process kill, physical disk/power loss, distributed multi-writer ordering,
  and physical action are not demonstrated.
- The probe demonstrates that a same-domain file checkpoint does not stop
  coordinated rollback of the database and checkpoint. Production freshness
  therefore requires an independently administered monotonic or immutable
  anchor. Legacy unchained rows establish a local migration baseline and cannot
  certify pre-migration truth.

## Deployment gate

Do not treat source import or local tests as AWS deployment. Deployment still
requires an authorized AWS identity, selected region, cost scope, and an
independently administered witness/key-revocation channel. No public release,
submission, paid provisioning, or automatic merge is authorized here.


