# Trust-root history tamper/restart fail-closed control

## Claim under test

An older trust-root history row must not be silently accepted after restart
merely because the active epoch and active root-set digest still match.

## Implementation

Each history row commits its epoch, root-set digest, and predecessor chain
digest into a deterministic SHA-256 chain. Store startup validates:

1. exactly one row for every epoch from zero through the active epoch;
2. valid root-set and chain SHA-256 values;
3. every chain link against its predecessor; and
4. the final history root-set digest against the active state row.

Legacy databases gain the nullable chain column and establish a local migration
baseline. This is migration compatibility, not retrospective truth proof.

## Fresh acceptance result

- history-integrity targeted tests: PASS 5/5;
- trust-root regression slice: PASS 18/18 plus 3 subtests;
- scoped full suite: PASS 183/183 plus 58 subtests;
- changed-file Ruff and format check: PASS;
- compileall, synthetic demo and replayable tamper probe: PASS.

The probe changed the epoch-1 root-set digest without rewriting the stored
chain. SQLite reported `quick_check=ok`, proving the file remained structurally
valid, while the application rejected restart with
`REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_INVALID`. No attestation existed
before or after the tamper.

## Reproduce

    python -m pytest -q tests/test_external_witness_trust_root_history_integrity.py
    python -m pytest -q
    python ops/replay_ledger_witness_trust_root_history_tamper_restart_negative.py

## Scope

Evidence mode is `LOCAL_DETERMINISTIC_HMAC_SQLITE_FIXTURE`; IP classification
is `DERIVED`. This does not prove resistance to an attacker who can rewrite
the complete chain and its trust context, nor does it demonstrate an
independent asymmetric witness, managed KMS, AWS runtime, live camera,
physical storage/power failure, distributed writers, or physical action.
