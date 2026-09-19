"""Governed analytics query engine for the Bronze variant store.

Implements tasks 9.1-9.4 of the analytics/variant-query-and-visualization
capability: the six supported query scenarios, equivalent notebook and
SQL-endpoint surfaces for the same principal, per-row result traceability,
and reproducible store snapshots.

This is a local SQLite harness layered on ``VariantStore`` and
``MetadataStore``. It demonstrates the governed query contract and its
access-tier, traceability, and reproducibility behavior against
runtime-generated synthetic data. It is not a deployed Fabric/Databricks
notebook environment or SQL warehouse endpoint; a deployment must still
validate those services independently.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Mapping

from scripts.governance import GovernancePolicy
from scripts.metadata_store import MetadataStore
from scripts.variant_store import VariantStore


_SNAPSHOT_ID = re.compile(r"SNAPSHOT-[0-9]{4,}$")
FILTER_PASS_VALUE = "PASS"


class AnalyticsQueryError(ValueError):
    """Raised for malformed analytics query input."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StoreSnapshot:
    """An immutable, reproducible cut of the variant store as of a point in time.

    ``max_variant_rowid`` and ``max_provenance_rowid`` bound every query
    issued against this snapshot so that rows ingested after it was captured
    are excluded, which is what makes a re-run against the recorded snapshot
    reproduce the original result set (task 9.4).
    """

    snapshot_id: str
    captured_at: str
    max_variant_rowid: int
    max_provenance_rowid: int


@dataclass(frozen=True)
class QueryMeasurement:
    """Observed elapsed time for a governed analytics query."""

    scenario: str
    snapshot_id: str
    response_time_ms: float


class QueryResults(list[dict[str, Any]]):
    """List-compatible governed rows with observable query timing metadata."""

    def __init__(self, rows: list[dict[str, Any]], snapshot_id: str):
        super().__init__(rows)
        self.snapshot_id = snapshot_id
        self.response_time_ms: float | None = None
        self.scenario: str | None = None


def _measured(scenario: str) -> Callable[[Callable[..., QueryResults]], Callable[..., QueryResults]]:
    """Record an elapsed time around a supported governed query method."""

    def decorate(method: Callable[..., QueryResults]) -> Callable[..., QueryResults]:
        @wraps(method)
        def measured_method(self: "AnalyticsQueryEngine", *args: Any, **kwargs: Any) -> QueryResults:
            started = time.perf_counter()
            results = method(self, *args, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000
            results.scenario = scenario
            results.response_time_ms = elapsed_ms
            self._query_measurements.append(
                QueryMeasurement(scenario, results.snapshot_id, elapsed_ms)
            )
            return results

        return measured_method

    return decorate


# SQL templates shared by every surface: the notebook-style scenario methods
# below and the SQL-endpoint surface (SqlQueryAdapter) both execute this
# identical text through AnalyticsQueryEngine.execute_sql, so equivalence
# between the two surfaces is structural rather than merely tested.
GENE_QUERY = """
    SELECT rowid AS _rowid, * FROM variant_records
    WHERE gene = :gene AND rowid <= :max_rowid
    ORDER BY source_file_uri, POS
"""
PASS_FILTER_QUERY = """
    SELECT rowid AS _rowid, * FROM variant_records
    WHERE FILTER = :filter_value AND rowid <= :max_rowid
    ORDER BY source_file_uri, POS
"""
CROSS_COHORT_QUERY = """
    SELECT rowid AS _rowid, v.* FROM variant_records v
    WHERE v.rowid <= :max_rowid
      AND v.cohort_id IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM variant_records v2
          WHERE v2.rowid <= :max_rowid
            AND v2.CHROM = v.CHROM AND v2.POS = v.POS
            AND v2.REF = v.REF AND v2.ALT = v.ALT
            AND v2.cohort_id IS NOT NULL AND v2.cohort_id <> v.cohort_id
      )
    ORDER BY v.CHROM, v.POS, v.REF, v.ALT, v.cohort_id
"""
ALLELE_IN_SAMPLE_QUERY = """
    SELECT rowid AS _rowid, * FROM variant_records
    WHERE sample_id = :sample_id AND CHROM = :chrom AND POS = :pos
      AND REF = :ref AND ALT = :alt AND rowid <= :max_rowid
    ORDER BY source_file_uri
"""
PIPELINE_VERSION_QUERY = """
    SELECT rowid AS _rowid, * FROM variant_records
    WHERE pipeline_version = :pipeline_version AND rowid <= :max_rowid
    ORDER BY source_file_uri, POS
"""


class AnalyticsQueryEngine:
    """Governed, snapshot-aware query core over the Bronze variant store.

    Every scenario is authorized against the caller's variant-store access
    tier before any row is read (an unauthorized caller is denied with an
    explicit error), and a caller without subject-linkage access receives
    sample/cohort attributes with subject linkage withheld rather than a
    whole-query denial.
    """

    def __init__(self, variant_store: VariantStore, metadata_store: MetadataStore):
        self.variant_store = variant_store
        self.metadata_store = metadata_store
        self.governance: GovernancePolicy = metadata_store.governance
        self._query_measurements: list[QueryMeasurement] = []
        self._ensure_snapshot_table()

    @property
    def query_measurements(self) -> tuple[QueryMeasurement, ...]:
        """Return the observed timings in execution order for supported queries."""
        return tuple(self._query_measurements)

    # -- snapshots -----------------------------------------------------
    def _ensure_snapshot_table(self) -> None:
        with self.variant_store.connection:
            self.variant_store.connection.execute("""
                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    snapshot_id TEXT PRIMARY KEY NOT NULL,
                    captured_at TEXT NOT NULL,
                    max_variant_rowid INTEGER NOT NULL,
                    max_provenance_rowid INTEGER NOT NULL
                )
            """)

    def create_snapshot(self, snapshot_id: str | None = None) -> StoreSnapshot:
        """Record an immutable, reproducible cut of the store's current rows."""
        connection = self.variant_store.connection
        if snapshot_id is None:
            sequence = connection.execute(
                "SELECT COUNT(*) FROM analytics_snapshots"
            ).fetchone()[0]
            snapshot_id = f"SNAPSHOT-{sequence + 1:04d}"
        elif _SNAPSHOT_ID.fullmatch(snapshot_id) is None:
            raise AnalyticsQueryError("snapshot_id must match SNAPSHOT-####.")
        max_variant_rowid = connection.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM variant_records"
        ).fetchone()[0]
        max_provenance_rowid = connection.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM run_provenance"
        ).fetchone()[0]
        captured_at = _timestamp()
        with connection:
            connection.execute(
                """INSERT INTO analytics_snapshots
                   (snapshot_id, captured_at, max_variant_rowid, max_provenance_rowid)
                   VALUES (?, ?, ?, ?)""",
                (snapshot_id, captured_at, max_variant_rowid, max_provenance_rowid),
            )
        return StoreSnapshot(snapshot_id, captured_at, max_variant_rowid, max_provenance_rowid)

    def get_snapshot(self, snapshot_id: str) -> StoreSnapshot:
        row = self.variant_store.connection.execute(
            "SELECT * FROM analytics_snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        if row is None:
            raise AnalyticsQueryError(f"Unknown snapshot: {snapshot_id}")
        return StoreSnapshot(
            row["snapshot_id"], row["captured_at"],
            row["max_variant_rowid"], row["max_provenance_rowid"],
        )

    def resolve_snapshot(self, as_of_snapshot: "StoreSnapshot | str | None") -> StoreSnapshot:
        """Resolve a snapshot argument, creating a fresh one when none is given."""
        if as_of_snapshot is None:
            return self.create_snapshot()
        if isinstance(as_of_snapshot, StoreSnapshot):
            return as_of_snapshot
        return self.get_snapshot(as_of_snapshot)

    # -- access control and traceability --------------------------------
    def _has_subject_linkage(self, principal_id: str) -> bool:
        row = self.governance.connection.execute(
            """SELECT 1 FROM governance_capability_grants
               WHERE principal_id = ? AND capability = 'subject_linkage'""",
            (principal_id,),
        ).fetchone()
        return row is not None

    def _provenance_index(self, max_provenance_rowid: int) -> dict[tuple[Any, Any], str]:
        rows = self.variant_store.connection.execute(
            """SELECT source_file_uri, pipeline_version, run_id
               FROM run_provenance WHERE rowid <= ?""",
            (max_provenance_rowid,),
        ).fetchall()
        return {(row["source_file_uri"], row["pipeline_version"]): row["run_id"] for row in rows}

    def _project(self, principal_id: str, row: Mapping[str, Any],
                 provenance_index: Mapping[tuple[Any, Any], str]) -> dict[str, Any]:
        result = {key: value for key, value in dict(row).items() if key != "_rowid"}
        result["producing_run"] = provenance_index.get(
            (result.get("source_file_uri"), result.get("pipeline_version"))
        )
        if not self._has_subject_linkage(principal_id):
            result.pop("research_subject_id", None)
        return result

    def trace(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Return a result row's source file URI, producing run, reference
        build and pipeline version, without a separate lookup path outside
        the analytics surface (task 9.3)."""
        for key in ("source_file_uri", "reference_build", "pipeline_version"):
            if key not in row:
                raise AnalyticsQueryError(f"Result row is missing {key}.")
        producing_run = row.get("producing_run")
        if producing_run is None:
            max_provenance_rowid = self.variant_store.connection.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM run_provenance"
            ).fetchone()[0]
            producing_run = self._provenance_index(max_provenance_rowid).get(
                (row["source_file_uri"], row["pipeline_version"])
            )
        return {
            "source_file_uri": row["source_file_uri"],
            "producing_run": producing_run,
            "reference_build": row["reference_build"],
            "pipeline_version": row["pipeline_version"],
        }

    # -- SQL-endpoint surface --------------------------------------------
    def _execute_sql(self, principal_id: str, sql: str,
                     parameters: Mapping[str, Any] | None,
                     snapshot: StoreSnapshot) -> QueryResults:
        self.governance.authorize_variant_store(principal_id)
        provenance_index = self._provenance_index(snapshot.max_provenance_rowid)
        rows = self.variant_store.connection.execute(sql, dict(parameters or {})).fetchall()
        return QueryResults(
            [self._project(principal_id, row, provenance_index) for row in rows],
            snapshot.snapshot_id,
        )

    @_measured("sql_endpoint")
    def execute_sql(self, principal_id: str, sql: str, parameters: Mapping[str, Any] | None = None,
                    *, as_of_snapshot: "StoreSnapshot | str | None" = None) -> QueryResults:
        """Execute a governed, read-only SQL SELECT against the variant store.

        This is the SQL-endpoint surface: it runs the identical SQL text the
        notebook-style scenario methods use, through the same authorization,
        de-identification and traceability pipeline, so the same principal
        gets an equivalent result set from either surface.
        """
        if not isinstance(sql, str) or not sql.strip().lower().startswith("select"):
            raise AnalyticsQueryError("Only read-only SELECT statements are supported.")
        snapshot = self.resolve_snapshot(as_of_snapshot)
        return self._execute_sql(principal_id, sql, parameters, snapshot)

    # -- six supported query scenarios (task 9.1) ------------------------
    @_measured("gene")
    def query_by_gene(self, principal_id: str, gene: str, *,
                      as_of_snapshot: "StoreSnapshot | str | None" = None) -> QueryResults:
        if not isinstance(gene, str) or not gene.strip():
            raise AnalyticsQueryError("gene is required.")
        snapshot = self.resolve_snapshot(as_of_snapshot)
        return self._execute_sql(
            principal_id, GENE_QUERY,
            {"gene": gene, "max_rowid": snapshot.max_variant_rowid}, snapshot,
        )

    @_measured("quality_filter")
    def query_pass_filter(self, principal_id: str, *,
                          as_of_snapshot: "StoreSnapshot | str | None" = None) -> QueryResults:
        snapshot = self.resolve_snapshot(as_of_snapshot)
        return self._execute_sql(
            principal_id, PASS_FILTER_QUERY,
            {"filter_value": FILTER_PASS_VALUE, "max_rowid": snapshot.max_variant_rowid}, snapshot,
        )

    @_measured("cross_cohort")
    def query_cross_cohort(self, principal_id: str, *,
                           as_of_snapshot: "StoreSnapshot | str | None" = None) -> QueryResults:
        snapshot = self.resolve_snapshot(as_of_snapshot)
        rows = self._execute_sql(
            principal_id, CROSS_COHORT_QUERY,
            {"max_rowid": snapshot.max_variant_rowid}, snapshot,
        )
        cohorts_by_key: dict[tuple[Any, ...], list[str]] = {}
        for row in rows:
            key = (row["CHROM"], row["POS"], row["REF"], row["ALT"])
            bucket = cohorts_by_key.setdefault(key, [])
            if row["cohort_id"] not in bucket:
                bucket.append(row["cohort_id"])
        for row in rows:
            key = (row["CHROM"], row["POS"], row["REF"], row["ALT"])
            row["cohorts"] = sorted(cohorts_by_key[key])
        return rows

    @_measured("allele_in_sample")
    def query_allele_in_sample(self, principal_id: str, sample_id: str, chrom: str, pos: int,
                               ref: str, alt: str, *,
                               as_of_snapshot: "StoreSnapshot | str | None" = None) -> QueryResults:
        for name, value in (("sample_id", sample_id), ("chrom", chrom), ("ref", ref), ("alt", alt)):
            if not isinstance(value, str) or not value.strip():
                raise AnalyticsQueryError(f"{name} is required.")
        if not isinstance(pos, int) or isinstance(pos, bool):
            raise AnalyticsQueryError("pos must be an integer.")
        snapshot = self.resolve_snapshot(as_of_snapshot)
        return self._execute_sql(
            principal_id, ALLELE_IN_SAMPLE_QUERY,
            {"sample_id": sample_id, "chrom": chrom, "pos": pos, "ref": ref, "alt": alt,
             "max_rowid": snapshot.max_variant_rowid}, snapshot,
        )

    @_measured("pipeline_version")
    def query_by_pipeline_version(self, principal_id: str, pipeline_version: str, *,
                                  as_of_snapshot: "StoreSnapshot | str | None" = None) -> QueryResults:
        if not isinstance(pipeline_version, str) or not pipeline_version.strip():
            raise AnalyticsQueryError("pipeline_version is required.")
        snapshot = self.resolve_snapshot(as_of_snapshot)
        return self._execute_sql(
            principal_id, PIPELINE_VERSION_QUERY,
            {"pipeline_version": pipeline_version, "max_rowid": snapshot.max_variant_rowid}, snapshot,
        )

    @_measured("sequencing_run")
    def query_by_sequencing_run(self, principal_id: str, sequencing_run_id: str, *,
                                as_of_snapshot: "StoreSnapshot | str | None" = None) -> QueryResults:
        sample_ids = self.metadata_store.samples_for_sequencing_run(sequencing_run_id)
        if not sample_ids:
            snapshot = self.resolve_snapshot(as_of_snapshot)
            self.governance.authorize_variant_store(principal_id)
            return QueryResults([], snapshot.snapshot_id)
        snapshot = self.resolve_snapshot(as_of_snapshot)
        placeholders = ", ".join(f":sample_{index}" for index in range(len(sample_ids)))
        sql = f"""
            SELECT rowid AS _rowid, * FROM variant_records
            WHERE sample_id IN ({placeholders}) AND rowid <= :max_rowid
            ORDER BY source_file_uri, POS
        """
        parameters: dict[str, Any] = {
            f"sample_{index}": sample_id for index, sample_id in enumerate(sample_ids)
        }
        parameters["max_rowid"] = snapshot.max_variant_rowid
        return self._execute_sql(principal_id, sql, parameters, snapshot)


class SqlQueryAdapter:
    """SQL-endpoint façade over :meth:`AnalyticsQueryEngine.execute_sql`.

    Exposed as a distinct surface so tests and documentation can address a
    SQL-endpoint style entry point separately from the Python method-call
    surface, while both execute the identical governed SQL templates.
    """

    GENE_QUERY = GENE_QUERY
    PASS_FILTER_QUERY = PASS_FILTER_QUERY
    CROSS_COHORT_QUERY = CROSS_COHORT_QUERY
    ALLELE_IN_SAMPLE_QUERY = ALLELE_IN_SAMPLE_QUERY
    PIPELINE_VERSION_QUERY = PIPELINE_VERSION_QUERY

    def __init__(self, engine: AnalyticsQueryEngine):
        self.engine = engine

    def execute(self, principal_id: str, sql: str, parameters: Mapping[str, Any] | None = None,
                *, as_of_snapshot: "StoreSnapshot | str | None" = None) -> list[dict[str, Any]]:
        return self.engine.execute_sql(principal_id, sql, parameters, as_of_snapshot=as_of_snapshot)


class NotebookSession:
    """Represents a single notebook run against the governed variant store.

    A session records the store snapshot it reads once, at construction, and
    every query it issues is bound to that recorded snapshot. Re-running a
    notebook by constructing a new session against the same recorded
    ``snapshot`` reproduces the original result set even if the store has
    since been ingested into further (task 9.4).
    """

    def __init__(self, engine: AnalyticsQueryEngine, principal_id: str,
                 snapshot: "StoreSnapshot | str | None" = None):
        self.engine = engine
        self.principal_id = principal_id
        self.snapshot = engine.resolve_snapshot(snapshot)

    def query_by_gene(self, gene: str) -> list[dict[str, Any]]:
        return self.engine.query_by_gene(self.principal_id, gene, as_of_snapshot=self.snapshot)

    def query_pass_filter(self) -> list[dict[str, Any]]:
        return self.engine.query_pass_filter(self.principal_id, as_of_snapshot=self.snapshot)

    def query_cross_cohort(self) -> list[dict[str, Any]]:
        return self.engine.query_cross_cohort(self.principal_id, as_of_snapshot=self.snapshot)

    def query_allele_in_sample(self, sample_id: str, chrom: str, pos: int, ref: str,
                                alt: str) -> list[dict[str, Any]]:
        return self.engine.query_allele_in_sample(
            self.principal_id, sample_id, chrom, pos, ref, alt, as_of_snapshot=self.snapshot
        )

    def query_by_pipeline_version(self, pipeline_version: str) -> list[dict[str, Any]]:
        return self.engine.query_by_pipeline_version(
            self.principal_id, pipeline_version, as_of_snapshot=self.snapshot
        )

    def query_by_sequencing_run(self, sequencing_run_id: str) -> list[dict[str, Any]]:
        return self.engine.query_by_sequencing_run(
            self.principal_id, sequencing_run_id, as_of_snapshot=self.snapshot
        )