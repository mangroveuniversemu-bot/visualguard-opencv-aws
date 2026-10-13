# REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_NEGATIVE001

## Contract

- A revocation-aware attestation signs its exact non-negative
  `revocation_epoch`.
- SQLite persists one monotonic epoch and a per-provider/key revocation row.
- Revocation and verified-attestation append serialize through
  `BEGIN IMMEDIATE`.
- Stale/future epochs, revoked keys, tampered epochs, and conflicting replays
  fail closed. Exact attestation replay is idempotent.

## Falsifier before implementation

Command:

`python -m pytest -q tests/test_external_witness_revocation_epoch.py`

Observed: test collection failed because
`CaptureReplayWitnessRevocationStore` did not exist. A first full-suite attempt
then exposed a test-harness rendezvous risk: both threads could race while
creating the schema and leave one participant waiting at the barrier. The test
was corrected by bootstrapping schema before the append-versus-revocation
race; production transaction semantics were unchanged.

## Fresh results

- New revocation tests: PASS 5/5.
- New revocation tests repeated 10 times: PASS 50/50.
- Witness compatibility group: PASS 20/20.
- Existing OpenCV group: PASS 120/120 plus 47 subtests.
- Full suite: PASS 200/200 plus 47 subtests.
- Ruff check and format check: PASS.
- `compileall`: PASS.
- Probe: epoch persisted as 1 after restart; stale epoch returned
  `REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE`; current-epoch revoked key
  returned `REPLAY_LEDGER_WITNESS_KEY_REVOKED`; a different trusted key at
  epoch 1 was accepted.
- Seed: NONE.

## Runtime

Python 3.12.14; SQLite 3.53.1; OpenCV 5.0.0;
opencv-python-headless 5.0.0.93; NumPy 2.5.3; pytest 9.0.2; Ruff 0.14.13.

## Limits

Authentication is an HMAC-SHA256 shared-secret fixture in the same package.
Live external witness, asymmetric signing, revocation distribution, managed
KMS, AWS, camera, physical disk, and physical action are `NOT_RUN`.

