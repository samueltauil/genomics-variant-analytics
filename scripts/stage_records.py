"""Staging log for files copied from the landing zone into object storage.

Records the six fields the staging spec requires and withholds any artifact whose destination
checksum does not match its source. Checksums are supplied by the caller that read the bytes;
this module compares and records them rather than fetching anything itself.
"""

import re
import sqlite3
from urllib.parse import urlsplit

from scripts.scan_landing import local_path
from scripts.validate_submission import fields, text
from scripts.governance import CLASSIFICATIONS

APPLICATION_ID = 0x47535447
SCHEMA_VERSION = 1

STATES = frozenset({"staged", "failed"})
INTEGRITY_RESULTS = frozenset({"verified", "mismatch", "not-checked"})
STORAGE_TIERS = frozenset({"Hot", "Cool", "Cold", "Archive"})

# Declared handling labels, not inferred sensitivity.

RECORD_FIELDS = frozenset({
    "source_path", "run_id", "sample_id", "destination_uri",
    "storage_tier", "classification", "source_checksum", "destination_checksum",
})

CHECKSUM = re.compile(r"[0-9a-f]{64}")
ALLOWED_SCHEMES = frozenset({"abfss", "https"})


def _checksum(value, label):
    if not isinstance(value, str) or not CHECKSUM.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase 64-character SHA-256 digest.")
    return value


def _destination_uri(value):
    text(value, "Destination URI")
    if any(character.isspace() or ord(character) < 0x20 for character in value):
        raise ValueError("Destination URI must not contain whitespace or control characters.")
    if "\\" in value:
        raise ValueError("Destination URI must not contain backslashes.")

    parts = urlsplit(value)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Destination URI scheme must be one of {sorted(ALLOWED_SCHEMES)}.")
    if parts.query or parts.fragment or parts.password:
        raise ValueError("Destination URI must not carry a query, fragment or password.")
    if not parts.hostname:
        raise ValueError("Destination URI must name a host.")
    if not parts.path.startswith("/") or parts.path == "/":
        raise ValueError("Destination URI must address an object, not a container root.")
    if any(segment in {".", ".."} for segment in parts.path.split("/")):
        raise ValueError("Destination URI must not contain relative path segments.")
    return value


class StagingLog:
    """Append-and-revise log of staging operations, keyed on the landing-zone source path."""

    def __init__(self, database):
        self._connection = sqlite3.connect(local_path(database))
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            application_id = self._connection.execute("PRAGMA application_id").fetchone()[0]
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            existing = self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()

            if not existing:
                self._create()
            elif application_id != APPLICATION_ID or version != SCHEMA_VERSION:
                raise ValueError("Database is not a staging log of a supported version.")
        except Exception:
            self._connection.close()
            raise

    def _create(self):
        with self._connection:
            self._connection.execute("""
                CREATE TABLE staging (
                    source_path TEXT PRIMARY KEY NOT NULL,
                    run_id TEXT,
                    sample_id TEXT,
                    destination_uri TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('staged', 'failed')),
                    integrity_result TEXT NOT NULL
                        CHECK (integrity_result IN ('verified', 'mismatch', 'not-checked')),
                    source_checksum TEXT,
                    destination_checksum TEXT,
                    storage_tier TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    CHECK (integrity_result <> 'mismatch' OR state = 'failed'),
                    CHECK (integrity_result <> 'verified' OR state = 'staged')
                )
            """)
            self._connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def record(self, record, recorded_at):
        """Compare the supplied checksums and persist one staging outcome."""
        fields(record, RECORD_FIELDS, "Staging record")
        source_path = text(record["source_path"], "Source path")
        destination_uri = _destination_uri(record["destination_uri"])
        text(recorded_at, "Recorded timestamp")

        if record["storage_tier"] not in STORAGE_TIERS:
            raise ValueError(f"Storage tier must be one of {sorted(STORAGE_TIERS)}.")
        if record["classification"] not in CLASSIFICATIONS:
            raise ValueError(f"Classification must be one of {sorted(CLASSIFICATIONS)}.")
        for identifier in ("run_id", "sample_id"):
            if record[identifier] is not None:
                text(record[identifier], identifier)

        source_checksum = _checksum(record["source_checksum"], "Source checksum")
        destination_checksum = _checksum(record["destination_checksum"], "Destination checksum")
        verified = source_checksum == destination_checksum

        with self._connection:
            self._connection.execute("""
                INSERT INTO staging (
                    source_path, run_id, sample_id, destination_uri, state, integrity_result,
                    source_checksum, destination_checksum, storage_tier, classification, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    run_id = excluded.run_id, sample_id = excluded.sample_id,
                    destination_uri = excluded.destination_uri, state = excluded.state,
                    integrity_result = excluded.integrity_result,
                    source_checksum = excluded.source_checksum,
                    destination_checksum = excluded.destination_checksum,
                    storage_tier = excluded.storage_tier,
                    classification = excluded.classification,
                    recorded_at = excluded.recorded_at
            """, (
                source_path, record["run_id"], record["sample_id"], destination_uri,
                "staged" if verified else "failed", "verified" if verified else "mismatch",
                source_checksum, destination_checksum,
                record["storage_tier"], record["classification"], recorded_at,
            ))

        return self.get(source_path)

    def get(self, source_path):
        row = self._connection.execute(
            "SELECT * FROM staging WHERE source_path = ?", (text(source_path, "Source path"),)
        ).fetchone()
        return dict(row) if row else None

    def report(self):
        """Every staging outcome, including failures, for operator review."""
        return [
            dict(row) for row in
            self._connection.execute("SELECT * FROM staging ORDER BY source_path")
        ]

    def available_for_processing(self):
        """Only artifacts whose destination matched their source are advertised downstream."""
        return [
            dict(row) for row in self._connection.execute(
                "SELECT * FROM staging WHERE state = 'staged' AND integrity_result = 'verified'"
                " ORDER BY source_path"
            )
        ]

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
