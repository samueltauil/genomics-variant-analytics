"""Local governance controls for the accelerator.

This module is a SQLite-backed development model of policy, workspace grants,
de-identified projections, and a hash-chained audit log. It is evidence for
local behavior only; Azure identity, private networking, and service-side
tamper resistance still require deployment validation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping


ACCESS_TIERS = (
    "raw_genomic_files",
    "variant_store",
    "cohort_analytics",
    "synthetic_demo",
)
CLASSIFICATIONS = frozenset({
    "genomic-primary",
    "genomic-secondary",
    "genomic-variant",
    "reference",
    "synthetic-demo",
})
WORKSPACES = frozenset({"research", "clinical"})
_SYNTHETIC_ID = re.compile(r"SYN-[A-Z0-9][A-Z0-9_-]*$")


class AuthorizationError(PermissionError):
    """Raised when a policy decision explicitly denies an operation."""


def synthetic_id(value: Any, name: str = "identifier") -> str:
    if not isinstance(value, str) or _SYNTHETIC_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must match SYN-[A-Z0-9][A-Z0-9_-]*.")
    return value


def _timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class AuditTrail:
    """Append-only, hash-chained audit records in a supplied SQLite connection."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS governance_audit (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    affected_data_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE
                )
            """)
            self.connection.execute("""
                CREATE TRIGGER IF NOT EXISTS governance_audit_no_update
                BEFORE UPDATE ON governance_audit
                BEGIN SELECT RAISE(ABORT, 'audit records are append-only'); END
            """)
            self.connection.execute("""
                CREATE TRIGGER IF NOT EXISTS governance_audit_no_delete
                BEFORE DELETE ON governance_audit
                BEGIN SELECT RAISE(ABORT, 'audit records are append-only'); END
            """)

    def record(
        self,
        event_type: str,
        principal_id: str,
        operation: str,
        affected_data: Mapping[str, Any],
        recorded_at: Any = None,
    ) -> dict[str, Any]:
        synthetic_id(principal_id, "principal_id")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type is required.")
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation is required.")
        if not isinstance(affected_data, Mapping):
            raise ValueError("affected_data must be a mapping.")
        payload = json.dumps(dict(affected_data), sort_keys=True, separators=(",", ":"))
        timestamp = _timestamp(recorded_at)
        previous = self.connection.execute(
            "SELECT entry_hash FROM governance_audit ORDER BY event_id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["entry_hash"] if previous else "GENESIS"
        material = "\n".join(
            (event_type, principal_id, operation, payload, timestamp, previous_hash)
        ).encode("utf-8")
        entry_hash = hashlib.sha256(material).hexdigest()
        with self.connection:
            self.connection.execute(
                """INSERT INTO governance_audit
                   (event_type, principal_id, operation, affected_data_json,
                    recorded_at, previous_hash, entry_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (event_type, principal_id, operation, payload, timestamp,
                 previous_hash, entry_hash),
            )
        return self.entries()[-1]

    def entries(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM governance_audit ORDER BY event_id"
        ).fetchall()
        return [
            {**dict(row), "affected_data": json.loads(row["affected_data_json"])}
            for row in rows
        ]

    def verify(self) -> bool:
        previous_hash = "GENESIS"
        for entry in self.entries():
            payload = json.dumps(
                entry["affected_data"], sort_keys=True, separators=(",", ":")
            )
            material = "\n".join((
                entry["event_type"], entry["principal_id"], entry["operation"],
                payload, entry["recorded_at"], previous_hash,
            )).encode("utf-8")
            if entry["previous_hash"] != previous_hash:
                return False
            if entry["entry_hash"] != hashlib.sha256(material).hexdigest():
                return False
            previous_hash = entry["entry_hash"]
        return True


class GovernancePolicy:
    """Four-tier role assignments and explicit local authorization decisions."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS governance_tier_grants (
                    principal_id TEXT NOT NULL,
                    access_tier TEXT NOT NULL CHECK (access_tier IN (
                        'raw_genomic_files', 'variant_store',
                        'cohort_analytics', 'synthetic_demo'
                    )),
                    PRIMARY KEY (principal_id, access_tier)
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS governance_capability_grants (
                    principal_id TEXT NOT NULL,
                    capability TEXT NOT NULL CHECK (capability IN ('subject_linkage')),
                    PRIMARY KEY (principal_id, capability)
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS governance_workspace_grants (
                    principal_id TEXT NOT NULL,
                    workspace TEXT NOT NULL CHECK (workspace IN ('research', 'clinical')),
                    PRIMARY KEY (principal_id, workspace)
                )
            """)
        self.audit = AuditTrail(connection)

    def grant_tier(self, principal_id: str, access_tier: str) -> None:
        synthetic_id(principal_id, "principal_id")
        if access_tier not in ACCESS_TIERS:
            raise ValueError(f"Unsupported access tier: {access_tier}")
        with self.connection:
            self.connection.execute(
                "INSERT INTO governance_tier_grants VALUES (?, ?)",
                (principal_id, access_tier),
            )

    def revoke_tier(self, principal_id: str, access_tier: str) -> None:
        synthetic_id(principal_id, "principal_id")
        if access_tier not in ACCESS_TIERS:
            raise ValueError(f"Unsupported access tier: {access_tier}")
        with self.connection:
            result = self.connection.execute(
                "DELETE FROM governance_tier_grants WHERE principal_id = ? AND access_tier = ?",
                (principal_id, access_tier),
            )
        if result.rowcount != 1:
            raise ValueError("Access-tier grant does not exist.")

    def grant_capability(self, principal_id: str, capability: str) -> None:
        synthetic_id(principal_id, "principal_id")
        if capability != "subject_linkage":
            raise ValueError(f"Unsupported capability: {capability}")
        with self.connection:
            self.connection.execute(
                "INSERT INTO governance_capability_grants VALUES (?, ?)",
                (principal_id, capability),
            )

    def grant_workspace(self, principal_id: str, workspace: str) -> None:
        synthetic_id(principal_id, "principal_id")
        if workspace not in WORKSPACES:
            raise ValueError(f"Unsupported workspace: {workspace}")
        with self.connection:
            self.connection.execute(
                "INSERT INTO governance_workspace_grants VALUES (?, ?)",
                (principal_id, workspace),
            )

    def authorize(self, principal_id: str, access_tier: str, operation: str,
                  affected_data: Mapping[str, Any] | None = None) -> None:
        synthetic_id(principal_id, "principal_id")
        if access_tier not in ACCESS_TIERS:
            raise ValueError(f"Unsupported access tier: {access_tier}")
        granted = self.connection.execute(
            "SELECT 1 FROM governance_tier_grants WHERE principal_id = ? AND access_tier = ?",
            (principal_id, access_tier),
        ).fetchone()
        if granted is None:
            self.audit.record(
                "data_access", principal_id, f"deny:{operation}",
                {"access_tier": access_tier, **dict(affected_data or {})},
            )
            raise AuthorizationError(
                f"Principal {principal_id} is not authorized for {access_tier}."
            )
        self.audit.record(
            "data_access", principal_id, operation,
            {"access_tier": access_tier, **dict(affected_data or {})},
        )

    def authorize_raw_file(self, principal_id: str, artifact_uri: str) -> None:
        """Authorize a raw FASTQ/BAM/CRAM read, denying it without the raw tier."""
        self.authorize(
            principal_id, "raw_genomic_files", "read_raw_file",
            {"artifact_uri": artifact_uri},
        )

    def authorize_variant_store(self, principal_id: str) -> None:
        self.authorize(principal_id, "variant_store", "read_variant_store")

    def read_cohort_aggregates(
        self, principal_id: str, aggregate: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return an aggregate only after an explicit cohort-analytics grant."""
        self.authorize(principal_id, "cohort_analytics", "read_cohort_aggregates")
        return dict(aggregate)

    def project_variant(self, principal_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
        self.authorize(principal_id, "variant_store", "query_variants")
        result = dict(record)
        has_linkage = self.connection.execute(
            """SELECT 1 FROM governance_capability_grants
               WHERE principal_id = ? AND capability = 'subject_linkage'""",
            (principal_id,),
        ).fetchone()
        if has_linkage is None:
            result.pop("research_subject_id", None)
        return result

    def record_pipeline_execution(
        self,
        principal_id: str,
        run_id: str,
        *,
        workflow_id: str,
        workflow_version: str,
        outcome: str,
    ) -> dict[str, Any]:
        synthetic_id(run_id, "run_id")
        return self.audit.record(
            "pipeline_execution",
            principal_id,
            "pipeline_execution",
            {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "workflow_version": workflow_version,
                "outcome": outcome,
            },
        )

    def record_reprocessing(
        self,
        principal_id: str,
        sample_id: str,
        prior_pipeline_version: str,
        new_pipeline_version: str,
    ) -> dict[str, Any]:
        synthetic_id(sample_id, "sample_id")
        if not isinstance(prior_pipeline_version, str) or not prior_pipeline_version.strip():
            raise ValueError("prior_pipeline_version is required.")
        if not isinstance(new_pipeline_version, str) or not new_pipeline_version.strip():
            raise ValueError("new_pipeline_version is required.")
        return self.audit.record(
            "reprocessing",
            principal_id,
            "reprocess_sample",
            {
                "sample_id": sample_id,
                "prior_pipeline_version": prior_pipeline_version,
                "new_pipeline_version": new_pipeline_version,
            },
        )

    def transfer_workspace(
        self, principal_id: str, source: str, destination: str,
        dataset: str, approval_id: str | None = None,
    ) -> dict[str, Any]:
        synthetic_id(principal_id, "principal_id")
        if source not in WORKSPACES or destination not in WORKSPACES or source == destination:
            raise ValueError("Workspace transfer must cross research and clinical.")
        grants = {
            row["workspace"] for row in self.connection.execute(
                "SELECT workspace FROM governance_workspace_grants WHERE principal_id = ?",
                (principal_id,),
            )
        }
        if not {source, destination}.issubset(grants) or not approval_id:
            self.audit.record(
                "cross_workspace_transfer", principal_id, "deny:transfer",
                {"source": source, "destination": destination, "dataset": dataset},
            )
            raise AuthorizationError("Cross-workspace transfer requires both grants and approval.")
        synthetic_id(approval_id, "approval_id")
        return self.audit.record(
            "cross_workspace_transfer", principal_id, "transfer",
            {"source": source, "destination": destination, "dataset": dataset,
             "approval_id": approval_id},
        )
