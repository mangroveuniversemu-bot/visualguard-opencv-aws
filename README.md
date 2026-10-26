# VisualGuard — OpenCV 5 on AWS

Project repository for **OpenCV AI Competition 2026, powered by AWS**.

## Current status

**PRIVATE_AWS_SYNTHETIC_EXECUTION_VERIFIED** on `claude/practical-ride-st6n28`.
A private `AWS_IAM` Lambda in `us-east-1` was deployed from source commit
`832b1b476ce88e3fa95e83ac5749f64af0f4bd63`. Live-camera integration and
physical action remain `NOT_RUN` / `NONE`; real-world alarm accuracy is not
established. The public owner-review film is separate from the AWS evidence
contract and has not been byte-bound or independently reviewed under CHECK146.

Current public owner-review film: [VisualGuard | Two Views. One Next Step.](https://youtu.be/AEDHXknTBy8)
(2:20). It combines 2026-10-04 exhibition footage, labelled AI-generated
illustration, edited captures of the local application using synthetic inputs,
and saved private AWS execution evidence. It does not show live-camera
inference or physical equipment control.

The 180-second storyboard and CHECK146 video gate are historical preparation
artifacts; CHECK146 verifies its six bound evidence files, four saved AWS
cases and eight local negative controls, not this newer film or field accuracy.

- **OpenCV 5 workload.** `vision/scene_analysis.py` analyses 640×480
  two-view frames. Quality gates (Sobel/Laplacian sharpness, `calcHist`
  exposure, dark-cell occlusion) are measured from pixels. Lit red
  indicators are detected with HSV `inRange`, morphology, `findContours`
  and shape tests. The two views are fused, and every capture is bound to
  the existing durable replay ledger. The previous 24×16 threshold
  pipeline is kept unchanged.
- **Evaluation.** 540 held-out synthetic pairs: 94.26% exact with 0 unsafe
  misses. The naive red-count baseline scores 50% with 60 unsafe misses;
  the legacy brightness baseline scores 31.85% with 76. Known failure:
  round red stickers false-stop 30/30. See `docs/TECHNICAL_REPORT.md`.
- **Endpoint.** `service/app.py` serves an English judge UI at `/` and
  `POST /v1/inspect` from the same host. The page reads `/healthz` and
  `/v1/samples`, displays the reported OpenCV/runtime connection, and uses
  same-origin requests, so judges need no account or AWS credentials once the
  already-approved public endpoint is deployed. Public AWS mode will use a
  DynamoDB-backed
  global limit of five `/v1/inspect` POST attempts per Taiwan calendar day;
  malformed POSTs consume a slot, and health/sample GETs do not. A failed quota
  store blocks inference. Each response returns the decision,
  the planned follow-up (never
  executed) and a perceive/decide/plan trace. The `Dockerfile` has `http`
  and `lambda` targets. Public AWS smoke validation is deliberately limited to
  one inference request so it preserves the shared daily quota. The public AWS
  rollout is pending the DynamoDB table and the Lambda role's single-table
  `UpdateItem` permission.
- **Hosted verification.** Existing GitHub Actions run `40249719964` at
  baseline `b85ebb0873cf030ab95fd32c1d886df59bf74c86` passed 268 tests and
  116 subtests. Local Windows review results are separate and are not the hosted
  run.
- **CHECK146 evidence index.** Reverification passed for six bound artifacts,
  four saved AWS cases and eight local negative controls. This verifies saved
  evidence consistency, not source authenticity, current-film review or field
  performance.
- **AWS (private synthetic execution verified).** The OIDC workflow deployed
  an `AWS_IAM` Lambda and invoked health, alarm and clear synthetic cases;
  an AWS Console invocation added the empty-views negative control. The
  evidence is bound in `evidence/AWS_EXECUTION_20261026_40223113044.json`.
  No public endpoint, live camera or physical action is claimed.
- **Video evidence boundary.** The public 2:20 film is available at the link
  above. It is not bound to the older 180-second CHECK146 storyboard contract,
  and it has no independent reviewer receipt. The older contract remains
  pending; its templates do not describe the newer public film.

Docs: `docs/ARCHITECTURE.md`, `docs/TECHNICAL_REPORT.md`,
`docs/SUBMISSION_GAP.md`, `docs/AWS_DEPLOYMENT_RUNBOOK.md`,
`docs/AWS_DEMO_CAPTURE_PACKET.md`.

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
python ops/verify_demo_capture_packet.py
python ops/render_demo_storyboard.py --check
python -m pytest -q tests/test_demo_evidence_contract.py
python -m pytest -q tests/test_final_demo_video_evidence.py
python ops/verify_final_demo_video_evidence.py \
  --video .local/final-demo.mp4 \
  --receipt .local/final-demo-receipt.json \
  --review .local/final-demo-review.json
python run_demo.py
python -m pytest -q tests/test_scene_analysis.py tests/test_service.py tests/test_aws_lambda_deploy.py
python ops/evaluate_scene_pipeline.py --output /tmp/eval.json
python -m service.app --port 8080   # demo page at http://127.0.0.1:8080/
python ops/smoke_test_endpoint.py --base-url http://127.0.0.1:8080
docker build --target http -t visualguard:http .
docker run --read-only --tmpfs /tmp -p 8080:8080 visualguard:http
python ops/aws_lambda_deploy.py --mode preview   # no AWS call
```

Fresh results on 2026-10-22, session host with Python 3.13.16:

- full suite 243/243 plus 116 subtests;
- CHECK137 evaluation at `b3049dd`;
- CHECK138: images rebuilt from `git archive b3049dd`, read-only HTTP
  container smoke 9/9, Lambda image through the Runtime Interface Emulator.

Hosted GitHub Actions run `39808657344` (Python 3.12) passed the test job
and the container build/smoke job at `b3049dd`. None of this is AWS
execution.

The preflight exits `2` while blocked and `0` only after every static gate plus
both read-only AWS checks pass. See `.env.example` for variable names; keep
values in an authorized runtime or secret store, never in the repository.

Historical checkpoint (2026-10-15): final-video gate targeted tests 8/8 and
scoped branch full suite 214/214 plus 66 subtests; changed-file Ruff, format
check, compileall, JSON parsing, and the underlying demo-contract probe passed.
The missing-video probe returned `VIDEO_MISSING` at that checkpoint. A separate
2:20 owner-review film was produced later, but it is not byte-bound to CHECK146
or independently reviewed. Contract v002 still describes a 180-second, six-
segment storyboard and private AWS synthetic evidence. Live-camera use and
physical action remain `NOT_RUN` / `NONE`.
See
`evidence/VISUALGUARD_DEMO_EVIDENCE_CONTRACT001.json`.
Hosted GitHub Actions run `38654945975` / job `116162376099` passed the
underlying contract, final-video gate quality checks, and full 214-test suite
at functional commit `9051a943b3f40a4e3a7e57cc86213d39f701448a`.

Fresh AWS evidence on 2026-10-26: workflow run `40223113044` deployed the
private Lambda from `832b1b4`, captured three CloudWatch `REPORT` lines and
returned the bounded health/alarm/clear outcomes. Supplemental RequestId
`5e91ad05-2270-4828-b1dc-619fc4ebdd62` proves the empty-views negative
control. Validation run `40224824470` passed both test and container jobs.
Reserved concurrency 2 was rejected by the account quota and is not configured.

## Provenance and limits

- Parent checkpoint: AWS execution readback committed at `3442e3aa0e8d6003c538ecd2045cd65b2e697710`.
- AWS source commit: `832b1b476ce88e3fa95e83ac5749f64af0f4bd63`.
- IP classification: `DERIVED`; no private patent algorithm, customer data, or
  another submission's implementation was imported.
- Live external witness, asymmetric signing, managed KMS, camera, process kill,
  physical disk/power loss, distributed multi-writer ordering, and physical
  action are not demonstrated. AWS runtime evidence is limited to private
  Lambda invocations over synthetic inputs.
- The probe demonstrates that a same-domain file checkpoint does not stop
  coordinated rollback of the database and checkpoint. Production freshness
  therefore requires an independently administered monotonic or immutable
  anchor. Legacy unchained rows establish a local migration baseline and cannot
  certify pre-migration truth.
- The matrix proves deterministic local routing over fixed arrays, not field
  performance, source authenticity, or executed automation. Separate AWS-side
  records prove only private Lambda execution over synthetic inputs.
- Scene-pipeline metrics come from procedurally rendered frames. Generator
  and detector have the same author, so they establish behaviour on this
  generator only, not field accuracy.
- Response field `execution_environment` is self-reported. The Lambda
  emulator reports `AWS_LAMBDA` locally, so only AWS-side records (invoke
  results, CloudWatch `REPORT` lines) can upgrade AWS status.
- Passing the final-video gate would prove only that reviewed video bytes match
  the bounded local-plus-private-AWS synthetic contract. It would not prove
  field accuracy, source authenticity, live camera, public availability or
  physical action. The older receipt templates do not establish a byte-bound review of the newer public film.

## Deployment gate

The one-time private AWS execution is complete and must not be repeated under
its expired US$1 operation allowance. A public Function URL, further paid
provisioning, competition submission, or automatic merge still requires
separate owner authorization.



Capture-packet validation on 2026-10-26: local targeted suite PASS 28/28 across packet, contract and final-video gates. The packet performs no AWS call and does not claim recorded media or review.

Storyboard validation on 2026-10-26: the deterministic offline storyboard (separate from the later public film) passed with six ordered segments / 180 seconds; SHA-256 `661d2936f180cfd9befd3c7d17737ad3321b77670527a307ed3cf0ba0f441090`. Related local gate suite PASS 33/33. The storyboard makes no AWS call and remains `PREPARED_NOT_RECORDED` / `NOT_RUN`.
