# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut adds an explicit signed witness domain: application,
purpose, ledger identity, deployment environment, and signature algorithm.
The first domain-aware append persists the store domain in SQLite under the
same `BEGIN IMMEDIATE` lock as the attestation. Cross-ledger,
cross-environment, wrong-purpose, wrong-application, algorithm-confusion,
legacy-downgrade, restart, and competing-domain append cases fail closed.
HMAC remains a deterministic local fixture and does not prove independent
trust-domain separation.

## Reproduce

```bash
python -m pip install -r requirements-vision.txt pytest==9.0.2 ruff==0.14.13
python -m pytest -q tests/test_external_witness_revocation_epoch.py
python -m pytest -q tests/test_external_witness_domain_separation.py
python -m pytest -q tests/test_external_witness_authenticity.py \
  tests/test_external_witness_key_rotation.py \
  tests/test_external_witness_revocation_epoch.py \
  tests/test_external_witness_domain_separation.py
python -m pytest -q tests/test_opencv5_inspection.py
python -m pytest -q
python ops/replay_ledger_witness_domain_separation_negative.py
python ops/replay_ledger_witness_revocation_epoch_negative.py
python run_demo.py
```

Fresh local results on 2026-10-13: domain separation 6/6 plus 5 subtests;
domain separation repeated 10 times 60/60 plus 50 subtests; witness
compatibility 26/26 plus 5 subtests; OpenCV 120/120 plus 47 subtests; scoped
branch full suite 146/146 plus 52 subtests; changed-file Ruff and compileall
PASS. Four crash probes referenced by the inherited OpenCV tests were restored
from the CHECK086 artifact so the Git branch is self-contained. See
`evidence/REPLAY_LEDGER_WITNESS_DOMAIN_SEPARATION_NEGATIVE001.md`.

## Provenance and limits

- Parent checkpoint: CHECK090,
  `REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_NEGATIVE001`.
- Parent Drive artifact SHA-256:
  `c4e1088e5d16d2928de86513c287dd42dc3f0dfcfc9ffad15d6fbbeca40a4255`.
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

