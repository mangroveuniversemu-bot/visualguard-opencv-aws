"""Tamper an older trust-root history row and prove restart fails closed."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.opencv5_inspection import (  # noqa: E402
    CaptureReplayLedgerSchemaError,
    CaptureReplayWitnessRevocationStore,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_A = "fixture-hmac-root-2026-11"
KEY_B = "fixture-hmac-root-2026-12"
KEY_C = "fixture-hmac-root-2027-01"


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "witness.sqlite3"
        with CaptureReplayWitnessRevocationStore(database) as store:
            store.cas_update_trust_root_set(
                expected_epoch=0,
                replacement_epoch=1,
                trusted_roots=((PROVIDER_ID, KEY_A), (PROVIDER_ID, KEY_B)),
            )
            store.cas_update_trust_root_set(
                expected_epoch=1,
                replacement_epoch=2,
                trusted_roots=((PROVIDER_ID, KEY_B), (PROVIDER_ID, KEY_C)),
            )

        connection = sqlite3.connect(database)
        before = connection.execute(
            "SELECT root_set_sha256 FROM replay_ledger_witness_trust_root_history "
            "WHERE trust_root_epoch = 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE replay_ledger_witness_trust_root_history "
            "SET root_set_sha256 = ? WHERE trust_root_epoch = 1",
            ("f" * 64,),
        )
        connection.commit()
        quick_check = [
            str(row[0]) for row in connection.execute("PRAGMA quick_check").fetchall()
        ]
        attestation_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM replay_ledger_witness_attestation"
            ).fetchone()[0]
        )
        connection.close()

        try:
            CaptureReplayWitnessRevocationStore(database)
        except CaptureReplayLedgerSchemaError as error:
            restart_error = str(error)
        else:
            raise AssertionError("tampered history was accepted after restart")
        if (
            quick_check != ["ok"]
            or restart_error != "REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_INVALID"
            or attestation_count != 0
        ):
            raise AssertionError("logical history tamper did not fail closed")

        print(
            json.dumps(
                {
                    "cut": (
                        "REPLAY_LEDGER_WITNESS_TRUST_ROOT_HISTORY_TAMPER_"
                        "RESTART_FAIL_CLOSED_NEGATIVE001"
                    ),
                    "evidence_mode": "LOCAL_DETERMINISTIC_HMAC_SQLITE_FIXTURE",
                    "ip_classification": "DERIVED",
                    "tamper": "OLDER_ROOT_SET_DIGEST_CHANGED_WITHOUT_CHAIN_REWRITE",
                    "original_epoch_1_root_set_sha256": before,
                    "tampered_epoch_1_root_set_sha256": "f" * 64,
                    "sqlite_quick_check_after_tamper": quick_check,
                    "restart_error": restart_error,
                    "attestation_count_after_tamper": attestation_count,
                    "live_external_witness": "NOT_RUN",
                    "aws": "NOT_RUN",
                    "camera": "NOT_RUN",
                    "physical_action": "NONE",
                    "seed": "NONE",
                    "known_limitation": (
                        "A database attacker able to rewrite the full history chain "
                        "and its trust context is outside this local-fixture claim."
                    ),
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
