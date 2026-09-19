import tempfile
import unittest
from pathlib import Path

from scripts.analytics_query import (
    AnalyticsQueryEngine,
    NotebookSession,
    SqlQueryAdapter,
)
from scripts.governance import AuthorizationError
from scripts.metadata_store import MetadataStore
from scripts.variant_store import VariantStore


def synthetic_vcf(*rows):
    return "\n".join([
        "##fileformat=VCFv4.3",
        "##INFO=<ID=GENE,Number=1,Type=String,Description=\"Synthetic gene\">",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
        *rows,
        "",
    ])


def provenance(**overrides):
    base = {
        "run_id": "SYN-RUN-A",
        "sample_id": "SYN-SAMPLE-A",
        "research_subject_id": "SYN-SUBJECT-A",
        "cohort_id": "SYN-COHORT-A",
        "pipeline_version": "release-1.0.0",
        "reference_build": "GRCh38",
        "reference_version_or_digest": "manifest-sha256:synthetic-reference-001",
        "classification": "genomic-variant",
        "source_file_uri": "abfss://synthetic/vcf/run-a.vcf",
        "ingestion_timestamp": "2026-09-15T18:00:00-04:00",
    }
    base.update(overrides)
    return base


class AnalyticsQueryEngineTests(unittest.TestCase):
    """Covers OpenSpec tasks 9.1-9.4: the six query scenarios, equivalent
    notebook/SQL surfaces, per-row traceability, and reproducible snapshots,
    all against runtime-generated synthetic VCF/metadata (no genomic files)."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.variant_store = VariantStore(Path(self.temporary.name) / "bronze.sqlite3")
        self.addCleanup(self.variant_store.close)
        self.metadata_store = MetadataStore(Path(self.temporary.name) / "metadata.sqlite3")
        self.addCleanup(self.metadata_store.close)
        self.engine = AnalyticsQueryEngine(self.variant_store, self.metadata_store)

        self.principal = "SYN-ANALYST-001"
        self.metadata_store.grant_tier(self.principal, "variant_store")

        # Run A: SYN-COHORT-A / SYN-SAMPLE-A, gene GENE1 at chr1:101 A>G (PASS),
        # plus a low-quality variant that fails the quality filter.
        self.variant_store.ingest_vcf_text(
            synthetic_vcf(
                "1\t101\tSYN-VAR-001\tA\tG\t99\tPASS\tGENE=GENE1\tGT\t0/1",
                "1\t202\tSYN-VAR-002\tC\tT\t12\tq10\tGENE=GENE1\tGT\t0/1",
            ),
            provenance(),
        )
        # Run B: SYN-COHORT-B / SYN-SAMPLE-B, the same GENE1 variant at
        # chr1:101 A>G, so it is shared across two cohorts.
        self.variant_store.ingest_vcf_text(
            synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t99\tPASS\tGENE=GENE1\tGT\t1/1"),
            provenance(
                run_id="SYN-RUN-B", sample_id="SYN-SAMPLE-B",
                research_subject_id="SYN-SUBJECT-B", cohort_id="SYN-COHORT-B",
                source_file_uri="abfss://synthetic/vcf/run-b.vcf",
            ),
        )
        # Run C: an older pipeline version reprocessing SYN-SAMPLE-A.
        self.variant_store.ingest_vcf_text(
            synthetic_vcf("1\t303\tSYN-VAR-003\tG\tA\t80\tPASS\tGENE=GENE2\tGT\t0/1"),
            provenance(
                run_id="SYN-RUN-C", pipeline_version="release-0.9.0",
                source_file_uri="abfss://synthetic/vcf/run-c.vcf",
            ),
        )

        # Lineage for the sequencing-run query scenario.
        self.metadata_store.add_entity("SYN-SUBJECT-A", "subject")
        self.metadata_store.add_entity("SYN-SAMPLE-A", "sample", ["SYN-SUBJECT-A"])
        self.metadata_store.add_entity("SYN-SEQRUN-A", "sequencing_run", ["SYN-SAMPLE-A"])

    def test_query_by_gene_returns_matching_rows_with_context(self):
        rows = self.engine.query_by_gene(self.principal, "GENE1")
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["gene"], "GENE1")
            self.assertIn(row["sample_id"], {"SYN-SAMPLE-A", "SYN-SAMPLE-B"})
            self.assertIn(row["cohort_id"], {"SYN-COHORT-A", "SYN-COHORT-B"})
            self.assertIn("FILTER", row)
            self.assertEqual(row["reference_build"], "GRCh38")
            self.assertIn(row["pipeline_version"], {"release-1.0.0"})

    def test_quality_filter_query_returns_only_pass_records(self):
        rows = self.engine.query_pass_filter(self.principal)
        self.assertTrue(all(row["FILTER"] == "PASS" for row in rows))
        self.assertTrue(any(row["ID"] == "SYN-VAR-002" for row in self.variant_store.records()))
        self.assertFalse(any(row["ID"] == "SYN-VAR-002" for row in rows))

    def test_cross_cohort_query_lists_each_variants_cohorts(self):
        rows = self.engine.query_cross_cohort(self.principal)
        shared = [row for row in rows if row["ID"] == "SYN-VAR-001"]
        self.assertEqual(len(shared), 2)
        for row in shared:
            self.assertEqual(set(row["cohorts"]), {"SYN-COHORT-A", "SYN-COHORT-B"})
        self.assertFalse(any(row["ID"] == "SYN-VAR-003" for row in rows))

    def test_allele_in_sample_query(self):
        rows = self.engine.query_allele_in_sample(
            self.principal, "SYN-SAMPLE-A", "1", 101, "A", "G"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sample_id"], "SYN-SAMPLE-A")
        self.assertEqual(rows[0]["genotype"], "0/1")

    def test_pipeline_version_query_returns_producing_run(self):
        rows = self.engine.query_by_pipeline_version(self.principal, "release-0.9.0")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pipeline_version"], "release-0.9.0")
        self.assertEqual(rows[0]["producing_run"], "SYN-RUN-C")

    def test_sequencing_run_query_resolves_through_lineage(self):
        rows = self.engine.query_by_sequencing_run(self.principal, "SYN-SEQRUN-A")
        self.assertEqual({row["ID"] for row in rows}, {"SYN-VAR-001", "SYN-VAR-002", "SYN-VAR-003"})
        self.assertTrue(all(row["sample_id"] == "SYN-SAMPLE-A" for row in rows))

    def test_unauthorized_principal_is_denied_not_emptied(self):
        with self.assertRaises(AuthorizationError):
            self.engine.query_by_gene("SYN-NO-GRANT", "GENE1")

    def test_deidentified_caller_keeps_sample_and_cohort_but_not_subject(self):
        rows = self.engine.query_by_gene(self.principal, "GENE1")
        self.assertTrue(all("research_subject_id" not in row for row in rows))
        self.assertTrue(all(row["sample_id"] and row["cohort_id"] for row in rows))

    def test_subject_linked_caller_keeps_research_subject_id(self):
        self.metadata_store.grant_capability(self.principal, "subject_linkage")
        rows = self.engine.query_by_gene(self.principal, "GENE1")
        self.assertTrue(all(row["research_subject_id"] for row in rows))

    def test_result_traceability_without_separate_lookup(self):
        rows = self.engine.query_by_gene(self.principal, "GENE1")
        row = next(row for row in rows if row["ID"] == "SYN-VAR-001" and row["sample_id"] == "SYN-SAMPLE-A")
        origin = self.engine.trace(row)
        self.assertEqual(origin["source_file_uri"], "abfss://synthetic/vcf/run-a.vcf")
        self.assertEqual(origin["producing_run"], "SYN-RUN-A")
        self.assertEqual(origin["reference_build"], "GRCh38")
        self.assertEqual(origin["pipeline_version"], "release-1.0.0")
        # Already attached to the result row, with no separate lookup needed.
        self.assertEqual(row["producing_run"], "SYN-RUN-A")

    def test_notebook_and_sql_surfaces_return_equivalent_results(self):
        snapshot = self.engine.create_snapshot()
        notebook_rows = self.engine.query_by_gene(self.principal, "GENE1", as_of_snapshot=snapshot)

        adapter = SqlQueryAdapter(self.engine)
        sql_rows = adapter.execute(
            self.principal, SqlQueryAdapter.GENE_QUERY,
            {"gene": "GENE1", "max_rowid": snapshot.max_variant_rowid},
            as_of_snapshot=snapshot,
        )

        key = lambda row: (row["source_file_uri"], row["ID"])
        self.assertEqual(sorted(notebook_rows, key=key), sorted(sql_rows, key=key))

    def test_notebook_session_reproduces_recorded_snapshot(self):
        session = NotebookSession(self.engine, self.principal)
        original = session.query_by_gene("GENE1")

        self.variant_store.ingest_vcf_text(
            synthetic_vcf("1\t404\tSYN-VAR-004\tA\tT\t90\tPASS\tGENE=GENE1\tGT\t0/1"),
            provenance(
                run_id="SYN-RUN-D", source_file_uri="abfss://synthetic/vcf/run-d.vcf",
            ),
        )

        rerun_session = NotebookSession(self.engine, self.principal, snapshot=session.snapshot)
        rerun = rerun_session.query_by_gene("GENE1")
        self.assertEqual(
            sorted((row["source_file_uri"], row["ID"]) for row in original),
            sorted((row["source_file_uri"], row["ID"]) for row in rerun),
        )

        fresh_session = NotebookSession(self.engine, self.principal)
        refreshed = fresh_session.query_by_gene("GENE1")
        self.assertEqual(len(refreshed), len(original) + 1)


if __name__ == "__main__":
    unittest.main()