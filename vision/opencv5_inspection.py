"""Fail-closed OpenCV 5 inspection over fixed synthetic grayscale frames.

This module exercises real OpenCV image operations. It is not a camera,
physical safety controller, AWS deployment, or production vision system.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from importlib.metadata import PackageNotFoundError, version
import json
import math
from numbers import Real
from pathlib import Path
import sqlite3
import threading

import cv2
import numpy as np


OPENCV_VERSION = "5.0.0"
PACKAGE_VERSION = "5.0.0.93"
PIPELINE_VERSION = "opencv5-threshold-v1"
CAPTURE_ENVELOPE_SCHEMA_VERSION = 1
MIN_VISIBLE_FRACTION = 0.90
MAX_VIEW_CAPTURE_SKEW_SECONDS = 0.25
MAX_BATCH_VIEW_TIME_DIVERGENCE_SECONDS = 0.25
REPLAY_LEDGER_BUSY_TIMEOUT_MS = 5000
REPLAY_LEDGER_WAL_AUTOCHECKPOINT_PAGES = 1000
REPLAY_LEDGER_CAPTURE_TABLE_SQL = """CREATE TABLE capture_replay (
    capture_id TEXT PRIMARY KEY,
    envelope_schema_version INTEGER NOT NULL,
    envelope_sha256 TEXT NOT NULL,
    policy_sha256 TEXT NOT NULL
)"""
REPLAY_LEDGER_CAPTURE_TABLE_INFO = (
    (0, "capture_id", "TEXT", 0, None, 1),
    (1, "envelope_schema_version", "INTEGER", 1, None, 0),
    (2, "envelope_sha256", "TEXT", 1, None, 0),
    (3, "policy_sha256", "TEXT", 1, None, 0),
)
REPLAY_LEDGER_ROWSET_SCHEMA_VERSION = 1
REPLAY_LEDGER_ROWSET_TABLE_SQL = """CREATE TABLE replay_ledger_rowset (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    rowset_schema_version INTEGER NOT NULL,
    row_count INTEGER NOT NULL,
    rowset_sha256 TEXT NOT NULL
)"""
REPLAY_LEDGER_ROWSET_TABLE_INFO = (
    (0, "singleton", "INTEGER", 0, None, 1),
    (1, "rowset_schema_version", "INTEGER", 1, None, 0),
    (2, "row_count", "INTEGER", 1, None, 0),
    (3, "rowset_sha256", "TEXT", 1, None, 0),
)
REPLAY_LEDGER_ANCHOR_RECOVERY_VERSION = 1
REPLAY_LEDGER_EXTERNAL_WITNESS_VERSION = 1
REPLAY_LEDGER_DOMAIN_WITNESS_VERSION = 2
REPLAY_LEDGER_ALGORITHM_WITNESS_VERSION = 3
REPLAY_LEDGER_POLICY_EPOCH_WITNESS_VERSION = 4
REPLAY_LEDGER_WITNESS_SIGNATURE_ALGORITHM = "HMAC-SHA256"
REPLAY_LEDGER_WITNESS_SIGNATURE_ALGORITHMS = {
    "HMAC-SHA256": hashlib.sha256,
    "HMAC-SHA512": hashlib.sha512,
}
REPLAY_LEDGER_ANCHOR_TRANSITION_TABLE_SQL = """CREATE TABLE replay_ledger_anchor_transition (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    transition_id TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL
)"""
REPLAY_LEDGER_ANCHOR_TRANSITION_TABLE_INFO = (
    (0, "singleton", "INTEGER", 0, None, 1),
    (1, "transition_id", "TEXT", 1, None, 0),
    (2, "receipt_json", "TEXT", 1, None, 0),
    (3, "receipt_sha256", "TEXT", 1, None, 0),
)
REPLAY_LEDGER_POLICY_SCHEMA_VERSION = 1
REPLAY_LEDGER_POLICY_TABLE_SQL = """CREATE TABLE replay_ledger_policy (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    policy_schema_version INTEGER NOT NULL,
    max_entries INTEGER NOT NULL,
    max_wal_backlog_frames INTEGER NOT NULL,
    max_new_entries_per_batch INTEGER NOT NULL
)"""
REPLAY_LEDGER_POLICY_TABLE_INFO = (
    (0, "singleton", "INTEGER", 0, None, 1),
    (1, "policy_schema_version", "INTEGER", 1, None, 0),
    (2, "max_entries", "INTEGER", 1, None, 0),
    (3, "max_wal_backlog_frames", "INTEGER", 1, None, 0),
    (4, "max_new_entries_per_batch", "INTEGER", 1, None, 0),
)
CALIBRATION_GEOMETRY = "synthetic-24x16-roi-8-4-16-12-v1"
VIEW_SOURCE_IDS = {
    "front": "camera-front-v1",
    "side": "camera-side-v1",
}
CALIBRATION_PROFILE = {
    "geometry": CALIBRATION_GEOMETRY,
    "view_source_ids": VIEW_SOURCE_IDS,
}
CALIBRATION_DIGEST = hashlib.sha256(
    json.dumps(CALIBRATION_PROFILE, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


@dataclass(frozen=True)
class View:
    pixels: np.ndarray
    visible_fraction: float = 1.0
    source_id: str | None = None
    capture_id: str | None = None
    captured_at: float | None = None


class CaptureReplayLedgerSchemaError(RuntimeError):
    """Raised when persisted replay state cannot be safely interpreted."""


class CaptureReplayLedgerIntegrityError(RuntimeError):
    """Raised when replay storage or persisted rows fail integrity checks."""


class CaptureReplayLedgerDurabilityError(RuntimeError):
    """Raised when SQLite cannot provide the required durability contract."""


class CaptureReplayLedgerAnchorError(RuntimeError):
    """Raised when an external monotonic replay anchor cannot be trusted."""


class CaptureReplayWitnessError(RuntimeError):
    """Raised when signed replay-ledger witness evidence fails closed."""


@dataclass(frozen=True)
class CaptureReplayAnchorState:
    """Provider-neutral commitment to one complete replay-ledger state."""

    sequence: int
    rowset_sha256: str
    policy_sha256: str
    capture_schema_sha256: str
    rowset_schema_sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "sequence": self.sequence,
            "rowset_sha256": self.rowset_sha256,
            "policy_sha256": self.policy_sha256,
            "capture_schema_sha256": self.capture_schema_sha256,
            "rowset_schema_sha256": self.rowset_schema_sha256,
        }


@dataclass(frozen=True)
class CaptureReplayWitnessKey:
    """Bounded local-fixture trust policy for one witness key."""

    verifying_key: bytes
    active_from: int = 0
    retire_at: int | None = None
    key_epoch: int = 0


@dataclass(frozen=True)
class CaptureReplayWitnessDomain:
    """Signed use-domain for one replay-ledger witness attestation."""

    application_id: str
    purpose: str
    ledger_id: str
    deployment_environment: str
    signature_algorithm: str = REPLAY_LEDGER_WITNESS_SIGNATURE_ALGORITHM

    def as_dict(self) -> dict[str, str]:
        return {
            "application_id": self.application_id,
            "purpose": self.purpose,
            "ledger_id": self.ledger_id,
            "deployment_environment": self.deployment_environment,
            "signature_algorithm": self.signature_algorithm,
        }


class CaptureReplayAnchor:
    """Minimal compare-and-swap contract for a monotonic external anchor."""

    def read(self) -> CaptureReplayAnchorState | None:
        raise NotImplementedError

    def compare_and_swap(
        self,
        expected: CaptureReplayAnchorState | None,
        replacement: CaptureReplayAnchorState,
    ) -> bool:
        raise NotImplementedError


class CaptureReplayWitnessVerifier:
    """Verify a bounded HMAC fixture witness without claiming live trust.

    HMAC is used only to make the local negative controls deterministic. A
    deployed external witness should replace this shared-secret fixture with
    an independently administered asymmetric or managed signing service.
    """

    _PAYLOAD_FIELDS = {
        "witness_version",
        "provider_id",
        "key_id",
        "issued_at",
        "state",
    }
    _DOMAIN_FIELDS = {
        "application_id",
        "purpose",
        "ledger_id",
        "deployment_environment",
        "signature_algorithm",
    }
    _REVOCATION_EPOCH_FIELD = "revocation_epoch"
    _KEY_EPOCH_FIELD = "key_epoch"
    _MIGRATION_EPOCH_FIELD = "migration_epoch"

    def __init__(
        self,
        *,
        provider_id: str,
        key_id: str | None = None,
        verifying_key: bytes | None = None,
        trusted_keys: dict[str, CaptureReplayWitnessKey] | None = None,
        expected_domain: CaptureReplayWitnessDomain | None = None,
        required_key_epoch: int | None = None,
        required_migration_epoch: int | None = None,
        max_age_seconds: int,
        max_future_skew_seconds: int = 5,
    ) -> None:
        if (
            not isinstance(provider_id, str)
            or provider_id != provider_id.strip()
            or not provider_id
            or len(provider_id) > 128
        ):
            raise ValueError("provider_id must be a non-empty bounded string")
        if trusted_keys is None:
            if key_id is None or verifying_key is None:
                raise ValueError(
                    "key_id and verifying_key are required without trusted_keys"
                )
            trusted_keys = {key_id: CaptureReplayWitnessKey(verifying_key)}
        elif key_id is not None or verifying_key is not None:
            raise ValueError(
                "use either key_id/verifying_key or trusted_keys, not both"
            )
        if not isinstance(trusted_keys, dict) or not 1 <= len(trusted_keys) <= 16:
            raise ValueError("trusted_keys must contain between 1 and 16 keys")
        normalized_keys = {}
        for trusted_key_id, policy in trusted_keys.items():
            if (
                not isinstance(trusted_key_id, str)
                or trusted_key_id != trusted_key_id.strip()
                or not trusted_key_id
                or len(trusted_key_id) > 128
            ):
                raise ValueError("key_id must be a non-empty bounded string")
            if not isinstance(policy, CaptureReplayWitnessKey):
                raise TypeError("trusted key policy must be CaptureReplayWitnessKey")
            if (
                not isinstance(policy.verifying_key, bytes)
                or len(policy.verifying_key) < 32
            ):
                raise ValueError("verifying_key must contain at least 32 bytes")
            if (
                not isinstance(policy.active_from, int)
                or isinstance(policy.active_from, bool)
                or policy.active_from < 0
            ):
                raise ValueError("active_from must be a non-negative integer")
            if policy.retire_at is not None and (
                not isinstance(policy.retire_at, int)
                or isinstance(policy.retire_at, bool)
                or policy.retire_at <= policy.active_from
            ):
                raise ValueError("retire_at must be later than active_from")
            if (
                not isinstance(policy.key_epoch, int)
                or isinstance(policy.key_epoch, bool)
                or policy.key_epoch < 0
            ):
                raise ValueError("key_epoch must be a non-negative integer")
            normalized_keys[trusted_key_id] = policy
        if (
            not isinstance(max_age_seconds, int)
            or isinstance(max_age_seconds, bool)
            or max_age_seconds <= 0
        ):
            raise ValueError("max_age_seconds must be a positive integer")
        if (
            not isinstance(max_future_skew_seconds, int)
            or isinstance(max_future_skew_seconds, bool)
            or max_future_skew_seconds < 0
        ):
            raise ValueError("max_future_skew_seconds must be a non-negative integer")
        if expected_domain is not None:
            if not isinstance(expected_domain, CaptureReplayWitnessDomain):
                raise TypeError("expected_domain must be CaptureReplayWitnessDomain")
            for name, value in expected_domain.as_dict().items():
                if (
                    not isinstance(value, str)
                    or value != value.strip()
                    or not value
                    or len(value) > 128
                    or "\0" in value
                ):
                    raise ValueError(f"{name} must be a non-empty bounded string")
            if expected_domain.signature_algorithm not in (
                REPLAY_LEDGER_WITNESS_SIGNATURE_ALGORITHMS
            ):
                raise ValueError("unsupported witness signature algorithm")
        if required_key_epoch is not None and (
            expected_domain is None
            or not isinstance(required_key_epoch, int)
            or isinstance(required_key_epoch, bool)
            or required_key_epoch < 0
        ):
            raise ValueError(
                "required_key_epoch needs a domain and a non-negative integer"
            )
        if required_migration_epoch is not None and (
            required_key_epoch is None
            or not isinstance(required_migration_epoch, int)
            or isinstance(required_migration_epoch, bool)
            or required_migration_epoch < 0
        ):
            raise ValueError(
                "required_migration_epoch needs a key epoch and a non-negative integer"
            )
        self.provider_id = provider_id
        self._trusted_keys = normalized_keys
        self.expected_domain = expected_domain
        self.required_key_epoch = required_key_epoch
        self.required_migration_epoch = required_migration_epoch
        self.max_age_seconds = max_age_seconds
        self.max_future_skew_seconds = max_future_skew_seconds

    @classmethod
    def canonical_payload(cls, payload: object) -> bytes:
        """Return the exact signed bytes for a schema-valid payload."""
        valid_fields = (
            cls._PAYLOAD_FIELDS,
            cls._PAYLOAD_FIELDS | {cls._REVOCATION_EPOCH_FIELD},
            cls._PAYLOAD_FIELDS | cls._DOMAIN_FIELDS,
            cls._PAYLOAD_FIELDS | cls._DOMAIN_FIELDS | {cls._REVOCATION_EPOCH_FIELD},
            cls._PAYLOAD_FIELDS | cls._DOMAIN_FIELDS | {cls._KEY_EPOCH_FIELD},
            cls._PAYLOAD_FIELDS
            | cls._DOMAIN_FIELDS
            | {cls._REVOCATION_EPOCH_FIELD, cls._KEY_EPOCH_FIELD},
            cls._PAYLOAD_FIELDS
            | cls._DOMAIN_FIELDS
            | {cls._KEY_EPOCH_FIELD, cls._MIGRATION_EPOCH_FIELD},
            cls._PAYLOAD_FIELDS
            | cls._DOMAIN_FIELDS
            | {
                cls._REVOCATION_EPOCH_FIELD,
                cls._KEY_EPOCH_FIELD,
                cls._MIGRATION_EPOCH_FIELD,
            },
        )
        if not isinstance(payload, dict) or set(payload) not in valid_fields:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_SCHEMA_INVALID")
        try:
            return json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise CaptureReplayWitnessError(
                "REPLAY_LEDGER_WITNESS_SCHEMA_INVALID"
            ) from error

    @staticmethod
    def _state_from_value(value: object) -> CaptureReplayAnchorState:
        if not isinstance(value, dict) or set(value) != {
            "sequence",
            "rowset_sha256",
            "policy_sha256",
            "capture_schema_sha256",
            "rowset_schema_sha256",
        }:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_STATE_INVALID")
        state = CaptureReplayAnchorState(
            sequence=value["sequence"],
            rowset_sha256=value["rowset_sha256"],
            policy_sha256=value["policy_sha256"],
            capture_schema_sha256=value["capture_schema_sha256"],
            rowset_schema_sha256=value["rowset_schema_sha256"],
        )
        if not CaptureReplayLedger._valid_anchor_state(state):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_STATE_INVALID")
        return state

    def verify(
        self,
        witness: object,
        *,
        local_state: CaptureReplayAnchorState,
        minimum_sequence: int,
        now: int,
        required_revocation_epoch: int | None = None,
    ) -> dict[str, int | str]:
        """Authenticate and compare a witness against local monotonic state."""
        if not isinstance(witness, dict):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_SCHEMA_INVALID")
        if "signature" not in witness:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_UNSIGNED")
        witness_fields = set(witness) - {"signature"}
        expected_fields = self._PAYLOAD_FIELDS
        expected_version = REPLAY_LEDGER_EXTERNAL_WITNESS_VERSION
        if self.expected_domain is not None:
            expected_fields = expected_fields | self._DOMAIN_FIELDS
            expected_version = REPLAY_LEDGER_DOMAIN_WITNESS_VERSION
            if self.required_key_epoch is not None:
                expected_fields = expected_fields | {self._KEY_EPOCH_FIELD}
                expected_version = REPLAY_LEDGER_ALGORITHM_WITNESS_VERSION
                if self.required_migration_epoch is not None:
                    expected_fields = expected_fields | {self._MIGRATION_EPOCH_FIELD}
                    expected_version = REPLAY_LEDGER_POLICY_EPOCH_WITNESS_VERSION
        if witness_fields not in (
            expected_fields,
            expected_fields | {self._REVOCATION_EPOCH_FIELD},
        ):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_SCHEMA_INVALID")
        payload = {name: witness[name] for name in witness_fields}
        if (
            payload["witness_version"] != expected_version
            or payload["provider_id"] != self.provider_id
        ):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_IDENTITY_MISMATCH")
        if self.expected_domain is not None:
            domain_failures = {
                "application_id": "REPLAY_LEDGER_WITNESS_APPLICATION_MISMATCH",
                "purpose": "REPLAY_LEDGER_WITNESS_PURPOSE_MISMATCH",
                "ledger_id": "REPLAY_LEDGER_WITNESS_LEDGER_MISMATCH",
                "deployment_environment": (
                    "REPLAY_LEDGER_WITNESS_ENVIRONMENT_MISMATCH"
                ),
                "signature_algorithm": "REPLAY_LEDGER_WITNESS_ALGORITHM_MISMATCH",
            }
            for name, expected in self.expected_domain.as_dict().items():
                actual = payload[name]
                if (
                    not isinstance(actual, str)
                    or actual != actual.strip()
                    or not actual
                    or len(actual) > 128
                    or "\0" in actual
                ):
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_SCHEMA_INVALID"
                    )
                if actual != expected:
                    raise CaptureReplayWitnessError(domain_failures[name])
        issued_at = payload["issued_at"]
        witness_key_id = payload["key_id"]
        key_epoch = payload.get(self._KEY_EPOCH_FIELD)
        migration_epoch = payload.get(self._MIGRATION_EPOCH_FIELD)
        revocation_epoch = payload.get(self._REVOCATION_EPOCH_FIELD)
        signature = witness["signature"]
        signature_algorithm = payload.get(
            "signature_algorithm", REPLAY_LEDGER_WITNESS_SIGNATURE_ALGORITHM
        )
        digest = REPLAY_LEDGER_WITNESS_SIGNATURE_ALGORITHMS.get(signature_algorithm)
        signature_length = digest().digest_size * 2 if digest is not None else 0
        if (
            not isinstance(issued_at, int)
            or isinstance(issued_at, bool)
            or issued_at < 0
            or not isinstance(signature, str)
            or len(signature) != signature_length
            or any(character not in "0123456789abcdef" for character in signature)
        ):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_SCHEMA_INVALID")
        if digest is None:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_ALGORITHM_MISMATCH")
        if key_epoch is not None and (
            not isinstance(key_epoch, int)
            or isinstance(key_epoch, bool)
            or key_epoch < 0
        ):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_SCHEMA_INVALID")
        if revocation_epoch is not None and (
            not isinstance(revocation_epoch, int)
            or isinstance(revocation_epoch, bool)
            or revocation_epoch < 0
        ):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_SCHEMA_INVALID")
        if migration_epoch is not None and (
            not isinstance(migration_epoch, int)
            or isinstance(migration_epoch, bool)
            or migration_epoch < 0
        ):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_SCHEMA_INVALID")
        if (
            not isinstance(witness_key_id, str)
            or witness_key_id != witness_key_id.strip()
            or not witness_key_id
            or len(witness_key_id) > 128
        ):
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_SCHEMA_INVALID")
        if not isinstance(now, int) or isinstance(now, bool) or now < 0:
            raise ValueError("now must be a non-negative integer")
        key_policy = self._trusted_keys.get(witness_key_id)
        if key_policy is None:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_KEY_UNKNOWN")
        if self.required_key_epoch is not None:
            if key_epoch != self.required_key_epoch:
                raise CaptureReplayWitnessError(
                    "REPLAY_LEDGER_WITNESS_KEY_EPOCH_MISMATCH"
                )
            if key_policy.key_epoch != self.required_key_epoch:
                raise CaptureReplayWitnessError(
                    "REPLAY_LEDGER_WITNESS_KEY_POLICY_EPOCH_MISMATCH"
                )
        if (
            self.required_migration_epoch is not None
            and migration_epoch != self.required_migration_epoch
        ):
            raise CaptureReplayWitnessError(
                "REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_MISMATCH"
            )
        if now < key_policy.active_from:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_KEY_NOT_YET_ACTIVE")
        if key_policy.retire_at is not None and now >= key_policy.retire_at:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_KEY_RETIRED")
        expected_signature = hmac.new(
            key_policy.verifying_key,
            self.canonical_payload(payload),
            digest,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise CaptureReplayWitnessError(
                "REPLAY_LEDGER_WITNESS_AUTHENTICATION_FAILED"
            )
        if required_revocation_epoch is not None:
            if (
                not isinstance(required_revocation_epoch, int)
                or isinstance(required_revocation_epoch, bool)
                or required_revocation_epoch < 0
            ):
                raise ValueError(
                    "required_revocation_epoch must be a non-negative integer"
                )
            if revocation_epoch is None:
                raise CaptureReplayWitnessError(
                    "REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_MISSING"
                )
            if revocation_epoch < required_revocation_epoch:
                raise CaptureReplayWitnessError(
                    "REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_STALE"
                )
            if revocation_epoch > required_revocation_epoch:
                raise CaptureReplayWitnessError(
                    "REPLAY_LEDGER_WITNESS_REVOCATION_EPOCH_FROM_FUTURE"
                )
        if issued_at > now + self.max_future_skew_seconds:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_FROM_FUTURE")
        if now - issued_at > self.max_age_seconds:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_STALE")
        if (
            not isinstance(minimum_sequence, int)
            or isinstance(minimum_sequence, bool)
            or minimum_sequence < 0
        ):
            raise ValueError("minimum_sequence must be a non-negative integer")
        state = self._state_from_value(payload["state"])
        if state.sequence < minimum_sequence:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_REGRESSED")
        if not CaptureReplayLedger._valid_anchor_state(local_state):
            raise ValueError("local_state must be a valid anchor state")
        if local_state.sequence < state.sequence:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_ROLLBACK_DETECTED")
        if local_state.sequence > state.sequence:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_BEHIND")
        if local_state != state:
            raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_STATE_MISMATCH")
        result = {
            "status": "VERIFIED_AUTHENTICATED_FIXTURE",
            "provider_id": self.provider_id,
            "key_id": witness_key_id,
            "issued_at": issued_at,
            "sequence": state.sequence,
        }
        if self.expected_domain is not None:
            result.update(self.expected_domain.as_dict())
        if revocation_epoch is not None:
            result["revocation_epoch"] = revocation_epoch
        if key_epoch is not None:
            result["key_epoch"] = key_epoch
        if migration_epoch is not None:
            result["migration_epoch"] = migration_epoch
        return result


class CaptureReplayWitnessRevocationStore:
    """Persist and serialize fixture witness revocation policy.

    The store intentionally shares one SQLite write lock between revocation and
    verified-attestation append. This makes their winning order authoritative:
    an append that commits first is historical evidence, while a revocation
    that commits first causes the old epoch to fail closed. It is still only a
    local HMAC fixture and does not claim an independently managed service.
    """

    _STATE_SQL = """CREATE TABLE replay_ledger_witness_revocation_state (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        revocation_epoch INTEGER NOT NULL CHECK (revocation_epoch >= 0)
    )"""
    _REVOKED_KEY_SQL = """CREATE TABLE replay_ledger_witness_revoked_key (
        provider_id TEXT NOT NULL,
        key_id TEXT NOT NULL,
        revoked_epoch INTEGER NOT NULL CHECK (revoked_epoch > 0),
        PRIMARY KEY (provider_id, key_id)
    )"""
    _ATTESTATION_SQL = """CREATE TABLE replay_ledger_witness_attestation (
        fingerprint_sha256 TEXT PRIMARY KEY,
        provider_id TEXT NOT NULL,
        key_id TEXT NOT NULL,
        revocation_epoch INTEGER NOT NULL CHECK (revocation_epoch >= 0),
        issued_at INTEGER NOT NULL CHECK (issued_at >= 0),
        sequence INTEGER NOT NULL CHECK (sequence >= 0),
        witness_json TEXT NOT NULL
    )"""
    _DOMAIN_SQL = """CREATE TABLE replay_ledger_witness_domain (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        application_id TEXT NOT NULL,
        purpose TEXT NOT NULL,
        ledger_id TEXT NOT NULL,
        deployment_environment TEXT NOT NULL,
        signature_algorithm TEXT NOT NULL
    )"""
    _ALGORITHM_POLICY_SQL = """CREATE TABLE replay_ledger_witness_algorithm_policy (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        signature_algorithm TEXT NOT NULL,
        key_id TEXT NOT NULL,
        key_epoch INTEGER NOT NULL CHECK (key_epoch >= 0),
        migration_epoch INTEGER NOT NULL CHECK (migration_epoch >= 0)
    )"""

    def __init__(self, database: str | Path) -> None:
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(
            str(database),
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            self._connection.execute(
                f"PRAGMA busy_timeout = {REPLAY_LEDGER_BUSY_TIMEOUT_MS}"
            )
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute(
                self._STATE_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            self._connection.execute(
                self._REVOKED_KEY_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            self._connection.execute(
                self._ATTESTATION_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            self._connection.execute(
                self._DOMAIN_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            self._connection.execute(
                self._ALGORITHM_POLICY_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            policy_columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(replay_ledger_witness_algorithm_policy)"
                ).fetchall()
            }
            if "migration_epoch" not in policy_columns:
                self._connection.execute(
                    "ALTER TABLE replay_ledger_witness_algorithm_policy "
                    "ADD COLUMN migration_epoch INTEGER NOT NULL DEFAULT 0 "
                    "CHECK (migration_epoch >= 0)"
                )
            self._connection.execute(
                "INSERT OR IGNORE INTO replay_ledger_witness_revocation_state "
                "VALUES (1, 0)"
            )
            if self._connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise CaptureReplayLedgerIntegrityError("SQLITE_INTEGRITY_CHECK_FAILED")
            rows = self._connection.execute(
                "SELECT singleton, revocation_epoch "
                "FROM replay_ledger_witness_revocation_state"
            ).fetchall()
            if (
                len(rows) != 1
                or rows[0][0] != 1
                or not isinstance(rows[0][1], int)
                or rows[0][1] < 0
            ):
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_WITNESS_REVOCATION_STATE_INVALID"
                )
        except BaseException:
            self._connection.close()
            raise

    def __enter__(self) -> CaptureReplayWitnessRevocationStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _valid_identity(value: object) -> bool:
        return (
            isinstance(value, str)
            and value == value.strip()
            and 1 <= len(value) <= 128
            and "\0" not in value
        )

    def _current_epoch_unlocked(self) -> int:
        row = self._connection.execute(
            "SELECT revocation_epoch "
            "FROM replay_ledger_witness_revocation_state WHERE singleton = 1"
        ).fetchone()
        if row is None or not isinstance(row[0], int) or row[0] < 0:
            raise CaptureReplayLedgerSchemaError(
                "REPLAY_LEDGER_WITNESS_REVOCATION_STATE_INVALID"
            )
        return int(row[0])

    def current_epoch(self) -> int:
        with self._lock:
            return self._current_epoch_unlocked()

    def _revocation_list_unlocked(self) -> tuple[tuple[str, str], ...]:
        rows = self._connection.execute(
            "SELECT provider_id, key_id "
            "FROM replay_ledger_witness_revoked_key "
            "ORDER BY provider_id, key_id"
        ).fetchall()
        revocations: list[tuple[str, str]] = []
        for provider_id, key_id in rows:
            if not self._valid_identity(provider_id) or not self._valid_identity(
                key_id
            ):
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_INVALID"
                )
            revocations.append((str(provider_id), str(key_id)))
        return tuple(revocations)

    def revocation_list_state(self) -> tuple[int, tuple[tuple[str, str], ...]]:
        """Return the monotonic epoch and complete persisted revocation list."""
        with self._lock:
            return self._current_epoch_unlocked(), self._revocation_list_unlocked()

    def attestation_count(self) -> int:
        with self._lock:
            return int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM replay_ledger_witness_attestation"
                ).fetchone()[0]
            )

    def active_algorithm_policy(self) -> tuple[str, str, int] | None:
        """Return the persisted algorithm/key epoch policy, if initialized."""
        with self._lock:
            row = self._connection.execute(
                "SELECT signature_algorithm, key_id, key_epoch "
                "FROM replay_ledger_witness_algorithm_policy WHERE singleton = 1"
            ).fetchone()
            if row is None:
                return None
            return str(row[0]), str(row[1]), int(row[2])

    def active_algorithm_policy_state(self) -> tuple[str, str, int, int] | None:
        """Return algorithm, key epoch, and monotonic migration epoch."""
        with self._lock:
            row = self._connection.execute(
                "SELECT signature_algorithm, key_id, key_epoch, migration_epoch "
                "FROM replay_ledger_witness_algorithm_policy WHERE singleton = 1"
            ).fetchone()
            if row is None:
                return None
            return str(row[0]), str(row[1]), int(row[2]), int(row[3])

    def migrate_algorithm(
        self,
        *,
        expected_algorithm: str,
        expected_key_id: str,
        expected_key_epoch: int,
        replacement_algorithm: str,
        replacement_key_id: str,
        replacement_key_epoch: int,
        expected_migration_epoch: int = 0,
        replacement_migration_epoch: int = 1,
    ) -> tuple[str, str, int]:
        """CAS the active policy while monotonically advancing its epoch."""
        if (
            expected_algorithm not in REPLAY_LEDGER_WITNESS_SIGNATURE_ALGORITHMS
            or replacement_algorithm not in REPLAY_LEDGER_WITNESS_SIGNATURE_ALGORITHMS
            or not self._valid_identity(expected_key_id)
            or not self._valid_identity(replacement_key_id)
            or not isinstance(expected_key_epoch, int)
            or isinstance(expected_key_epoch, bool)
            or expected_key_epoch < 0
            or not isinstance(replacement_key_epoch, int)
            or isinstance(replacement_key_epoch, bool)
            or replacement_key_epoch < 0
            or not isinstance(expected_migration_epoch, int)
            or isinstance(expected_migration_epoch, bool)
            or expected_migration_epoch < 0
            or not isinstance(replacement_migration_epoch, int)
            or isinstance(replacement_migration_epoch, bool)
        ):
            raise ValueError("invalid witness algorithm migration")
        expected = (
            expected_algorithm,
            expected_key_id,
            expected_key_epoch,
            expected_migration_epoch,
        )
        replacement = (
            replacement_algorithm,
            replacement_key_id,
            replacement_key_epoch,
            replacement_migration_epoch,
        )
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT signature_algorithm, key_id, key_epoch, migration_epoch "
                    "FROM replay_ledger_witness_algorithm_policy "
                    "WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_ALGORITHM_POLICY_UNINITIALIZED"
                    )
                current = (str(row[0]), str(row[1]), int(row[2]), int(row[3]))
                if current != expected:
                    if current == replacement:
                        self._connection.execute("COMMIT")
                        return replacement[:3]
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_ALGORITHM_MIGRATION_CONFLICT"
                    )
                if replacement_migration_epoch <= int(current[3]):
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_POLICY_ROLLBACK"
                    )
                if replacement_migration_epoch != int(current[3]) + 1:
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_GAP"
                    )
                domain_row = self._connection.execute(
                    "SELECT signature_algorithm "
                    "FROM replay_ledger_witness_domain WHERE singleton = 1"
                ).fetchone()
                if domain_row is None or str(domain_row[0]) != expected_algorithm:
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_ALGORITHM_MIGRATION_CONFLICT"
                    )
                self._connection.execute(
                    "UPDATE replay_ledger_witness_algorithm_policy "
                    "SET signature_algorithm = ?, key_id = ?, key_epoch = ?, "
                    "migration_epoch = ? "
                    "WHERE singleton = 1",
                    replacement,
                )
                self._connection.execute(
                    "UPDATE replay_ledger_witness_domain "
                    "SET signature_algorithm = ? WHERE singleton = 1",
                    (replacement_algorithm,),
                )
                self._connection.execute("COMMIT")
                return replacement[:3]
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def revoke(self, provider_id: str, key_id: str) -> int:
        """Idempotently revoke a key and return its persisted epoch."""
        if not self._valid_identity(provider_id) or not self._valid_identity(key_id):
            raise ValueError("provider_id and key_id must be bounded strings")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._connection.execute(
                    "SELECT revoked_epoch "
                    "FROM replay_ledger_witness_revoked_key "
                    "WHERE provider_id = ? AND key_id = ?",
                    (provider_id, key_id),
                ).fetchone()
                if existing is not None:
                    self._connection.execute("COMMIT")
                    return int(existing[0])
                epoch = self._current_epoch_unlocked() + 1
                self._connection.execute(
                    "UPDATE replay_ledger_witness_revocation_state "
                    "SET revocation_epoch = ? WHERE singleton = 1",
                    (epoch,),
                )
                self._connection.execute(
                    "INSERT INTO replay_ledger_witness_revoked_key VALUES (?, ?, ?)",
                    (provider_id, key_id, epoch),
                )
                self._connection.execute("COMMIT")
                return epoch
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def cas_update_revocation_list(
        self,
        *,
        expected_epoch: int,
        replacement_epoch: int,
        revoked_keys: object,
    ) -> tuple[int, tuple[tuple[str, str], ...]]:
        """CAS an additive revocation-list snapshot and advance one epoch.

        ``revoked_keys`` is the complete replacement snapshot, not a delta.
        Once persisted, identities cannot be removed by a later update.  An
        exact retry of the already-committed replacement is idempotent.
        """
        if (
            not isinstance(expected_epoch, int)
            or isinstance(expected_epoch, bool)
            or expected_epoch < 0
            or not isinstance(replacement_epoch, int)
            or isinstance(replacement_epoch, bool)
            or replacement_epoch < 0
            or not isinstance(revoked_keys, (list, tuple, set, frozenset))
            or not 1 <= len(revoked_keys) <= 64
        ):
            raise ValueError("invalid witness revocation-list update")
        normalized: set[tuple[str, str]] = set()
        for identity in revoked_keys:
            if (
                not isinstance(identity, (list, tuple))
                or len(identity) != 2
                or not self._valid_identity(identity[0])
                or not self._valid_identity(identity[1])
            ):
                raise ValueError("invalid witness revocation-list identity")
            normalized.add((str(identity[0]), str(identity[1])))
        if len(normalized) != len(revoked_keys):
            raise ValueError("duplicate witness revocation-list identity")
        replacement = tuple(sorted(normalized))
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                current_epoch = self._current_epoch_unlocked()
                current = self._revocation_list_unlocked()
                if expected_epoch != current_epoch:
                    if replacement_epoch == current_epoch and replacement == current:
                        self._connection.execute("COMMIT")
                        return current_epoch, current
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_CONFLICT"
                    )
                if replacement_epoch <= current_epoch:
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_ROLLBACK"
                    )
                if replacement_epoch != current_epoch + 1:
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_EPOCH_GAP"
                    )
                if not set(current).issubset(normalized):
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_ROLLBACK"
                    )
                if replacement == current:
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_NO_CHANGE"
                    )
                for provider_id, key_id in sorted(normalized - set(current)):
                    self._connection.execute(
                        "INSERT INTO replay_ledger_witness_revoked_key "
                        "VALUES (?, ?, ?)",
                        (provider_id, key_id, replacement_epoch),
                    )
                cursor = self._connection.execute(
                    "UPDATE replay_ledger_witness_revocation_state "
                    "SET revocation_epoch = ? "
                    "WHERE singleton = 1 AND revocation_epoch = ?",
                    (replacement_epoch, expected_epoch),
                )
                if cursor.rowcount != 1:
                    raise CaptureReplayWitnessError(
                        "REPLAY_LEDGER_WITNESS_REVOCATION_LIST_CONFLICT"
                    )
                self._connection.execute("COMMIT")
                return replacement_epoch, replacement
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def verify_and_append(
        self,
        verifier: CaptureReplayWitnessVerifier,
        witness: object,
        *,
        local_state: CaptureReplayAnchorState,
        minimum_sequence: int,
        now: int,
    ) -> dict[str, int | str]:
        """Verify and append under the same lock used by revocation."""
        if not isinstance(verifier, CaptureReplayWitnessVerifier):
            raise TypeError("verifier must be CaptureReplayWitnessVerifier")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                epoch = self._current_epoch_unlocked()
                result = verifier.verify(
                    witness,
                    local_state=local_state,
                    minimum_sequence=minimum_sequence,
                    now=now,
                    required_revocation_epoch=epoch,
                )
                persisted_domain = self._connection.execute(
                    "SELECT application_id, purpose, ledger_id, "
                    "deployment_environment, signature_algorithm "
                    "FROM replay_ledger_witness_domain WHERE singleton = 1"
                ).fetchone()
                domain = verifier.expected_domain
                if domain is None:
                    if persisted_domain is not None:
                        raise CaptureReplayWitnessError(
                            "REPLAY_LEDGER_WITNESS_DOMAIN_REQUIRED"
                        )
                else:
                    domain_values = tuple(domain.as_dict().values())
                    if persisted_domain is None:
                        self._connection.execute(
                            "INSERT INTO replay_ledger_witness_domain "
                            "VALUES (1, ?, ?, ?, ?, ?)",
                            domain_values,
                        )
                    elif tuple(persisted_domain) != domain_values:
                        if tuple(persisted_domain[:4]) == domain_values[:4]:
                            raise CaptureReplayWitnessError(
                                "REPLAY_LEDGER_WITNESS_ALGORITHM_POLICY_MISMATCH"
                            )
                        raise CaptureReplayWitnessError(
                            "REPLAY_LEDGER_WITNESS_STORE_DOMAIN_MISMATCH"
                        )
                assert isinstance(witness, dict)
                key_id = str(result["key_id"])
                persisted_algorithm = self._connection.execute(
                    "SELECT signature_algorithm, key_id, key_epoch, migration_epoch "
                    "FROM replay_ledger_witness_algorithm_policy "
                    "WHERE singleton = 1"
                ).fetchone()
                if "key_epoch" not in result:
                    if persisted_algorithm is not None:
                        raise CaptureReplayWitnessError(
                            "REPLAY_LEDGER_WITNESS_ALGORITHM_MIGRATION_REQUIRED"
                        )
                else:
                    assert domain is not None
                    requested_migration_epoch = int(result.get("migration_epoch", 0))
                    requested_algorithm = (
                        domain.signature_algorithm,
                        key_id,
                        int(result["key_epoch"]),
                        requested_migration_epoch,
                    )
                    if persisted_algorithm is None:
                        self._connection.execute(
                            "INSERT INTO replay_ledger_witness_algorithm_policy "
                            "VALUES (1, ?, ?, ?, ?)",
                            requested_algorithm,
                        )
                    else:
                        persisted_migration_epoch = int(persisted_algorithm[3])
                        if "migration_epoch" not in result:
                            if persisted_migration_epoch > 0:
                                raise CaptureReplayWitnessError(
                                    "REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_REQUIRED"
                                )
                        elif requested_migration_epoch < persisted_migration_epoch:
                            raise CaptureReplayWitnessError(
                                "REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_STALE"
                            )
                        elif requested_migration_epoch > persisted_migration_epoch:
                            raise CaptureReplayWitnessError(
                                "REPLAY_LEDGER_WITNESS_MIGRATION_EPOCH_FROM_FUTURE"
                            )
                        if tuple(persisted_algorithm) != requested_algorithm:
                            raise CaptureReplayWitnessError(
                                "REPLAY_LEDGER_WITNESS_ALGORITHM_POLICY_MISMATCH"
                            )
                revoked = self._connection.execute(
                    "SELECT revoked_epoch "
                    "FROM replay_ledger_witness_revoked_key "
                    "WHERE provider_id = ? AND key_id = ?",
                    (verifier.provider_id, key_id),
                ).fetchone()
                if revoked is not None:
                    raise CaptureReplayWitnessError("REPLAY_LEDGER_WITNESS_KEY_REVOKED")
                canonical = json.dumps(
                    witness,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
                cursor = self._connection.execute(
                    "INSERT OR IGNORE INTO replay_ledger_witness_attestation "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        fingerprint,
                        verifier.provider_id,
                        key_id,
                        epoch,
                        result["issued_at"],
                        result["sequence"],
                        canonical,
                    ),
                )
                self._connection.execute("COMMIT")
                return {
                    **result,
                    "status": "APPENDED" if cursor.rowcount else "REPLAYED",
                    "fingerprint_sha256": fingerprint,
                    "revocation_epoch": epoch,
                }
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise


def _valid_sha256(digest: object) -> bool:
    return (
        isinstance(digest, str)
        and len(digest) == 64
        and all(c in "0123456789abcdef" for c in digest)
    )


def _valid_replay_entry(capture_id: object, digest: object) -> bool:
    return (
        isinstance(capture_id, str)
        and capture_id == capture_id.strip()
        and 1 <= len(capture_id) <= 256
        and "\0" not in capture_id
        and _valid_sha256(digest)
    )


class CaptureReplayLedger:
    """Bounded durable capture-ID ledger with atomic pair registration."""

    def __init__(
        self,
        database: str | Path,
        *,
        max_entries: int = 10_000,
        max_wal_backlog_frames: int = 1000,
        max_new_entries_per_batch: int = 1000,
        anchor: CaptureReplayAnchor | None = None,
    ):
        if (
            not isinstance(max_entries, int)
            or isinstance(max_entries, bool)
            or max_entries <= 0
        ):
            raise ValueError("max_entries must be a positive integer")
        if (
            not isinstance(max_wal_backlog_frames, int)
            or isinstance(max_wal_backlog_frames, bool)
            or max_wal_backlog_frames <= 0
        ):
            raise ValueError("max_wal_backlog_frames must be a positive integer")
        if (
            not isinstance(max_new_entries_per_batch, int)
            or isinstance(max_new_entries_per_batch, bool)
            or max_new_entries_per_batch <= 0
        ):
            raise ValueError("max_new_entries_per_batch must be a positive integer")
        self.max_entries = max_entries
        self.max_wal_backlog_frames = max_wal_backlog_frames
        self.max_new_entries_per_batch = max_new_entries_per_batch
        if anchor is not None and not isinstance(anchor, CaptureReplayAnchor):
            raise TypeError("anchor must implement CaptureReplayAnchor")
        self._anchor = anchor
        self._lock = threading.Lock()
        self._file_backed = str(database) != ":memory:"
        self._connection = sqlite3.connect(
            str(database),
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            self._connection.execute("PRAGMA busy_timeout = 5000")
            if self._connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise CaptureReplayLedgerIntegrityError("SQLITE_INTEGRITY_CHECK_FAILED")
            capture_table_preexisting = (
                self._connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'capture_replay'"
                ).fetchone()
                is not None
            )
            self._connection.execute(
                REPLAY_LEDGER_CAPTURE_TABLE_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            columns = {
                row[1]
                for row in self._connection.execute("PRAGMA table_info(capture_replay)")
            }
            if "envelope_schema_version" not in columns:
                raise CaptureReplayLedgerSchemaError("LEGACY_REPLAY_LEDGER_SCHEMA")
            if "policy_sha256" not in columns:
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_CAPTURE_POLICY_MISSING"
                )
            if not self._capture_schema_matches_unlocked():
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_CAPTURE_SCHEMA_INVALID"
                )
            versions = {
                int(row[0])
                for row in self._connection.execute(
                    "SELECT DISTINCT envelope_schema_version FROM capture_replay"
                )
            }
            if versions - {CAPTURE_ENVELOPE_SCHEMA_VERSION}:
                raise CaptureReplayLedgerSchemaError("MIXED_REPLAY_LEDGER_SCHEMA")
            rows = self._connection.execute(
                "SELECT capture_id, envelope_sha256, policy_sha256 FROM capture_replay"
            )
            if any(
                not _valid_replay_entry(capture_id, digest)
                or not _valid_sha256(policy_digest)
                for capture_id, digest, policy_digest in rows
            ):
                raise CaptureReplayLedgerIntegrityError("INVALID_REPLAY_LEDGER_ROW")

            policy_table_preexisting = (
                self._connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'replay_ledger_policy'"
                ).fetchone()
                is not None
            )
            if not policy_table_preexisting and capture_table_preexisting:
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_POLICY_METADATA_MISSING"
                )
            self._connection.execute(
                REPLAY_LEDGER_POLICY_TABLE_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            policy_columns = {
                row[1]: int(row[5])
                for row in self._connection.execute(
                    "PRAGMA table_info(replay_ledger_policy)"
                )
            }
            if (
                set(policy_columns)
                != {
                    "singleton",
                    "policy_schema_version",
                    "max_entries",
                    "max_wal_backlog_frames",
                    "max_new_entries_per_batch",
                }
                or policy_columns["singleton"] != 1
            ):
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_POLICY_METADATA_INVALID"
                )
            if not policy_table_preexisting:
                self._connection.execute(
                    "INSERT INTO replay_ledger_policy VALUES (?, ?, ?, ?, ?)",
                    (
                        1,
                        REPLAY_LEDGER_POLICY_SCHEMA_VERSION,
                        self.max_entries,
                        self.max_wal_backlog_frames,
                        self.max_new_entries_per_batch,
                    ),
                )
            if not self._policy_schema_matches_unlocked():
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_POLICY_METADATA_INVALID"
                )
            policy_rows = self._connection.execute(
                "SELECT singleton, policy_schema_version, max_entries, "
                "max_wal_backlog_frames, max_new_entries_per_batch "
                "FROM replay_ledger_policy"
            ).fetchall()
            if (
                len(policy_rows) != 1
                or any(not isinstance(value, int) for value in policy_rows[0])
                or policy_rows[0][0] != 1
                or policy_rows[0][1] != REPLAY_LEDGER_POLICY_SCHEMA_VERSION
                or any(value <= 0 for value in policy_rows[0][2:])
            ):
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_POLICY_METADATA_INVALID"
                )
            if self._policy_evidence_unlocked() != {
                "policy_schema_version": REPLAY_LEDGER_POLICY_SCHEMA_VERSION,
                "max_entries": self.max_entries,
                "max_wal_backlog_frames": self.max_wal_backlog_frames,
                "max_new_entries_per_batch": self.max_new_entries_per_batch,
            }:
                raise CaptureReplayLedgerSchemaError("REPLAY_LEDGER_POLICY_DRIFT")
            expected_policy_digest = self._expected_policy_digest()
            capture_policy_digests = {
                row[0]
                for row in self._connection.execute(
                    "SELECT DISTINCT policy_sha256 FROM capture_replay"
                )
            }
            if capture_policy_digests - {expected_policy_digest}:
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_CAPTURE_POLICY_MISMATCH"
                )

            rowset_table_preexisting = (
                self._connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'replay_ledger_rowset'"
                ).fetchone()
                is not None
            )
            if not rowset_table_preexisting and capture_table_preexisting:
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_ROWSET_METADATA_MISSING"
                )
            self._connection.execute(
                REPLAY_LEDGER_ROWSET_TABLE_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            if not rowset_table_preexisting:
                identity = self._actual_rowset_identity_unlocked()
                self._connection.execute(
                    "INSERT INTO replay_ledger_rowset VALUES (?, ?, ?, ?)",
                    (
                        1,
                        identity["rowset_schema_version"],
                        identity["row_count"],
                        identity["sha256"],
                    ),
                )
            if not self._rowset_schema_matches_unlocked():
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_ROWSET_METADATA_INVALID"
                )
            if not self._rowset_matches_unlocked():
                raise CaptureReplayLedgerIntegrityError("REPLAY_LEDGER_ROWSET_MISMATCH")
            self._connection.execute(
                REPLAY_LEDGER_ANCHOR_TRANSITION_TABLE_SQL.replace(
                    "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                )
            )
            if not self._anchor_transition_schema_matches_unlocked():
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_ANCHOR_TRANSITION_SCHEMA_INVALID"
                )
            self._pending_anchor_recovery_receipt_unlocked()
        except (
            CaptureReplayLedgerSchemaError,
            CaptureReplayLedgerIntegrityError,
            CaptureReplayLedgerAnchorError,
        ):
            self._connection.close()
            raise
        except sqlite3.DatabaseError as error:
            self._connection.close()
            raise CaptureReplayLedgerIntegrityError(
                "SQLITE_INTEGRITY_CHECK_FAILED"
            ) from error
        try:
            journal_mode = str(
                self._connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute(
                f"PRAGMA wal_autocheckpoint = {REPLAY_LEDGER_WAL_AUTOCHECKPOINT_PAGES}"
            )
            self._connection.execute(
                f"PRAGMA busy_timeout = {REPLAY_LEDGER_BUSY_TIMEOUT_MS}"
            )
            durability = self._durability_evidence_unlocked()
        except sqlite3.DatabaseError as error:
            self._connection.close()
            raise CaptureReplayLedgerDurabilityError(
                "REPLAY_LEDGER_DURABILITY_UNAVAILABLE"
            ) from error
        expected_journal = "wal" if self._file_backed else "memory"
        if journal_mode != expected_journal or not self._durability_matches(durability):
            self._connection.close()
            raise CaptureReplayLedgerDurabilityError(
                "REPLAY_LEDGER_DURABILITY_UNAVAILABLE"
            )
        try:
            row_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM capture_replay"
                ).fetchone()[0]
            )
            if not self._file_backed:
                self._startup_checkpoint = self._checkpoint_unlocked("PASSIVE")
            elif row_count:
                self._startup_checkpoint = self._checkpoint_unlocked("PASSIVE")
            else:
                self._startup_checkpoint = {
                    "status": "COMPLETE",
                    "mode": "PASSIVE",
                    "busy": 0,
                    "log_frames": 0,
                    "checkpointed_frames": 0,
                    "backlog_frames": 0,
                    "backlog_limit_frames": self.max_wal_backlog_frames,
                }
        except sqlite3.DatabaseError as error:
            self._connection.close()
            raise CaptureReplayLedgerDurabilityError(
                "REPLAY_LEDGER_STARTUP_CHECKPOINT_FAILED"
            ) from error
        try:
            self._validate_or_bootstrap_anchor_unlocked()
        except CaptureReplayLedgerAnchorError:
            self._connection.close()
            raise

    def __enter__(self) -> CaptureReplayLedger:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def entry_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM capture_replay"
            ).fetchone()
            return int(row[0])

    @staticmethod
    def _valid_anchor_state(state: object) -> bool:
        return (
            isinstance(state, CaptureReplayAnchorState)
            and isinstance(state.sequence, int)
            and not isinstance(state.sequence, bool)
            and state.sequence >= 0
            and _valid_sha256(state.rowset_sha256)
            and _valid_sha256(state.policy_sha256)
            and _valid_sha256(state.capture_schema_sha256)
            and _valid_sha256(state.rowset_schema_sha256)
        )

    def _local_anchor_state_unlocked(self) -> CaptureReplayAnchorState:
        rowset = self._rowset_metadata_unlocked()
        return CaptureReplayAnchorState(
            sequence=int(rowset["row_count"]),
            rowset_sha256=str(rowset["sha256"]),
            policy_sha256=self._expected_policy_digest(),
            capture_schema_sha256=self._expected_capture_schema_digest(),
            rowset_schema_sha256=self._expected_rowset_schema_digest(),
        )

    def _anchor_transition_schema_matches_unlocked(self) -> bool:
        try:
            schema_row = self._connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' "
                "AND name = 'replay_ledger_anchor_transition'"
            ).fetchone()
            if (
                schema_row is None
                or not isinstance(schema_row[0], str)
                or self._normalized_sql(schema_row[0])
                != self._normalized_sql(REPLAY_LEDGER_ANCHOR_TRANSITION_TABLE_SQL)
            ):
                return False
            table_info = tuple(
                tuple(row)
                for row in self._connection.execute(
                    "PRAGMA table_info(replay_ledger_anchor_transition)"
                )
            )
            row_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM replay_ledger_anchor_transition"
                ).fetchone()[0]
            )
            return (
                table_info == REPLAY_LEDGER_ANCHOR_TRANSITION_TABLE_INFO
                and row_count <= 1
            )
        except (sqlite3.Error, TypeError, ValueError):
            return False

    @staticmethod
    def _anchor_state_from_dict(
        value: object,
    ) -> CaptureReplayAnchorState:
        if not isinstance(value, dict) or set(value) != {
            "sequence",
            "rowset_sha256",
            "policy_sha256",
            "capture_schema_sha256",
            "rowset_schema_sha256",
        }:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        state = CaptureReplayAnchorState(
            sequence=value["sequence"],
            rowset_sha256=value["rowset_sha256"],
            policy_sha256=value["policy_sha256"],
            capture_schema_sha256=value["capture_schema_sha256"],
            rowset_schema_sha256=value["rowset_schema_sha256"],
        )
        if not CaptureReplayLedger._valid_anchor_state(state):
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        return state

    @staticmethod
    def _anchor_recovery_payload(
        expected: CaptureReplayAnchorState,
        replacement: CaptureReplayAnchorState,
    ) -> dict[str, object]:
        return {
            "receipt_version": REPLAY_LEDGER_ANCHOR_RECOVERY_VERSION,
            "expected": expected.as_dict(),
            "replacement": replacement.as_dict(),
        }

    @classmethod
    def _make_anchor_recovery_receipt(
        cls,
        expected: CaptureReplayAnchorState,
        replacement: CaptureReplayAnchorState,
    ) -> dict[str, object]:
        payload = cls._anchor_recovery_payload(expected, replacement)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        receipt_sha256 = hashlib.sha256(canonical).hexdigest()
        transition_id = hashlib.sha256(
            b"capture-replay-anchor-transition-v1\0" + canonical
        ).hexdigest()
        return {
            **payload,
            "transition_id": transition_id,
            "receipt_sha256": receipt_sha256,
        }

    @classmethod
    def _validate_anchor_recovery_receipt(
        cls, receipt: object
    ) -> tuple[
        dict[str, object],
        CaptureReplayAnchorState,
        CaptureReplayAnchorState,
    ]:
        if not isinstance(receipt, dict) or set(receipt) != {
            "receipt_version",
            "expected",
            "replacement",
            "transition_id",
            "receipt_sha256",
        }:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        if receipt["receipt_version"] != REPLAY_LEDGER_ANCHOR_RECOVERY_VERSION:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        expected = cls._anchor_state_from_dict(receipt["expected"])
        replacement = cls._anchor_state_from_dict(receipt["replacement"])
        if replacement.sequence <= expected.sequence:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        canonical_receipt = cls._make_anchor_recovery_receipt(expected, replacement)
        if receipt != canonical_receipt:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        return canonical_receipt, expected, replacement

    def _pending_anchor_recovery_receipt_unlocked(
        self,
    ) -> dict[str, object] | None:
        if not self._anchor_transition_schema_matches_unlocked():
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_TRANSITION_SCHEMA_INVALID"
            )
        rows = self._connection.execute(
            "SELECT transition_id, receipt_json, receipt_sha256 "
            "FROM replay_ledger_anchor_transition"
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        transition_id, receipt_json, receipt_sha256 = rows[0]
        if (
            not _valid_sha256(transition_id)
            or not isinstance(receipt_json, str)
            or not _valid_sha256(receipt_sha256)
        ):
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        try:
            receipt = json.loads(receipt_json)
        except (json.JSONDecodeError, TypeError) as error:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            ) from error
        canonical, _, _ = self._validate_anchor_recovery_receipt(receipt)
        if (
            transition_id != canonical["transition_id"]
            or receipt_sha256 != canonical["receipt_sha256"]
            or receipt_json
            != json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        ):
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_INVALID"
            )
        return canonical

    def _store_anchor_recovery_receipt_unlocked(
        self,
        expected: CaptureReplayAnchorState,
        replacement: CaptureReplayAnchorState,
    ) -> dict[str, object]:
        if self._pending_anchor_recovery_receipt_unlocked() is not None:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_ALREADY_PENDING"
            )
        receipt = self._make_anchor_recovery_receipt(expected, replacement)
        self._connection.execute(
            "INSERT INTO replay_ledger_anchor_transition "
            "(singleton, transition_id, receipt_json, receipt_sha256) "
            "VALUES (1, ?, ?, ?)",
            (
                receipt["transition_id"],
                json.dumps(receipt, sort_keys=True, separators=(",", ":")),
                receipt["receipt_sha256"],
            ),
        )
        return receipt

    def _clear_anchor_recovery_receipt_unlocked(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute("DELETE FROM replay_ledger_anchor_transition")
            self._connection.execute("COMMIT")
        except sqlite3.Error as error:
            try:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_RECOVERY_CLEAR_FAILED"
            ) from error
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _read_anchor_unlocked(self) -> CaptureReplayAnchorState | None:
        if self._anchor is None:
            return None
        try:
            state = self._anchor.read()
        except Exception as error:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_UNAVAILABLE"
            ) from error
        if state is not None and not self._valid_anchor_state(state):
            raise CaptureReplayLedgerAnchorError("REPLAY_LEDGER_ANCHOR_INVALID")
        return state

    def _compare_anchor_unlocked(
        self,
        anchor_state: CaptureReplayAnchorState | None,
        local_state: CaptureReplayAnchorState,
    ) -> None:
        if anchor_state is None:
            if local_state.sequence:
                raise CaptureReplayLedgerAnchorError("REPLAY_LEDGER_ANCHOR_MISSING")
            return
        if anchor_state.sequence > local_state.sequence:
            raise CaptureReplayLedgerAnchorError("REPLAY_LEDGER_SNAPSHOT_ROLLBACK")
        if anchor_state.sequence < local_state.sequence:
            raise CaptureReplayLedgerAnchorError("REPLAY_LEDGER_ANCHOR_BEHIND")
        if anchor_state != local_state:
            raise CaptureReplayLedgerAnchorError("REPLAY_LEDGER_ANCHOR_MISMATCH")

    def _validate_anchor_unlocked(self) -> CaptureReplayAnchorState | None:
        if self._anchor is None:
            return None
        anchor_state = self._read_anchor_unlocked()
        self._compare_anchor_unlocked(anchor_state, self._local_anchor_state_unlocked())
        return anchor_state

    def _validate_or_bootstrap_anchor_unlocked(self) -> None:
        if self._anchor is None:
            return
        local_state = self._local_anchor_state_unlocked()
        anchor_state = self._read_anchor_unlocked()
        if anchor_state is not None:
            pending = self._pending_anchor_recovery_receipt_unlocked()
            if anchor_state == local_state and pending is not None:
                _, _, replacement = self._validate_anchor_recovery_receipt(pending)
                if replacement != local_state:
                    raise CaptureReplayLedgerAnchorError(
                        "REPLAY_LEDGER_ANCHOR_RECOVERY_STATE_MISMATCH"
                    )
                self._clear_anchor_recovery_receipt_unlocked()
                return
            if anchor_state.sequence < local_state.sequence:
                if pending is None:
                    raise CaptureReplayLedgerAnchorError("REPLAY_LEDGER_ANCHOR_BEHIND")
                _, expected, replacement = self._validate_anchor_recovery_receipt(
                    pending
                )
                if expected != anchor_state or replacement != local_state:
                    raise CaptureReplayLedgerAnchorError(
                        "REPLAY_LEDGER_ANCHOR_RECOVERY_STATE_MISMATCH"
                    )
                return
            self._compare_anchor_unlocked(anchor_state, local_state)
            return
        if local_state.sequence:
            raise CaptureReplayLedgerAnchorError("REPLAY_LEDGER_ANCHOR_MISSING")
        try:
            advanced = self._anchor.compare_and_swap(None, local_state)
        except Exception as error:
            raise CaptureReplayLedgerAnchorError(
                "REPLAY_LEDGER_ANCHOR_UNAVAILABLE"
            ) from error
        if not advanced:
            self._compare_anchor_unlocked(self._read_anchor_unlocked(), local_state)

    def anchor_evidence(self) -> dict[str, int | str]:
        """Return validated anchor evidence without claiming live protection."""
        with self._lock:
            if self._anchor is None:
                return {"mode": "NOT_CONFIGURED"}
            state = self._validate_anchor_unlocked()
            assert state is not None
            return {
                "mode": "CONFIGURED_FIXTURE_OR_EXTERNAL",
                **state.as_dict(),
            }

    def pending_anchor_recovery_receipt(
        self,
    ) -> dict[str, object] | None:
        """Return the validated local transition proof, if one is pending."""
        with self._lock:
            receipt = self._pending_anchor_recovery_receipt_unlocked()
            if receipt is None:
                return None
            return json.loads(json.dumps(receipt))

    def _anchor_recovery_contract_matches_unlocked(self) -> bool:
        try:
            return (
                self._durability_matches(self._durability_evidence_unlocked())
                and self._connection.execute("PRAGMA quick_check").fetchall()
                == [("ok",)]
                and self._capture_schema_matches_unlocked()
                and self._policy_matches_unlocked()
                and self._capture_rows_status_unlocked() is None
                and self._rowset_schema_matches_unlocked()
                and self._rowset_matches_unlocked()
                and self._anchor_transition_schema_matches_unlocked()
            )
        except (sqlite3.Error, TypeError, ValueError):
            return False

    def recover_anchor(self, receipt: object) -> dict[str, object]:
        """Advance one DB-ahead transition only when every proof still binds."""
        with self._lock:
            if self._anchor is None:
                raise CaptureReplayLedgerAnchorError(
                    "REPLAY_LEDGER_ANCHOR_NOT_CONFIGURED"
                )
            supplied, expected, replacement = self._validate_anchor_recovery_receipt(
                receipt
            )
            pending = self._pending_anchor_recovery_receipt_unlocked()
            if pending is None:
                raise CaptureReplayLedgerAnchorError(
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_NOT_PENDING"
                )
            if supplied != pending:
                raise CaptureReplayLedgerAnchorError(
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_RECEIPT_MISMATCH"
                )
            if not self._anchor_recovery_contract_matches_unlocked():
                raise CaptureReplayLedgerAnchorError(
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_STATE_MISMATCH"
                )
            if replacement != self._local_anchor_state_unlocked():
                raise CaptureReplayLedgerAnchorError(
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_STATE_MISMATCH"
                )
            current = self._read_anchor_unlocked()
            if current == replacement:
                status = "ALREADY_ADVANCED"
            elif current != expected:
                raise CaptureReplayLedgerAnchorError(
                    "REPLAY_LEDGER_ANCHOR_RECOVERY_STALE"
                )
            else:
                try:
                    advanced = self._anchor.compare_and_swap(expected, replacement)
                except Exception as error:
                    raise CaptureReplayLedgerAnchorError(
                        "REPLAY_LEDGER_ANCHOR_UNAVAILABLE"
                    ) from error
                if not advanced:
                    if self._read_anchor_unlocked() != replacement:
                        raise CaptureReplayLedgerAnchorError(
                            "REPLAY_LEDGER_ANCHOR_RECOVERY_CAS_FAILED"
                        )
                    status = "ALREADY_ADVANCED"
                else:
                    status = "RECOVERED"
            self._clear_anchor_recovery_receipt_unlocked()
            return {
                "status": status,
                "transition_id": supplied["transition_id"],
                "receipt_sha256": supplied["receipt_sha256"],
                "sequence": replacement.sequence,
            }

    def _policy_evidence_unlocked(self) -> dict[str, int]:
        row = self._connection.execute(
            "SELECT policy_schema_version, max_entries, "
            "max_wal_backlog_frames, max_new_entries_per_batch "
            "FROM replay_ledger_policy WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise CaptureReplayLedgerSchemaError(
                "REPLAY_LEDGER_POLICY_METADATA_MISSING"
            )
        return {
            "policy_schema_version": int(row[0]),
            "max_entries": int(row[1]),
            "max_wal_backlog_frames": int(row[2]),
            "max_new_entries_per_batch": int(row[3]),
        }

    def _expected_policy(self) -> dict[str, int]:
        return {
            "policy_schema_version": REPLAY_LEDGER_POLICY_SCHEMA_VERSION,
            "max_entries": self.max_entries,
            "max_wal_backlog_frames": self.max_wal_backlog_frames,
            "max_new_entries_per_batch": self.max_new_entries_per_batch,
        }

    @staticmethod
    def _normalized_sql(statement: str) -> str:
        return " ".join(statement.split())

    def _capture_schema_matches_unlocked(self) -> bool:
        try:
            schema_row = self._connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'capture_replay'"
            ).fetchone()
            if (
                schema_row is None
                or not isinstance(schema_row[0], str)
                or self._normalized_sql(schema_row[0])
                != self._normalized_sql(REPLAY_LEDGER_CAPTURE_TABLE_SQL)
            ):
                return False
            table_info = tuple(
                tuple(row)
                for row in self._connection.execute("PRAGMA table_info(capture_replay)")
            )
            return table_info == REPLAY_LEDGER_CAPTURE_TABLE_INFO
        except (sqlite3.Error, TypeError, ValueError):
            return False

    def _expected_capture_schema_identity(self) -> dict[str, object]:
        return {
            "ddl": self._normalized_sql(REPLAY_LEDGER_CAPTURE_TABLE_SQL),
            "table_info": [list(row) for row in REPLAY_LEDGER_CAPTURE_TABLE_INFO],
        }

    def _expected_capture_schema_digest(self) -> str:
        canonical = json.dumps(
            self._expected_capture_schema_identity(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    def capture_schema_identity(self) -> dict[str, object]:
        """Return the validated capture-table DDL identity and digest."""
        with self._lock:
            if not self._capture_schema_matches_unlocked():
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_CAPTURE_SCHEMA_INVALID"
                )
            return {
                **self._expected_capture_schema_identity(),
                "sha256": self._expected_capture_schema_digest(),
            }

    def capture_schema_digest(self) -> str:
        """Return SHA-256 over canonical capture-table DDL and metadata."""
        return str(self.capture_schema_identity()["sha256"])

    def _rowset_schema_matches_unlocked(self) -> bool:
        try:
            schema_row = self._connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'replay_ledger_rowset'"
            ).fetchone()
            if (
                schema_row is None
                or not isinstance(schema_row[0], str)
                or self._normalized_sql(schema_row[0])
                != self._normalized_sql(REPLAY_LEDGER_ROWSET_TABLE_SQL)
            ):
                return False
            table_info = tuple(
                tuple(row)
                for row in self._connection.execute(
                    "PRAGMA table_info(replay_ledger_rowset)"
                )
            )
            if table_info != REPLAY_LEDGER_ROWSET_TABLE_INFO:
                return False
            row_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM replay_ledger_rowset"
                ).fetchone()[0]
            )
            return row_count == 1
        except (sqlite3.Error, TypeError, ValueError):
            return False

    def _actual_rowset_identity_unlocked(self) -> dict[str, int | str]:
        rows = [
            list(row)
            for row in self._connection.execute(
                "SELECT capture_id, envelope_schema_version, "
                "envelope_sha256, policy_sha256 FROM capture_replay "
                "ORDER BY capture_id"
            )
        ]
        canonical = json.dumps(
            {
                "rowset_schema_version": REPLAY_LEDGER_ROWSET_SCHEMA_VERSION,
                "rows": rows,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {
            "rowset_schema_version": REPLAY_LEDGER_ROWSET_SCHEMA_VERSION,
            "row_count": len(rows),
            "sha256": hashlib.sha256(canonical).hexdigest(),
        }

    def _expected_rowset_schema_identity(self) -> dict[str, object]:
        return {
            "ddl": self._normalized_sql(REPLAY_LEDGER_ROWSET_TABLE_SQL),
            "table_info": [list(row) for row in REPLAY_LEDGER_ROWSET_TABLE_INFO],
        }

    def _expected_rowset_schema_digest(self) -> str:
        canonical = json.dumps(
            self._expected_rowset_schema_identity(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    def rowset_schema_identity(self) -> dict[str, object]:
        """Return validated rowset-metadata DDL identity and digest."""
        with self._lock:
            if not self._rowset_schema_matches_unlocked():
                raise CaptureReplayLedgerSchemaError(
                    "REPLAY_LEDGER_ROWSET_METADATA_INVALID"
                )
            return {
                **self._expected_rowset_schema_identity(),
                "sha256": self._expected_rowset_schema_digest(),
            }

    def rowset_schema_digest(self) -> str:
        """Return SHA-256 over canonical rowset-metadata DDL and metadata."""
        return str(self.rowset_schema_identity()["sha256"])

    def _rowset_metadata_unlocked(self) -> dict[str, int | str]:
        row = self._connection.execute(
            "SELECT rowset_schema_version, row_count, rowset_sha256 "
            "FROM replay_ledger_rowset WHERE singleton = 1"
        ).fetchone()
        if (
            row is None
            or not isinstance(row[0], int)
            or not isinstance(row[1], int)
            or row[0] != REPLAY_LEDGER_ROWSET_SCHEMA_VERSION
            or row[1] < 0
            or not _valid_sha256(row[2])
        ):
            raise CaptureReplayLedgerSchemaError(
                "REPLAY_LEDGER_ROWSET_METADATA_INVALID"
            )
        return {
            "rowset_schema_version": int(row[0]),
            "row_count": int(row[1]),
            "sha256": str(row[2]),
        }

    def _rowset_commitment_matches_unlocked(self) -> bool:
        try:
            return (
                self._rowset_metadata_unlocked()
                == self._actual_rowset_identity_unlocked()
            )
        except (
            CaptureReplayLedgerSchemaError,
            sqlite3.Error,
            TypeError,
            ValueError,
        ):
            return False

    def _rowset_matches_unlocked(self) -> bool:
        return self._rowset_commitment_matches_unlocked()

    def _update_rowset_commitment_unlocked(self) -> None:
        identity = self._actual_rowset_identity_unlocked()
        updated = self._connection.execute(
            "UPDATE replay_ledger_rowset SET rowset_schema_version = ?, "
            "row_count = ?, rowset_sha256 = ? WHERE singleton = 1",
            (
                identity["rowset_schema_version"],
                identity["row_count"],
                identity["sha256"],
            ),
        ).rowcount
        if updated != 1:
            raise CaptureReplayLedgerSchemaError(
                "REPLAY_LEDGER_ROWSET_METADATA_INVALID"
            )

    def rowset_identity(self) -> dict[str, int | str]:
        """Return validated canonical commitment over the complete rowset."""
        with self._lock:
            if (
                not self._rowset_schema_matches_unlocked()
                or not self._rowset_matches_unlocked()
            ):
                raise CaptureReplayLedgerIntegrityError("REPLAY_LEDGER_ROWSET_MISMATCH")
            return self._rowset_metadata_unlocked()

    def _policy_schema_matches_unlocked(self) -> bool:
        try:
            schema_row = self._connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'replay_ledger_policy'"
            ).fetchone()
            if (
                schema_row is None
                or not isinstance(schema_row[0], str)
                or self._normalized_sql(schema_row[0])
                != self._normalized_sql(REPLAY_LEDGER_POLICY_TABLE_SQL)
            ):
                return False
            table_info = tuple(
                tuple(row)
                for row in self._connection.execute(
                    "PRAGMA table_info(replay_ledger_policy)"
                )
            )
            if table_info != REPLAY_LEDGER_POLICY_TABLE_INFO:
                return False
            row_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM replay_ledger_policy"
                ).fetchone()[0]
            )
            return row_count == 1
        except (sqlite3.Error, TypeError, ValueError):
            return False

    def _policy_matches_unlocked(self) -> bool:
        try:
            return (
                self._policy_schema_matches_unlocked()
                and self._policy_evidence_unlocked() == self._expected_policy()
            )
        except (
            CaptureReplayLedgerSchemaError,
            sqlite3.Error,
            TypeError,
            ValueError,
        ):
            return False

    def _expected_policy_identity(self) -> dict[str, object]:
        return {
            "ddl": self._normalized_sql(REPLAY_LEDGER_POLICY_TABLE_SQL),
            "table_info": [list(row) for row in REPLAY_LEDGER_POLICY_TABLE_INFO],
            "values": self._expected_policy(),
        }

    def _expected_policy_digest(self) -> str:
        canonical = json.dumps(
            self._expected_policy_identity(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    def policy_identity(self) -> dict[str, object]:
        """Return the validated policy values and their canonical identity."""
        with self._lock:
            if not self._policy_matches_unlocked():
                raise CaptureReplayLedgerSchemaError("REPLAY_LEDGER_POLICY_DRIFT")
            return {
                "values": self._policy_evidence_unlocked(),
                "sha256": self._expected_policy_digest(),
            }

    def policy_digest(self) -> str:
        """Return SHA-256 over canonical policy DDL, metadata, and values."""
        return str(self.policy_identity()["sha256"])

    def policy_evidence(self) -> dict[str, int]:
        """Return the persisted admission policy bound to this ledger."""
        with self._lock:
            return self._policy_evidence_unlocked()

    def _capture_rows_status_unlocked(self) -> str | None:
        versions = {
            int(row[0])
            for row in self._connection.execute(
                "SELECT DISTINCT envelope_schema_version FROM capture_replay"
            )
        }
        if versions - {CAPTURE_ENVELOPE_SCHEMA_VERSION}:
            return "SCHEMA_MISMATCH"
        expected_policy_digest = self._expected_policy_digest()
        rows = self._connection.execute(
            "SELECT capture_id, envelope_sha256, policy_sha256 FROM capture_replay"
        ).fetchall()
        if any(
            not _valid_replay_entry(capture_id, digest)
            or not _valid_sha256(policy_digest)
            for capture_id, digest, policy_digest in rows
        ):
            return "INTEGRITY_ERROR"
        if any(policy_digest != expected_policy_digest for _, _, policy_digest in rows):
            return "POLICY_BINDING_ERROR"
        return None

    def _durability_evidence_unlocked(self) -> dict[str, int | str]:
        return {
            "journal_mode": str(
                self._connection.execute("PRAGMA journal_mode").fetchone()[0]
            ).lower(),
            "synchronous": int(
                self._connection.execute("PRAGMA synchronous").fetchone()[0]
            ),
            "wal_autocheckpoint": int(
                self._connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
            ),
            "busy_timeout_ms": int(
                self._connection.execute("PRAGMA busy_timeout").fetchone()[0]
            ),
        }

    def _durability_matches(self, evidence: dict[str, int | str]) -> bool:
        expected_journal = "wal" if self._file_backed else "memory"
        return evidence == {
            "journal_mode": expected_journal,
            "synchronous": 2,
            "wal_autocheckpoint": REPLAY_LEDGER_WAL_AUTOCHECKPOINT_PAGES,
            "busy_timeout_ms": REPLAY_LEDGER_BUSY_TIMEOUT_MS,
        }

    def durability_evidence(self) -> dict[str, int | str]:
        with self._lock:
            return self._durability_evidence_unlocked()

    def startup_checkpoint_evidence(self) -> dict[str, int | str]:
        """Return the immutable PASSIVE checkpoint observed during open."""
        with self._lock:
            return dict(self._startup_checkpoint)

    def _checkpoint_unlocked(self, mode: str) -> dict[str, int | str]:
        if not self._file_backed:
            return {
                "status": "NOT_APPLICABLE",
                "mode": mode,
                "busy": 0,
                "log_frames": 0,
                "checkpointed_frames": 0,
                "backlog_frames": 0,
                "backlog_limit_frames": self.max_wal_backlog_frames,
            }
        if not self._durability_matches(self._durability_evidence_unlocked()):
            raise CaptureReplayLedgerDurabilityError("REPLAY_LEDGER_DURABILITY_DRIFT")
        busy, log_frames, checkpointed_frames = self._connection.execute(
            f"PRAGMA wal_checkpoint({mode})"
        ).fetchone()
        busy = int(busy)
        log_frames = int(log_frames)
        checkpointed_frames = int(checkpointed_frames)
        backlog_frames = max(log_frames - checkpointed_frames, 0)
        status = (
            "LIMIT_EXCEEDED"
            if backlog_frames > self.max_wal_backlog_frames
            else "BUSY"
            if busy
            else "PARTIAL"
            if checkpointed_frames < log_frames
            else "COMPLETE"
        )
        return {
            "status": status,
            "mode": mode,
            "busy": busy,
            "log_frames": log_frames,
            "checkpointed_frames": checkpointed_frames,
            "backlog_frames": backlog_frames,
            "backlog_limit_frames": self.max_wal_backlog_frames,
        }

    def checkpoint(self, mode: str = "PASSIVE") -> dict[str, int | str]:
        """Checkpoint WAL and expose reader-starvation backlog state."""
        if not isinstance(mode, str) or mode.upper() not in {"PASSIVE", "TRUNCATE"}:
            raise ValueError("checkpoint mode must be PASSIVE or TRUNCATE")
        normalized_mode = mode.upper()
        with self._lock:
            return self._checkpoint_unlocked(normalized_mode)

    def check_and_record(self, entries: dict[str, str]) -> tuple[str, int]:
        """Atomically compare and register capture IDs and envelope digests."""
        with self._lock:
            try:
                durability = self._durability_evidence_unlocked()
                if not self._durability_matches(durability):
                    count = int(
                        self._connection.execute(
                            "SELECT COUNT(*) FROM capture_replay"
                        ).fetchone()[0]
                    )
                    return "DURABILITY_ERROR", count
                preflight_count = int(
                    self._connection.execute(
                        "SELECT COUNT(*) FROM capture_replay"
                    ).fetchone()[0]
                )
                if not self._capture_schema_matches_unlocked():
                    return "CAPTURE_SCHEMA_ERROR", preflight_count
                if not self._policy_matches_unlocked():
                    return "POLICY_ERROR", preflight_count
                row_status = self._capture_rows_status_unlocked()
                if row_status is not None:
                    return row_status, preflight_count
                if not self._rowset_schema_matches_unlocked():
                    return "ROWSET_SCHEMA_ERROR", preflight_count
                if not self._rowset_matches_unlocked():
                    return "ROWSET_ERROR", preflight_count
                try:
                    if self._pending_anchor_recovery_receipt_unlocked() is not None:
                        return "ANCHOR_ERROR", preflight_count
                    self._validate_anchor_unlocked()
                except CaptureReplayLedgerAnchorError:
                    return "ANCHOR_ERROR", preflight_count
                if self._file_backed and preflight_count:
                    checkpoint = self._checkpoint_unlocked("PASSIVE")
                    if checkpoint["status"] == "LIMIT_EXCEEDED":
                        return "BACKLOG_LIMIT", preflight_count
                if not entries or any(
                    not _valid_replay_entry(capture_id, digest)
                    for capture_id, digest in entries.items()
                ):
                    return "INVALID_ENTRY", preflight_count
                capture_ids = tuple(entries)
                placeholders = ",".join("?" for _ in capture_ids)
                preflight_existing = {
                    row[0]
                    for row in self._connection.execute(
                        f"SELECT capture_id FROM capture_replay "
                        f"WHERE capture_id IN ({placeholders})",
                        capture_ids,
                    )
                }
                if (
                    len(capture_ids) - len(preflight_existing)
                    > self.max_new_entries_per_batch
                ):
                    return "BATCH_LIMIT", preflight_count
                self._connection.execute("BEGIN IMMEDIATE")
                count = int(
                    self._connection.execute(
                        "SELECT COUNT(*) FROM capture_replay"
                    ).fetchone()[0]
                )
                if not self._capture_schema_matches_unlocked():
                    self._connection.execute("ROLLBACK")
                    return "CAPTURE_SCHEMA_ERROR", count
                if not self._policy_matches_unlocked():
                    self._connection.execute("ROLLBACK")
                    return "POLICY_ERROR", count
                if not entries or any(
                    not _valid_replay_entry(capture_id, digest)
                    for capture_id, digest in entries.items()
                ):
                    self._connection.execute("ROLLBACK")
                    return "INVALID_ENTRY", count
                if self._connection.execute("PRAGMA quick_check").fetchall() != [
                    ("ok",)
                ]:
                    self._connection.execute("ROLLBACK")
                    return "INTEGRITY_ERROR", count
                row_status = self._capture_rows_status_unlocked()
                if row_status is not None:
                    self._connection.execute("ROLLBACK")
                    return row_status, count
                if not self._rowset_schema_matches_unlocked():
                    self._connection.execute("ROLLBACK")
                    return "ROWSET_SCHEMA_ERROR", count
                if not self._rowset_matches_unlocked():
                    self._connection.execute("ROLLBACK")
                    return "ROWSET_ERROR", count
                try:
                    if self._pending_anchor_recovery_receipt_unlocked() is not None:
                        self._connection.execute("ROLLBACK")
                        return "ANCHOR_ERROR", count
                    pre_anchor_state = self._validate_anchor_unlocked()
                except CaptureReplayLedgerAnchorError:
                    self._connection.execute("ROLLBACK")
                    return "ANCHOR_ERROR", count
                expected_policy_digest = self._expected_policy_digest()
                capture_ids = tuple(entries)
                placeholders = ",".join("?" for _ in capture_ids)
                existing = {
                    row[0]: (row[1], row[2])
                    for row in self._connection.execute(
                        f"SELECT capture_id, envelope_sha256, policy_sha256 "
                        f"FROM capture_replay WHERE capture_id IN ({placeholders})",
                        capture_ids,
                    )
                }
                if any(
                    existing[capture_id][0] != entries[capture_id]
                    for capture_id in existing
                ):
                    self._connection.execute("ROLLBACK")
                    return "MISMATCH", len(existing)

                missing = [
                    (
                        capture_id,
                        CAPTURE_ENVELOPE_SCHEMA_VERSION,
                        digest,
                        expected_policy_digest,
                    )
                    for capture_id, digest in entries.items()
                    if capture_id not in existing
                ]
                if len(missing) > self.max_new_entries_per_batch:
                    self._connection.execute("ROLLBACK")
                    return "BATCH_LIMIT", count
                if count + len(missing) > self.max_entries:
                    self._connection.execute("ROLLBACK")
                    return "FULL", count

                self._connection.executemany(
                    "INSERT INTO capture_replay("
                    "capture_id, envelope_schema_version, envelope_sha256, "
                    "policy_sha256) VALUES (?, ?, ?, ?)",
                    missing,
                )
                self._update_rowset_commitment_unlocked()
                post_anchor_state = self._local_anchor_state_unlocked()
                if missing and self._anchor is not None:
                    assert pre_anchor_state is not None
                    self._store_anchor_recovery_receipt_unlocked(
                        pre_anchor_state, post_anchor_state
                    )
                self._connection.execute("COMMIT")
                if missing and self._anchor is not None:
                    try:
                        advanced = self._anchor.compare_and_swap(
                            pre_anchor_state, post_anchor_state
                        )
                        if not advanced:
                            current_anchor = self._read_anchor_unlocked()
                            if current_anchor != post_anchor_state:
                                return "ANCHOR_ERROR", count + len(missing)
                        self._clear_anchor_recovery_receipt_unlocked()
                    except Exception:
                        return "ANCHOR_ERROR", count + len(missing)
                return ("RECORDED" if missing else "REPLAYED", count + len(missing))
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise


def frame(alarm: bool) -> np.ndarray:
    """Return a fixed 24x16 synthetic frame as an OpenCV-compatible array."""
    image = np.zeros((16, 24), dtype=np.uint8)
    image[4:12, 8:16] = 255 if alarm else 32
    return image


def _package_version() -> str:
    try:
        return version("opencv-python-headless")
    except PackageNotFoundError:
        return "unknown"


def runtime_evidence() -> dict:
    build = cv2.getBuildInformation()
    return {
        "opencv_version": cv2.__version__,
        "package": "opencv-python-headless",
        "package_version": _package_version(),
        "build_sha256": hashlib.sha256(build.encode()).hexdigest(),
        "algorithm": "cv2.threshold+cv2.countNonZero",
    }


def runtime_matches_contract(
    *, expected_opencv: str = OPENCV_VERSION, expected_package: str = PACKAGE_VERSION
) -> bool:
    evidence = runtime_evidence()
    return (
        evidence["opencv_version"] == expected_opencv
        and evidence["package_version"] == expected_package
    )


def _valid_capture_time(value: object) -> bool:
    """Accept finite real timestamps while rejecting bool's integer subtype."""
    return (
        isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    )


def observe(view: View) -> dict:
    image = view.pixels
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.shape != (16, 24)
    ):
        raise ValueError("INVALID_FRAME")
    if not 0.0 <= view.visible_fraction <= 1.0:
        raise ValueError("INVALID_VISIBILITY")
    roi = image[4:12, 8:16]
    _, thresholded = cv2.threshold(roi, 199, 255, cv2.THRESH_BINARY)
    bright = int(cv2.countNonZero(thresholded))
    return {
        "bright_pixels": bright,
        "alarm": bright >= 32,
        "visible_fraction": view.visible_fraction,
        "frame_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
    }


def capture_envelope_sha256(
    logical_view: str,
    view: View,
    captured_at: float,
    *,
    calibration_digest: str,
    pipeline_version: str,
    opencv_version: str,
    package_version: str,
    schema_version: int = CAPTURE_ENVELOPE_SCHEMA_VERSION,
) -> str:
    """Commit a frame to provenance and the interpretation contract."""
    envelope = {
        "calibration_digest": calibration_digest,
        "capture_id": view.capture_id,
        "captured_at": float(captured_at),
        "logical_view": logical_view,
        "opencv_version": opencv_version,
        "package_version": package_version,
        "pixel_dtype": str(view.pixels.dtype),
        "pixel_shape": list(view.pixels.shape),
        "pipeline_version": pipeline_version,
        "schema_version": schema_version,
        "source_id": view.source_id,
        "view_captured_at": float(view.captured_at),
    }
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical + b"\0" + view.pixels.tobytes()).hexdigest()


def inspect(
    views: dict[str, View],
    *,
    captured_at: float,
    now: float,
    calibration_digest: str = CALIBRATION_DIGEST,
    pipeline_version: str = PIPELINE_VERSION,
    expected_opencv: str = OPENCV_VERSION,
    expected_package: str = PACKAGE_VERSION,
    replay_ledger: CaptureReplayLedger | None = None,
) -> dict:
    """Inspect two bound views and stop closed on stale or changed evidence."""
    if not runtime_matches_contract(
        expected_opencv=expected_opencv, expected_package=expected_package
    ):
        return {"decision": "STOP", "reason": "DEPENDENCY_VERSION_CHANGED"}
    if not _valid_capture_time(captured_at) or not _valid_capture_time(now):
        return {"decision": "STOP", "reason": "INVALID_CAPTURE_TIME"}
    if now < captured_at or now - captured_at > 5:
        return {"decision": "STOP", "reason": "STALE_OR_FUTURE_FRAME"}
    if calibration_digest != CALIBRATION_DIGEST or pipeline_version != PIPELINE_VERSION:
        return {"decision": "STOP", "reason": "CALIBRATION_OR_PIPELINE_CHANGED"}
    if not isinstance(views, dict):
        return {"decision": "STOP", "reason": "INVALID_VIEW_CONTAINER"}
    if set(views) != {"front", "side"}:
        return {"decision": "REQUEST_VIEW", "reason": "INCOMPLETE_COVERAGE"}
    if any(not isinstance(view, View) for view in views.values()):
        return {"decision": "STOP", "reason": "INVALID_VIEW"}
    view_capture_times = {name: view.captured_at for name, view in views.items()}
    if any(not _valid_capture_time(value) for value in view_capture_times.values()):
        return {"decision": "STOP", "reason": "INVALID_VIEW_CAPTURE_TIME"}
    if any(now < value or now - value > 5 for value in view_capture_times.values()):
        return {"decision": "STOP", "reason": "STALE_OR_FUTURE_VIEW"}
    view_capture_skew = max(view_capture_times.values()) - min(
        view_capture_times.values()
    )
    if view_capture_skew > MAX_VIEW_CAPTURE_SKEW_SECONDS:
        return {"decision": "REQUEST_VIEW", "reason": "VIEW_CAPTURE_TIME_SKEW"}
    earliest_view_capture = min(view_capture_times.values())
    latest_view_capture = max(view_capture_times.values())
    batch_view_time_divergence = max(
        earliest_view_capture - captured_at,
        captured_at - latest_view_capture,
        0.0,
    )
    if batch_view_time_divergence > MAX_BATCH_VIEW_TIME_DIVERGENCE_SECONDS:
        return {"decision": "STOP", "reason": "BATCH_VIEW_TIME_DIVERGENCE"}
    if any(
        views[name].source_id != source_id
        for name, source_id in VIEW_SOURCE_IDS.items()
    ):
        return {"decision": "REQUEST_VIEW", "reason": "VIEW_SOURCE_MISMATCH"}
    capture_ids = [view.capture_id for view in views.values()]
    if any(
        not isinstance(capture_id, str) or not capture_id.strip()
        for capture_id in capture_ids
    ):
        return {"decision": "REQUEST_VIEW", "reason": "INVALID_CAPTURE_ID"}
    if len(set(capture_ids)) != len(capture_ids):
        return {"decision": "REQUEST_VIEW", "reason": "DUPLICATED_CAPTURE_ID"}
    front_pixels = views["front"].pixels
    side_pixels = views["side"].pixels
    if (
        isinstance(front_pixels, np.ndarray)
        and isinstance(side_pixels, np.ndarray)
        and np.shares_memory(front_pixels, side_pixels)
    ):
        return {"decision": "REQUEST_VIEW", "reason": "DUPLICATED_VIEW_BUFFER"}
    try:
        if any(view.visible_fraction < MIN_VISIBLE_FRACTION for view in views.values()):
            return {"decision": "REQUEST_VIEW", "reason": "OCCLUDED_VIEW"}
        observations = {}
        for name, view in views.items():
            observation = observe(view)
            observation["capture_envelope_sha256"] = capture_envelope_sha256(
                name,
                view,
                captured_at,
                calibration_digest=calibration_digest,
                pipeline_version=pipeline_version,
                opencv_version=expected_opencv,
                package_version=expected_package,
                schema_version=CAPTURE_ENVELOPE_SCHEMA_VERSION,
            )
            observations[name] = observation
    except (TypeError, ValueError):
        return {"decision": "STOP", "reason": "INVALID_FRAME"}
    if replay_ledger is None:
        return {"decision": "STOP", "reason": "REPLAY_LEDGER_REQUIRED"}
    if not isinstance(replay_ledger, CaptureReplayLedger):
        return {"decision": "STOP", "reason": "INVALID_REPLAY_LEDGER"}
    try:
        replay_status, replay_entries = replay_ledger.check_and_record(
            {
                view.capture_id: observations[name]["capture_envelope_sha256"]
                for name, view in views.items()
            }
        )
    except sqlite3.Error:
        return {"decision": "STOP", "reason": "REPLAY_LEDGER_ERROR"}
    if replay_status == "MISMATCH":
        return {"decision": "STOP", "reason": "CAPTURE_ID_REPLAY_MISMATCH"}
    if replay_status == "FULL":
        return {"decision": "STOP", "reason": "CAPTURE_REPLAY_LEDGER_FULL"}
    if replay_status == "BACKLOG_LIMIT":
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_BACKLOG_LIMIT",
        }
    if replay_status == "BATCH_LIMIT":
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_BATCH_LIMIT",
        }
    if replay_status == "POLICY_ERROR":
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_POLICY_DRIFT",
        }
    if replay_status == "POLICY_BINDING_ERROR":
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_POLICY_BINDING_MISMATCH",
        }
    if replay_status == "ROWSET_ERROR":
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_ROWSET_MISMATCH",
        }
    if replay_status == "ROWSET_SCHEMA_ERROR":
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_ROWSET_SCHEMA_MISMATCH",
        }
    if replay_status == "ANCHOR_ERROR":
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_ANCHOR_ERROR",
        }
    if replay_status in {"SCHEMA_MISMATCH", "CAPTURE_SCHEMA_ERROR"}:
        return {"decision": "STOP", "reason": "CAPTURE_REPLAY_SCHEMA_MISMATCH"}
    if replay_status == "DURABILITY_ERROR":
        return {"decision": "STOP", "reason": "CAPTURE_REPLAY_DURABILITY_ERROR"}
    if replay_status in {"INTEGRITY_ERROR", "INVALID_ENTRY"}:
        return {"decision": "STOP", "reason": "CAPTURE_REPLAY_INTEGRITY_ERROR"}
    try:
        replay_capture_schema_identity = replay_ledger.capture_schema_identity()
    except CaptureReplayLedgerSchemaError:
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_SCHEMA_MISMATCH",
        }
    try:
        replay_policy_identity = replay_ledger.policy_identity()
    except CaptureReplayLedgerSchemaError:
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_POLICY_DRIFT",
        }
    try:
        replay_rowset_schema_identity = replay_ledger.rowset_schema_identity()
    except CaptureReplayLedgerSchemaError:
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_ROWSET_SCHEMA_MISMATCH",
        }
    try:
        replay_rowset_identity = replay_ledger.rowset_identity()
    except (
        CaptureReplayLedgerIntegrityError,
        CaptureReplayLedgerSchemaError,
    ):
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_ROWSET_MISMATCH",
        }
    try:
        replay_anchor_evidence = replay_ledger.anchor_evidence()
    except CaptureReplayLedgerAnchorError:
        return {
            "decision": "STOP",
            "reason": "CAPTURE_REPLAY_ANCHOR_ERROR",
        }
    alarm = any(observation["alarm"] for observation in observations.values())
    return {
        "decision": "STOP" if alarm else "REVIEW",
        "reason": "ALARM" if alarm else "HUMAN_REVIEW",
        "observations": observations,
        "evidence": {
            **runtime_evidence(),
            "calibration_digest": calibration_digest,
            "captured_at": float(captured_at),
            "view_captured_at": {
                name: float(value) for name, value in view_capture_times.items()
            },
            "view_capture_skew_seconds": float(view_capture_skew),
            "batch_view_time_divergence_seconds": float(batch_view_time_divergence),
            "batch_view_time_tolerance_seconds": (
                MAX_BATCH_VIEW_TIME_DIVERGENCE_SECONDS
            ),
            "pipeline_version": pipeline_version,
            "view_source_ids": {name: view.source_id for name, view in views.items()},
            "capture_ids": {name: view.capture_id for name, view in views.items()},
            "capture_envelope_versions": {
                "calibration_digest": calibration_digest,
                "opencv_version": expected_opencv,
                "package_version": expected_package,
                "pipeline_version": pipeline_version,
                "schema_version": CAPTURE_ENVELOPE_SCHEMA_VERSION,
            },
            "capture_replay_status": replay_status,
            "capture_replay_ledger_entries": replay_entries,
            "capture_replay_durability": replay_ledger.durability_evidence(),
            "capture_replay_schema_sha256": (replay_capture_schema_identity["sha256"]),
            "capture_replay_policy": replay_policy_identity["values"],
            "capture_replay_policy_sha256": replay_policy_identity["sha256"],
            "capture_replay_rowset_entries": (replay_rowset_identity["row_count"]),
            "capture_replay_rowset_schema_sha256": (
                replay_rowset_schema_identity["sha256"]
            ),
            "capture_replay_rowset_sha256": replay_rowset_identity["sha256"],
            "capture_replay_anchor": replay_anchor_evidence,
        },
        "physical_action": "NONE",
    }


def verify_consequence(
    expected_alarm: bool,
    observed: View,
    *,
    calibration_digest: str = CALIBRATION_DIGEST,
    pipeline_version: str = PIPELINE_VERSION,
) -> dict:
    if calibration_digest != CALIBRATION_DIGEST or pipeline_version != PIPELINE_VERSION:
        return {
            "closure": "MISMATCH",
            "reason": "EVIDENCE_VERSION_CHANGED",
            "physical_action": "NONE",
        }
    try:
        result = observe(observed)
    except (TypeError, ValueError):
        return {
            "closure": "MISMATCH",
            "reason": "INVALID_FRAME",
            "physical_action": "NONE",
        }
    matches = result["alarm"] == expected_alarm
    return {
        "closure": "MATCH" if matches else "MISMATCH",
        "reason": "EXPECTED_CONSEQUENCE" if matches else "CONSEQUENCE_MISMATCH",
        "observed": result,
        "physical_action": "NONE",
    }
