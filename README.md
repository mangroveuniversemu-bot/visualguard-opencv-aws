# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut makes the trust-root history fail closed on restart
when an older root digest, epoch row, or chain digest is modified. Every
committed snapshot now extends a deterministic SHA-256 history chain; startup
requires consecutive epochs from zero through the active epoch, a valid chain,
and a final history digest matching the active root set. The negative probe
shows SQLite `quick_check=ok` while application-level validation still rejects
the logically tampered database before an attestation can be appended. HMAC
and the chain remain deterministic local fixtures and do not prove an
independent trust domain.

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
python run_demo.py
```

Fresh local results on 2026-10-14: history-integrity targeted tests 5/5;
trust-root regression slice 18/18 plus 3 subtests; scoped branch full suite
183/183 plus 58 subtests; changed-file Ruff, format check, compileall, synthetic
demo and the tamper/restart probe PASS. See
`evidence/REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_TAMPER_RESTART_FAIL_CLOSED_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK115,
  `REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_ABORT_RESTART_ATOMICITY_NEGATIVE001`.
- Parent commit: `63cdff202f5a59b337283ddadccbb0001844d8ba`.
- IP classification: `DERIVED`; no private patent algorithm, customer data, or
  another submission's implementation was imported.
- Live external witness, asymmetric signing, managed KMS, AWS runtime, camera,
  process kill, physical disk/power loss, distributed multi-writer ordering,
  and physical action are not demonstrated.
- A database attacker able to rewrite the complete chain and its trust context
  is outside this local-fixture claim. Legacy unchained rows establish a local
  baseline during migration; the chain cannot certify their pre-migration
  truth.

## Deployment gate

Do not treat source import or local tests as AWS deployment. Deployment still
requires an authorized AWS identity, selected region, cost scope, and an
independently administered witness/key-revocation channel. No public release,
submission, paid provisioning, or automatic merge is authorized here.


