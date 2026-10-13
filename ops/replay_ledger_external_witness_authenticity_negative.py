"""Replay HMAC witness authenticity and monotonicity negative controls.

The witness and key are deterministic local fixtures. This proves the verifier
contract and stable failure modes only; it is not a deployed independent trust
domain, managed key, asymmetric signature, or live provider observation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision.opencv5_inspection import (
    CaptureReplayAnchorState,
    CaptureReplayWitnessError,
    CaptureReplayWitnessVerifier,
)


PROVIDER_ID = "fixture-independent-witness"
KEY_ID = "fixture-hmac-key-2026-10"
VERIFYING_KEY = b"visualguard-witness-fixture-key-0001"
WRONG_KEY = b"visualguard-witness-fixture-key-9999"
NOW = 2_000_000_000


def state(sequence: int) -> CaptureReplayAnchorState:
    return CaptureReplayAnchorState(
        sequence=sequence,
        rowset_sha256=hashlib.sha256(
            f"rowset-{sequence}".encode("utf-8")
        ).hexdigest(),
        policy_sha256="a" * 64,
        capture_schema_sha256="b" * 64,
        rowset_schema_sha256="c" * 64,
    )


def sign(
    anchor_state: CaptureReplayAnchorState,
    *,
    issued_at: int = NOW,
    key: bytes = VERIFYING_KEY,
) -> dict[str, object]:
    payload = {
        "witness_version": 1,
        "provider_id": PROVIDER_ID,
        "key_id": KEY_ID,
        "issued_at": issued_at,
        "state": anchor_state.as_dict(),
    }
    signature = hmac.new(
        key,
        CaptureReplayWitnessVerifier.canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()
    return {**payload, "signature": signature}


def rejected(
    verifier: CaptureReplayWitnessVerifier,
    witness: object,
    *,
    local_state: CaptureReplayAnchorState,
    minimum_sequence: int = 2,
) -> str:
    try:
        verifier.verify(
            witness,
            local_state=local_state,
            minimum_sequence=minimum_sequence,
            now=NOW,
        )
    except CaptureReplayWitnessError as error:
        return str(error)
    return "UNEXPECTED_ACCEPT"


def exercise() -> dict[str, object]:
    verifier = CaptureReplayWitnessVerifier(
        provider_id=PROVIDER_ID,
        key_id=KEY_ID,
        verifying_key=VERIFYING_KEY,
        max_age_seconds=300,
        max_future_skew_seconds=5,
    )
    current_state = state(2)
    unsigned = sign(current_state)
    del unsigned["signature"]
    tampered = sign(current_state)
    tampered["state"]["rowset_sha256"] = "f" * 64

    return {
        "valid": verifier.verify(
            sign(current_state),
            local_state=current_state,
            minimum_sequence=2,
            now=NOW,
        ),
        "unsigned": rejected(
            verifier, unsigned, local_state=current_state
        ),
        "wrong_key": rejected(
            verifier,
            sign(current_state, key=WRONG_KEY),
            local_state=current_state,
        ),
        "stale": rejected(
            verifier,
            sign(current_state, issued_at=NOW - 301),
            local_state=current_state,
        ),
        "regressed": rejected(
            verifier, sign(state(1)), local_state=current_state
        ),
        "co_rollback": rejected(
            verifier, sign(current_state), local_state=state(1)
        ),
        "tampered": rejected(
            verifier, tampered, local_state=current_state
        ),
    }


def main() -> None:
    print(
        json.dumps(
            {
                "authentication": "HMAC_SHA256_SHARED_SECRET_FIXTURE_ONLY",
                "live_external_witness": "NOT_RUN",
                "result": exercise(),
                "seed": "NONE",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
