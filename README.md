# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut persists a signed witness-key revocation epoch in
SQLite. Revocation and verified-attestation append acquire the same
`BEGIN IMMEDIATE` write lock, so whichever transaction commits first defines
the accepted history. Stale epochs, future epochs, revoked keys, epoch
tampering, replay, restart, and append-versus-revocation concurrency are
covered by local HMAC fixtures. HMAC does not prove independent trust-domain
separation.

## Reproduce

```bash
python -m pip install -r requirements-vision.txt pytest==9.0.2 ruff==0.14.13
python -m pytest -q tests/test_external_witness_revocation_epoch.py
python -m pytest -q tests/test_external_witness_authenticity.py \
  tests/test_external_witness_key_rotation.py \
  tests/test_external_witness_revocation_epoch.py
python -m pytest -q tests/test_opencv5_inspection.py
python -m pytest -q
python ops/replay_ledger_witness_revocation_epoch_negative.py
python run_demo.py
```

Fresh local results on 2026-10-13: revocation 5/5, witness compatibility
20/20, OpenCV 120/120 plus 47 subtests, full suite 200/200 plus 47 subtests,
Ruff and compileall PASS. See
`evidence/REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK086,
  `REPLAY_LEDGER_EXTERNAL_WITNESS_KEY_ROTATION_NEGATIVE001`.
- Parent Drive artifact SHA-256:
  `0cc5354febf14a5663816dfc6f5a3eb5d027a98964f507396ad32d5ad7165a37`.
- IP classification: `DERIVED`; no private patent algorithm, customer data, or
  another submission's implementation was imported.
- Live external witness, asymmetric signing, managed KMS, AWS runtime, camera,
  physical disk, and physical action are not demonstrated.

## Deployment gate

Do not treat source import or local tests as AWS deployment. Deployment still
requires an authorized AWS identity, selected region, cost scope, and an
independently administered witness/key-revocation channel. No public release,
submission, paid provisioning, or automatic merge is authorized here.

