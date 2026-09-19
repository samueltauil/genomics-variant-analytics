"""Instrumented local KPI collector for the accelerator demo.

This module is intentionally a local synthetic harness, not an Azure
production telemetry implementation.  It records pipeline, arrival,
queryability, query, and cost events in SQLite, then derives every KPI from
those persisted events and the local Bronze variant-store rows.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analytics_query import AnalyticsQueryEngine
from scripts.metadata_store import MetadataStore
from scripts.variant_store import VariantStore


TERMINAL_PIPELINE_STATES = frozenset({"succeeded", "failed"})


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone.")
    return parsed


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class KpiMeasurement:
    """A metric derived solely from persisted local measurement records."""

    name: str
    value: float
    unit: str
    numerator: float | None
    denominator: float | None
    source: str
    measurement_scope: str = "local synthetic measurement"


class KpiEventStore:
    """Append-only local event and cost ledger used by the KPI collector."""

    def __init__(self, database: str | Path):
        self.connection = sqlite3.connect(Path(database))
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS kpi_events (
                    event_id TEXT PRIMARY KEY NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    run_id TEXT,
                    sample_id TEXT,
                    related_run_id TEXT,
                    state TEXT
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS kpi_cost_ledger (
                    cost_id TEXT PRIMARY KEY NOT NULL,
                    incurred_at TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    sample_id TEXT NOT NULL,
                    amount_usd REAL NOT NULL CHECK(amount_usd >= 0),
                    source TEXT NOT NULL
                )
            """)

    def close(self) -> None:
        self.connection.close()

    def record_event(
        self,
        event_id: str,
        event_type: str,
        occurred_at: str,
        *,
        run_id: str | None = None,
        sample_id: str | None = None,
        related_run_id: str | None = None,
        state: str | None = None,
    ) -> None:
        _timestamp(occurred_at)
        if not event_id or not event_type:
            raise ValueError("event_id and event_type are required.")
        with self.connection:
            self.connection.execute(
                """INSERT INTO kpi_events
                   (event_id, event_type, occurred_at, run_id, sample_id, related_run_id, state)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (event_id, event_type, occurred_at, run_id, sample_id, related_run_id, state),
            )

    def record_cost(
        self, cost_id: str, incurred_at: str, run_id: str, sample_id: str,
        amount_usd: float, source: str,
    ) -> None:
        _timestamp(incurred_at)
        if not cost_id or not run_id or not sample_id or not source:
            raise ValueError("cost_id, run_id, sample_id, and source are required.")
        if amount_usd < 0:
            raise ValueError("amount_usd must not be negative.")
        with self.connection:
            self.connection.execute(
                """INSERT INTO kpi_cost_ledger
                   (cost_id, incurred_at, run_id, sample_id, amount_usd, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (cost_id, incurred_at, run_id, sample_id, amount_usd, source),
            )


class AcceleratorKpiCollector:
    """Calculates accelerator KPIs from instrumented SQLite records."""

    def __init__(self, events: KpiEventStore, variant_store: VariantStore):
        self.events = events
        self.variant_store = variant_store

    def pipeline_success_rate(self) -> KpiMeasurement:
        rows = self.events.connection.execute(
            """SELECT state, COUNT(*) AS count FROM kpi_events
               WHERE event_type = 'pipeline_finished' AND state IN ('succeeded', 'failed')
               GROUP BY state"""
        ).fetchall()
        counts = {row["state"]: row["count"] for row in rows}
        succeeded = counts.get("succeeded", 0)
        total = sum(counts.values())
        return self._ratio("pipeline_success_rate", succeeded, total, "percent")

    def arrival_to_queryable_duration(self) -> KpiMeasurement:
        rows = self.events.connection.execute("""
            SELECT arrival.occurred_at AS arrival_at, queryable.occurred_at AS queryable_at
            FROM kpi_events AS arrival
            JOIN kpi_events AS queryable
              ON queryable.run_id = arrival.run_id
            WHERE arrival.event_type = 'arrival'
              AND queryable.event_type = 'queryable'
        """).fetchall()
        durations = [
            (_timestamp(row["queryable_at"]) - _timestamp(row["arrival_at"])).total_seconds()
            for row in rows
        ]
        return self._mean(
            "arrival_to_queryable_duration", durations, "seconds",
            "recorded arrival and queryable timestamps",
        )

    def query_response_time(self) -> KpiMeasurement:
        rows = self.events.connection.execute("""
            SELECT started.occurred_at AS started_at, finished.occurred_at AS finished_at
            FROM kpi_events AS started
            JOIN kpi_events AS finished
              ON finished.run_id = started.run_id
             AND finished.event_id = replace(started.event_id, 'query-started', 'query-finished')
            WHERE started.event_type = 'query_started'
              AND finished.event_type = 'query_finished'
        """).fetchall()
        durations_ms = [
            (_timestamp(row["finished_at"]) - _timestamp(row["started_at"])).total_seconds() * 1000
            for row in rows
        ]
        return self._mean(
            "query_response_time", durations_ms, "milliseconds",
            "recorded query start and finish timestamps",
        )

    def records_linked_to_source_files(self) -> KpiMeasurement:
        row = self.variant_store.connection.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN source_file_uri IS NOT NULL
                                 AND trim(source_file_uri) <> '' THEN 1 ELSE 0 END) AS linked
            FROM variant_records
        """).fetchone()
        return self._ratio(
            "records_linked_to_source_files", row["linked"] or 0, row["total"], "percent"
        )

    def reprocessing_time(self) -> KpiMeasurement:
        rows = self.events.connection.execute("""
            SELECT started.occurred_at AS started_at, finished.occurred_at AS finished_at
            FROM kpi_events AS started
            JOIN kpi_events AS finished
              ON finished.run_id = started.run_id
            WHERE started.event_type = 'pipeline_started'
              AND started.related_run_id IS NOT NULL
              AND finished.event_type = 'pipeline_finished'
              AND finished.state = 'succeeded'
        """).fetchall()
        durations = [
            (_timestamp(row["finished_at"]) - _timestamp(row["started_at"])).total_seconds()
            for row in rows
        ]
        return self._mean(
            "reprocessing_time", durations, "seconds",
            "recorded reprocessing pipeline start and success timestamps",
        )

    def cost_per_sample(self) -> KpiMeasurement:
        row = self.events.connection.execute("""
            SELECT COALESCE(SUM(amount_usd), 0) AS total_cost,
                   COUNT(DISTINCT sample_id) AS sample_count
            FROM kpi_cost_ledger
        """).fetchone()
        return self._ratio(
            "cost_per_sample", row["total_cost"], row["sample_count"], "USD per sample",
            scale=1,
        )

    def collect(self) -> tuple[KpiMeasurement, ...]:
        return (
            self.pipeline_success_rate(),
            self.arrival_to_queryable_duration(),
            self.query_response_time(),
            self.records_linked_to_source_files(),
            self.reprocessing_time(),
            self.cost_per_sample(),
        )

    @staticmethod
    def _ratio(
        name: str, numerator: float, denominator: float, unit: str, *, scale: float = 100
    ) -> KpiMeasurement:
        if denominator == 0:
            raise ValueError(f"{name} cannot be measured without recorded denominator data.")
        return KpiMeasurement(
            name, numerator / denominator * scale, unit, numerator, denominator,
            "recorded counts or cost ledger",
        )

    @staticmethod
    def _mean(
        name: str, values: list[float], unit: str, source: str
    ) -> KpiMeasurement:
        if not values:
            raise ValueError(f"{name} cannot be measured without recorded events.")
        return KpiMeasurement(name, sum(values) / len(values), unit, sum(values), len(values), source)


def _vcf() -> str:
    return "\n".join((
        "##fileformat=VCFv4.3",
        "##INFO=<ID=GENE,Number=1,Type=String,Description=\"Synthetic gene\">",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
        "1\t101\tSYN-KPI-VAR-001\tA\tG\t99\tPASS\tGENE=KPI1\tGT\t0/1",
        "",
    ))


def _provenance(run_id: str, sample_id: str, source_file_uri: str, timestamp: str) -> dict[str, str]:
    return {
        "run_id": run_id,
        "sample_id": sample_id,
        "research_subject_id": f"SYN-SUBJECT-{sample_id.removeprefix('SYN-SAMPLE-')}",
        "cohort_id": "SYN-COHORT-KPI",
        "pipeline_version": "release-kpi-local-1.0.0",
        "reference_build": "GRCh38",
        "reference_version_or_digest": "manifest-sha256:synthetic-kpi-reference-001",
        "classification": "genomic-variant",
        "source_file_uri": source_file_uri,
        "ingestion_timestamp": timestamp,
    }


def run_local_synthetic_harness(state_root: str | Path) -> tuple[KpiMeasurement, ...]:
    """Create real local synthetic stores and return six measured KPI values."""

    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    event_store = KpiEventStore(root / "kpi_events.sqlite3")
    variant_store = VariantStore(root / "kpi_variant_store.sqlite3")
    metadata_store = MetadataStore(root / "kpi_metadata.sqlite3")
    try:
        metadata_store.grant_tier("SYN-KPI-ANALYST", "variant_store")
        events = (
            ("arrival-a", "arrival", "2026-09-19T09:00:00Z", "SYN-KPI-RUN-A", "SYN-SAMPLE-A", None, None),
            ("pipeline-started-a", "pipeline_started", "2026-09-19T09:01:00Z", "SYN-KPI-RUN-A", "SYN-SAMPLE-A", None, None),
            ("pipeline-finished-a", "pipeline_finished", "2026-09-19T09:05:00Z", "SYN-KPI-RUN-A", "SYN-SAMPLE-A", None, "succeeded"),
            ("queryable-a", "queryable", "2026-09-19T09:09:00Z", "SYN-KPI-RUN-A", "SYN-SAMPLE-A", None, None),
            ("arrival-b", "arrival", "2026-09-19T09:10:00Z", "SYN-KPI-RUN-B", "SYN-SAMPLE-B", None, None),
            ("pipeline-started-b", "pipeline_started", "2026-09-19T09:11:00Z", "SYN-KPI-RUN-B", "SYN-SAMPLE-B", None, None),
            ("pipeline-finished-b", "pipeline_finished", "2026-09-19T09:15:00Z", "SYN-KPI-RUN-B", "SYN-SAMPLE-B", None, "failed"),
            ("pipeline-started-c", "pipeline_started", "2026-09-19T09:20:00Z", "SYN-KPI-RUN-C", "SYN-SAMPLE-A", "SYN-KPI-RUN-A", None),
            ("pipeline-finished-c", "pipeline_finished", "2026-09-19T09:26:00Z", "SYN-KPI-RUN-C", "SYN-SAMPLE-A", "SYN-KPI-RUN-A", "succeeded"),
            ("queryable-c", "queryable", "2026-09-19T09:30:00Z", "SYN-KPI-RUN-C", "SYN-SAMPLE-A", None, None),
        )
        for event in events:
            event_store.record_event(*event[:3], run_id=event[3], sample_id=event[4],
                                     related_run_id=event[5], state=event[6])

        variant_store.ingest_vcf_text(
            _vcf(), _provenance(
                "SYN-KPI-RUN-A", "SYN-SAMPLE-A", "abfss://synthetic/kpi/run-a.vcf",
                "2026-09-19T09:09:00Z",
            )
        )
        variant_store.ingest_vcf_text(
            _vcf().replace("SYN-KPI-VAR-001", "SYN-KPI-VAR-002"), _provenance(
                "SYN-KPI-RUN-C", "SYN-SAMPLE-A", "abfss://synthetic/kpi/run-c.vcf",
                "2026-09-19T09:30:00Z",
            )
        )

        engine = AnalyticsQueryEngine(variant_store, metadata_store)
        query_run_id = "SYN-KPI-QUERY-001"
        event_store.record_event("query-started-001", "query_started", _utc_now(), run_id=query_run_id)
        engine.query_by_gene("SYN-KPI-ANALYST", "KPI1")
        event_store.record_event("query-finished-001", "query_finished", _utc_now(), run_id=query_run_id)

        event_store.record_cost(
            "cost-a", "2026-09-19T09:05:00Z", "SYN-KPI-RUN-A", "SYN-SAMPLE-A", 1.25,
            "local synthetic execution ledger",
        )
        event_store.record_cost(
            "cost-b", "2026-09-19T09:15:00Z", "SYN-KPI-RUN-B", "SYN-SAMPLE-B", 0.75,
            "local synthetic execution ledger",
        )
        event_store.record_cost(
            "cost-c", "2026-09-19T09:26:00Z", "SYN-KPI-RUN-C", "SYN-SAMPLE-A", 1.00,
            "local synthetic execution ledger",
        )
        return AcceleratorKpiCollector(event_store, variant_store).collect()
    finally:
        metadata_store.close()
        variant_store.close()
        event_store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure local accelerator KPIs from instrumented data.")
    parser.add_argument("--state-root", type=Path, help="Directory for local generated KPI stores.")
    args = parser.parse_args()
    if args.state_root is None:
        with tempfile.TemporaryDirectory(prefix="accelerator-kpis-") as directory:
            measurements = run_local_synthetic_harness(directory)
    else:
        measurements = run_local_synthetic_harness(args.state_root)
    print(json.dumps([asdict(measurement) for measurement in measurements], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
