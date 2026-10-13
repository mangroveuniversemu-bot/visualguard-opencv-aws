"""Replay signed-domain, restart and append-race witness controls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision.opencv5_inspection import (  # noqa: E402
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
PRIMARY = CaptureReplayWitnessDomain(
    application_id="visualguard-opencv5",
    purpose="capture-replay-ledger-attestation",
    ledger_id="visualguard-fixture-ledger-a",
    deployment_environment="local-fixture",
)
OTHER_LEDGER = CaptureReplayWitnessDomain(
    application_id=PRIMARY.application_id,
    purpose=PRIMARY.purpose,
    ledger_id="visualguard-fixture-ledger-b",
    deployment_environment=PRIMARY.deployment_environment,
)


def state() -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=2,
        rowset_sha256=hashlib.sha256(b"rowset-2").hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def sign(domain=PRIMARY, **overrides) -> dict[str, object]:
    signed_domain = domain.as_dict()
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
    return {
        **payload,
        "signature": hmac.new(
            KEY,
            CaptureReplayWitnessVerifier.canonical_payload(payload),
            hashlib.sha256,
        ).hexdigest(),
    }


def verifier(domain=PRIMARY):
    return CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        trusted_keys={KEY_ID: CaptureReplayWitnessKey(KEY)},
        expected_domain=domain,
        max_age_seconds=300,
    )


def verify_error(**overrides) -> str:
    try:
        verifier().verify(
            sign(**overrides),
            local_state=state(),
            minimum_sequence=2,
            now=NOW,
        )
    except CaptureReplayWitnessError as error:
        return str(error)
    return "UNEXPECTED_ACCEPT"


def append(store, domain):
    return store.verify_and_append(
        verifier(domain),
        sign(domain),
        local_state=state(),
        minimum_sequence=2,
        now=NOW,
    )


def exercise() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="witness-domain-") as temporary:
        restart_db = Path(temporary) / "restart.sqlite3"
        with CaptureReplayWitnessRevocationStore(restart_db) as store:
            append(store, PRIMARY)
        with CaptureReplayWitnessRevocationStore(restart_db) as reopened:
            try:
                append(reopened, OTHER_LEDGER)
            except CaptureReplayWitnessError as error:
                restart_cross_ledger = str(error)
            else:
                restart_cross_ledger = "UNEXPECTED_ACCEPT"

        race_db = Path(temporary) / "race.sqlite3"
        with CaptureReplayWitnessRevocationStore(race_db):
            pass
        barrier = threading.Barrier(2)

        def race(domain):
            with CaptureReplayWitnessRevocationStore(race_db) as store:
                barrier.wait()
                try:
                    return append(store, domain)["status"]
                except CaptureReplayWitnessError as error:
                    return str(error)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(race, PRIMARY),
                executor.submit(race, OTHER_LEDGER),
            ]
            statuses = [future.result(timeout=10) for future in futures]
        with CaptureReplayWitnessRevocationStore(race_db) as reopened:
            race_count = reopened.attestation_count()

    return {
        "domain_failures": {
            "application": verify_error(application_id="other-application"),
            "purpose": verify_error(purpose="other-purpose"),
            "ledger": verify_error(ledger_id="visualguard-fixture-ledger-b"),
            "environment": verify_error(deployment_environment="aws-production"),
            "algorithm": verify_error(signature_algorithm="HMAC-SHA512"),
        },
        "restart_cross_ledger": restart_cross_ledger,
        "concurrent_append_statuses": statuses,
        "concurrent_attestation_count": race_count,
    }


def main() -> None:
    print(
        json.dumps(
            {
                **exercise(),
                "authentication": "HMAC_SHA256_SHARED_SECRET_FIXTURE_ONLY",
                "live_external_witness": "NOT_RUN",
                "aws_live": "NOT_RUN",
                "camera_live": "NOT_RUN",
                "physical_action": "NONE",
                "seed": "NONE",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
