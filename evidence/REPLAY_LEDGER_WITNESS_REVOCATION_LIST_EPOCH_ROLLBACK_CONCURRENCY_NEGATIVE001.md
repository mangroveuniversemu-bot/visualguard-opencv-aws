# Replay ledger witness revocation-list epoch negative control

## Contract

- SQLite persists one authoritative revocation-list epoch and the complete
  revoked provider/key identity set.
- `cas_update_revocation_list` compares the expected epoch and complete
  replacement snapshot inside `BEGIN IMMEDIATE`.
- A valid update preserves all existing entries, adds at least one identity,
  and advances exactly one epoch. The exact committed retry is idempotent.
- Removal/rollback, epoch gaps, no-op epoch advances and stale competing CAS
  writers fail closed without changing the authoritative list.
- Verification and append share the SQLite writer boundary with revocation.
  An append racing revocation can only commit before the update or fail on its
  stale epoch; a current-epoch witness from a revoked key is always rejected.
- The epoch, list and rejection behavior persist after SQLite restart.

## Fresh execution

- Targeted revocation-list tests: 8 passed plus 3 subtests.
- Scoped source-tree suite: 165 passed plus 55 subtests.
- OpenCV: 5.0.0 (`opencv-python-headless==5.0.0.93`).
- Python: 3.12.14; SQLite: 3.53.1; NumPy: 2.5.3; pytest: 9.0.2;
  Ruff: 0.14.13.
- Seed: NONE.

The replayable probe committed epoch 1 with one revoked identity, reopened the
database, rejected a replacement snapshot that removed that identity with
`REPLAY_LEDGER_WITNESS_REVOCATION_LIST_ROLLBACK`, and rejected the revoked key
at the current epoch with `REPLAY_LEDGER_WITNESS_KEY_REVOKED`. The observed
append-versus-revocation ordering committed the append first, leaving one
historical attestation; the test accepts only that outcome or the alternative
serialized stale-epoch rejection.

## Commands

```text
python -m pytest -q tests/test_external_witness_revocation_list_epoch.py
python -m pytest -q
python ops/replay_ledger_witness_revocation_list_epoch_negative.py
ruff check <changed Python files>
ruff format --check <changed Python files>
python -m compileall -q vision tests ops run_demo.py
python run_demo.py
```

## Retained failures

- The first targeted command addressed the existing isolated environment with
  a relative path one directory too shallow and exited 127 before collection.
- The first product run passed 8 tests but exposed two incorrect test regexes
  for the deliberate `REVOCATION_LIST_EPOCH_GAP` and
  `REVOCATION_LIST_NO_CHANGE` errors; the expectations were corrected.
- The first Ruff format check requested formatting of the three changed Python
  files. Ruff 0.14.13 formatted them; all authoritative reruns passed.

## Limits

The witness keys are same-host HMAC fixtures. Live external witness,
asymmetric signing, managed KMS, AWS runtime, camera, physical-disk crash
behavior, distributed multi-writer ordering and physical action were NOT_RUN.
