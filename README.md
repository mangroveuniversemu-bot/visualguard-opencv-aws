# VisualGuard — OpenCV 5 on AWS

Private engineering repository for **OpenCV AI Competition 2026, powered by
AWS**.

## Current status

**SOURCE_IMPORTED_AND_LOCALLY_VERIFIED** on the development branch. The source
was recovered from the append-only CHECK086 Google Drive artifact and is now
reviewable as text instead of only as an archive. AWS deployment, live camera
input, an independently operated witness, and physical action remain
`NOT_RUN`.

The current bounded cut packages the OpenCV 5 replay, eight judging-facing
negative controls, downstream routing, and the AWS disclosure into a
machine-verifiable 180-second demo contract. Artifact digests, required
segments, and claim boundaries fail closed. The plan is
`PREPARED_NOT_RECORDED`; it cannot label fixed arrays, the blocked AWS
preflight, or an unrecorded script as live evidence.

The AWS deployment preflight is executable but fail-closed. It requires
explicit owner authorization, approved region/account/role, deployment target,
cost scope, and immutable artifact digest before making any AWS call. If those
gates pass, it permits only `sts get-caller-identity` and `iam get-role` reads;
deployment and endpoint creation remain `NOT_RUN`.

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
python -m pytest -q tests/test_judging_negative_control_matrix.py
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
python ops/opencv5_judging_negative_control_matrix.py
python ops/aws_deployment_preflight.py \
  --output evidence/CHECK129_AWS_DEPLOYMENT_PREFLIGHT.json
python ops/verify_demo_evidence_contract.py
python -m pytest -q tests/test_demo_evidence_contract.py
python run_demo.py
```

The preflight exits `2` while blocked and `0` only after every static gate plus
both read-only AWS checks pass. See `.env.example` for variable names; keep
values in an authorized runtime or secret store, never in the repository.

Fresh local results on 2026-10-15: demo-contract targeted tests 7/7; contract,
matrix, and OpenCV inspection regression slice 132/132 plus 55 subtests; scoped
branch full suite 206/206 plus 66 subtests; changed-file Ruff, format check,
compileall, and contract probe PASS as executions. The contract binds two
artifacts across six required segments at exactly 180 seconds. Every matrix row
has `action_executed=false` and `physical_action=NONE`; AWS, live camera, and
video recording remain `NOT_RUN`/`PREPARED_NOT_RECORDED`.
See
`evidence/VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.md`.

Fresh preflight evidence on 2026-10-15: six targeted tests pass, including
account/region mismatch and missing-CLI controls. The real local probe blocks
before AWS because no owner-authorized AWS configuration is present; AWS API,
deployment, endpoint, camera, and physical action remain `NOT_RUN`.

## Provenance and limits

- Parent checkpoint: CHECK129, `VISUALGUARD_AWS_DEPLOYMENT_PREFLIGHT001`.
- Parent commit: `135c07ee9f0110c9688c6cc6f4b8854e0b0a8679`.
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
- The matrix proves deterministic local routing over fixed arrays, not field
  performance, source authenticity, AWS integration, or executed automation.
- Passing the demo contract proves only that a prepared script matches its
  bound artifacts and claim limits; it does not prove a video was recorded.

## Deployment gate

Do not treat source import or local tests as AWS deployment. Deployment still
requires an authorized AWS identity, selected region, cost scope, and an
independently administered witness/key-revocation channel. No public release,
submission, paid provisioning, or automatic merge is authorized here.


