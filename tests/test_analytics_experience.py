import tempfile
import unittest
from pathlib import Path

from scripts.analytics_experience import (
    EXPLORATORY_NOTICE,
    AnalyticsViewModels,
    AssistedCohortExploration,
)
from scripts.analytics_query import AnalyticsQueryEngine
from scripts.metadata_store import FILE_STAGES, MetadataStore
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
    value = {
        "run_id": "SYN-RUN-A",
        "sample_id": "SYN-SAMPLE-A",
        "research_subject_id": "SYN-SUBJECT-A",
        "cohort_id": "SYN-COHORT-A",
        "pipeline_version": "release-1.0.0",
        "reference_build": "GRCh38",
        "reference_version_or_digest": "manifest-sha256:synthetic-reference-001",
        "classification": "genomic-variant",
        "source_file_uri": "abfss://synthetic/vcf/run-a.vcf",
        "ingestion_timestamp": "2026-09-19T10:00:00-04:00",
    }
    value.update(overrides)
    return value


class AnalyticsExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.variant_store = VariantStore(Path(self.temporary.name) / "bronze.sqlite3")
        self.addCleanup(self.variant_store.close)
        self.metadata_store = MetadataStore(Path(self.temporary.name) / "metadata.sqlite3")
        self.addCleanup(self.metadata_store.close)
        self.engine = AnalyticsQueryEngine(self.variant_store, self.metadata_store)
        self.views = AnalyticsViewModels(self.engine)
        self.principal = "SYN-ANALYST-001"
        self.metadata_store.grant_tier(self.principal, "variant_store")
        self._seed_variant_rows()
        self._seed_sample_lineage()

    def _seed_variant_rows(self):
        cohort_a_benchmark = [
            f"1\t{1000 + index}\tSYN-BENCH-A-{index:03d}\tA\tG\t60\tPASS\tGENE=BENCHGENE\tGT\t0/1"
            for index in range(1, 25)
        ]
        cohort_b_benchmark = [
            f"1\t{1000 + index}\tSYN-BENCH-B-{index:03d}\tA\tG\t60\tPASS\tGENE=BENCHGENE\tGT\t1/1"
            for index in range(1, 25)
        ]
        self.variant_store.ingest_vcf_text(
            synthetic_vcf(
                "1\t101\tSYN-VAR-001\tA\tG\t99\tPASS\tGENE=GENE1\tGT\t0/1",
                "1\t102\tSYN-VAR-002\tC\tT\t12\tq10\tGENE=GENE1\tGT\t0/1",
                *cohort_a_benchmark,
            ),
            provenance(),
        )
        self.variant_store.ingest_vcf_text(
            synthetic_vcf(
                "1\t101\tSYN-VAR-001\tA\tG\t99\tPASS\tGENE=GENE1\tGT\t1/1",
                *cohort_b_benchmark,
            ),
            provenance(
                run_id="SYN-RUN-B",
                sample_id="SYN-SAMPLE-B",
                research_subject_id="SYN-SUBJECT-B",
                cohort_id="SYN-COHORT-B",
                source_file_uri="abfss://synthetic/vcf/run-b.vcf",
            ),
        )

    def _seed_sample_lineage(self):
        self.metadata_store.add_pipeline_run("SYN-PIPELINE-A", "synthetic-workflow", "1.0")
        self.metadata_store.add_entity("SYN-SUBJECT-A", "subject")
        self.metadata_store.add_entity("SYN-SAMPLE-A", "sample", ["SYN-SUBJECT-A"])
        self.metadata_store.add_entity("SYN-SEQRUN-A", "sequencing_run", ["SYN-SAMPLE-A"])
        parents = ["SYN-SEQRUN-A"]
        for entity_id, kind in (
            ("SYN-FASTQ-A", "fastq"),
            ("SYN-BAM-A", "bam"),
            ("SYN-VCF-A", "vcf"),
        ):
            run_id = "SYN-SEQRUN-A" if kind == "fastq" else "SYN-PIPELINE-A"
            self.metadata_store.add_entity(
                entity_id,
                kind,
                parents,
                file_metadata={
                    "storage_uri": f"abfss://synthetic@storage.invalid/{entity_id}.{kind}",
                    "analysis_stage": FILE_STAGES[kind],
                    "producing_run": run_id,
                    "integrity_result": "passed",
                },
            )
            parents = [entity_id]

    def test_six_access_aware_views_render_synthetic_data(self):
        rendered = (
            self.views.gene_centric(self.principal, "GENE1"),
            self.views.variant_frequency(self.principal),
            self.views.cohort_comparison(self.principal),
            self.views.quality_filter_funnel(self.principal, "GENE1"),
            self.views.sample_to_file_lineage(self.principal, "SYN-SAMPLE-A"),
            self.views.processing_status(self.principal),
        )
        self.assertEqual(
            [view["view"] for view in rendered],
            [
                "gene-centric", "variant-frequency", "cohort-comparison",
                "quality-filter-funnel", "sample-to-file-lineage", "processing-status",
            ],
        )
        self.assertTrue(all(view["rows"] for view in rendered))
        self.assertTrue(rendered[0]["query"]["response_time_ms"] >= 0)
        self.assertTrue(rendered[4]["subject_linkage_withheld"])
        self.assertFalse(any(row["kind"] == "subject" for row in rendered[4]["rows"]))
        self.assertIsNone(rendered[5]["rows"][0]["execution_target"])

    def test_every_supported_query_reports_measured_response_time(self):
        queries = (
            lambda: self.engine.query_by_gene(self.principal, "GENE1"),
            lambda: self.engine.query_pass_filter(self.principal),
            lambda: self.engine.query_cross_cohort(self.principal),
            lambda: self.engine.query_allele_in_sample(
                self.principal, "SYN-SAMPLE-A", "1", 101, "A", "G"
            ),
            lambda: self.engine.query_by_pipeline_version(self.principal, "release-1.0.0"),
            lambda: self.engine.query_by_sequencing_run(self.principal, "SYN-SEQRUN-A"),
        )
        for query in queries:
            results = query()
            self.assertIsNotNone(results.response_time_ms)
            self.assertGreaterEqual(results.response_time_ms, 0)
            self.assertLessEqual(results.response_time_ms, 1_000)
        self.assertEqual(
            {measurement.scenario for measurement in self.engine.query_measurements},
            {
                "gene", "quality_filter", "cross_cohort", "allele_in_sample",
                "pipeline_version", "sequencing_run",
            },
        )

    def test_assisted_exploration_is_governed_traceable_and_exploratory(self):
        response = AssistedCohortExploration(self.engine).ask(
            self.principal,
            "Show research subject identities for gene GENE1 shared across cohorts.",
        )
        self.assertEqual(response.governed_scenario, "cross_cohort")
        self.assertEqual(response.exploratory_notice, EXPLORATORY_NOTICE)
        self.assertTrue(response.results)
        self.assertEqual(len(response.results), len(response.traceability))
        self.assertTrue(all("research_subject_id" not in row for row in response.results))
        self.assertTrue(all(
            {"source_file_uri", "producing_run", "reference_build", "pipeline_version"} <= set(trace)
            for trace in response.traceability
        ))


if __name__ == "__main__":
    unittest.main()
