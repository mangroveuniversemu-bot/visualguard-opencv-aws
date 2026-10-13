# REPLAY_LEDGER_WITNESS_DOMAIN_SEPARATION_NEGATIVE001

## Contract

- A v2 attestation signs an explicit application, purpose, ledger identity,
  deployment environment, and signature algorithm.
- A domain-aware verifier requires exact equality for all five values and does
  not accept an unscoped v1 attestation.
- The first accepted v2 attestation persists the store domain in SQLite.
- Domain binding and attestation append share one `BEGIN IMMEDIATE` write
  transaction, so competing domains cannot both become authoritative.
- Exact replay in the same domain remains idempotent.

## Falsifier and retained failure

The new negative controls reject:

- another application: `REPLAY_LEDGER_WITNESS_APPLICATION_MISMATCH`;
- another purpose: `REPLAY_LEDGER_WITNESS_PURPOSE_MISMATCH`;
- another ledger: `REPLAY_LEDGER_WITNESS_LEDGER_MISMATCH`;
- another environment: `REPLAY_LEDGER_WITNESS_ENVIRONMENT_MISMATCH`;
- another claimed algorithm: `REPLAY_LEDGER_WITNESS_ALGORITHM_MISMATCH`;
- a second domain after restart:
  `REPLAY_LEDGER_WITNESS_STORE_DOMAIN_MISMATCH`;
- legacy downgrade after binding: `REPLAY_LEDGER_WITNESS_DOMAIN_REQUIRED`.

The first expanded-suite attempt retained a useful source-packaging failure:
the CHECK090 ZIP and Git tree omitted four crash-probe scripts still referenced
by `tests/test_opencv5_inspection.py`. That run produced 116 PASS and four
missing-file failures. The exact probes were recovered from the CHECK086
artifact, added to this branch, and the scoped suite was rerun successfully.

## Fresh results

- Domain separation: PASS 6/6 plus 5 subtests.
- Domain separation repeated 10 times: PASS 60/60 plus 50 subtests.
- Witness compatibility: PASS 26/26 plus 5 subtests.
- OpenCV: PASS 120/120 plus 47 subtests.
- Scoped branch full suite: PASS 146/146 plus 52 subtests.
- Changed-file Ruff check and format check: PASS.
- `compileall`: PASS.
- Demo: v2 domain append `APPENDED`; revocation epoch advanced to 1.
- Concurrency probe: exactly one domain `APPENDED`; the other returned
  `REPLAY_LEDGER_WITNESS_STORE_DOMAIN_MISMATCH`; persisted count was 1.
- Seed: NONE.

## Runtime

Python 3.12.14; SQLite 3.53.1; OpenCV 5.0.0;
opencv-python-headless 5.0.0.93; NumPy 2.5.3; pytest 9.0.2; Ruff 0.14.13.

## Limits

Authentication is still an HMAC-SHA256 shared-secret fixture in the same
package. Live external witness, asymmetric signing, revocation distribution,
managed KMS, AWS, camera, physical disk, distributed multi-writer ordering,
and physical action are `NOT_RUN`.
