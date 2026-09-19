"""Access-aware analytics view models and exploratory query adapter.

These local/reference adapters render only results obtained through
``AnalyticsQueryEngine``. They do not expose table or file credentials and
they preserve the query engine's de-identified projection.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from scripts.analytics_query import AnalyticsQueryEngine, QueryResults


EXPLORATORY_NOTICE = (
    "Exploratory AI-assisted analysis only; not a diagnosis, clinical "
    "determination, treatment recommendation, or clinical decision support."
)
_GENE = re.compile(r"\bgene\s+([A-Za-z0-9._-]+)\b", re.IGNORECASE)


def _view(name: str, rows: list[dict[str, Any]], results: QueryResults) -> dict[str, Any]:
    return {
        "view": name,
        "rows": rows,
        "query": {
            "scenario": results.scenario,
            "snapshot_id": results.snapshot_id,
            "response_time_ms": results.response_time_ms,
        },
    }


class AnalyticsViewModels:
    """Six view models backed exclusively by the governed query engine."""

    def __init__(self, engine: AnalyticsQueryEngine):
        self.engine = engine

    def gene_centric(self, principal_id: str, gene: str) -> dict[str, Any]:
        results = self.engine.query_by_gene(principal_id, gene)
        rows = [
            {
                "variant": f"{row['CHROM']}:{row['POS']} {row['REF']}>{row['ALT']}",
                "sample_id": row["sample_id"],
                "cohort_id": row["cohort_id"],
                "filter": row["FILTER"],
                "reference_build": row["reference_build"],
                "pipeline_version": row["pipeline_version"],
            }
            for row in results
        ]
        return _view("gene-centric", rows, results)

    def variant_frequency(self, principal_id: str) -> dict[str, Any]:
        results = self.engine.query_pass_filter(principal_id)
        frequency = Counter(
            f"{row['CHROM']}:{row['POS']} {row['REF']}>{row['ALT']}" for row in results
        )
        rows = [
            {"variant": variant, "sample_count": count}
            for variant, count in sorted(frequency.items())
        ]
        return _view("variant-frequency", rows, results)

    def cohort_comparison(self, principal_id: str) -> dict[str, Any]:
        results = self.engine.query_cross_cohort(principal_id)
        grouped: dict[str, set[str]] = {}
        for row in results:
            key = f"{row['CHROM']}:{row['POS']} {row['REF']}>{row['ALT']}"
            grouped.setdefault(key, set()).update(row["cohorts"])
        rows = [
            {"variant": variant, "cohorts": sorted(cohorts), "cohort_count": len(cohorts)}
            for variant, cohorts in sorted(grouped.items())
        ]
        return _view("cohort-comparison", rows, results)

    def quality_filter_funnel(self, principal_id: str, gene: str) -> dict[str, Any]:
        all_results = self.engine.query_by_gene(principal_id, gene)
        passed_results = self.engine.query_pass_filter(principal_id)
        passed_gene = [row for row in passed_results if row["gene"] == gene]
        rows = [
            {"stage": "gene-matched", "variant_count": len(all_results)},
            {"stage": "filter-pass", "variant_count": len(passed_gene)},
            {"stage": "filtered-out", "variant_count": len(all_results) - len(passed_gene)},
        ]
        return _view("quality-filter-funnel", rows, all_results)

    def sample_to_file_lineage(self, principal_id: str, sample_id: str) -> dict[str, Any]:
        self.engine.governance.authorize_variant_store(principal_id)
        entities = self.engine.metadata_store.trace_sample(sample_id)["entities"]
        subject_linkage = self.engine._has_subject_linkage(principal_id)
        rows = [
            {
                key: value
                for key, value in entity.items()
                if subject_linkage or key != "research_subject_id"
            }
            for entity in entities
            if subject_linkage or entity["kind"] != "subject"
        ]
        return {
            "view": "sample-to-file-lineage",
            "rows": rows,
            "subject_linkage_withheld": not subject_linkage,
        }

    def processing_status(self, principal_id: str) -> dict[str, Any]:
        self.engine.governance.authorize_variant_store(principal_id)
        rows = [
            {
                "run_id": row["run_id"],
                "state": "ingestion-completed",
                "execution_target": None,
                "failure_reason": None,
                "accepted_count": row["accepted_count"],
                "rejected_count": row["rejected_count"],
                "pipeline_version": row["pipeline_version"],
            }
            for row in self.engine.variant_store.connection.execute(
                """SELECT run_id, pipeline_version, accepted_count, rejected_count
                   FROM run_provenance ORDER BY ingestion_timestamp, run_id"""
            )
        ]
        return {
            "view": "processing-status",
            "rows": rows,
            "limitations": (
                "Local ingestion provenance does not record execution target or failure "
                "reason; unavailable values are null rather than inferred."
            ),
        }


@dataclass(frozen=True)
class ExplorationResponse:
    question: str
    governed_scenario: str
    results: tuple[dict[str, Any], ...]
    traceability: tuple[dict[str, Any], ...]
    exploratory_notice: str = EXPLORATORY_NOTICE


class AssistedCohortExploration:
    """Bounded natural-language cohort exploration through governed queries only."""

    def __init__(self, engine: AnalyticsQueryEngine):
        self.engine = engine

    def ask(self, principal_id: str, question: str) -> ExplorationResponse:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question is required.")
        gene = _GENE.search(question)
        normalized = question.lower()
        if gene is None:
            raise ValueError("Only questions naming a gene are supported.")
        if "cohort" in normalized and (
            "more than one" in normalized or "shared" in normalized or "across" in normalized
        ):
            results = self.engine.query_cross_cohort(principal_id)
            rows = [row for row in results if row["gene"] == gene.group(1)]
            scenario = "cross_cohort"
        else:
            results = self.engine.query_by_gene(principal_id, gene.group(1))
            rows = list(results)
            scenario = "gene"
        self.engine.governance.audit.record(
            "data_access",
            principal_id,
            "ai_assisted_cohort_exploration",
            {"scenario": scenario, "question": question, "subject_linked": self.engine._has_subject_linkage(principal_id)},
        )
        return ExplorationResponse(
            question=question,
            governed_scenario=scenario,
            results=tuple(rows),
            traceability=tuple(self.engine.trace(row) for row in rows),
        )
