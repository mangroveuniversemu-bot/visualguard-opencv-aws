"""Replay a trust-root rotation abort and prove restart atomicity."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.opencv5_inspection import (  # noqa: E402
    CaptureReplayAnchorState,
    CaptureReplayWitnessError,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessRevocationStore,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-root-2026-11"
OTHER_KEY_ID = "fixture-hmac-root-2026-12"
THIRD_KEY_ID = "fixture-hmac-root-2027-01"
KEY = b"visualguard-witness-fixture-trust-root-key-01"
OTHER_KEY = b"visualguard-witness-fixture-trust-root-key-02"
THIRD_KEY = b"visualguard-witness-fixture-trust-root-key-03"
NOW = 2_000_000_400


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=6,
        rowset_sha256=hashlib.sha256(b"trust-root-atomicity-rowset-6").hexdigest(),
        policy_sha256="7" * 64,
        capture_schema_sha256="8" * 64,
        rowset_schema_sha256="9" * 64,
    )


def signed_witness(*, key_id: str, key: bytes, epoch: int) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": key_id,
        "revocation_epoch": 0,
        "trust_root_epoch": epoch,
        "issued_at": NOW,
        "state": state().as_dict(),
    }
    return {
        **payload,
        "signature": hmac.new(
            key,
            CaptureReplayWitnessVerifier.canonical_payload(payload),
            hashlib.sha256,
        ).hexdigest(),
    }


def verifier() -> CaptureReplayWitnessVerifier:
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={
            KEY_ID: CaptureReplayWitnessKey(KEY),
            OTHER_KEY_ID: CaptureReplayWitnessKey(OTHER_KEY),
            THIRD_KEY_ID: CaptureReplayWitnessKey(THIRD_KEY),
        },
        max_age_seconds=300,
    )


def append(
    store: CaptureReplayWitnessRevocationStore,
    witness: dict[str, object],
) -> dict[str, int | str]:
    return store.verify_and_append(
        verifier(),
        witness,
        local_state=state(),
        minimum_sequence=6,
        now=NOW,
    )


def install_abort_trigger(database: Path) -> None:
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TRIGGER fail_trust_root_state_update
        BEFORE UPDATE ON replay_ledger_witness_trust_root_state
        WHEN OLD.trust_root_epoch = 1 AND NEW.trust_root_epoch = 2
        BEGIN
            SELECT RAISE(ABORT, 'INJECTED_TRUST_ROOT_UPDATE_ABORT');
        END"""
    )
    connection.commit()
    connection.close()


def remove_abort_trigger(database: Path) -> None:
    connection = sqlite3.connect(database)
    connection.execute("DROP TRIGGER fail_trust_root_state_update")
    connection.commit()
    connection.close()


def raw_snapshot(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(database)
    epoch, digest = connection.execute(
        "SELECT trust_root_epoch, root_set_sha256 "
        "FROM replay_ledger_witness_trust_root_state WHERE singleton = 1"
    ).fetchone()
    roots = connection.execute(
        "SELECT provider_id, key_id FROM replay_ledger_witness_trust_root "
        "ORDER BY provider_id, key_id"
    ).fetchall()
    history = connection.execute(
        "SELECT trust_root_epoch, root_set_sha256 "
        "FROM replay_ledger_witness_trust_root_history ORDER BY trust_root_epoch"
    ).fetchall()
    quick_check = connection.execute("PRAGMA quick_check").fetchall()
    connection.close()
    return {
        "epoch": epoch,
        "digest": digest,
        "roots": [list(row) for row in roots],
        "history": [list(row) for row in history],
        "quick_check": [row[0] for row in quick_check],
    }


def main() -> None:
    roots = ((PROVIDER_ID, KEY_ID), (PROVIDER_ID, OTHER_KEY_ID))
    replacement = ((PROVIDER_ID, OTHER_KEY_ID), (PROVIDER_ID, THIRD_KEY_ID))
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "witness.sqlite3"
        with CaptureReplayWitnessRevocationStore(database) as store:
            store.cas_update_trust_root_set(
                expected_epoch=0,
                replacement_epoch=1,
                trusted_roots=roots,
            )
        before_abort = raw_snapshot(database)
        install_abort_trigger(database)
        abort_error = None
        with CaptureReplayWitnessRevocationStore(database) as store:
            try:
                store.cas_update_trust_root_set(
                    expected_epoch=1,
                    replacement_epoch=2,
                    trusted_roots=replacement,
                )
            except sqlite3.IntegrityError as error:
                abort_error = str(error)
        if abort_error != "INJECTED_TRUST_ROOT_UPDATE_ABORT":
            raise AssertionError(f"unexpected injected-abort result: {abort_error!r}")
        after_abort = raw_snapshot(database)
        if after_abort != before_abort:
            raise AssertionError("aborted rotation changed persisted trust-root state")
        with CaptureReplayWitnessRevocationStore(database) as restarted:
            restarted_state = restarted.trust_root_set_state()
        if restarted_state != (1, roots):
            raise AssertionError(f"restart observed torn state: {restarted_state!r}")

        remove_abort_trigger(database)
        with CaptureReplayWitnessRevocationStore(database) as store:
            append_status = append(
                store,
                signed_witness(key_id=KEY_ID, key=KEY, epoch=1),
            )["status"]
            retry_epoch, retry_roots = store.cas_update_trust_root_set(
                expected_epoch=1,
                replacement_epoch=2,
                trusted_roots=replacement,
            )
        with CaptureReplayWitnessRevocationStore(database) as restarted:
            final_epoch, final_roots = restarted.trust_root_set_state()
            attestation_count = restarted.attestation_count()
            try:
                append(
                    restarted,
                    signed_witness(key_id=KEY_ID, key=KEY, epoch=1),
                )
            except CaptureReplayWitnessError as error:
                stale_error = str(error)
            else:
                raise AssertionError("removed root was accepted after committed retry")
        final_snapshot = raw_snapshot(database)
        if (
            append_status != "APPENDED"
            or retry_epoch != 2
            or retry_roots != replacement
            or final_epoch != 2
            or final_roots != replacement
            or attestation_count != 1
            or stale_error != "REPLAY_LEDGER_WITNESS_TRUST_ROOT_EPOCH_STALE"
            or final_snapshot["quick_check"] != ["ok"]
            or len(final_snapshot["history"]) != 3
        ):
            raise AssertionError("post-abort retry/restart invariant failed")

        print(
            json.dumps(
                {
                    "cut": (
                        "REPLAY_LEDGER_WITNESS_TRUST_ROOT_SET_ABORT_RESTART_"
                        "ATOMICITY_NEGATIVE001"
                    ),
                    "evidence_mode": "LOCAL_DETERMINISTIC_HMAC_SQLITE_FIXTURE",
                    "ip_classification": "DERIVED",
                    "failure_injection": (
                        "SQLITE_TRIGGER_ABORT_AFTER_ROOT_ROWS_MUTATED_BEFORE_STATE_COMMIT"
                    ),
                    "abort_error": abort_error,
                    "snapshot_unchanged_after_abort": after_abort == before_abort,
                    "restart_state_after_abort": {
                        "epoch": restarted_state[0],
                        "roots": [list(identity) for identity in restarted_state[1]],
                    },
                    "post_abort_append": append_status,
                    "retry_epoch": final_epoch,
                    "retry_roots": [list(identity) for identity in final_roots],
                    "history_epoch_count": len(final_snapshot["history"]),
                    "attestation_count": attestation_count,
                    "removed_root_after_retry": stale_error,
                    "sqlite_quick_check": final_snapshot["quick_check"],
                    "live_external_witness": "NOT_RUN",
                    "aws": "NOT_RUN",
                    "camera": "NOT_RUN",
                    "physical_action": "NONE",
                    "seed": "NONE",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
