"""Negative controls for signed witness and persisted store domains."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from vision.opencv5_inspection import (
    CaptureReplayAnchorState,
    CaptureReplayWitnessDomain,
    CaptureReplayWitnessError,
    CaptureReplayWitnessKey,
    CaptureReplayWitnessRevocationStore,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-key-domain-2026-10"
KEY = b"visualguard-witness-fixture-domain-key-01"
NOW = 2_000_000_000
PRIMARY_DOMAIN = CaptureReplayWitnessDomain(
    application_id="visualguard-opencv5",
    purpose="capture-replay-ledger-attestation",
    ledger_id="visualguard-fixture-ledger-a",
    deployment_environment="local-fixture",
)


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=2,
        rowset_sha256=hashlib.sha256(b"rowset-2").hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def domain_payload(domain: CaptureReplayWitnessDomain) -> dict[str, str]:
    return domain.as_dict()


def signed_witness(
    domain: CaptureReplayWitnessDomain = PRIMARY_DOMAIN,
    *,
    overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    signed_domain = domain_payload(domain)
    if overrides:
        signed_domain.update(overrides)
    payload = {
        "witness_version": 2,
        "provider_id": PROVIDER_ID,
        "key_id": KEY_ID,
        "revocation_epoch": 0,
        "issued_at": NOW,
        **signed_domain,
        "state": state().as_dict(),
    }
    signature = hmac.new(
        KEY,
        CaptureReplayWitnessVerifier.canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()
    return {**payload, "signature": signature}


def verifier(domain: CaptureReplayWitnessDomain = PRIMARY_DOMAIN):
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={KEY_ID: CaptureReplayWitnessKey(KEY)},
        expected_domain=domain,
        max_age_seconds=300,
    )


def append(store, domain, witness):
    return store.verify_and_append(
        verifier(domain),
        witness,
        local_state=state(),
        minimum_sequence=2,
        now=NOW,
    )


class ExternalWitnessDomainSeparationCases(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "domain.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_domain_rejected(self, overrides, code):
        with self.assertRaisesRegex(CaptureReplayWitnessError, f"^{code}$"):
            verifier().verify(
                signed_witness(overrides=overrides),
                local_state=state(),
                minimum_sequence=2,
                now=NOW,
            )

    def test_valid_domain_is_signed_appended_and_replayed_exactly(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            first = append(store, PRIMARY_DOMAIN, signed_witness())
            replay = append(store, PRIMARY_DOMAIN, signed_witness())
            self.assertEqual(first["status"], "APPENDED")
            self.assertEqual(replay["status"], "REPLAYED")
            self.assertEqual(first["ledger_id"], PRIMARY_DOMAIN.ledger_id)
            self.assertEqual(store.attestation_count(), 1)

    def test_wrong_application_purpose_ledger_environment_and_algorithm_fail(self):
        cases = {
            "application_id": (
                "other-application",
                "REPLAY_LEDGER_WITNESS_APPLICATION_MISMATCH",
            ),
            "purpose": (
                "other-purpose",
                "REPLAY_LEDGER_WITNESS_PURPOSE_MISMATCH",
            ),
            "ledger_id": (
                "visualguard-fixture-ledger-b",
                "REPLAY_LEDGER_WITNESS_LEDGER_MISMATCH",
            ),
            "deployment_environment": (
                "aws-production",
                "REPLAY_LEDGER_WITNESS_ENVIRONMENT_MISMATCH",
            ),
            "signature_algorithm": (
                "HMAC-SHA512",
                "REPLAY_LEDGER_WITNESS_ALGORITHM_MISMATCH",
            ),
        }
        for field, (value, code) in cases.items():
            with self.subTest(field=field):
                self.assert_domain_rejected({field: value}, code)

    def test_store_domain_binding_survives_sqlite_restart(self):
        other = CaptureReplayWitnessDomain(
            application_id=PRIMARY_DOMAIN.application_id,
            purpose=PRIMARY_DOMAIN.purpose,
            ledger_id="visualguard-fixture-ledger-b",
            deployment_environment=PRIMARY_DOMAIN.deployment_environment,
        )
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            self.assertEqual(
                append(store, PRIMARY_DOMAIN, signed_witness())["status"],
                "APPENDED",
            )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_STORE_DOMAIN_MISMATCH$",
            ):
                append(reopened, other, signed_witness(other))
            self.assertEqual(reopened.attestation_count(), 1)

    def test_domain_bound_store_rejects_legacy_downgrade(self):
        with CaptureReplayWitnessRevocationStore(self.database) as store:
            append(store, PRIMARY_DOMAIN, signed_witness())
        legacy_payload = {
            "witness_version": 1,
            "provider_id": PROVIDER_ID,
            "key_id": KEY_ID,
            "revocation_epoch": 0,
            "issued_at": NOW,
            "state": state().as_dict(),
        }
        legacy = {
            **legacy_payload,
            "signature": hmac.new(
                KEY,
                CaptureReplayWitnessVerifier.canonical_payload(legacy_payload),
                hashlib.sha256,
            ).hexdigest(),
        }
        legacy_verifier = CaptureReplayWitnessVerifier(
            provider_id=PROVIDER_ID,
            trusted_keys={KEY_ID: CaptureReplayWitnessKey(KEY)},
            max_age_seconds=300,
        )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            with self.assertRaisesRegex(
                CaptureReplayWitnessError,
                "^REPLAY_LEDGER_WITNESS_DOMAIN_REQUIRED$",
            ):
                reopened.verify_and_append(
                    legacy_verifier,
                    legacy,
                    local_state=state(),
                    minimum_sequence=2,
                    now=NOW,
                )

    def test_competing_domain_appends_serialize_to_one_store_domain(self):
        other = CaptureReplayWitnessDomain(
            application_id=PRIMARY_DOMAIN.application_id,
            purpose=PRIMARY_DOMAIN.purpose,
            ledger_id="visualguard-fixture-ledger-b",
            deployment_environment=PRIMARY_DOMAIN.deployment_environment,
        )
        with CaptureReplayWitnessRevocationStore(self.database):
            pass
        barrier = threading.Barrier(2)

        def race(domain):
            with CaptureReplayWitnessRevocationStore(self.database) as store:
                barrier.wait()
                try:
                    return append(store, domain, signed_witness(domain))
                except CaptureReplayWitnessError as error:
                    return str(error)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                executor.submit(race, PRIMARY_DOMAIN),
                executor.submit(race, other),
            ]
            outcomes = [future.result(timeout=10) for future in results]
        statuses = [
            outcome if isinstance(outcome, str) else outcome["status"]
            for outcome in outcomes
        ]
        self.assertCountEqual(
            statuses,
            ["APPENDED", "REPLAY_LEDGER_WITNESS_STORE_DOMAIN_MISMATCH"],
        )
        with CaptureReplayWitnessRevocationStore(self.database) as reopened:
            self.assertEqual(reopened.attestation_count(), 1)

    def test_replayable_probe_reports_domain_failures_restart_and_race(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "replay_ledger_witness_domain_separation_negative.py"
        )
        probe = subprocess.run(
            [sys.executable, script],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        evidence = json.loads(probe.stdout)
        self.assertEqual(evidence["live_external_witness"], "NOT_RUN")
        self.assertEqual(evidence["aws_live"], "NOT_RUN")
        self.assertEqual(
            evidence["restart_cross_ledger"],
            "REPLAY_LEDGER_WITNESS_STORE_DOMAIN_MISMATCH",
        )
        self.assertCountEqual(
            evidence["concurrent_append_statuses"],
            ["APPENDED", "REPLAY_LEDGER_WITNESS_STORE_DOMAIN_MISMATCH"],
        )


if __name__ == "__main__":
    unittest.main()
