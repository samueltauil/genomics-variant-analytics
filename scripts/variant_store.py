"""Local, SQLite-backed Delta-compatible Bronze variant store.

The store models the row contract and ingestion behavior locally without
requiring a Delta engine or checking genomic payloads into the repository.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scripts.governance import CLASSIFICATIONS


VARIANT_FIELDS = (
    "CHROM",
    "POS",
    "ID",
    "REF",
    "ALT",
    "QUAL",
    "FILTER",
    "INFO",
    "sample_id",
    "research_subject_id",
    "cohort_id",
    "gene",
    "transcript",
    "variant_consequence",
    "genotype",
    "allele_frequency",
    "reference_build",
    "pipeline_version",
    "source_file_uri",
    "ingestion_timestamp",
)
MANDATORY_FIELDS = ("CHROM", "POS", "REF", "ALT")
ANNOTATION_KEYS = {
    "gene": ("GENE", "gene"),
    "transcript": ("TRANSCRIPT", "transcript"),
    "variant_consequence": ("CONSEQUENCE", "VARIANT_CONSEQUENCE", "variant_consequence"),
    "allele_frequency": ("AF", "ALLELE_FREQUENCY", "allele_frequency"),
}
_SYNTHETIC_ID = re.compile(r"SYN-[A-Z0-9][A-Z0-9_-]*$")
_ADLS_URI = re.compile(r"^(?:abfss|https)://\S+$")
_ONELAKE_URI = re.compile(r"^onelake://\S+$")


@dataclass(frozen=True)
class OneLakeShortcut:
    """Metadata-only shortcut declaration; it never copies the source artifact."""

    name: str
    shortcut_uri: str
    adls_uri: str
    artifact_id: str


@dataclass(frozen=True)
class SourceResolution:
    source_file_uri: str
    canonical_adls_uri: str
    artifact_id: str | None
    current_tier: str | None
    shortcut_name: str | None


DEFAULT_LAYOUT = {
    "table_name": "variant_records",
    "strategy": "clustered",
    "partition_columns": (),
    "clustering_columns": ("gene", "sample_id", "cohort_id"),
    "rationale": "Keep gene-, sample-, and cohort-scoped queries locality-aware without high-cardinality partitions.",
}


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required.")
    return value.strip()


def _synthetic_or_none(value: Any, name: str) -> str | None:
    if value is None:
        return None
    value = _required_text(value, name)
    if _SYNTHETIC_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a synthetic SYN- identifier.")
    return value


def _timestamp(value: Any) -> str:
    value = _required_text(value, "ingestion_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("ingestion_timestamp must be an ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError("ingestion_timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _scalar(value: str | None) -> str | None:
    return None if value in (None, "", ".") else value


def _parse_info(raw_info: str | None) -> dict[str, str | None]:
    if raw_info in (None, "", "."):
        return {}
    values: dict[str, str | None] = {}
    for item in raw_info.split(";"):
        if not item:
            continue
        key, separator, value = item.partition("=")
        values[key] = value if separator else None
    return values


def _lookup(values: Mapping[str, str | None], keys: tuple[str, ...]) -> str | None:
    lowered = {key.lower(): value for key, value in values.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, "", "."):
            return value
    return None


def _parse_number(value: str | None) -> float | None:
    value = _scalar(value)
    if value is None:
        return None
    try:
        return float(value.split(",")[0])
    except ValueError:
        return None


class VariantStore:
    """A local Bronze store with run-level provenance and rejection capture."""

    def __init__(self, database: str | Path):
        self.connection = sqlite3.connect(Path(database))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def __enter__(self) -> "VariantStore":
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        columns = ", ".join(
            f'"{field}" {self._column_type(field)}' for field in VARIANT_FIELDS
        )
        with self.connection:
            self.connection.execute(f"""
                CREATE TABLE IF NOT EXISTS variant_records (
                    {columns}
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS run_provenance (
                    run_id TEXT PRIMARY KEY NOT NULL,
                    source_file_uri TEXT NOT NULL,
                    sample_id TEXT,
                    research_subject_id TEXT,
                    cohort_id TEXT,
                    pipeline_version TEXT NOT NULL,
                    reference_build TEXT NOT NULL,
                    reference_version_or_digest TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    ingestion_timestamp TEXT NOT NULL,
                    accepted_count INTEGER NOT NULL DEFAULT 0,
                    rejected_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (source_file_uri, pipeline_version)
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS rejected_records (
                    rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES run_provenance(run_id),
                    source_file_uri TEXT NOT NULL,
                    source_line_number INTEGER NOT NULL,
                    reason TEXT NOT NULL
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS variant_classification (
                    run_id TEXT PRIMARY KEY NOT NULL REFERENCES run_provenance(run_id),
                    classification TEXT NOT NULL
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS adls_artifacts (
                    artifact_id TEXT PRIMARY KEY NOT NULL,
                    adls_uri TEXT UNIQUE NOT NULL,
                    current_tier TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS onelake_shortcuts (
                    name TEXT PRIMARY KEY NOT NULL,
                    shortcut_uri TEXT UNIQUE NOT NULL,
                    adls_uri TEXT NOT NULL REFERENCES adls_artifacts(adls_uri),
                    artifact_id TEXT NOT NULL REFERENCES adls_artifacts(artifact_id)
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS table_layout (
                    table_name TEXT PRIMARY KEY NOT NULL,
                    strategy TEXT NOT NULL,
                    partition_columns_json TEXT NOT NULL,
                    clustering_columns_json TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    maintenance_state TEXT NOT NULL,
                    last_maintenance_at TEXT,
                    last_maintenance_operation TEXT
                )
            """)
            self.connection.execute(
                """INSERT OR IGNORE INTO table_layout
                   (table_name, strategy, partition_columns_json, clustering_columns_json,
                    rationale, maintenance_state)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    DEFAULT_LAYOUT["table_name"],
                    DEFAULT_LAYOUT["strategy"],
                    json.dumps(DEFAULT_LAYOUT["partition_columns"]),
                    json.dumps(DEFAULT_LAYOUT["clustering_columns"]),
                    DEFAULT_LAYOUT["rationale"],
                    "not_run",
                ),
            )

    @staticmethod
    def _column_type(field: str) -> str:
        if field == "POS":
            return "INTEGER"
        if field in {"QUAL", "allele_frequency"}:
            return "REAL"
        return "TEXT"

    def schema_fields(self) -> tuple[str, ...]:
        rows = self.connection.execute(
            "PRAGMA table_info(variant_records)"
        ).fetchall()
        return tuple(row["name"] for row in rows)

    def register_adls_artifact(
        self,
        artifact_id: str,
        adls_uri: str,
        *,
        current_tier: str = "hot",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        artifact_id = _required_text(artifact_id, "artifact_id")
        adls_uri = self._validate_adls_uri(adls_uri)
        current_tier = _required_text(current_tier, "current_tier")
        with self.connection:
            self.connection.execute(
                """INSERT INTO adls_artifacts
                   (artifact_id, adls_uri, current_tier, metadata_json)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(adls_uri) DO UPDATE SET
                     artifact_id = excluded.artifact_id,
                     current_tier = excluded.current_tier,
                     metadata_json = excluded.metadata_json""",
                (artifact_id, adls_uri, current_tier, json.dumps(dict(metadata or {}))),
            )

    def configure_onelake_shortcut(
        self,
        name: str,
        shortcut_uri: str,
        adls_uri: str,
        *,
        artifact_id: str,
    ) -> OneLakeShortcut:
        name = _required_text(name, "name")
        shortcut_uri = self._validate_shortcut_uri(shortcut_uri)
        adls_uri = self._validate_adls_uri(adls_uri)
        artifact_id = _required_text(artifact_id, "artifact_id")
        artifact = self.connection.execute(
            "SELECT artifact_id FROM adls_artifacts WHERE adls_uri = ?",
            (adls_uri,),
        ).fetchone()
        if artifact is None or artifact["artifact_id"] != artifact_id:
            raise ValueError("Shortcut target must reference a registered ADLS artifact.")
        with self.connection:
            self.connection.execute(
                """INSERT INTO onelake_shortcuts
                   (name, shortcut_uri, adls_uri, artifact_id)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     shortcut_uri = excluded.shortcut_uri,
                     adls_uri = excluded.adls_uri,
                     artifact_id = excluded.artifact_id""",
                (name, shortcut_uri, adls_uri, artifact_id),
            )
        return OneLakeShortcut(name, shortcut_uri, adls_uri, artifact_id)

    def update_artifact_tier(self, adls_uri: str, current_tier: str) -> None:
        adls_uri = self._validate_adls_uri(adls_uri)
        current_tier = _required_text(current_tier, "current_tier")
        with self.connection:
            result = self.connection.execute(
                "UPDATE adls_artifacts SET current_tier = ? WHERE adls_uri = ?",
                (current_tier, adls_uri),
            )
        if result.rowcount != 1:
            raise ValueError("Unknown ADLS artifact.")

    def resolve_source_file_uri(self, source_file_uri: str) -> SourceResolution:
        source_file_uri = _required_text(source_file_uri, "source_file_uri")
        shortcut = self.connection.execute(
            """SELECT name, adls_uri, artifact_id
               FROM onelake_shortcuts
               WHERE shortcut_uri = ?""",
            (source_file_uri,),
        ).fetchone()
        if shortcut is not None:
            canonical_uri = shortcut["adls_uri"]
            shortcut_name = shortcut["name"]
            artifact_id = shortcut["artifact_id"]
        else:
            canonical_uri = self._validate_adls_uri(source_file_uri)
            shortcut_name = None
            artifact = self.connection.execute(
                """SELECT artifact_id FROM adls_artifacts WHERE adls_uri = ?""",
                (canonical_uri,),
            ).fetchone()
            artifact_id = artifact["artifact_id"] if artifact is not None else None
        tier_row = self.connection.execute(
            "SELECT current_tier FROM adls_artifacts WHERE adls_uri = ?",
            (canonical_uri,),
        ).fetchone()
        return SourceResolution(
            source_file_uri=source_file_uri,
            canonical_adls_uri=canonical_uri,
            artifact_id=artifact_id,
            current_tier=tier_row["current_tier"] if tier_row is not None else None,
            shortcut_name=shortcut_name,
        )

    def configure_table_layout(
        self,
        *,
        strategy: str = DEFAULT_LAYOUT["strategy"],
        partition_columns: tuple[str, ...] = DEFAULT_LAYOUT["partition_columns"],
        clustering_columns: tuple[str, ...] = DEFAULT_LAYOUT["clustering_columns"],
        rationale: str = DEFAULT_LAYOUT["rationale"],
    ) -> None:
        if (set(partition_columns) | set(clustering_columns)) - set(VARIANT_FIELDS):
            raise ValueError("Layout columns must be variant-store fields.")
        with self.connection:
            self.connection.execute(
                """UPDATE table_layout SET strategy = ?, partition_columns_json = ?,
                   clustering_columns_json = ?, rationale = ? WHERE table_name = ?""",
                (
                    _required_text(strategy, "strategy"),
                    json.dumps(tuple(partition_columns)),
                    json.dumps(tuple(clustering_columns)),
                    _required_text(rationale, "rationale"),
                    DEFAULT_LAYOUT["table_name"],
                ),
            )

    def record_maintenance(
        self,
        *,
        state: str,
        operation: str,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        state = _required_text(state, "state")
        operation = _required_text(operation, "operation")
        completed_at = _timestamp(completed_at) if completed_at is not None else datetime.now(
            timezone.utc
        ).isoformat().replace("+00:00", "Z")
        with self.connection:
            self.connection.execute(
                """UPDATE table_layout SET maintenance_state = ?, last_maintenance_at = ?,
                   last_maintenance_operation = ? WHERE table_name = ?""",
                (state, completed_at, operation, DEFAULT_LAYOUT["table_name"]),
            )
        return self.inspect_table_layout()

    def inspect_table_layout(self) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM table_layout WHERE table_name = ?",
            (DEFAULT_LAYOUT["table_name"],),
        ).fetchone()
        if row is None:
            raise ValueError("Variant table layout metadata is missing.")
        result = dict(row)
        result["partition_columns"] = tuple(json.loads(result.pop("partition_columns_json")))
        result["clustering_columns"] = tuple(json.loads(result.pop("clustering_columns_json")))
        return result

    @staticmethod
    def _validate_adls_uri(value: str) -> str:
        value = _required_text(value, "adls_uri")
        if _ADLS_URI.fullmatch(value) is None:
            raise ValueError("ADLS URI must use abfss:// or https:// syntax.")
        return value

    @staticmethod
    def _validate_shortcut_uri(value: str) -> str:
        value = _required_text(value, "shortcut_uri")
        if _ONELAKE_URI.fullmatch(value) is None:
            raise ValueError("OneLake shortcut URI must use onelake:// syntax.")
        return value

    def ingest_vcf_text(self, vcf_text: str, provenance: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(vcf_text, str):
            raise ValueError("VCF input must be text.")
        run = self._validate_provenance(provenance)
        existing = self.connection.execute(
            """SELECT run_id, accepted_count, rejected_count
               FROM run_provenance
               WHERE source_file_uri = ? AND pipeline_version = ?""",
            (run["source_file_uri"], run["pipeline_version"]),
        ).fetchone()
        if existing is not None:
            return {
                "run_id": existing["run_id"],
                "accepted_count": existing["accepted_count"],
                "rejected_count": existing["rejected_count"],
                "maintenance": self.inspect_table_layout(),
                "idempotent": True,
            }

        header: list[str] | None = None
        accepted: list[dict[str, Any]] = []
        rejected: list[tuple[int, str]] = []
        for line_number, line in enumerate(vcf_text.splitlines(), start=1):
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                header = line.removeprefix("#").split("\t")
                continue
            if not line or line.startswith("#"):
                continue
            try:
                if header is None:
                    raise ValueError("VCF header is missing.")
                accepted.append(self._parse_record(line, header, run))
            except ValueError as error:
                rejected.append((line_number, str(error)))

        if header is None:
            raise ValueError("VCF header is missing.")
        with self.connection:
            self.connection.execute(
                """INSERT INTO run_provenance
                   (run_id, source_file_uri, sample_id, research_subject_id, cohort_id,
                    pipeline_version, reference_build, reference_version_or_digest,
                    classification, ingestion_timestamp, accepted_count, rejected_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run["run_id"], run["source_file_uri"], run["sample_id"],
                    run["research_subject_id"], run["cohort_id"],
                    run["pipeline_version"], run["reference_build"],
                    run["reference_version_or_digest"], run["classification"],
                    run["ingestion_timestamp"],
                    len(accepted), len(rejected),
                ),
            )
            self.connection.execute(
                "INSERT INTO variant_classification (run_id, classification) VALUES (?, ?)",
                (run["run_id"], run["classification"]),
            )
            self.connection.executemany(
                f"""INSERT INTO variant_records
                    ({", ".join(f'"{field}"' for field in VARIANT_FIELDS)})
                    VALUES ({", ".join("?" for _ in VARIANT_FIELDS)})""",
                [tuple(record[field] for field in VARIANT_FIELDS) for record in accepted],
            )
            self.connection.executemany(
                """INSERT INTO rejected_records
                   (run_id, source_file_uri, source_line_number, reason)
                   VALUES (?, ?, ?, ?)""",
                [(run["run_id"], run["source_file_uri"], line, reason)
                 for line, reason in rejected],
            )
        return {
            "run_id": run["run_id"],
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "maintenance": self.inspect_table_layout(),
            "idempotent": False,
        }

    def _validate_provenance(self, provenance: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(provenance, Mapping):
            raise ValueError("Provenance must be a mapping.")
        run_id = _synthetic_or_none(provenance.get("run_id"), "run_id")
        if run_id is None:
            raise ValueError("run_id is required.")
        source_file_uri = _required_text(provenance.get("source_file_uri"), "source_file_uri")
        self.resolve_source_file_uri(source_file_uri)
        return {
            "run_id": run_id,
            "source_file_uri": source_file_uri,
            "sample_id": _synthetic_or_none(provenance.get("sample_id"), "sample_id"),
            "research_subject_id": _synthetic_or_none(
                provenance.get("research_subject_id"), "research_subject_id"
            ),
            "cohort_id": _synthetic_or_none(provenance.get("cohort_id"), "cohort_id"),
            "pipeline_version": _required_text(provenance.get("pipeline_version"), "pipeline_version"),
            "reference_build": _required_text(provenance.get("reference_build"), "reference_build"),
            "reference_version_or_digest": _required_text(
                provenance.get("reference_version_or_digest"), "reference_version_or_digest"
            ),
            "classification": self._classification(provenance.get("classification")),
            "ingestion_timestamp": _timestamp(provenance.get("ingestion_timestamp")),
        }

    @staticmethod
    def _classification(value: Any) -> str:
        value = _required_text(value, "classification")
        if value not in CLASSIFICATIONS:
            raise ValueError(f"Classification must be one of {sorted(CLASSIFICATIONS)}.")
        return value

    def _parse_record(
        self, line: str, header: list[str], run: Mapping[str, Any]
    ) -> dict[str, Any]:
        values = line.split("\t")
        if len(values) < 8:
            raise ValueError("VCF record has fewer than eight core columns.")
        fields = dict(zip(header, values))
        for field in MANDATORY_FIELDS:
            if _scalar(fields.get(field)) is None:
                raise ValueError(f"Missing mandatory field: {field}.")
        try:
            position = int(fields["POS"])
        except (TypeError, ValueError) as error:
            raise ValueError("POS must be an integer.") from error
        info = _parse_info(fields.get("INFO"))
        format_values: dict[str, str | None] = {}
        format_keys = fields.get("FORMAT", "").split(":") if fields.get("FORMAT") else []
        sample_values = values[9].split(":") if len(values) > 9 else []
        if format_keys and len(values) > 9:
            format_values = dict(zip(format_keys, sample_values))
        allele_frequency = _lookup(info, ANNOTATION_KEYS["allele_frequency"])
        if allele_frequency is None:
            allele_frequency = _lookup(format_values, ANNOTATION_KEYS["allele_frequency"])
        return {
            "CHROM": fields["CHROM"],
            "POS": position,
            "ID": _scalar(fields.get("ID")),
            "REF": fields["REF"],
            "ALT": fields["ALT"],
            "QUAL": _parse_number(fields.get("QUAL")),
            "FILTER": _scalar(fields.get("FILTER")),
            "INFO": _scalar(fields.get("INFO")),
            "sample_id": run["sample_id"],
            "research_subject_id": run["research_subject_id"],
            "cohort_id": run["cohort_id"],
            "gene": _lookup(info, ANNOTATION_KEYS["gene"]),
            "transcript": _lookup(info, ANNOTATION_KEYS["transcript"]),
            "variant_consequence": _lookup(info, ANNOTATION_KEYS["variant_consequence"]),
            "genotype": _scalar(_lookup(format_values, ("GT", "genotype"))),
            "allele_frequency": _parse_number(allele_frequency),
            "reference_build": run["reference_build"],
            "pipeline_version": run["pipeline_version"],
            "source_file_uri": run["source_file_uri"],
            "ingestion_timestamp": run["ingestion_timestamp"],
        }

    def records(self, *, source_file_uri: str | None = None) -> list[dict[str, Any]]:
        if source_file_uri is None:
            rows = self.connection.execute(
                "SELECT * FROM variant_records ORDER BY source_file_uri, POS"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM variant_records WHERE source_file_uri = ? ORDER BY POS",
                (source_file_uri,),
            ).fetchall()
        return [dict(row) for row in rows]

    def provenance(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM run_provenance WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown ingestion run.")
        return dict(row)

    def classification_for_run(self, run_id: str) -> str:
        row = self.connection.execute(
            "SELECT classification FROM run_provenance WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown ingestion run.")
        return row["classification"]

    def records_with_classification(
        self, *, source_file_uri: str | None = None
    ) -> list[dict[str, Any]]:
        """Return exact variant rows with classification as adjacent metadata."""
        query = """
            SELECT v.*, p.classification
            FROM variant_records v
            JOIN run_provenance p
              ON p.source_file_uri = v.source_file_uri
             AND p.pipeline_version = v.pipeline_version
        """
        parameters: tuple[Any, ...] = ()
        if source_file_uri is not None:
            query += " WHERE v.source_file_uri = ?"
            parameters = (source_file_uri,)
        query += " ORDER BY v.source_file_uri, v.POS"
        return [dict(row) for row in self.connection.execute(query, parameters)]

    def rejected_records(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id is None:
            rows = self.connection.execute(
                "SELECT * FROM rejected_records ORDER BY rejection_id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM rejected_records WHERE run_id = ? ORDER BY rejection_id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]
