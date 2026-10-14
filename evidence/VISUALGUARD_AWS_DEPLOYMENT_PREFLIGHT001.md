# VisualGuard AWS deployment preflight

- Cut: `VISUALGUARD_AWS_DEPLOYMENT_PREFLIGHT001`
- Recorded: `2026-10-14T17:29:47Z`
- Parent checkpoint: `CHECK126`
- Parent commit: `7f9447cb1df02901ba0e6797d950b3b2708cd605`
- Provenance: `DERIVED`
- Evidence mode: `AWS_READ_ONLY_PREFLIGHT`

## Result

The preflight is implemented and tested, but the real local run is `BLOCKED`.
No owner-authorization flag, approved region/account/runtime role, deployment
target, cost scope, or artifact digest was present. The probe therefore made
zero AWS commands and exited `2` as designed.

This is not AWS deployment evidence. `aws_api=NOT_RUN`,
`deployment=NOT_RUN`, `endpoint=NOT_DEPLOYED`, `camera=NOT_RUN`, and
`physical_action=NONE`.

## Fresh verification

- Targeted tests: `6 passed in 0.02s`.
- Full branch suite: `199 passed, 66 subtests passed in 3.19s`.
- Ruff check and format check: `PASS`.
- Compileall for changed Python files: `PASS`.
- Real preflight output SHA-256:
  `7e3c0d1292b9f001d02165de502339ee810be727f87a0d0166b742a82d594bd2`.
- Targeted-test output SHA-256:
  `d5be81bbe49b412357ba177be7fae47b32ba70b563d2a01ec6ee15df362cc215`.
- Full-suite output SHA-256:
  `d4f3bb5e285cc27498b9fe1adf3d00835e04ecb122760cb4a99eee958702cab9`.
- JUnit SHA-256:
  `abab56f135e4bdfd11e271ae55508928e277ee0a6400f01c65e8488251c92266`.
- Seed: `NONE`.

## Falsifiers and safety boundary

The targeted tests prove that mismatched region/account/role, missing CLI, and
wrong caller identity block progress. A fully mocked success path proves only
the allowlist and state transition; it is `SDK_MOCK`, not AWS evidence. The
allowlist contains only `sts:GetCallerIdentity` and `iam:GetRole`. The script
has no create, update, invoke, or delete operation.

Resume only in an owner-authorized runtime with all required values supplied
outside the repository. Preserve the resulting JSON before considering any
provisioning step.
