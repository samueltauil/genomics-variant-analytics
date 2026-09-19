import tempfile
import unittest
from pathlib import Path

from scripts.lineage import CatalogContext, LineageResolver
from scripts.metadata_store import MetadataStore
from scripts.stage_records import StagingLog
from scripts.variant_store import VariantStore


VCF = "\n".join([
    "##fileformat=VCFv4.3",
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
    "1\t101\tSYN-VAR-001\tA\tG\t99\tPASS\tGENE=GENE1\tGT\t0/1",
    "",
])


class LineageResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.variant_store = VariantStore(root / "variants.sqlite3")
        self.metadata_store = MetadataStore(root / "metadata.sqlite3")
        self.staging = StagingLog(root / "staging.sqlite3")
        self.addCleanup(self.variant_store.close)
        self.addCleanup(self.metadata_store.close)
        self.addCleanup(self.staging.close)

        self.principal = "SYN-ANALYST-001"
        self.metadata_store.grant_tier(self.principal, "variant_store")
        self.metadata_store.grant_capability(self.principal, "subject_linkage")
        self.subjectless = "SYN-ANALYST-002"
        self.metadata_store.grant_tier(self.subjectless, "variant_store")
        self.raw_reader = "SYN-ANALYST-003"
        self.metadata_store.grant_tier(self.raw_reader, "variant_store")
        self.metadata_store.grant_tier(self.raw_reader, "raw_genomic_files")

        landing = str(root / "landing" / "SYN-RUN-001" / "SYN-SAMPLE-001.vcf")
        self.source_uri = "abfss://synthetic@lake.dfs.core.windows.net/Process/VCF/SYN-RUN-001.vcf"
        self.staging.record({
            "source_path": landing,
            "run_id": "SYN-RUN-001",
            "sample_id": "SYN-SAMPLE-001",
            "destination_uri": self.source_uri,
            "storage_tier": "Hot",
            "classification": "genomic-variant",
            "source_checksum": "a" * 64,
            "destination_checksum": "a" * 64,
        }, "2026-09-19T15:00:00Z")

        self.metadata_store.add_entity("SYN-SUBJECT-001", "subject")
        self.metadata_store.add_entity("SYN-SAMPLE-001", "sample", ["SYN-SUBJECT-001"])
        self.metadata_store.add_entity("SYN-SEQRUN-001", "sequencing_run", ["SYN-SAMPLE-001"])
        self.metadata_store.add_entity(
            "SYN-FASTQ-001", "fastq", ["SYN-SEQRUN-001"],
            file_metadata={
                "storage_uri": "abfss://synthetic@lake/Process/FASTQ/SYN-FASTQ-001.fastq",
                "analysis_stage": "sequencing", "producing_run": "SYN-SEQRUN-001",
                "integrity_result": "passed",
            },
        )
        self.metadata_store.add_pipeline_run("SYN-PIPELINE-001", "synthetic-workflow", "release-1.0.0")
        self.metadata_store.add_entity(
            "SYN-BAM-001", "bam", ["SYN-FASTQ-001"],
            file_metadata={
                "storage_uri": "abfss://synthetic@lake/Process/BAM/SYN-BAM-001.bam",
                "analysis_stage": "alignment", "producing_run": "SYN-PIPELINE-001",
                "integrity_result": "passed",
            },
        )
        self.metadata_store.add_entity(
            "SYN-VCF-001", "vcf", ["SYN-BAM-001"],
            file_metadata={
                "storage_uri": self.source_uri,
                "analysis_stage": "variant-calling", "producing_run": "SYN-PIPELINE-001",
                "integrity_result": "passed",
            },
        )
        self.variant_store.ingest_vcf_text(VCF, {
            "run_id": "SYN-PIPELINE-001", "sample_id": "SYN-SAMPLE-001",
            "research_subject_id": "SYN-SUBJECT-001", "cohort_id": "SYN-COHORT-001",
            "pipeline_version": "release-1.0.0", "reference_build": "GRCh38",
            "reference_version_or_digest": "manifest-sha256:synthetic-001",
            "classification": "genomic-variant", "source_file_uri": self.source_uri,
            "ingestion_timestamp": "2026-09-19T15:00:00Z",
        })

        catalog = CatalogContext()
        catalog.register(
            "SYN-CATALOG-VCF-001", "VCF", self.source_uri, "SYN-RUN-001 VCF",
            classifications=("genomic-variant",),
        )
        self.resolver = LineageResolver(
            self.variant_store, self.metadata_store, self.staging, catalog
        )
        self.variant = self.variant_store.records()[0]

    def test_backward_trace_returns_full_chain_and_catalog_simulation(self):
        trace = self.resolver.backward_trace(self.principal, self.variant)
        kinds = {entity["kind"] for entity in trace["metadata_chain"]["entities"]}
        self.assertEqual(kinds, {"subject", "sample", "sequencing_run", "fastq", "bam", "vcf"})
        self.assertEqual(trace["pipeline_run"]["run_id"], "SYN-PIPELINE-001")
        self.assertTrue(trace["staged_artifact"]["destination_uri"].endswith("SYN-RUN-001.vcf"))
        self.assertEqual(trace["catalog_status"]["mode"], "simulation")
        self.assertFalse(trace["catalog_status"]["live"])

    def test_deidentified_trace_withholds_subject_but_keeps_chain_to_sample(self):
        trace = self.resolver.backward_trace(self.subjectless, self.variant)
        self.assertFalse(trace["access"]["subject_linkage_visible"])
        self.assertNotIn("research_subject_id", trace["variant_result"])
        self.assertNotIn("SYN-SUBJECT-001", {
            entity["entity_id"] for entity in trace["metadata_chain"]["entities"]
        })
        self.assertIn("SYN-SAMPLE-001", {
            entity["entity_id"] for entity in trace["metadata_chain"]["entities"]
        })

    def test_forward_trace_returns_staged_artifact_and_variant_record(self):
        trace = self.resolver.forward_trace(self.principal, trace_path := trace_path_for(self))
        self.assertEqual(trace["staged_artifact"]["state"], "staged")
        self.assertEqual(trace["derived"][0]["pipeline_run"]["run_id"], "SYN-PIPELINE-001")
        self.assertEqual(trace["derived"][0]["variant_records"][0]["ID"], "SYN-VAR-001")

    def test_raw_content_visibility_is_separate_from_lineage_visibility(self):
        trace = self.resolver.forward_trace(self.subjectless, trace_path_for(self))
        self.assertFalse(trace["access"]["raw_content_readable"])
        self.assertFalse(trace["landing_file"]["content_readable"])
        raw_trace = self.resolver.forward_trace(self.raw_reader, trace_path_for(self))
        self.assertTrue(raw_trace["access"]["raw_content_readable"])


def trace_path_for(test):
    return test.staging.report()[0]["source_path"]


if __name__ == "__main__":
    unittest.main()
